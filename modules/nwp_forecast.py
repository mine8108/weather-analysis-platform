"""
NWP 数值预报模块：GFS 预报接入、高温/体感指数、时间图与空气质量图渲染

数据来源：Open-Meteo 数值预报 API (https://api.open-meteo.com/v1/forecast)
- 免注册、免费、支持 GFS 模式 (models=gfs / gfs_seamless)
- 单点逐时预报最长 16 天
- 空气质量数据来自 Open-Meteo Air Quality API（CAMS，最长 7 天）

说明：本模块刻意不使用非 BMP emoji（如 surrograge pair），以兼容
Streamlit Cloud 的标签编码要求。
"""

import sys
import os
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_with_backoff, supabase_secrets_ready, check_response_size
from config import (AQI_STANDARD_LABEL, safe_chart, _is_dark,
                    WARN_LEVEL_ORDER, LIFE_INDEX_META as _LIFE_INDEX_META,
                    WIND_DIRECTIONS, level_label)
from modules.design_tokens import (
    aqi_token,
    color_value,
    css_var,
    token_value,
    warn_token,
)
from modules.aqi import comprehensive_aqi
from modules import gfs_cache
from modules import warn_rules
from modules.quota import take_outbound
from modules.nwp.calc import (
    heat_index, _calc_ssd, _calc_life_indices, _analyze_forecast,
)

_LOG = logging.getLogger(__name__)


def _sev(token: str) -> str:
    """把严重度 token 名解析成当前主题下的 CSS 变量引用。

    ``_calc_life_indices`` 返回的是**语义 token 名**（如 ``"sev-best"``）而不是
    hex：同一份计算结果在亮/暗两套主题下都要可读，把颜色定死在返回结构里
    会导致换肤后颜色不跟随（这正是改造前的问题）。
    """
    return css_var(token)


# ============================================================
# 一、模式选项
# ============================================================
GFS_MODELS = {
    "GFS 无缝混合 (gfs_seamless)": "gfs_seamless",
    "自动 (默认 blend)": None,
}

# 单点预报返回的变量 -> 标准字段映射（均衡集：核心四要素 + 湿度 + 风速）
_FC_HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "weather_code",
    "precipitation_probability",
]


# ============================================================
# 二、数据获取
# ============================================================


# 数据 schema 版本：列集合变化时递增，使旧缓存（如缺 wind_direction 列）失效强制重拉
_GFS_FC_SCHEMA_VERSION = "v3"


# 缓存网格 0.01°（约 1 km）。GFS/Open-Meteo 的网格本身是公里级，四舍五入
# 到 0.01° 不会改变可用性，却能把“同城不同坐标”收敛到同一个键，显著提升
# 跨用户命中率，也限制用户换坐标刷缓存的空间。
_GFS_CACHE_GRID = 0.01


def _gfs_cache_coords(lat, lon):
    """把坐标归一到缓存网格，返回 (lat, lon)。"""
    step = _GFS_CACHE_GRID
    return (round(lat / step) * step, round(lon / step) * step)


def _gfs_forecast_cache_key(lat, lon, days, model, window=None):
    """基于请求参数生成短周期缓存 key（避免同一参数反复触发限流）。

    window: 形如 'YYYYmmdd_YYYYmmdd' 的过去窗口标识（hindcast 验证用）。

    这个格式与 `sql/schema.sql` 中 `put_gfs_cache` 的正则校验绑定：
    `^gfs_fc_cache_[^_]+_{lat:.4f}_{lon:.4f}_..._{model}$`。改动键格式时
    必须同步改 SQL，否则缓存写入会被服务端拒绝。
    """
    model_part = model if model else "blend"
    wpart = window if window else f"d{int(days)}"
    cache_lat, cache_lon = _gfs_cache_coords(lat, lon)
    return (f"gfs_fc_cache_{_GFS_FC_SCHEMA_VERSION}_{cache_lat:.4f}_"
            f"{cache_lon:.4f}_{wpart}_{model_part}")


# 缓存 TTL 由数据库 get_gfs_cache / put_gfs_cache 统一控制（1 小时）。


def _gfs_df_to_records(df):
    """DataFrame -> list[dict]（timestamp 转 ISO 字符串供 jsonb 存储）"""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _gfs_records_to_df(records):
    """list[dict] -> DataFrame（timestamp 转回 datetime）"""
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _cache_client(admin=False):
    """创建 GFS 缓存客户端；读取用用户客户端，写入用 service_role。

    写入必须由应用服务端完成。若使用登录用户客户端，任何用户都能直接调
    ``put_gfs_cache`` 伪造缓存；改用 service_role 后，函数只对该角色开放。
    读取仍走用户客户端，RLS 继续生效。
    """
    if not supabase_secrets_ready():
        return None
    try:
        from auth import get_supabase, get_supabase_admin
        return get_supabase_admin() if admin else get_supabase()
    except Exception:
        _LOG.warning("创建 GFS 缓存客户端失败", exc_info=True)
        return None


def _load_gfs_from_cache(cache_key):
    """从 Supabase 读取二级缓存（跨用户 / 跨重启共享）。失败返回 None。

    过滤字段改用 ``updated_at``：旧实现按 ``created_at`` 过滤，而 upsert 不会
    刷新 ``created_at``，缓存会在首次写入一小时后对所有人永久失效。
    安全修复（SEC-25）：读取也走 service_role。``get_gfs_cache`` 已从客户端
    角色收回，避免登录用户按可预测 key 探测「某坐标最近是否被查询过」。
    """
    try:
        sb = _cache_client(admin=True)
        if sb is None:
            return None
        records = gfs_cache.read_from(sb, cache_key)
        if records:
            return _gfs_records_to_df(records)
    except Exception:
        _LOG.warning("读取 GFS 二级缓存失败 cache_key=%s", cache_key,
                     exc_info=True)
    return None


def _save_gfs_to_cache(cache_key, lat, lon, days, model, df):
    """写入 Supabase 二级缓存（失败只记日志，不影响返回）。

    写入使用 service_role 客户端，统一经 ``put_gfs_cache`` RPC。表级
    insert/update 已从客户端角色收回，RPC 只对 service_role 开放，因此
    登录用户无法直接伪造缓存；函数内仍会校验键、坐标与数据形状。
    """
    try:
        sb = _cache_client(admin=True)
        if sb is None:
            return
        gfs_cache.save_to(
            sb, cache_key, lat, lon, days, model, _gfs_df_to_records(df))
    except Exception:
        _LOG.warning("写入 GFS 二级缓存失败 cache_key=%s", cache_key,
                     exc_info=True)


