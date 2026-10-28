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
from html import escape
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
_GFS_FC_SCHEMA_VERSION = "v4"


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
        "precipitation_probability": h.get("precipitation_probability", [None] * len(h["time"])),
    })
    df["station_id"] = f"GFS({lat:.2f},{lon:.2f})"
    df.attrs["weather_metadata"] = {"fetched_at": datetime.now(timezone.utc).isoformat(),
        "grid_lat": data.get("latitude"), "grid_lon": data.get("longitude"),
        "timezone": data.get("timezone", "Asia/Shanghai"), "units": data.get("hourly_units", {})}

    st.session_state[cache_key] = (datetime.now(timezone.utc), df)
    # 第三层落地后写入二级缓存（失败静默忽略）
    _save_gfs_to_cache(
        cache_key, cache_lat, cache_lon, _days_key, model, df)
    return df, None


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_gfs_current(lat, lon, model="gfs_seamless"):
    """获取单点当前模式天气 (Open-Meteo `current=` 参数)，TTL 600 秒。
    返回 dict: {temperature, humidity, apparent_temperature, wind_speed,
                precipitation, precipitation_probability, weather_code}
    失败返回 None。**不依赖服务器时钟**，有效时间使用接口 current.time，数据为模式估计。
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
                       "wind_speed_10m,precipitation,weather_code",
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
            "valid_at": cur.get("time"),
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
def _forecast_time_series(fdf, apparent=True, precipitation_hours=12, probability=False, context=None):
    from modules.nwp.presentation import forecast_figure
    fig = forecast_figure(fdf, apparent=apparent, precipitation_hours=precipitation_hours,
                          probability=probability, dark=bool(st.session_state.get("dark_mode", False)), context=context)
    if st.session_state.get("_weather_expanded") and not probability:
        fig.update_layout(height=210, margin=dict(l=38, r=18, t=25, b=32), legend=dict(y=1.18))
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
        st.success("当前有效数据未触发本工具的预警阈值；请结合官方预警与缺测情况判断。")

    # ---- 生活出行指南(嵌入智能分析节内,预报精度详情之前) ----
    if life_indices:
        _render_life_indices(life_indices, inline=True)

    # 精度增强面板
    prec = analysis.get("precision", {})
    if prec:
        st.write("#### 变化特征与数据范围")
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
def _render_current_conditions(fdf, context=None):
    """Current MODEL weather, always anchored to the successful forecast context."""
    from modules.weather_view_model import format_value, number
    context = context or st.session_state.get("fc_result_context") or {}
    city = context.get("city") or {}
    lat, lon = city.get("lat"), city.get("lon")
    cur = _fetch_gfs_current(lat, lon, context.get("model")) if lat is not None and lon is not None else None
    if cur and number(cur.get("temperature")) is not None:
        values, source = cur, "当前模式天气"
        valid_time = cur.get("valid_at") or "接口未返回有效时间"
    else:
        row = _get_now_row(fdf)
        if row is None:
            st.info("当前天气暂无可用数据。")
            return
        values, source, valid_time = row, "最近预报时次", str(row.get("timestamp", ""))
    st.caption(f"{source} · {valid_time} · 北京时间 · Open-Meteo 模式资料")
    columns = st.columns(4)
    for column, label, field, suffix, digits in zip(columns,
            ["气温", "体感温度", "相对湿度", "10 m 风速"],
            ["temperature", "apparent_temperature", "humidity", "wind_speed"],
            [" °C", " °C", " %", " m/s"], [1, 1, 0, 1]):
        column.metric(label, format_value(values.get(field), suffix, digits))
    return cur


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

    result = st.session_state.get("fc_result_context") or {}
    lat = result.get("city", {}).get("lat", st.session_state.get("fc_lat", 39.94))
    lon = result.get("city", {}).get("lon", st.session_state.get("fc_lon", 116.85))
    model = result.get("model", GFS_MODELS.get(st.session_state.get("fc_model"), "gfs_seamless"))
    model_label = next(k for k, v in GFS_MODELS.items() if v == model)
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
def _save_forecast_draft():
    st.session_state["_fc_draft"] = {
        "lat": st.session_state.get("_fc_lat_input", 39.94), "lon": st.session_state.get("_fc_lon_input", 116.85),
        "days": st.session_state.get("_fc_days_input", 7), "model_label": st.session_state.get("_fc_model_input", next(iter(GFS_MODELS)))}


def render_forecast_tab():
    from modules.forecast_context import make_intent, queue_intent, consume_intent, commit_success, fail_request, restore_previous
    from modules.nwp.presentation import forecast_summary, precipitation_windows, numeric_series
    from modules.ui.shell import page_heading
    from modules.weather_view_model import format_value
    from modules.ui.navigation import MODULES, queue_navigation
    intent = consume_intent(st.session_state)
    existing = st.session_state.get("fc_result_context") or {}
    initial = {"lat": existing.get("city", {}).get("lat", 39.94), "lon": existing.get("city", {}).get("lon", 116.85),
               "days": existing.get("days", 7), "model_label": next(k for k, v in GFS_MODELS.items() if v == existing.get("model", "gfs_seamless"))}
    draft = st.session_state.setdefault("_fc_draft", initial)
    if intent:
        draft = {"lat": intent["city"]["lat"], "lon": intent["city"]["lon"], "days": intent["days"],
                 "model_label": next(k for k, v in GFS_MODELS.items() if v == intent["model"])}
        st.session_state["_fc_draft"] = draft
    for field, key in [("lat", "_fc_lat_input"), ("lon", "_fc_lon_input"), ("days", "_fc_days_input"), ("model_label", "_fc_model_input")]:
        if intent and key in st.session_state and st.session_state[key] != draft[field]:
            st.session_state[key] = draft[field]
    current_result = st.session_state.get("fc_result_context")
    navigation_panel = None
    header = st.container(border=True, key="forecast_result_header")
    with header:
        title_col, action_col = st.columns([2, 1])
        with title_col:
            page_heading(f"{current_result['city']['name']} · 数值预报" if current_result else "数值预报",
                         (f"{current_result['city']['lat']:.2f}°, {current_result['city']['lon']:.2f}° · {current_result['source']} · UTC+8"
                          if current_result else "逐时预报与气象要素分析 · 北京时间（UTC+8）"))
        if current_result:
            query_action, history_action = action_col.columns(2)
            query_panel = query_action.popover("预报参数", icon=":material/tune:", width="stretch")
            has_navigation = bool(st.session_state.get("_forecast_previous_result")) or current_result.get("source_route", "forecast") != "forecast"
            navigation_panel = history_action.popover("返回与历史", icon=":material/history:", disabled=not has_navigation, width="stretch")
        else:
            query_panel = header.container()
        if current_result:
            action_col.caption(f"{current_result['coverage_start'].replace('T', ' ')[:16]} 至 {current_result['coverage_end'].replace('T', ' ')[:16]}")
    with query_panel:
        col1, col2, col3, col4 = st.columns([1, 1, 1.3, 1.8])
        # A closed popover may mount its inputs after later reruns. Seed the
        # serialized defaults from the durable draft as well as any live state.
        lat = col1.number_input("纬度", min_value=-90.0, max_value=90.0, value=float(draft["lat"]), step=.01, key="_fc_lat_input", on_change=_save_forecast_draft)
        lon = col2.number_input("经度", min_value=-180.0, max_value=180.0, value=float(draft["lon"]), step=.01, key="_fc_lon_input", on_change=_save_forecast_draft)
        days = col3.slider("预报天数", 1, 16, value=int(draft["days"]), key="_fc_days_input", on_change=_save_forecast_draft)
        model_label = col4.selectbox("数值模式", list(GFS_MODELS), index=list(GFS_MODELS).index(draft["model_label"]), key="_fc_model_input", on_change=_save_forecast_draft)
        model = GFS_MODELS[model_label]
        if st.button("获取预报", icon=":material/refresh:", type="primary", key="fc_fetch"):
            city = next((c for c in st.session_state.get("wall_cities", [])
                         if abs(c["lat"] - lat) < .00001 and abs(c["lon"] - lon) < .00001),
                        {"zh": f"{lat:.2f}°, {lon:.2f}°", "lat": lat, "lon": lon})
            queue_intent(st.session_state, make_intent(city, int(days), model=model))
            intent = consume_intent(st.session_state)
    if intent:
        with st.spinner(f"正在获取{intent['city']['name']}的预报…"):
            fdf, err = fetch_gfs_forecast(intent["city"]["lat"], intent["city"]["lon"], days=intent["days"], model=intent["model"])
        if err:
            fail_request(st.session_state, intent, err)
        else:
            try:
                commit_success(st.session_state, intent, fdf)
                st.session_state["fc_model"] = next(k for k, v in GFS_MODELS.items() if v == intent["model"])
                st.rerun()
            except ValueError as exc:
                fail_request(st.session_state, intent, str(exc))
    status = st.session_state.get("_forecast_status") or {}
    context = st.session_state.get("fc_result_context")
    if status.get("state") == "failed":
        st.warning(f"{status['city']['name']}加载失败。{status.get('message', '')}" + (" 下方保留上次成功的结果。" if context else ""))
    if context is None:
        st.info("从顶部天气卡片选择城市，或填写坐标获取预报。")
        return
    fdf = context["data"]
    lat, lon, days, model = context["city"]["lat"], context["city"]["lon"], context["days"], context["model"]
    model_label = next(k for k, v in GFS_MODELS.items() if v == model)
    if (abs(draft["lat"] - lat) > .00001 or abs(draft["lon"] - lon) > .00001 or draft["days"] != days
            or GFS_MODELS[draft["model_label"]] != model):
        st.caption("查询参数已调整；下方仍显示上次成功加载的结果，点击获取预报后更新。")
    with header:
        source_idx = next((i for i, (_, route, _) in enumerate(MODULES) if route == context["source_route"]), 2)
        if source_idx != 2 and navigation_panel.button("返回来源模块", key="forecast_return_source", width="stretch"):
            queue_navigation(source_idx, remember=False)
            st.rerun()
        if st.session_state.get("_forecast_previous_result") and navigation_panel.button("上一份结果", key="forecast_previous_result", width="stretch"):
            restore_previous(st.session_state)
            st.rerun()
        summary = forecast_summary(fdf)
        items = []
        for name, record, kind in [("最高气温", summary["maximum"], "warm"), ("最低气温", summary["minimum"], "cool")]:
            when = record["time"][:16] if record["time"] else "缺少有效数据"
            items.append(f'<div class="wb-summary-item {kind}"><span class="wb-symbol" aria-hidden="true">thermometer</span>'
                         f'<span class="wb-summary-label">{name}</span><strong>{escape(format_value(record["value"], " °C", 1))}</strong>'
                         f'<small>{escape(when)}</small></div>')
        rain_label = "累计降水" if summary["precipitation_complete"] else "有效时次降水小计"
        items.append(f'<div class="wb-summary-item rain"><span class="wb-symbol" aria-hidden="true">water_drop</span>'
                     f'<span class="wb-summary-label">{rain_label}</span><strong>{escape(format_value(summary["precipitation"], " mm", 1))}</strong>'
                     f'<small>{summary["valid_rain_hours"]} / {summary["hours"]} 有效间隔</small></div>')
        st.html('<div class="wb-summary-grid">' + ''.join(items) + '</div>')
    with st.container(border=True, key="forecast_main_chart"):
        chart_title, chart_options = st.columns([4, 1])
        chart_title.markdown("#### 气温与降水趋势")
        with chart_options.popover("图层设置", icon=":material/tune:", width="stretch"):
            apparent = st.checkbox("显示体感温度", value=True, key="fc_show_apparent")
            rain_hours = st.selectbox("降水累计窗口（小时）", [1, 3, 6, 12, 24], index=3, key="fc_rain_window")
            has_probability = numeric_series(fdf, "precipitation_probability").between(0, 100).any()
            probability = st.checkbox("显示接口提供的降水概率", value=False, disabled=not has_probability, key="fc_show_probability")
            if not has_probability:
                st.caption("当前返回数据未提供有效概率；不根据天气码估算。")
        safe_chart(_forecast_time_series(fdf, apparent, rain_hours, probability, context), "气温与降水趋势", key="fc_ts")
        windows = precipitation_windows(fdf, rain_hours)
        incomplete = int((~windows["complete"]).sum())
        st.caption(f"降水表示前 {rain_hours} 小时累计，柱子位于区间中心。缺测与边界不完整窗口共 {incomplete} 个，留空显示。温度缺测以断线表示。")
        from modules.report.base import export_data_csv
        st.download_button("下载逐时预报 CSV", export_data_csv(fdf),
                           file_name=f"forecast_{context['city_id']}_{days}d.csv", mime="text/csv", key="fc_download_csv")
        with st.expander("来源与时间口径"):
            metadata = context.get("provider_metadata") or {}
            st.caption(f"来源：{context['source']} · 时区：Asia/Shanghai · 本次结果接收：{context['received_at']}（UTC）")
            st.caption("模式起报时次：当前接口未提供。获取时间与预报有效时间分别列示，不将获取时间当作起报时间。")
            if metadata.get("fetched_at"):
                st.caption(f"接口获取时间：{metadata['fetched_at']}")
    with st.expander("当前模式天气", expanded=False):
        _render_current_conditions(fdf, context)

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
    max_hi = float(np.max(hi[np.isfinite(hi)])) if np.isfinite(hi).any() else float("nan")
    if max_t >= 35:
        msg = f"未来 72 小时将出现高温：最高气温 {max_t:.1f}℃，最大体感温度 {max_app:.1f}℃"
        if np.isfinite(max_hi):
            msg += f"，Rothfusz 热指数峰值 {max_hi:.1f}℃"
        st.warning("[高温] " + msg)
    elif np.isfinite(max_t):
        st.info(f"有效预报时次未达到 35℃（峰值 {max_t:.1f}℃）。缺测时次及其他热风险不在此判断范围内。")
    else:
        st.info("未来 72 小时缺少有效气温数据，无法判断是否达到高温阈值。")

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

    # Every derived panel uses the same successful city/model, including after a failed query.
    _cur = _fetch_gfs_current(lat, lon, model)
    life_indices = _calc_life_indices(fdf, current=_cur)
    st.session_state["life_indices"] = life_indices

    _render_forecast_advice(analysis, life_indices=life_indices)

    # ---- 预报验证（内置运行）----
    st.write("---")
    st.write("### [验证] 预报验证 (GFS vs 实况)")
    with st.expander("展开预报验证", expanded=False):
        _render_forecast_verification()