@retry_with_backoff(max_retries=3, base_delay=3, backoff_factor=2)
def fetch_gfs_forecast(lat, lon, days=7, model="gfs_seamless",
                       start_date=None, end_date=None):
    """获取 GFS 单点逐时预报 (Open-Meteo, 免注册)。

    三级缓存：① 会话内 session_state → ② Supabase 跨用户/跨重启 → ③ Open-Meteo 实时请求。
    返回 (DataFrame, error_msg)。成功时 error_msg 为 None。
    DataFrame 含标准字段：timestamp, temperature, humidity,
    apparent_temperature, precipitation, wind_speed, wind_direction,
    weather_code, station_id。
    （均衡集：保留核心四要素 + 湿度 + 风速 + 风向）

    hindcast 验证：传入 start_date / end_date（YYYY-MM-DD）时，改用 Open-Meteo
    的历史窗口（仍走 forecast 端点，返回该窗口模式最优估计），用于「预报验证」模块
    与实况配对比对。此时忽略 days 参数。
    """
    if start_date and end_date:
        window = f"{start_date.replace('-', '')}_{end_date.replace('-', '')}"
        _days_key = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days + 1
    else:
        window = None
        _days_key = days
    cache_key = _gfs_forecast_cache_key(lat, lon, _days_key, model, window)
    cache_lat, cache_lon = _gfs_cache_coords(lat, lon)
    # 第一层：同一会话内同参数缓存（带 1 小时 TTL，SEC-33：旧实现永不过期）
    cached = st.session_state.get(cache_key)
    if (isinstance(cached, tuple) and len(cached) == 2
            and isinstance(cached[0], datetime)):
        cached_ts, cached_df = cached
        if (datetime.now(timezone.utc) - cached_ts).total_seconds() < 3600:
            return cached_df, None
    # 第二层：Supabase 跨用户 / 跨重启共享缓存
    sb_df = _load_gfs_from_cache(cache_key)
    if sb_df is not None:
        st.session_state[cache_key] = (datetime.now(timezone.utc), sb_df)
        return sb_df, None

    # 安全修复（SEC-02）：服务端每用户每日出站配额，缓存未命中才占用
    allowed, quota_msg = take_outbound()
    if not allowed:
        return None, quota_msg

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        # 使用逗号分隔字符串，减少 URL 长度与同名参数数量
        "hourly": ",".join(_FC_HOURLY),
        "timezone": "Asia/Shanghai",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
    }
    if start_date and end_date:
        params["start_date"] = start_date
        params["end_date"] = end_date
    else:
        params["forecast_days"] = int(days)
    if model:
        params["models"] = model

    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    check_response_size(resp)
    data = resp.json()

    if "hourly" not in data:
        # 安全修复（SEC-34）：第三方响应体不回显给用户，细节只进服务端日志
        _LOG.warning("GFS 接口返回缺少 hourly 字段")
        return None, "数值预报接口返回异常数据，请稍后重试。"

    h = data["hourly"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(h["time"]),
        "temperature": h["temperature_2m"],
        "humidity": h["relative_humidity_2m"],
        "apparent_temperature": h["apparent_temperature"],
        "precipitation": h["precipitation"],
        "wind_speed": h["wind_speed_10m"],
        "wind_direction": h["wind_direction_10m"],
        "weather_code": h["weather_code"],
        "precipitation_probability": h.get("precipitation_probability", [0] * len(h["time"])),
    })
    df["station_id"] = f"GFS({lat:.2f},{lon:.2f})"

    st.session_state[cache_key] = (datetime.now(timezone.utc), df)
    # 第三层落地后写入二级缓存（失败静默忽略）
    _save_gfs_to_cache(
        cache_key, cache_lat, cache_lon, _days_key, model, df)
    return df, None


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_gfs_current(lat, lon, model="gfs_seamless"):
    """获取单点实时实测 (Open-Meteo `current=` 参数)，TTL 600 秒。
    返回 dict: {temperature, humidity, apparent_temperature, wind_speed,
                precipitation, precipitation_probability, weather_code}
    失败返回 None。**不依赖服务器时钟**，每次返回 Open-Meteo 当时的真"当前时刻"实测。
    """
    try:
        # 安全修复（SEC-02）：实况卡片同样计入每用户每日出站配额
        allowed, _quota_msg = take_outbound()
        if not allowed:
            return None
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": float(lat),
            "longitude": float(lon),
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                       "wind_speed_10m,precipitation,precipitation_probability,weather_code",
            "timezone": "Asia/Shanghai",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
        }
        if model:
            params["models"] = model
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        check_response_size(resp)
        data = resp.json()
        cur = data.get("current")
        if not cur:
            return None
        return {
            "temperature": cur.get("temperature_2m"),
            "humidity": cur.get("relative_humidity_2m"),
            "apparent_temperature": cur.get("apparent_temperature"),
            "wind_speed": cur.get("wind_speed_10m"),
            "precipitation": cur.get("precipitation"),
            "precipitation_probability": cur.get("precipitation_probability"),
            "weather_code": cur.get("weather_code"),
        }
    except Exception:
        return None


# ============================================================
# 二-2、空气质量预报 (Open-Meteo Air Quality API / CAMS)
# ============================================================

# 国标 AQI 分指数表的单一真相源是 config.AQI_BREAKPOINTS，计算由 modules.aqi 统一实现。
# 本模块不再持有断点表，仅保留下方的等级→色 token 映射供图表使用。

# 国标六级 (AQI 区间, 等级, token 名)
# 色值统一由 design_tokens 提供：改造前本表与 config.AQI_LEVELS 各存一份 hex，
# 两处取值不同，同一个 AQI 等级在分析页与预报页呈现不同颜色。
_AQ_LEVELS = [
    (0, 50, "优", "aqi-1"),
    (51, 100, "良", "aqi-2"),
    (101, 150, "轻度污染", "aqi-3"),
    (151, 200, "中度污染", "aqi-4"),
    (201, 300, "重度污染", "aqi-5"),
    (301, 99999, "严重污染", "aqi-6"),
]


def _aq_color(token: str, dark: bool | None = None) -> str:
    """AQI token → 具体色值。

    图表场景必须用具体色值而非 var()：plotly.js 绘制的是 SVG，
    不会解析 CSS 自定义属性（本机实测 var() 会整段失效）。
    """
    return token_value(token, dark)


def _compute_cn_aqi(conc):
    """按国标由六项浓度计算 AQI，返回 (aqi:int|None, level:str, primary:str, color:str)。

    计算委托 modules.aqi.comprehensive_aqi（单一实现），本函数只做
    「四元组 + 具体色值」的适配：图表侧需要 hex 而非 var()。
    说明（A 方案）：PM2.5/PM10 国标用 24h 均值，此处以逐时浓度近似代入 24h 限值表，
    牺牲部分严谨度换取与 GFS 逐时曲线对齐；气态污染物用 1h 表，正确。
    标准版本见 config.AQI_STANDARD_LABEL。
    """
    result = comprehensive_aqi(conc or {})
    if result["aqi"] is None:
        return None, "无数据", "—", token_value("text-muted")
    return (result["aqi"], result["level"], result["primary"] or "无",
            _aq_color(aqi_token(result["level"])))


def fetch_air_quality(lat, lon, days=7):
    """获取空气质量预报 (Open-Meteo Air Quality API, 数据源 CAMS)。
    返回 (DataFrame, current_dict, error_msg)，成功时 error_msg 为 None。
    - DataFrame: timestamp + 6 项浓度 + aqi/level/primary/color（口径见 config.AQI_STANDARD_LABEL）。
    - current_dict: 实时浓度 dict（用于实况卡片），失败为 None。
    会话内缓存 1 小时，避免重复请求（CAMS 更新频率约每日数次）。
    """
    days = min(int(days), 7)
    cache_key = f"aq_cache_{lat:.4f}_{lon:.4f}_{days}"
    cached = st.session_state.get(cache_key)
    if cached is not None:
        ts, df, current = cached
        if (datetime.now(timezone.utc) - ts).total_seconds() < 3600:
            return df, current, None
    # 安全修复（SEC-02）：CAMS 请求同样计入每用户每日出站配额
    allowed, quota_msg = take_outbound()
    if not allowed:
        return None, None, quota_msg
    try:
        url = "https://air-quality-api.open-meteo.com/v1/air-quality"
        params = {
            "latitude": float(lat),
            "longitude": float(lon),
            "hourly": "pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
            "current": "pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone",
            "forecast_days": days,
            # 与 GFS 保持一致，确保 AQI 时间轴与 GFS 对齐
            "timezone": "Asia/Shanghai",
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        check_response_size(resp)
        data = resp.json()
        if "hourly" not in data:
            _LOG.warning("空气质量接口返回缺少 hourly 字段")
            return None, None, "空气质量接口返回异常数据，请稍后重试。"
        h = data["hourly"]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(h["time"]),
            "pm2_5": h.get("pm2_5"),
            "pm10": h.get("pm10"),
            "co": h.get("carbon_monoxide"),
            "no2": h.get("nitrogen_dioxide"),
            "so2": h.get("sulphur_dioxide"),
            "o3": h.get("ozone"),
        })
        # 逐行计算国标 AQI（A 方案：逐时近似）。
        # 注意：Open-Meteo 的 CO 返回单位是 μg/m³，而国标 HJ633 CO 限值表用 mg/m³，
        # 必须 ÷1000 换算，否则 CO 的 IAQI 会放大 1000 倍、AQI 直接破千。
        def _co_mgm3(v):
            if v is None:
                return None
            try:
                if np.isnan(v):
                    return None
            except (TypeError, ValueError):
                return None
            return float(v) / 1000.0

        res = df.apply(
            lambda r: _compute_cn_aqi({
                "pm2_5": r["pm2_5"], "pm10": r["pm10"],
                "co": _co_mgm3(r["co"]),
                "no2": r["no2"], "so2": r["so2"], "o3": r["o3"]}),
            axis=1, result_type="expand",
        )
        df["aqi"] = res[0]
        df["level"] = res[1]
        df["primary"] = res[2]
        df["color"] = res[3]
        current = None
        cur = data.get("current")
        if cur:
            _co_raw = cur.get("carbon_monoxide")
            current = {
                "pm2_5": cur.get("pm2_5"), "pm10": cur.get("pm10"),
                "co": (float(_co_raw) / 1000.0) if _co_raw is not None else None,
                "no2": cur.get("nitrogen_dioxide"),
                "so2": cur.get("sulphur_dioxide"), "o3": cur.get("ozone"),
            }
        st.session_state[cache_key] = (datetime.now(timezone.utc), df, current)
        return df, current, None
    except Exception as e:  # noqa: BLE001
        _LOG.warning("空气质量获取失败：%s", type(e).__name__)
        return None, None, "空气质量获取失败，请稍后重试。"


def air_quality_aqi_chart(aq_df, dark=None):
    """国标 AQI 折线 + 六级色带，色带 / 折线 / 图例三层互不遮挡。
    X 轴为 timestamp，与 GFS 时间轴对齐。

    针对原实现的三处可读性缺陷重写：
    ① 原「图例」是写在绘图区右下角的灰字注释：既不是真图例（没有色块与颜色的对应
       关系），又压在折线末端。现改为绘图区外的横向图例，六档各带色块与区间上限。
    ② 原实现画最高一档用 add_hrect(y0=300, y1=700)，而 Plotly 的 shape 参与
       autorange，Y 轴被撑到 0-700；AQI 只有几十时折线被压成贴底的水平线，
       起伏几乎不可读。现按峰值贴合分档边界显式设 range。
    ③ 原实现没有任何读数锚点。现补「现在」竖线、峰值点标记与峰值标注（含等级），
       悬停同时给出数值与等级，读者不必靠颜色记忆判断当前档位。
    """
    if dark is None:
        dark = _is_dark()

    ts = aq_df["timestamp"]
    aqi = pd.to_numeric(aq_df["aqi"], errors="coerce")
    valid = aqi.dropna()

    def _level_of(v):
        """AQI 数值 → (等级名, 色值)。"""
        for lo, hi, nm, tok in _AQ_LEVELS:
            if lo <= v <= hi:
                return nm, _aq_color(tok, dark)
        return "—", token_value("text-muted", dark)

    fig = go.Figure()

    # ---- 一、六级背景色带（layer="below"：沉在折线之下，永不遮挡数据）----
    _band_edges = [0, 50, 100, 150, 200, 300, 500]
    for i, (_lo, _hi, _nm, tok) in enumerate(_AQ_LEVELS):
        fig.add_hrect(y0=_band_edges[i], y1=_band_edges[i + 1],
                      fillcolor=_aq_color(tok, dark), opacity=0.18, line_width=0, layer="below")
    # 分档色两两相近（中度/重度/严重尤其接近），补一条细虚线拉开识别度
    for _edge in _band_edges[1:-1]:
        fig.add_hline(y=_edge, line_width=1, line_dash="dot",
                      line_color="rgba(120,120,120,0.45)", layer="below")

    # ---- 二、AQI 折线（蓝色：六个分档色里没有蓝色，不会与任何色带混色）----
    if "level" in aq_df.columns:
        _levels = aq_df["level"].fillna("—").astype(str).to_numpy()
    else:
        _levels = np.array([_level_of(v)[0] if pd.notna(v) else "—" for v in aqi])
    fig.add_trace(go.Scatter(
        x=ts, y=aqi, mode="lines", name="国标 AQI",
        line=dict(color="#1d4ed8" if not dark else "#60a5fa", width=2.6),
        customdata=_levels,
        hovertemplate="%{x|%m-%d %H:%M}<br>国标 AQI %{y:.0f}（%{customdata}）<extra></extra>",
    ))

    # ---- 三、Y 轴：贴合数据峰值并抬到最近的分档边界，保证色带完整可辨 ----
    _peak = float(valid.max()) if len(valid) else 0.0
    _y_max = max(60.0, _peak * 1.25)
    for _cand in _band_edges[1:]:
        if _y_max <= _cand:
            _y_max = float(_cand)
            break

    # ---- 四、读数锚点：现在竖线 + 峰值点与峰值标注 ----
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    try:
        if ts.min() <= now <= ts.max():
            fig.add_vline(x=now, line_width=1.6, line_dash="dash",
                          line_color=token_value("chart-ref-line"),
                          annotation_text="现在", annotation_position="top left",
                          annotation_font=dict(
                              size=10,
                              color=token_value("chart-ref-line")))
    except (TypeError, ValueError):
        pass  # 时间轴异常时跳过参考线，不影响折线本身
    if len(valid):
        _pk_i = valid.idxmax()
        _pk_x, _pk_y = ts.loc[_pk_i], float(valid.loc[_pk_i])
        _pk_name, _pk_col = _level_of(_pk_y)
        fig.add_trace(go.Scatter(
            x=[_pk_x], y=[_pk_y], mode="markers", name="峰值",
            showlegend=False, hoverinfo="skip",
            marker=dict(size=10, color=_pk_col,
                        line=dict(color=token_value("chart-marker-line"),
                                  width=1.5)),
        ))
        # 峰值贴近上边界时把标注翻到点下方，避免顶到图例或被裁掉
        _above = _pk_y <= _y_max * 0.75
        fig.add_annotation(
            x=_pk_x, y=_pk_y, text=f"峰值 {_pk_y:.0f} · {_pk_name}",
            showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=_pk_col,
            ax=0, ay=-34 if _above else 34,
            xanchor="center", yanchor="bottom" if _above else "top",
            font=dict(size=10, color=_pk_col),
            bgcolor=token_value("chart-tip-bg"),
            bordercolor=_pk_col, borderwidth=1, borderpad=3,
        )

    # ---- 五、真图例：色块 + 等级 + 区间上限，整体位于绘图区之外（零遮挡）----
    # 注意：_AQ_LEVELS 的第 4 个元素是 **token 名**（如 "aqi-1"），不是颜色值。
    # 直接喂给 Plotly 会抛 ValueError（Invalid value ... Received value: 'aqi-1'），
    # 由 safe_chart 兜住并显示为「图表加载出现异常」。这里必须经 _aq_color() 解析。
    for (_lo, _hi, nm, tok), top in zip(_AQ_LEVELS, _band_edges[1:-1] + [None]):
        label = (f"{nm.replace('污染', '')} >{_band_edges[-2]}" if top is None
                 else f"{nm.replace('污染', '')} ≤{top}")
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label, showlegend=True,
            hoverinfo="skip",
            marker=dict(symbol="square", size=11, color=_aq_color(tok, dark),
                        line=dict(width=0)),
        ))

    # ---- 六、坐标轴与版式 ----
    fig.update_layout(
        xaxis_title="时间", yaxis_title="国标 AQI",
        hovermode="x unified", height=360,
        margin=dict(l=48, r=20, t=64, b=56),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=10), bgcolor="rgba(0,0,0,0)", borderwidth=0,
            itemsizing="constant", itemwidth=30,
        ),
    )
    fig.update_xaxes(tickformat="%m-%d %H:%M")
    fig.update_yaxes(range=[0, _y_max])
    return fig


# ============================================================
# 三、高温/体感指数
# ============================================================


# ============================================================
# 四、图表渲染
# ============================================================
def _forecast_time_series(fdf):
    """时间图：气温 + 体感温度(左轴) + 降水(右轴) + 精度增强

    Q1: 日温度包络带 (Min-Max 半透明填充)
    Q2: 12h 累计降水柱 (替代逐时柱，减少视觉噪音)
    Q3: 预报可信度梯度标注 (右上角: 0-3天高/4-7天中/8+天低)
    Q4: 降水概率幕布 (WMO 天气码 → 概率, 半透明背景层)
    """
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # ---- Q1: 日温度包络带 (先加，在气温线后面) ----
    df_temp = fdf[["timestamp", "temperature"]].copy()
    df_temp["date"] = fdf["timestamp"].dt.date
    day_min = df_temp.groupby("date")["temperature"].min()
    day_max = df_temp.groupby("date")["temperature"].max()
    dmax_arr = np.array([day_max[d.date()] for d in fdf["timestamp"]])
    dmin_arr = np.array([day_min[d.date()] for d in fdf["timestamp"]])
    fig.add_trace(go.Scatter(
        x=fdf["timestamp"], y=dmax_arr, mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=fdf["timestamp"], y=dmin_arr, mode="lines",
        fill="tonexty", fillcolor="rgba(231,76,60,0.10)",
        line=dict(width=0), name="日波动范围",
        hoverinfo="skip",
    ), secondary_y=False)

    # ---- 主气温线 ----
    fig.add_trace(
        go.Scatter(x=fdf["timestamp"], y=fdf["temperature"], mode="lines",
                   name="气温", line=dict(color=color_value("temp_color"), width=2.2),
                   hovertemplate="%{x|%m-%d %H:%M}<br>气温: %{y:.1f}C<extra></extra>"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=fdf["timestamp"], y=fdf["apparent_temperature"], mode="lines",
                   name="体感温度", line=dict(color="#e67e22", width=2, dash="dot"),
                   hovertemplate="%{x|%m-%d %H:%M}<br>体感: %{y:.1f}C<extra></extra>"),
        secondary_y=False,
    )

    # ---- Q4: 降水概率幕布 (WMO 天气码 → 概率) ----
    if "weather_code" in fdf.columns:
        def _wet_prob(c):
            if c in range(0, 20): return 0.10
            if c in range(20, 50): return 0.50
            if c in range(50, 70): return 0.70
            if c in range(70, 80): return 0.80
            if c in range(80, 87): return 0.90
            if c in range(95, 100): return 0.95
            return 0.10
        probs = np.array([_wet_prob(c) for c in fdf["weather_code"]], dtype=float)
        fig.add_trace(go.Scatter(
            x=fdf["timestamp"], y=probs, mode="none",
            fill="tozeroy", fillcolor="rgba(41,128,185,0.08)",
            name="降水概率", showlegend=True,
            hoverinfo="skip",
            yaxis="y2",
        ), secondary_y=True)
        # 概率刻度 (右侧第二 Y 轴)
        fig.add_trace(go.Scatter(
            x=fdf["timestamp"], y=probs, mode="lines",
            line=dict(color="rgba(41,128,185,0.35)", width=1, dash="dot"),
            name="降水概率", showlegend=True,
            hovertemplate="%{x|%m-%d %H:%M}<br>降水概率: %{y:.0%}<extra></extra>",
            yaxis="y3",
        ), secondary_y=False)
        # 用第三个隐含 Y 轴来显示概率刻度（只用于参考线，不显示独立轴）
        fig.update_layout(yaxis3=dict(overlaying="y2", side="right",
                                       range=[0, 1], showticklabels=False,
                                       showgrid=False))

    # ---- Q2: 12h 累计降水柱 (替代逐时柱) ----
    hp12 = fdf.set_index("timestamp")["precipitation"].resample("12h").sum().reset_index()
    fig.add_trace(
        go.Bar(x=hp12["timestamp"], y=hp12["precipitation"], name="降水 (12h)",
               marker_color=color_value("rain_color"), opacity=0.55,
               width=36000000,  # 12h in ms
               hovertemplate="%{x|%m-%d %H:%M} (12h)<br>降水: %{y:.1f} mm<extra></extra>"),
        secondary_y=True,
    )

    # ---- 当前时刻竖线 ----
    t_min = fdf["timestamp"].min()
    t_max = fdf["timestamp"].max()
    if t_min <= now <= t_max:
        fig.add_vline(x=now, line_width=2, line_dash="dash",
                      line_color="#c0392b",
                      annotation_text="现在",
                      annotation_position="top left",
                      annotation_font=dict(size=11, color="#c0392b"))

    # ---- Q3: 预报可信度标注 ----
    n_days = int((t_max - t_min).total_seconds() / 86400)
    fig.add_annotation(
        x=0.98, y=0.98, xref="paper", yref="paper",
        text=("可信度: <span style='color:#2ca02c'>0-3天高</span> | "
              "<span style='color:#d69e2e'>4-7天中</span> | "
              "<span style='color:#c0392b'>8+天低</span>"),
        showarrow=False, font=dict(size=10),
        bgcolor=token_value("chart-tip-bg"),
        bordercolor="#475569" if _is_dark() else "#ccc",
        borderwidth=1, borderpad=5, align="right",
    )

    # ---- 轴设置 ----
    fig.update_yaxes(title_text="温度 (C)", secondary_y=False)
    fig.update_yaxes(title_text="降水 (mm, 12h合计)", secondary_y=True)
    fig.update_xaxes(
        rangeselector=dict(
            buttons=list([
                dict(count=3, label="3d", step="day", stepmode="backward"),
                dict(count=7, label="7d", step="day", stepmode="backward"),
                dict(count=14, label="14d", step="day", stepmode="backward"),
                dict(step="all"),
            ])
        ),
        rangeslider=dict(visible=True, thickness=0.15),
        dtick=43200000,
        tickformat="%m-%d %H:%M",
    )
    fig.update_layout(
        title=dict(
            text="GFS 温度/体感/降水 预报 (精度增强)",
            y=0.01, x=0.5, xanchor="center", yanchor="bottom",
            font=dict(size=14),
        ),
        hovermode="x unified",
        height=500,
        margin=dict(l=40, r=20, t=20, b=80),
        legend=dict(
            x=0.01, y=0.98,
            xanchor="left", yanchor="top",
            bgcolor=token_value("chart-tip-bg"),
            bordercolor="#475569" if _is_dark() else "#ddd", borderwidth=1,
        ),
    )
    return fig


def _high_temp_72h_panel(hh):
    """72 小时高温预报面板（含 35/37/40℃ 国家预警阈值参考线）"""
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    fig.add_trace(go.Scatter(
        x=hh["timestamp"], y=hh["temperature"], mode="lines+markers",
        name="气温", line=dict(color=color_value("temp_color"), width=2), marker=dict(size=4),
    ))
    fig.add_trace(go.Scatter(
        x=hh["timestamp"], y=hh["apparent_temperature"], mode="lines",
        name="体感温度", line=dict(color="#e67e22", width=2),
    ))
    for thr, name, color in [(35, "高温黄 35℃", "#d69e2e"),
                             (37, "高温橙 37℃", "#d96c3d"),
                             (40, "高温红 40℃", "#c0392b")]:
        fig.add_hline(y=thr, line_dash="dash", line_color=color,
                      annotation_text=name, annotation_position="right")
    fig.update_layout(
        title=dict(
            text="未来 72 小时高温与体感温度",
            y=0.01, x=0.5, xanchor="center", yanchor="bottom",
            font=dict(size=14),
        ),
        xaxis_title="时间", yaxis_title="温度 (C)",
        hovermode="x unified", height=380,
        margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(
            x=0.01, y=0.98,
            xanchor="left", yanchor="top",
            bgcolor=token_value("chart-tip-bg"),
            bordercolor="#475569" if _is_dark() else "#ddd", borderwidth=1,
        ),
    )
    return fig


# ============================================================
# 风玫瑰：16 扇区频次权重 + 5 级风速着色 + 静风单列 + 主导风向
# 数据范围 = 整个预报期（fdf 全部小时）
# ============================================================

# 16 方位中文名（风向 = 风来自的方位）
_WIND_CN = {
    "N": "北风", "NNE": "东北偏北风", "NE": "东北风", "ENE": "东北偏东风",
    "E": "东风", "ESE": "东南偏东风", "SE": "东南风", "SSE": "东南偏南风",
    "S": "南风", "SSW": "西南偏南风", "SW": "西南风", "WSW": "西南偏西风",
    "W": "西风", "WNW": "西北偏西风", "NW": "西北风", "NNW": "西北偏北风",
}
# 蒲福风级 8 档分桶 (m/s)，静风（<0.5）单独列入图例不绘入玫瑰
_WS_BINS = [0.5, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2]
_WS_LABELS = ["0.5-1.5", "1.6-3.3", "3.4-5.4", "5.5-7.9",
              "8.0-10.7", "10.8-13.8", "13.9-17.1", "≥17.2"]
_WS_CN = ["软风", "轻风", "微风", "和风", "清风", "强风", "劲风", "大风及以上"]
# 蒲福风级配色带改走共享 token：改造前这里是 8 色、visualizer 的风玫瑰是另一套
# 9 色，同一个应用里两张风玫瑰图用不同颜色；且浅色档在暗色主题下几乎不可见。
_WS_COLORS = [css_var(f"beaufort-{i}") for i in range(1, 9)]
_CALM_THRESHOLD = 0.5  # 静风阈值 (m/s)
_CALM_COLOR = css_var("beaufort-9")  # 静风图例色


def _wind_rose_stats(fdf):
    """频次权重统计：返回主导风向(英文/中文/占比%)与静风占比%。
    无有效数据返回 None。"""
    if fdf is None or fdf.empty:
        return None
    valid = fdf.dropna(subset=["wind_direction", "wind_speed"])
    if valid.empty:
        return None
    total = len(valid)
    calm_mask = valid["wind_speed"] < _CALM_THRESHOLD
    calm_pct = int(round(calm_mask.sum() / total * 100))
    active = valid[~calm_mask]
    if active.empty:
        return {"dominant_en": "—", "dominant_cn": "无有效风", "dominant_pct": 0,
                "calm_pct": calm_pct}
    dirs = active["wind_direction"].values
    sectors = (dirs / 22.5).astype(int) % 16
    counts = np.bincount(sectors, minlength=16)
    dom_idx = int(np.argmax(counts))
    dom_pct = int(round(counts[dom_idx] / len(active) * 100))
    dom_en = WIND_DIRECTIONS[dom_idx]
    return {
        "dominant_en": dom_en,
        "dominant_cn": _WIND_CN.get(dom_en, dom_en),
        "dominant_pct": dom_pct,
        "calm_pct": calm_pct,
    }


def _wind_rose_chart(fdf, dark=None):
    """风速风向玫瑰图（16 扇区频次权重，蒲福 8 级风速着色 + 静风图例项）。
    返回 (fig, stats)；无有效数据返回 (None, None)。"""
    if dark is None:
        dark = _is_dark()
    if fdf is None or fdf.empty:
        return None, None
    # 防御：列缺失（如旧缓存 fdf 不含 wind_direction）直接降级，避免 KeyError 崩块
    if "wind_direction" not in fdf.columns or "wind_speed" not in fdf.columns:
        return None, None
    valid = fdf.dropna(subset=["wind_direction", "wind_speed"])
    if valid.empty:
        return None, None

    bg = token_value("surface")
    grid = token_value("chart-grid")
    tick_col = token_value("chart-axis")
    title_col = token_value("chart-title")
    seg_line = token_value("chart-marker-line")

    def _base_layout(fig):
        fig.update_layout(
            title=dict(text="风向风速玫瑰图", x=0.0, xanchor="left",
                       y=0.98, yanchor="top",
                       font=dict(size=15, color=title_col)),
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                # 径向频率刻度沿正东方向（模板样式），纯数字不带 % 后缀
                radialaxis=dict(angle=0, gridcolor=grid,
                                tickfont=dict(color=tick_col, size=10),
                                linecolor=grid),
                angularaxis=dict(
                    direction="clockwise", rotation=90,
                    tickmode="array",
                    tickvals=[i * 22.5 for i in range(16)],
                    ticktext=WIND_DIRECTIONS,
                    gridcolor=grid, tickfont=dict(color=tick_col, size=11),
                    linecolor=grid,
                ),
            ),
            showlegend=True,
            legend=dict(
                title=dict(text="风速等级 (m/s)",
                           font=dict(size=12, color=title_col)),
                orientation="v", x=1.04, xanchor="left",
                y=0.5, yanchor="middle",
                font=dict(size=12, color=tick_col),
            ),
            paper_bgcolor=bg, plot_bgcolor=bg,
            height=540, margin=dict(l=40, r=140, t=50, b=20),
        )
        return fig

    calm_mask = valid["wind_speed"] < _CALM_THRESHOLD
    active = valid[~calm_mask]
    theta16 = [i * 22.5 for i in range(16)]
    # 静风图例项（零值柱，仅用于图例展示）
    calm_trace = go.Barpolar(
        r=[0] * 16, theta=theta16, width=21,
        name=f"静风 (<{_CALM_THRESHOLD})",
        marker_color=_CALM_COLOR, marker_line_width=0,
        hoverinfo="skip",
    )
    if active.empty:
        # 全是静风：仍画一张空玫瑰，stats 里说明
        stats = _wind_rose_stats(fdf)
        fig = go.Figure([calm_trace])
        _base_layout(fig)
        fig.update_layout(polar=dict(radialaxis=dict(visible=False)))
        return fig, stats

    dirs = active["wind_direction"].values
    spds = active["wind_speed"].values
    sectors = (dirs / 22.5).astype(int) % 16
    ws_idx = np.digitize(spds, _WS_BINS) - 1
    ws_idx = np.clip(ws_idx, 0, len(_WS_LABELS) - 1)

    # 计数矩阵 [sector, level] -> 转频率百分比(基于 active 总数)
    counts = np.zeros((16, len(_WS_LABELS)))
    for s, w in zip(sectors, ws_idx):
        counts[s, w] += 1
    freq = counts / len(active) * 100.0

    stats = _wind_rose_stats(fdf)

    fig = go.Figure([calm_trace])
    for lvl in range(len(_WS_LABELS)):
        r = freq[:, lvl].tolist()
        fig.add_trace(go.Barpolar(
            r=r, theta=theta16, width=21,
            name=f"{_WS_CN[lvl]} ({_WS_LABELS[lvl]})",
            marker_color=_WS_COLORS[lvl],
            marker_line_color=seg_line,
            marker_line_width=1,
            hovertemplate="%{theta}°<br>" + _WS_CN[lvl] + " (" +
                          _WS_LABELS[lvl] + " m/s)<br>频率 %{r:.1f}%<extra></extra>",
        ))

    _base_layout(fig)
    return fig, stats


# ============================================================
# 五、智能分析与建议
# ============================================================


def _render_forecast_advice(analysis, life_indices=None):
    """渲染预报智能分析结果。life_indices 传入后作为子节嵌入到『预报精度详情』之前。"""
    st.write("---")
    st.write("### 智能分析与建议")

    # 总述
    st.markdown(f"**总结**：{analysis['summary']}")

    # 极端值卡片（统一卡片样式）
    ex = analysis["extremes"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(_uni_card("最高气温", f"{ex['max_temp'][0]:.0f}", "C",
                               delta=ex["max_temp"][1], color=css_var("temp")), unsafe_allow_html=True)
    with c2:
        st.markdown(_uni_card("最低气温", f"{ex['min_temp'][0]:.0f}", "C",
                               delta=ex["min_temp"][1], color=css_var("humid")), unsafe_allow_html=True)
    with c3:
        st.markdown(_uni_card("累计降水", f"{ex['total_precip']:.0f}", " mm",
                               color=css_var("pres")), unsafe_allow_html=True)
    with c4:
        st.markdown(_uni_card("最大风速", f"{ex['max_wind'][0]:.1f}", "m/s",
                               delta=ex["max_wind"][1], color=css_var("wind")), unsafe_allow_html=True)

    # 预警
    if analysis["warnings"]:
        st.write("#### 预警信号")
        sorted_w = sorted(analysis["warnings"], key=lambda w: WARN_LEVEL_ORDER.get(w["level"], 4))
        cols = st.columns(min(len(sorted_w), 2))
        for i, warn in enumerate(sorted_w):
            # 与 analyzer.py 共用同一套预警级别 token，消除「同一预警两个页面两种红」
            level_color = css_var(warn_token(warn["level"]))
            with cols[i % 2]:
                st.markdown(f"""<div style="background:color-mix(in srgb, {level_color} 12%, {css_var('surface')});border-left:4px solid {level_color};padding:10px 12px;border-radius:4px;margin-bottom:6px;font-size:13px">
<b style="color:{level_color};font-size:15px">{warn['icon']} {warn['type']}{warn['level']}</b>
<br><span style="color:{css_var('text-secondary')}">{warn['level_num']} | {warn['detail']}</span></div>""", unsafe_allow_html=True)
    else:
        st.success("[OK] 未来预报期内未触发预警信号")

    # ---- 生活出行指南(嵌入智能分析节内,预报精度详情之前) ----
    if life_indices:
        _render_life_indices(life_indices, inline=True)

    # 精度增强面板
    prec = analysis.get("precision", {})
    if prec:
        st.write("#### 预报精度详情")
        # 趋势数值（统一卡片样式）
        tt = prec.get("temp_trend", {})
        if tt:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(_uni_card("趋势变化", f"{tt['diff_mean']:+.1f}", "C",
                                       delta=f"±{tt['diff_std']:.1f}C", color=css_var("vis")), unsafe_allow_html=True)
            with c2:
                st.markdown(_uni_card("波动程度", tt.get("volatility", ""), "",
                                       delta=f"标准差 {tt['overall_std']:.1f}C", color=css_var("rain")), unsafe_allow_html=True)
            with c3:
                hot_days = prec.get("consecutive_hot", 0)
                d = f"最长 {hot_days} 天" if hot_days > 0 else None
                st.markdown(_uni_card("连续高温", f"{hot_days}", " 天",
                                       delta=d, color=css_var("temp")), unsafe_allow_html=True)
        # 降水精度
        pcat = prec.get("precip_cats", {})
        mp = prec.get("max_6h_precip")
        if pcat and any(pcat.values()):
            st.caption(f"降水强度分布：{prec.get('precip_summary', '')}"
                       + (f" | 最狂6h降水 {mp[0]:.1f} mm ({mp[1]})" if mp else ""))
        # 昼夜温差
        diur = prec.get("diurnal", {})
        if diur:
            dr = diur.get("max_range", (0, ""))
            wn = diur.get("warm_nights", 0)
            parts = []
            if dr[0] >= 15:
                parts.append(f"日较差最大 {dr[0]:.0f}C ({dr[1]})")
            else:
                parts.append(f"平均日较差 {diur.get('mean_range', 0):.1f}C")
            if wn > 0:
                parts.append(f"{wn} 天热带夜 (夜间>=25C)")
            st.caption(" | ".join(parts))

    # 耦合分析
    if analysis["coupling"]:
        st.write("#### 多要素耦合风险")
        for c in analysis["coupling"]:
            st.warning(f"{c['icon']} **{c['type']}** ({c['severity']}): {c['detail']}")



def _get_now_row(fdf):
    """兼容别名：实现已迁到 modules/nwp/calc.py。"""
    from modules.nwp.calc import _get_now_row as _impl
    return _impl(fdf)


# ============================================================
# 通用统计卡片（统一视觉语言，替代 st.metric）
# ============================================================
# 改造前本文件有三处几乎逐字重复的卡片构造代码，各自维护一份
# `bg/border/label_color/val_color = "#xxx" if dark else "#yyy"` 分支：
#   _uni_card / _render_current_conditions 内的 _card / _render_life_indices 内的 _card
# 三份分支的标准色并不一致（#1e293b vs #232a3d、#64748b vs #94a3b8），
# 于是同一页面里不同卡片在暗色下深浅不同。现在统一由下面的辅助函数产出，
# 且一律走 CSS 变量，主题切换无需 Python 重新渲染。
def _card_surface() -> tuple[str, str, str, str]:
    """返回卡片统一的 (底色, 描边, 弱化文字, 主文字) 四个 CSS 值。"""
    return (
        css_var("surface"),
        css_var("line"),
        css_var("text-muted"),
        css_var("text-primary"),
    )


def _uni_card(label, value, unit="", delta=None, color=None):
    """通用统计卡片：彩色左边框 + 标签/大值/副文本，统一替代 st.metric()

    ``color`` 传入 token 名（如 ``"temp"`` / ``"wind"``）或任意 CSS 颜色值；
    不传时用品牌强调色。改造前默认值是写死的 ``#3b82f6``，在暗色下偏暗。
    """
    color = color or css_var("accent")
    bg, border, label_c, val_c = _card_surface()

    delta_html = ""
    if delta:
        delta_html = f'<div style="font-size:0.72rem;color:{color};margin-top:4px;">{delta}</div>'

    return f"""
    <div style="background:{bg};border:1px solid {border};border-radius:12px;
                padding:16px 14px;position:relative;overflow:hidden;">
        <div style="position:absolute;left:0;top:0;bottom:0;width:4px;background:{color};border-radius:12px 0 0 12px;"></div>
        <div style="font-size:0.8rem;color:{label_c};margin-bottom:6px;padding-left:4px;">{label}</div>
        <div style="font-size:1.75rem;font-weight:700;color:{val_c};line-height:1.2;padding-left:4px;">
            {value}<span style="font-size:0.9rem;font-weight:400;color:{label_c};margin-left:3px;">{unit}</span>
        </div>
        {delta_html}
    </div>
    """


# ============================================================
# 五-2、当前实况卡片
# ============================================================
def _render_current_conditions(fdf):
    """渲染当前实况卡片：气温 / 风等级 / 湿度 / 降水概率
    优先用 Open-Meteo `current=` 真实时实测；服务器时钟异常或失败时 fallback 到 fdf 当前小时行。
    """
    from config import get_beaufort_level

    if fdf is None or fdf.empty:
        return

    # 真实时实测(独立 API 调用,不依赖服务器时钟)
    lat = st.session_state.get("fc_lat")
    lon = st.session_state.get("fc_lon")
    model_label = st.session_state.get("fc_model", "GFS 无缝混合 (gfs_seamless)")
    model_value = GFS_MODELS.get(model_label, "gfs_seamless")
    cur = _fetch_gfs_current(lat, lon, model_value) if (lat is not None and lon is not None) else None

    if cur and cur.get("temperature") is not None:
        # 真实时实测路径
        temp = float(cur["temperature"])
        app_temp = float(cur.get("apparent_temperature") or temp)
        wind = float(cur.get("wind_speed") or 0)
        humid = float(cur.get("humidity") or 0)
        precip_prob = float(cur.get("precipitation_probability") or 0)
        source = "实测"
    else:
        # Fallback: 用 fdf 当前小时行(可能受服务器时钟影响)
        now_row = _get_now_row(fdf)
        if now_row is None:
            return
        temp = float(now_row.get("temperature", 0))
        app_temp = float(now_row.get("apparent_temperature", temp))
        wind = float(now_row.get("wind_speed", 0))
        humid = float(now_row.get("humidity", 0))
        precip_prob = float(now_row.get("precipitation_probability", 0))
        source = "预报"

    # 实时空气质量（AQI 分指数口径见 config.AQI_STANDARD_LABEL）
    aq_aqi, aq_level, aq_primary, aq_color = None, "—", "—", "#94a3b8"
    if lat is not None and lon is not None:
        try:
            _, _aq_cur, _aq_err = fetch_air_quality(lat, lon, 1)
            if _aq_cur:
                aq_aqi, aq_level, aq_primary, aq_color = _compute_cn_aqi(_aq_cur)
        except Exception:  # noqa: BLE001
            pass

    bf_level, bf_name = get_beaufort_level(wind)

    # --- 干湿描述（颜色改走 token，暗色下自动取更亮一档）---
    if humid >= 80:
        humid_desc, humid_color = "潮湿", css_var("humid")
    elif humid >= 60:
        humid_desc, humid_color = "湿润", css_var("rain")
    elif humid >= 40:
        humid_desc, humid_color = "舒适", css_var("pres")
    else:
        humid_desc, humid_color = "干燥", css_var("wind")

    # --- 降水概率描述 ---
    if precip_prob >= 70:
        prob_desc, prob_color = "很可能下雨", css_var("humid")
    elif precip_prob >= 40:
        prob_desc, prob_color = "有可能下雨", css_var("rain")
    elif precip_prob >= 10:
        prob_desc, prob_color = "基本无雨", css_var("pres")
    else:
        prob_desc, prob_color = "晴朗", css_var("wind")

    bg, border, label_color, val_color = _card_surface()

    def _card(icon, label, value, unit, sub, color):
        return f"""
        <div style="background:{bg};border:1px solid {border};border-radius:12px;
                    padding:16px 12px;text-align:center;position:relative;overflow:hidden;">
            <div style="position:absolute;left:0;top:0;bottom:0;width:4px;background:{color};"></div>
            <div style="font-size:1.6rem;margin-bottom:4px;">{icon}</div>
            <div style="font-size:0.75rem;color:{label_color};margin-bottom:2px;">{label}</div>
            <div style="font-size:1.8rem;font-weight:700;color:{val_color};line-height:1.2;">
                {value}<span style="font-size:0.9rem;font-weight:400;color:{label_color};">{unit}</span>
            </div>
            <div style="font-size:0.72rem;color:{color};margin-top:4px;">{sub}</div>
        </div>
        """

    st.write(f"### 当前实况  · {source}")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(_card("[T]", "气温", f"{temp:.1f}", "C",
                         f"体感 {app_temp:.1f}C", css_var("temp")), unsafe_allow_html=True)
    with c2:
        st.markdown(_card("[W]", f"风力 {bf_level}级", f"{wind:.1f}", "m/s",
                         bf_name, css_var("wind")), unsafe_allow_html=True)
    with c3:
        st.markdown(_card("[H]", "相对湿度", f"{humid:.0f}", "%",
                         humid_desc, humid_color), unsafe_allow_html=True)
    with c4:
        st.markdown(_card("[P]", "降水概率", f"{precip_prob:.0f}", "%",
                         prob_desc, prob_color), unsafe_allow_html=True)
    with c5:
        if aq_aqi is not None:
            st.markdown(_card("[AQ]", "空气质量", f"{aq_aqi:.0f}", "",
                             f"{aq_level} · {aq_primary}", aq_color), unsafe_allow_html=True)
        else:
            st.markdown(_card("[AQ]", "空气质量", "—", "",
                             "暂无数据", css_var("text-muted")), unsafe_allow_html=True)


# ============================================================
# 五-3、生活指标计算 + 渲染
# ============================================================





# 指标显示名称和图标（定义见 config.LIFE_INDEX_META）


def _render_life_indices(indices, inline=False):
    """渲染 7 项生活指标卡片 (4+3 布局)。
    inline=False: 顶级节,输出 --- 分隔符 + ### 标题(独立调用时使用)
    inline=True:  子节,输出 #### 标题(嵌入到其他节时使用,无分隔符)
    """
    if not indices:
        return

    if not inline:
        st.write("---")
    title_level = "####" if inline else "###"
    st.write(f"{title_level} 生活出行指南")

    bg, border, label_color, val_color = _card_surface()

    def _card(key, info):
        icon, name = _LIFE_INDEX_META.get(key, ("[?]", key))
        level = info["level"]
        score = info["score"]
        advice = info["advice"]
        color = _sev(info["color"])
        score_text = f"{score}" if isinstance(score, int) else f"{score:.1f}"
        return f"""
        <div style="background:{bg};border:1px solid {border};border-radius:10px;
                    padding:14px 12px;position:relative;overflow:hidden;">
            <div style="position:absolute;left:0;top:0;bottom:0;width:4px;background:{color};"></div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                <span style="font-size:0.82rem;color:{label_color};">{icon} {name}</span>
                <span style="font-size:0.75rem;font-weight:600;color:{color};
                             background:color-mix(in srgb, {color} 16%, transparent);
                             padding:2px 8px;border-radius:10px;">{level}</span>
            </div>
            <div style="font-size:1.4rem;font-weight:700;color:{color};margin-bottom:4px;">{score_text}</div>
            <div style="font-size:0.72rem;color:{label_color};line-height:1.4;">{advice}</div>
        </div>
        """

    order = ["clothing", "umbrella", "comfort", "exercise", "uv", "carwash", "drying"]

    # 第一行 4 卡
    row1 = st.columns(4)
    for i, key in enumerate(order[:4]):
        with row1[i]:
            st.markdown(_card(key, indices[key]), unsafe_allow_html=True)

    # 第二行 3 卡
    row2 = st.columns(4)
    for i, key in enumerate(order[4:]):
        with row2[i]:
            st.markdown(_card(key, indices[key]), unsafe_allow_html=True)


# ============================================================
# 五-4、预报验证（内置运行）
# ============================================================
def _render_forecast_verification():
    """预报验证子区块：GFS(hindcast) vs 实况 定量评估。

    内置运行于预报 Tab，复用会话 lat/lon。三组实况来源可选：
      ① 会话观测数据 (已导入 df)  ② Open-Meteo 历史 API 同坐标  ③ 上传 CSV。
    指标 MAE/RMSE/Bias/r 由 modules.verify 计算，三图由同一模块构建。
    """
    from modules.verify import (align_obs_fc, compute_metrics,
                                make_scatter_1to1, make_timeseries_overlay,
                                make_error_hist, VERIFY_VARS, VERIFY_VAR_LABELS)
    from modules.data_loader import (fetch_open_meteo, load_csv, load_excel,
                                     normalize_columns, parse_timestamp)

    lat = st.session_state.get("fc_lat", 39.94)
    lon = st.session_state.get("fc_lon", 116.85)
    model_label = st.session_state.get("fc_model", "GFS 无缝混合 (gfs_seamless)")
    model = GFS_MODELS.get(model_label, "gfs_seamless")
    st.caption(f"验证坐标：{lat:.2f}N, {lon:.2f}E ｜ 模式：{model_label}")

    # ---- 实况来源 ----
    obs_options = {}
    if st.session_state.get("df") is not None:
        obs_options["会话观测数据 (已导入 df)"] = "session"
    obs_options["Open-Meteo 历史 API (同坐标)"] = "archive"
    obs_options["上传 CSV"] = "upload"
    src_label = st.radio("实况数据来源", list(obs_options.keys()),
                         key="verify_obs_src", horizontal=True)
    src = obs_options[src_label]

    # ---- 验证窗口 ----
    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("验证起始日", value=datetime.now() - timedelta(days=3),
                                key="verify_start")
    with c2:
        end_d = st.date_input("验证结束日", value=datetime.now() - timedelta(days=1),
                              key="verify_end")
    start_str = start_d.strftime("%Y-%m-%d")
    end_str = end_d.strftime("%Y-%m-%d")

    uploaded = None
    if src == "upload":
        uploaded = st.file_uploader("上传观测 CSV/Excel",
                                    type=["csv", "txt", "xlsx", "xls"],
                                    key="verify_upload")

    if st.button("运行预报验证", use_container_width=True, key="verify_run"):
        # 1) GFS hindcast（同窗口）
        with st.spinner("获取 GFS 同窗口数据..."):
            fc_df, fc_err = fetch_gfs_forecast(
                lat, lon, model=model, start_date=start_str, end_date=end_str
            )
        if fc_err:
            st.error(f"GFS 获取失败：{fc_err}")
            return

        # 2) 实况
        obs_df, obs_err = None, None
        if src == "session":
            obs_df = st.session_state.get("df")
        elif src == "archive":
            with st.spinner("获取 Open-Meteo 历史实况..."):
                obs_df, obs_err = fetch_open_meteo(lat, lon, start_str, end_str)
        elif src == "upload":
            if uploaded is None:
                st.warning("请先上传观测文件")
                return
            raw = (load_csv(uploaded) if uploaded.name.lower().endswith((".csv", ".txt"))
                   else load_excel(uploaded))
            raw = normalize_columns(raw)
            raw = parse_timestamp(raw)
            obs_df = raw

        if obs_df is None or (isinstance(obs_err, str) and obs_err):
            st.error(f"实况获取失败：{obs_err or '无数据'}")
            return

        # 3) 对齐 + 指标
        merged = align_obs_fc(obs_df, fc_df)
        if merged.empty:
            st.error("观测与预报时间无重叠，无法配对。请检查窗口与坐标是否一致。")
            return
        metrics = compute_metrics(merged)
        if not metrics:
            st.error("无可用对比变量（需 temperature/humidity/wind_speed/precipitation 同时存在）。")
            return

        # 4) 指标表
        st.success(f"配对样本 {len(merged)} 条（整点对齐）")
        rows = []
        for v in VERIFY_VARS:
            if v in metrics:
                m = metrics[v]
                rows.append({
                    "变量": VERIFY_VAR_LABELS[v],
                    "MAE": f"{m['mae']:.3f}",
                    "RMSE": f"{m['rmse']:.3f}",
                    "Bias(预报-实况)": f"{m['bias']:+.3f}",
                    "相关系数 r": f"{m['r']:.3f}" if np.isfinite(m["r"]) else "—",
                    "样本数": m["n"],
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("Bias 正=预报偏高，负=预报偏低；r 越接近 1 越好。hindcast 验证局限见页脚说明。")

        # 5) 变量选择器 + 三图
        avail = [v for v in VERIFY_VARS if v in metrics and np.isfinite(metrics[v]["mae"])]
        if avail:
            sel = st.selectbox("查看变量", avail,
                               format_func=lambda v: VERIFY_VAR_LABELS[v],
                               key="verify_var")
            label = VERIFY_VAR_LABELS[sel]
            safe_chart(make_scatter_1to1(merged, sel, label), f"{label} 1:1", key="v_scatter")
            safe_chart(make_timeseries_overlay(merged, sel, label), f"{label} 时序", key="v_ts")
            safe_chart(make_error_hist(merged, sel, label), f"{label} 误差", key="v_hist")

    st.caption("说明：Open-Meteo 对过去窗口返回的「预报」为模式同窗口最优估计（hindcast），"
               "非提前多日的业务级预报，用于模型可信度参考；空间上 GFS 格点与站点存在代表性差异。")


# ============================================================
# 六、主渲染入口
# ============================================================
def render_forecast_tab():
    """渲染「数值预报分析」Tab 全部内容"""
    st.subheader("[预报] 数值预报分析 (GFS)")
    st.caption("数据来源：Open-Meteo GFS 数值预报 (免注册, 最长 16 天)")

    col1, col2, col3 = st.columns(3)
    with col1:
        lat = st.number_input("纬度 (Latitude)", value=39.94,
                              min_value=-90.0, max_value=90.0, step=0.01, key="fc_lat")
    with col2:
        lon = st.number_input("经度 (Longitude)", value=116.85,
                              min_value=-180.0, max_value=180.0, step=0.01, key="fc_lon")
    with col3:
        days = st.slider("预报时效 (天)", 1, 16, 7, key="fc_days")

    model_label = st.selectbox("数值模式", list(GFS_MODELS.keys()), key="fc_model")
    model = GFS_MODELS[model_label]

    if st.button("[预报] 获取 GFS 预报", use_container_width=True, key="fc_fetch"):
        with st.spinner("正在获取 GFS 数值预报..."):
            fdf, err = fetch_gfs_forecast(lat, lon, days=days, model=model)
        if err:
            st.error(err)
        else:
            st.session_state["fc_df"] = fdf
            # 打通「预报 → 检测」数据流：检测 Tab 读取 nwp_forecast_for_analysis，
            # 原写入键 fc_df 与之不一致，导致检测 Tab 的「数值预报驱动分析」始终为空
            st.session_state["nwp_forecast_for_analysis"] = fdf
            st.success(f"[OK] 获取 {len(fdf)} 条逐时预报 (未来 {days} 天)")

    fdf = st.session_state.get("fc_df", None)
    if fdf is None:
        st.info("点击上方按钮获取 GFS 预报数据")
        return

    # ---- 当前实况卡片 ----
    _render_current_conditions(fdf)

    # ---- 时间图 ----
    st.write("### 时间图：逐时预报序列")
    ts_fig = _forecast_time_series(fdf)
    safe_chart(ts_fig, "温度/体感/降水 预报", key="fc_ts")
    # D: 说明 rangeslider 的 Plotly 天然限制
    st.caption("提示：底部缩放滑块仅关联左侧「气温」坐标轴（右轴降水不随滑块缩放），这是 Plotly 原生行为。")

    # ---- 空气质量预报 ----
    st.write("### 空气质量预报 (国标 AQI)")
    _aq_days = min(days, 7)
    if days > 7:
        st.info(
            f"空气质量预报（CAMS）最长提供 7 天，与 GFS 时效（{days} 天）的重叠窗口为前 7 天；"
            f"第 8 天起暂无空气质量数据，曲线留空。"
        )
    aq_df, aq_cur, aq_err = fetch_air_quality(lat, lon, _aq_days)
    if aq_err:
        st.warning(aq_err)
        st.session_state["nwp_air_quality_for_analysis"] = None
    else:
        safe_chart(air_quality_aqi_chart(aq_df), "空气质量 AQI 预报", key="fc_aqi")
        # 接入检测 Tab 的 AI 解读（预报模式也能解读空气质量）
        st.session_state["nwp_air_quality_for_analysis"] = aq_df
    st.caption(
        "数据来源：CAMS 全球大气成分预报（Open-Meteo Air Quality API，最长 7 天）。"
        f"国标等级按 {AQI_STANDARD_LABEL} 计算，PM2.5/PM10 采用逐时近似。"
    )

    st.write("### 72 小时高温预报面板")
    hh = fdf.head(72)
    panel_fig = _high_temp_72h_panel(hh)
    safe_chart(panel_fig, "72小时高温预报", key="fc_72h")

    max_t = float(hh["temperature"].max())
    max_app = float(hh["apparent_temperature"].max())
    hi = heat_index(hh["temperature"].values, hh["humidity"].values)
    max_hi = float(np.nanmax(hi)) if np.isfinite(np.nanmax(hi)) else float("nan")
    if max_t >= 35:
        msg = f"未来 72 小时将出现高温：最高气温 {max_t:.1f}℃，最大体感温度 {max_app:.1f}℃"
        if np.isfinite(max_hi):
            msg += f"，Rothfusz 热指数峰值 {max_hi:.1f}℃"
        st.warning("[高温] " + msg)
    else:
        st.success(f"[OK] 未来 72 小时无高温风险 (气温 < 35℃，峰值 {max_t:.1f}℃)")

    # ---- 风玫瑰预报（替换原降水预报板块）----
    st.write("### 风玫瑰预报 (全预报期)")
    wf, wstats = _wind_rose_chart(fdf)
    if wf is None:
        st.warning("缺少风向/风速数据，无法绘制风玫瑰图。")
    else:
        safe_chart(wf, "风玫瑰预报", key="fc_wind_rose")
        st.caption(
            "读图指南：方位为风的来向（N = 风从北方吹来）；半径为该风向的出现频率（%）；"
            "右侧图例按蒲福风级分档，1-5 级蓝色由浅至深，6 级（强风）起转暖色警示；"
            "静风不计入玫瑰，仅列于图例与下方统计。"
        )
        if wstats:
            dom = wstats["dominant_cn"]
            dom_en = wstats["dominant_en"]
            dom_pct = wstats["dominant_pct"]
            calm_pct = wstats["calm_pct"]
            st.caption(
                f"主导风向（频次最高）：{dom}（{dom_en}），占有效样本 {dom_pct}%；"
                f"静风（<{_CALM_THRESHOLD} m/s）占比 {calm_pct}%。"
            )

    # ---- 智能分析与建议 ----
    with st.spinner("正在生成预报智能分析..."):
        analysis = _analyze_forecast(fdf)
    st.session_state["fc_analysis"] = analysis

    # 生活指南计算提前到此处(将作为子节嵌入智能分析节)
    # 实时观测在入口处取好再传入，计算层不读 session_state、不联网。
    _lat = st.session_state.get("fc_lat")
    _lon = st.session_state.get("fc_lon")
    _model_label = st.session_state.get(
        "fc_model", "GFS 无缝混合 (gfs_seamless)")
    _cur = None
    if _lat is not None and _lon is not None:
        _cur = _fetch_gfs_current(
            _lat, _lon, GFS_MODELS.get(_model_label, "gfs_seamless"))
    life_indices = _calc_life_indices(fdf, current=_cur)
    st.session_state["life_indices"] = life_indices

    _render_forecast_advice(analysis, life_indices=life_indices)

    # ---- 预报验证（内置运行）----
    st.write("---")
    st.write("### [验证] 预报验证 (GFS vs 实况)")
    with st.expander("展开预报验证", expanded=False):
        _render_forecast_verification()

