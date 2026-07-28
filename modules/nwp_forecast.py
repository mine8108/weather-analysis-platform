"""
NWP 数值预报模块：GFS 预报接入、高温/体感指数、时间图与空间图渲染

数据来源：Open-Meteo 数值预报 API (https://api.open-meteo.com/v1/forecast)
- 免注册、免费、支持 GFS 模式 (models=gfs / gfs_seamless)
- 单点逐时预报最长 16 天
- 支持多坐标点单次请求（用于空间网格预报场，避免多次调用）

说明：本模块刻意不使用非 BMP emoji（如 surrograge pair），以兼容
Streamlit Cloud 的标签编码要求。
"""

import sys
import os
import json
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_with_backoff
from config import COLORS, safe_chart, _is_dark, WARN_LEVEL_ORDER, LIFE_INDEX_META as _LIFE_INDEX_META


# ============================================================
# 一、模式选项
# ============================================================
GFS_MODELS = {
    "GFS 无缝混合 (gfs_seamless)": "gfs_seamless",
    "自动 (默认 blend)": None,
}

# 空间图变量中文名
SPATIAL_VAR_LABELS = {
    "temperature_2m": "2m 气温 (℃)",
    "precipitation": "降水 (mm)",
    "surface_pressure": "地面气压 (hPa)",
    "wind_speed_10m": "风速 (m/s)",
}

# 单点预报返回的变量 -> 标准字段映射（均衡集：核心四要素 + 湿度 + 风速）
_FC_HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
    "precipitation_probability",
]


# ============================================================
# 二、数据获取
# ============================================================


def _gfs_forecast_cache_key(lat, lon, days, model, window=None):
    """基于请求参数生成短周期缓存 key（避免同一参数反复触发限流）。
    window: 形如 'YYYYmmdd_YYYYmmdd' 的过去窗口标识（hindcast 验证用）。
    """
    model_part = model if model else "blend"
    wpart = window if window else f"d{int(days)}"
    return f"gfs_fc_cache_{lat:.4f}_{lon:.4f}_{wpart}_{model_part}"


# TTL：缓存 1 小时内有效（GFS 约每小时更新一次）
_GFS_CACHE_TTL_HOURS = 1


def _gfs_df_to_records(df):
    """DataFrame -> list[dict]（timestamp 转 ISO 字符串供 jsonb 存储）"""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _gfs_records_to_df(records):
    """list[dict] -> DataFrame（timestamp 转回 datetime）"""
    df = pd.DataFrame(records)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def _load_gfs_from_cache(cache_key):
    """从 Supabase 读取二级缓存（跨用户 / 跨重启共享）。失败返回 None。"""
    try:
        if not st.secrets.get("SUPABASE_URL") or not st.secrets.get("SUPABASE_ANON_KEY"):
            return None
        from auth import get_supabase
        sb = get_supabase()
        if sb is None:
            return None
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=_GFS_CACHE_TTL_HOURS)).isoformat()
        res = (
            sb.table("gfs_cache")
            .select("*")
            .eq("cache_key", cache_key)
            .gte("created_at", cutoff)
            .execute()
        )
        if res.data:
            return _gfs_records_to_df(res.data[0]["data_json"])
    except Exception:
        return None
    return None


def _save_gfs_to_cache(cache_key, lat, lon, days, model, df):
    """写入 Supabase 二级缓存（失败静默忽略，不影响返回）。"""
    try:
        if not st.secrets.get("SUPABASE_URL") or not st.secrets.get("SUPABASE_ANON_KEY"):
            return
        from auth import get_supabase
        sb = get_supabase()
        if sb is None:
            return
        sb.table("gfs_cache").upsert({
            "cache_key": cache_key,
            "lat": float(lat),
            "lon": float(lon),
            "days": int(days),
            "model": model or "blend",
            "data_json": _gfs_df_to_records(df),
        }).execute()
    except Exception:
        pass


@retry_with_backoff(max_retries=3, base_delay=3, backoff_factor=2)
def fetch_gfs_forecast(lat, lon, days=7, model="gfs_seamless",
                       start_date=None, end_date=None):
    """获取 GFS 单点逐时预报 (Open-Meteo, 免注册)。

    三级缓存：① 会话内 session_state → ② Supabase 跨用户/跨重启 → ③ Open-Meteo 实时请求。
    返回 (DataFrame, error_msg)。成功时 error_msg 为 None。
    DataFrame 含标准字段：timestamp, temperature, humidity,
    apparent_temperature, precipitation, wind_speed, weather_code, station_id。
    （均衡集：保留核心四要素 + 湿度 + 风速；气压/云量/风向由空间图独立请求）

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
    # 第一层：同一会话内同参数直接命中
    cached = st.session_state.get(cache_key)
    if cached is not None:
        return cached, None
    # 第二层：Supabase 跨用户 / 跨重启共享缓存
    sb_df = _load_gfs_from_cache(cache_key)
    if sb_df is not None:
        st.session_state[cache_key] = sb_df
        return sb_df, None

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
    data = resp.json()

    if "hourly" not in data:
        return None, f"API 返回异常: {data}"

    h = data["hourly"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(h["time"]),
        "temperature": h["temperature_2m"],
        "humidity": h["relative_humidity_2m"],
        "apparent_temperature": h["apparent_temperature"],
        "precipitation": h["precipitation"],
        "wind_speed": h["wind_speed_10m"],
        "weather_code": h["weather_code"],
        "precipitation_probability": h.get("precipitation_probability", [0] * len(h["time"])),
    })
    df["station_id"] = f"GFS({lat:.2f},{lon:.2f})"

    st.session_state[cache_key] = df
    # 第三层落地后写入二级缓存（失败静默忽略）
    _save_gfs_to_cache(cache_key, lat, lon, _days_key, model, df)
    return df, None


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_gfs_current(lat, lon, model="gfs_seamless"):
    """获取单点实时实测 (Open-Meteo `current=` 参数)，TTL 600 秒。
    返回 dict: {temperature, humidity, apparent_temperature, wind_speed,
                precipitation, precipitation_probability, weather_code}
    失败返回 None。**不依赖服务器时钟**，每次返回 Open-Meteo 当时的真"当前时刻"实测。
    """
    try:
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

# 国标 HJ 633-2012 IAQI 节点
_IAQI_NODES = [0, 50, 100, 150, 200, 300, 400, 500]
# 各污染物浓度限值（与 IAQI 节点位置对应）。
# PM2.5/PM10 用 24h 均值表（A 方案：逐时近似，见下方说明）；气态污染物用 1h 表。
_PM25_BP = [0, 35, 75, 115, 150, 250, 350, 500]      # μg/m³
_PM10_BP = [0, 50, 150, 250, 350, 420, 500, 600]     # μg/m³
_SO2_BP  = [0, 150, 500, 650, 800]                    # μg/m³, 1h
_NO2_BP  = [0, 100, 200, 700, 1200]                   # μg/m³, 1h
_CO_BP   = [0, 5, 10, 35, 60, 90, 120, 150]           # mg/m³, 1h
_O3_BP   = [0, 160, 200, 300, 400]                    # μg/m³, 1h

# (df 列名, 中文标签, 限值表)
_AQ_POLLUTANTS = [
    ("pm2_5", "PM2.5", _PM25_BP),
    ("pm10", "PM10", _PM10_BP),
    ("so2", "SO₂", _SO2_BP),
    ("no2", "NO₂", _NO2_BP),
    ("co", "CO", _CO_BP),
    ("o3", "O₃", _O3_BP),
]

# 国标六级 (AQI 区间, 等级, 颜色)
_AQ_LEVELS = [
    (0, 50, "优", "#00e400"),
    (51, 100, "良", "#ffde33"),
    (101, 150, "轻度污染", "#ff9933"),
    (151, 200, "中度污染", "#cc0033"),
    (201, 300, "重度污染", "#660099"),
    (301, 99999, "严重污染", "#7e0023"),
]


def _iaqi(c, bp):
    """单污染物分指数 IAQI。c 为浓度（与 bp 单位一致），bp 为限值表。"""
    if c is None:
        return None
    try:
        c = float(c)
    except (TypeError, ValueError):
        return None
    if np.isnan(c):
        return None
    if c <= 0:
        return 0.0
    if c >= bp[-1]:
        # 超出末档：按最后两段线性外推（IAQI > 末节点）
        c_lo, c_hi = bp[-2], bp[-1]
        i_lo, i_hi = _IAQI_NODES[len(bp) - 2], _IAQI_NODES[-1]
        return (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo
    for i in range(len(bp) - 1):
        if c <= bp[i + 1]:
            c_lo, c_hi = bp[i], bp[i + 1]
            i_lo, i_hi = _IAQI_NODES[i], _IAQI_NODES[i + 1]
            return (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo
    return None


def _compute_cn_aqi(conc):
    """按 HJ 633-2012 由六项浓度计算国标 AQI。
    返回 (aqi:int|None, level:str, primary:str, color:str)。
    说明（A 方案）：PM2.5/PM10 国标用 24h 均值，此处以逐时浓度近似代入 24h 限值表，
    牺牲部分严谨度换取与 GFS 逐时曲线对齐；气态污染物用 1h 表，正确。
    """
    iaqis = []
    for key, label, bp in _AQ_POLLUTANTS:
        ia = _iaqi(conc.get(key), bp)
        if ia is not None:
            iaqis.append((ia, label))
    if not iaqis:
        return None, "无数据", "—", "#94a3b8"
    aqi = int(round(max(i for i, _ in iaqis)))
    level, color = "严重污染", "#7e0023"
    for lo, hi, name, col in _AQ_LEVELS:
        if lo <= aqi <= hi:
            level, color = name, col
            break
    primary = "无" if aqi <= 50 else max(iaqis, key=lambda x: x[0])[1]
    return aqi, level, primary, color


def fetch_air_quality(lat, lon, days=7):
    """获取空气质量预报 (Open-Meteo Air Quality API, 数据源 CAMS)。
    返回 (DataFrame, current_dict, error_msg)，成功时 error_msg 为 None。
    - DataFrame: timestamp + 6 项浓度 + aqi/level/primary/color（国标 HJ 633-2012）。
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
        data = resp.json()
        if "hourly" not in data:
            return None, None, f"空气质量接口返回异常: {data}"
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
        # 逐行计算国标 AQI（A 方案：逐时近似）
        res = df.apply(
            lambda r: _compute_cn_aqi({
                "pm2_5": r["pm2_5"], "pm10": r["pm10"], "co": r["co"],
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
            current = {
                "pm2_5": cur.get("pm2_5"), "pm10": cur.get("pm10"),
                "co": cur.get("carbon_monoxide"), "no2": cur.get("nitrogen_dioxide"),
                "so2": cur.get("sulphur_dioxide"), "o3": cur.get("ozone"),
            }
        st.session_state[cache_key] = (datetime.now(timezone.utc), df, current)
        return df, current, None
    except Exception as e:  # noqa: BLE001
        return None, None, f"空气质量获取失败: {e}"


def air_quality_aqi_chart(aq_df, dark=None):
    """国标 AQI 折线 + 六级背景色带。X 轴为 timestamp，与 GFS 时间轴对齐。"""
    if dark is None:
        dark = _is_dark()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=aq_df["timestamp"], y=aq_df["aqi"],
        mode="lines", name="国标 AQI",
        line=dict(color="#2dd4bf", width=2),
        hovertemplate="%{x|%m-%d %H:%M}<br>国标 AQI %{y:.0f}<extra></extra>",
    ))
    for y0, y1, col in [
        (0, 50, "#00e400"), (50, 100, "#ffde33"), (100, 150, "#ff9933"),
        (150, 200, "#cc0033"), (200, 300, "#660099"), (300, 700, "#7e0023"),
    ]:
        fig.add_hrect(y0=y0, y1=y1, fillcolor=col, opacity=0.10,
                      line_width=0, layer="below")
    fig.add_annotation(
        x=0.98, y=0.02, xref="paper", yref="paper",
        text="国标六级：优/良/轻度/中度/重度/严重",
        showarrow=False, font=dict(size=9),
        bgcolor="rgba(15,23,42,0.9)" if dark else "rgba(255,255,255,0.85)",
        bordercolor="#475569" if dark else "#ddd", borderwidth=1, borderpad=4,
        align="right",
    )
    fig.update_layout(
        xaxis_title="时间", yaxis_title="国标 AQI",
        hovermode="x unified", height=320,
        margin=dict(l=40, r=20, t=20, b=60),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(tickformat="%m-%d %H:%M")
    return fig


def _gfs_spatial_cache_key(center_lat, center_lon, step, half, days, model, variable):
    model_part = model if model else "blend"
    return (
        f"gfs_spatial_cache_{center_lat:.4f}_{center_lon:.4f}_"
        f"{step:.2f}_{half:.2f}_{int(days)}_{model_part}_{variable}"
    )


@retry_with_backoff(max_retries=3, base_delay=3, backoff_factor=2)
def fetch_gfs_spatial_grid(center_lat, center_lon, step=0.5, half=1.5,
                             days=1, model="gfs_seamless", variable="temperature_2m"):
    """抓取以 center 为中心、步长 step、半宽 half 的网格点 GFS 预报。

    通过 Open-Meteo 的多坐标点单次请求实现，避免逐点调用。
    返回 (lats, lons, times, field3d, error_msg)。
      - lats / lons: 一维 np.ndarray（网格坐标，lat 为主序）
      - times: DatetimeIndex
      - field3d: shape (n_lat, n_lon, n_time) 的预报场
    失败时 field3d 为 None，error_msg 含错误信息。
    """
    cache_key = _gfs_spatial_cache_key(center_lat, center_lon, step, half, days, model, variable)
    cached = st.session_state.get(cache_key)
    if cached is not None:
        return cached

    lat_coords, lon_coords = [], []
    grid_lats, grid_lons = [], []
    la = center_lat - half
    while la <= center_lat + half + step / 2:
        lo = center_lon - half
        while lo <= center_lon + half + step / 2:
            lat_coords.append(round(la, 4))
            lon_coords.append(round(lo, 4))
            grid_lats.append(round(la, 4))
            grid_lons.append(round(lo, 4))
            lo += step
        la += step

    n_lat = len(set(round(x, 4) for x in grid_lats))
    n_lon = len(set(round(x, 4) for x in grid_lons))
    n_loc = len(lat_coords)
    # 防止用户把步长调得太细导致 URL 超长或超时
    if n_loc > 100:
        return None, None, None, None, (
            f"网格点数过多 ({n_loc} 点，{n_lat}x{n_lon})。"
            f"请增大步长或缩小半宽，确保不超过 100 点。"
        )

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": ",".join(str(x) for x in lat_coords),
        "longitude": ",".join(str(x) for x in lon_coords),
        "hourly": variable,
        "forecast_days": int(days),
        "timezone": "Asia/Shanghai",
    }
    if model:
        params["models"] = model

    resp = requests.get(url, params=params, timeout=90)
    resp.raise_for_status()
    data = resp.json()

    # 统一为坐标点列表结构
    locs = data if isinstance(data, list) else [data]
    if not locs or "hourly" not in locs[0] or variable not in locs[0]["hourly"]:
        return None, None, None, None, f"API 返回异常: {data}"

    # 校验点数与顺序
    if len(locs) != n_loc:
        return None, None, None, None, (
            f"返回点数({len(locs)})与请求网格点数({n_loc})不一致，请减小网格范围或步长"
        )

    try:
        times = pd.to_datetime(locs[0]["hourly"]["time"])
        # 按输入顺序堆叠各点变量 -> (n_loc, n_time)
        field2d = np.array(
            [loc["hourly"][variable] for loc in locs], dtype=float
        )
        field3d = field2d.reshape(n_lat, n_lon, len(times))
    except Exception as e:  # noqa: BLE001
        return None, None, None, None, f"网格重构失败: {e}（n_lat={n_lat}, n_lon={n_lon}）"

    lats_arr = np.array(sorted(set(round(x, 4) for x in grid_lats)))
    lons_arr = np.array(sorted(set(round(x, 4) for x in grid_lons)))
    result = (lats_arr, lons_arr, times, field3d, None)
    st.session_state[cache_key] = result
    return result


# ============================================================
# 三、高温/体感指数
# ============================================================
def heat_index(temp_c, rh):
    """Rothfusz 热指数 (℃)。

    仅在 T >= 26.7℃ 且 RH > 40% 时有效，其余返回 NaN。
    用于高温预报面板中作为「计算热指数」参考。
    """
    t = np.asarray(temp_c, dtype=float)
    r = np.asarray(rh, dtype=float)
    hi = np.full_like(t, np.nan, dtype=float)
    mask = (t >= 26.7) & (r > 40)
    if not mask.any():
        return hi
    tt = t[mask]
    rr = r[mask]
    hi_val = (
        -8.78469475556
        + 1.61139411 * tt
        + 2.338548842 * rr
        - 0.14611605 * tt * rr
        - 0.012308094 * tt ** 2
        - 0.016424828 * rr ** 2
        + 0.002211732 * tt ** 2 * rr
        + 0.00072546 * tt * rr ** 2
        - 0.000003582 * tt ** 2 * rr ** 2
    )
    hi[mask] = hi_val
    return hi


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
                   name="气温", line=dict(color=COLORS["temp_color"], width=2.2),
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
               marker_color=COLORS["rain_color"], opacity=0.55,
               width=36000000,  # 12h in ms
               hovertemplate="%{x|%m-%d %H:%M} (12h)<br>降水: %{y:.1f} mm<extra></extra>"),
        secondary_y=True,
    )

    # ---- 当前时刻竖线 ----
    t_min = fdf["timestamp"].min()
    t_max = fdf["timestamp"].max()
    if t_min <= now <= t_max:
        fig.add_vline(x=now, line_width=2, line_dash="dash",
                      line_color="#d0021b",
                      annotation_text="现在",
                      annotation_position="top left",
                      annotation_font=dict(size=11, color="#d0021b"))

    # ---- Q3: 预报可信度标注 ----
    n_days = int((t_max - t_min).total_seconds() / 86400)
    fig.add_annotation(
        x=0.98, y=0.98, xref="paper", yref="paper",
        text=("可信度: <span style='color:#2ca02c'>0-3天高</span> | "
              "<span style='color:#f5a623'>4-7天中</span> | "
              "<span style='color:#d0021b'>8+天低</span>"),
        showarrow=False, font=dict(size=10),
        bgcolor="rgba(15,23,42,0.9)" if _is_dark() else "rgba(255,255,255,0.82)",
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
            bgcolor="rgba(15,23,42,0.9)" if _is_dark() else "rgba(255,255,255,0.85)",
            bordercolor="#475569" if _is_dark() else "#ddd", borderwidth=1,
        ),
    )
    return fig


def _high_temp_72h_panel(hh):
    """72 小时高温预报面板（含 35/37/40℃ 国家预警阈值参考线）"""
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    fig.add_trace(go.Scatter(
        x=hh["timestamp"], y=hh["temperature"], mode="lines+markers",
        name="气温", line=dict(color=COLORS["temp_color"], width=2), marker=dict(size=4),
    ))
    fig.add_trace(go.Scatter(
        x=hh["timestamp"], y=hh["apparent_temperature"], mode="lines",
        name="体感温度", line=dict(color="#e67e22", width=2),
    ))
    for thr, name, color in [(35, "高温黄 35℃", "#f5a623"),
                             (37, "高温橙 37℃", "#f26522"),
                             (40, "高温红 40℃", "#d0021b")]:
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
            bgcolor="rgba(15,23,42,0.9)" if _is_dark() else "rgba(255,255,255,0.85)",
            bordercolor="#475569" if _is_dark() else "#ddd", borderwidth=1,
        ),
    )
    return fig


def _daily_precip_chart(fdf):
    """逐日降水量柱状图"""
    daily = fdf.groupby(fdf["timestamp"].dt.date)["precipitation"].sum()
    fig = go.Figure(go.Bar(
        x=[str(d) for d in daily.index], y=daily.values,
        marker_color=COLORS["rain_color"],
        hovertemplate="日期 %{x}<br>降水 %{y:.1f} mm<extra></extra>",
    ))
    fig.update_layout(
        title="逐日降水量预报",
        xaxis_title="日期", yaxis_title="降水 (mm)",
        height=320, margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig


# R3: 自适应色阶 — 变量类型 → 最适合的 colormap
_COLORMAP_BY_VAR = {
    "temperature_2m": "RdBu_r",
    "precipitation": "Blues",
    "surface_pressure": "Viridis",
    "wind_speed_10m": "YlOrRd",
}

# 距平模式专用色阶（蓝=低于均值，白=均值，红=高于均值）
_ANOMALY_COLORMAP = "RdBu_r"


def _build_single_heatmap(field2d, lons, lats, vname, lon, lat,
                           title, cmap, show_contour=True):
    """构建单张热力图的 Figure（R1+R2+R3 核心）。"""
    fig = go.Figure()

    # R1: zsmooth 插值平滑
    fig.add_trace(go.Heatmap(
        z=field2d, x=lons, y=lats,
        colorscale=cmap,
        zsmooth="best",
        colorbar=dict(
            title=dict(text=vname, side="right", font=dict(size=13)),
            thickness=15, len=0.95, tickfont=dict(size=11),
        ),
        hovertemplate="经度 %{x:.2f}E<br>纬度 %{y:.2f}N<br>" + vname + ": %{z:.1f}<extra></extra>",
    ))

    # R2: 等值线叠加（半透明黑线，间距根据数据范围自适应）
    if show_contour:
        valid = field2d[np.isfinite(field2d)]
        if len(valid) >= 4:
            vmin, vmax = float(np.min(valid)), float(np.max(valid))
            span = vmax - vmin
            if span > 0:
                size = max(span / 8, 0.1)
                fig.add_trace(go.Contour(
                    z=field2d, x=lons, y=lats,
                    contours=dict(
                        start=vmin + size * 0.5,
                        end=vmax - size * 0.5,
                        size=size,
                    ),
                    line=dict(color="rgba(40,40,40,0.45)", width=0.8),
                    showscale=False, showlegend=False,
                    hovertemplate="",
                ))

    # 目标点标记
    fig.add_trace(go.Scatter(
        x=[lon], y=[lat], mode="markers+text", name="目标点",
        marker=dict(color="black", size=16, symbol="x", line=dict(width=2)),
        text=["目标"], textposition="middle right",
        textfont=dict(size=11, color="#e2e8f0" if _is_dark() else "#333"),
        hovertemplate="目标点 (%.2fN, %.2fE)<extra></extra>" % (lat, lon),
    ))
    fig.update_layout(
        title=dict(text=title, y=0.01, x=0.5, xanchor="center", yanchor="bottom",
                   font=dict(size=13)),
        xaxis_title=dict(text="经度 (E)", font=dict(size=12)),
        yaxis_title=dict(text="纬度 (N)", font=dict(size=12)),
        xaxis=dict(tickfont=dict(size=10), tickformat=".2f"),
        yaxis=dict(scaleanchor="x", scaleratio=1, tickfont=dict(size=10), tickformat=".2f"),
        height=400, margin=dict(l=50, r=50, t=25, b=50),
    )
    return fig


def _spatial_heatmap(lats, lons, times, field3d, lat, lon, hour_idx, variable,
                     mode="single"):
    """空间图三种模式。

    mode:
      "single"  — R1+R2+R3: 单时次插值热力图 + 等值线 + 自适应色阶
      "panel"   — R4: 2x2 多时次快照，自动取 4 个均匀间隔时次
      "anomaly" — R5: 距平模式 (格点值 − 全场均值)，突出异常区域

    返回: (fig, stats_dict) — panel 模式时 stats 为 None
    """
    field2d = field3d[:, :, hour_idx]
    vname = SPATIAL_VAR_LABELS.get(variable, variable)
    cmap = _COLORMAP_BY_VAR.get(variable, "RdYlBu_r")

    # 统计量
    valid = field2d[np.isfinite(field2d)]
    stats = {
        "min": float(np.min(valid)) if len(valid) > 0 else float("nan"),
        "max": float(np.max(valid)) if len(valid) > 0 else float("nan"),
        "mean": float(np.mean(valid)) if len(valid) > 0 else float("nan"),
        "n_points": int(field2d.size),
        "grid_shape": f"{field2d.shape[0]}x{field2d.shape[1]}",
        "time_str": str(times[hour_idx]),
    }

    if mode == "panel":
        # R4: 2x2 时次快照
        n_times = len(times)
        n_rows, n_cols = 2, 2
        # 取 4 个均匀间隔时次
        if n_times >= 4:
            indices = [
                int(n_times * 0.0),
                int(n_times * 0.25),
                int(n_times * 0.5),
                int(n_times * 0.75),
            ]
            indices = sorted(set(max(0, min(i, n_times - 1)) for i in indices))
            while len(indices) < 4:
                indices.append(min(indices[-1] + 1, n_times - 1))
            indices = sorted(set(indices))[:4]
        else:
            indices = list(range(n_times))
            while len(indices) < 4:
                indices.append(indices[-1])

        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=n_rows, cols=n_cols,
            subplot_titles=[str(times[i]) for i in indices],
            horizontal_spacing=0.08, vertical_spacing=0.12,
        )
        for idx_pos, t_idx in enumerate(indices):
            row = idx_pos // n_cols + 1
            col = idx_pos % n_cols + 1
            mono_fig = _build_single_heatmap(
                field3d[:, :, t_idx], lons, lats, vname, lon, lat,
                "", cmap, show_contour=True,
            )
            for trace in mono_fig.data:
                if hasattr(trace, "colorbar"):
                    trace.showscale = False if idx_pos < 3 else True
                fig.add_trace(trace, row=row, col=col)
        # 共享 x/y
        for row in range(1, n_rows + 1):
            for col in range(1, n_cols + 1):
                fig.update_xaxes(
                    title_text="经度 (E)" if row == n_rows else None,
                    tickfont=dict(size=9), tickformat=".2f",
                    row=row, col=col,
                )
                fig.update_yaxes(
                    title_text="纬度 (N)" if col == 1 else None,
                    scaleanchor="x", scaleratio=1,
                    tickfont=dict(size=9), tickformat=".2f",
                    row=row, col=col,
                )
        fig.update_layout(
            title=dict(text=f"{vname} 多时次快照", y=0.01, x=0.5,
                       xanchor="center", yanchor="bottom", font=dict(size=14)),
            height=720, margin=dict(l=50, r=50, t=30, b=50),
            showlegend=False,
        )
        return fig, None

    if mode == "anomaly":
        # R5: 距平模式
        mean_val = stats["mean"]
        anomaly = field2d - mean_val
        fig = go.Figure(go.Heatmap(
            z=anomaly, x=lons, y=lats,
            colorscale=_ANOMALY_COLORMAP,
            zsmooth="best",
            zmid=0,
            colorbar=dict(
                title=dict(text=f"{vname} 距平", side="right", font=dict(size=13)),
                thickness=15, len=0.95, tickfont=dict(size=11),
            ),
            hovertemplate="经度 %{x:.2f}E<br>纬度 %{y:.2f}N<br>距平: %{z:+.1f}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[lon], y=[lat], mode="markers+text", name="目标点",
            marker=dict(color="black", size=16, symbol="x", line=dict(width=2)),
            text=["目标"], textposition="middle right",
            textfont=dict(size=11, color="#e2e8f0" if _is_dark() else "#333"),
            hovertemplate="目标点 (%.2fN, %.2fE)<extra></extra>" % (lat, lon),
        ))
        fig.update_layout(
            title=dict(text=f"{vname} 距平空间分布 (均值={mean_val:.1f})",
                       y=0.01, x=0.5, xanchor="center", yanchor="bottom",
                       font=dict(size=14)),
            xaxis_title=dict(text="经度 (E)", font=dict(size=13)),
            yaxis_title=dict(text="纬度 (N)", font=dict(size=13)),
            xaxis=dict(tickfont=dict(size=11), tickformat=".2f"),
            yaxis=dict(scaleanchor="x", scaleratio=1, tickfont=dict(size=11), tickformat=".2f"),
            height=520, margin=dict(l=50, r=50, t=45, b=50),
        )
        # 距平统计
        av = anomaly[np.isfinite(anomaly)]
        stats["min"] = float(np.min(av)) if len(av) > 0 else float("nan")
        stats["max"] = float(np.max(av)) if len(av) > 0 else float("nan")
        stats["mean"] = float(np.mean(av)) if len(av) > 0 else float("nan")
        return fig, stats

    # mode == "single" (default) — R1+R2+R3
    fig = _build_single_heatmap(
        field2d, lons, lats, vname, lon, lat,
        f"{vname} 空间分布 @ {times[hour_idx]}",
        cmap, show_contour=True,
    )
    return fig, stats


# ============================================================
# 五、智能分析与建议
# ============================================================
def _analyze_forecast(fdf):
    """分析 GFS 预报数据（增强版：6h 滚动 + 趋势置信 + 连续事件 + 昼夜温差）。

    返回 dict：
      warnings, extremes, trends, coupling, summary, recommendations,
      precision (新增: 趋势数值详情, 6h断片, 连续事件, 日较差)
    """
    daily = fdf.copy()
    daily["date"] = fdf["timestamp"].dt.date
    # 6h 滚动窗口
    daily["hour6"] = daily["timestamp"].dt.floor("6h")

    dmax_t = daily.groupby("date")["temperature"].max()
    dmin_t = daily.groupby("date")["temperature"].min()
    dprecip = daily.groupby("date")["precipitation"].sum()
    dmax_ws = daily.groupby("date")["wind_speed"].max()
    davg_rh = daily.groupby("date")["humidity"].mean()
    # 昼夜温差
    diurnal = dmax_t - dmin_t

    # 6h 聚合：温度和降水
    h6_temp = daily.groupby("hour6")["temperature"].max()
    h6_precip = daily.groupby("hour6")["precipitation"].sum()

    ndays = len(dmax_t)
    results = {
        "warnings": [],
        "extremes": {},
        "trends": {},
        "coupling": [],
        "summary": "",
        "recommendations": {"travel": [], "agri": []},
        "precision": {},  # 新增精度信息
    }

    # ----- 1. 高温预警（含连续事件检测）-----
    hot = dmax_t[dmax_t >= 35]
    # 连续高温检测
    consecutive_hot = 0
    max_consec_hot = 0
    hot_streak_dates = []
    for d, val in dmax_t.items():
        if val >= 35:
            consecutive_hot += 1
            if consecutive_hot > max_consec_hot:
                max_consec_hot = consecutive_hot
                hot_streak_dates = list(dmax_t.index)[max(0, dmax_t.index.get_loc(d) - consecutive_hot + 1):dmax_t.index.get_loc(d) + 1]
        else:
            consecutive_hot = 0
    results["precision"]["consecutive_hot"] = max_consec_hot
    results["precision"]["hot_streak"] = [str(d) for d in hot_streak_dates]

    if len(hot) > 0:
        peak = hot.max()
        peak_date = str(hot.idxmax())
        if peak >= 40:
            level, lv_num, icon_ = "红色", "I级", "[红]"
        elif peak >= 37:
            level, lv_num, icon_ = "橙色", "II级", "[橙]"
        else:
            level, lv_num, icon_ = "黄色", "III级", "[黄]"
        hot_detail = f"未来{ndays}天中{len(hot)}天日最高气温>=35C，峰值{peak:.1f}C ({peak_date})"
        if max_consec_hot >= 3:
            hot_detail += f"，其中连续{max_consec_hot}天高温（"
            hot_detail += "~".join(hot_streak_dates[:2]) if len(hot_streak_dates) >= 2 else hot_streak_dates[0]
            hot_detail += "）"
        hot_detail += "。"
        results["warnings"].append({
            "type": "高温", "level": level, "level_num": lv_num,
            "detail": hot_detail, "icon": icon_,
        })

    # ----- 2. 暴雨预警（含连续降水检测 + 强度分类）-----
    # 降水强度分类
    precip_cats = {"大雨(25-50mm)": 0, "暴雨(50-100mm)": 0, "大暴雨(>=100mm)": 0}
    heavy = dprecip[dprecip >= 25]
    consecutive_rain = 0
    max_consec_rain = 0
    for d, val in dprecip.items():
        if val >= 0.1:
            consecutive_rain += 1
            max_consec_rain = max(max_consec_rain, consecutive_rain)
        else:
            consecutive_rain = 0
    results["precision"]["consecutive_rain"] = max_consec_rain

    for d, val in dprecip.items():
        if val >= 100:
            precip_cats["大暴雨(>=100mm)"] += 1
            lv, lnum = "红色", "I级"
        elif val >= 75:
            precip_cats["暴雨(50-100mm)"] += 1
            lv, lnum = "橙色", "II级"
        elif val >= 50:
            precip_cats["暴雨(50-100mm)"] += 1
            lv, lnum = "黄色", "III级"
        elif val >= 25:
            precip_cats["大雨(25-50mm)"] += 1
            continue
        else:
            continue
        results["warnings"].append({
            "type": "暴雨", "level": lv, "level_num": lnum,
            "detail": f"{d} 日降水量 {val:.1f} mm，需关注短时强降水。",
            "icon": "[暴]",
        })
    results["precision"]["precip_cats"] = precip_cats
    # 6h 最大降水片段
    if len(h6_precip) > 0:
        results["precision"]["max_6h_precip"] = (float(h6_precip.max()), str(h6_precip.idxmax()))

    # ----- 3. 大风预警 -----
    windy = dmax_ws[dmax_ws >= 10.8]
    for d, val in windy.items():
        if val >= 24.5:
            lv, lnum = "橙色", "II级"
        elif val >= 17.2:
            lv, lnum = "黄色", "III级"
        elif val >= 10.8:
            lv, lnum = "蓝色", "IV级"
        else:
            continue
        results["warnings"].append({
            "type": "大风", "level": lv, "level_num": lnum,
            "detail": f"{d} 最大风速 {val:.1f} m/s，需注意户外作业安全。",
            "icon": "[风]",
        })

    # ----- 4. 极端值 + 日较差 -----
    results["extremes"] = {
        "max_temp": (float(dmax_t.max()), str(dmax_t.idxmax())),
        "min_temp": (float(dmin_t.min()), str(dmin_t.idxmin())),
        "max_daily_precip": (float(dprecip.max()), str(dprecip.idxmax())),
        "total_precip": float(dprecip.sum()),
        "max_wind": (float(dmax_ws.max()), str(dmax_ws.idxmax())),
        "ndays": ndays,
    }
    results["precision"]["diurnal"] = {
        "max_range": (float(diurnal.max()), str(diurnal.idxmax())),
        "mean_range": float(diurnal.mean()),
        "warm_nights": int((dmin_t >= 25).sum()),  # 热带夜
    }

    # ----- 5. 趋势（含置信区间 + 波动） -----
    first3 = dmax_t.iloc[:min(3, ndays)]
    last3 = dmax_t.iloc[-min(3, ndays):]
    diff_mean = last3.mean() - first3.mean()
    diff_std = np.sqrt(first3.std() ** 2 + last3.std() ** 2)
    t_parts = []
    if abs(diff_mean) > 3:
        t_parts.append("明显" + ("升温" if diff_mean > 0 else "降温"))
    elif abs(diff_mean) > 1:
        t_parts.append("小幅" + ("升温" if diff_mean > 0 else "降温"))
    else:
        t_parts.append("基本平稳")
    t_trend = t_parts[0]
    # 波动程度
    overall_std = float(dmax_t.std())
    if overall_std > 5:
        t_volatility = "剧烈波动"
    elif overall_std > 3:
        t_volatility = "波动较大"
    elif overall_std > 1.5:
        t_volatility = "小幅波动"
    else:
        t_volatility = "变化平缓"
    results["trends"]["temperature"] = t_trend
    results["precision"]["temp_trend"] = {
        "diff_mean": float(diff_mean),
        "diff_std": float(diff_std),
        "overall_std": overall_std,
        "volatility": t_volatility,
    }

    # 降水趋势（含强度分布）
    precip_days = int((dprecip > 0.1).sum())
    results["trends"]["precip_days"] = precip_days
    if precip_days == 0:
        results["trends"]["precip"] = "全程无有效降水"
    elif precip_days <= ndays * 0.3:
        results["trends"]["precip"] = "降水日数较少"
    else:
        results["trends"]["precip"] = "降水日数偏多"
    # 降水强度摘要
    results["precision"]["precip_summary"] = (
        f"大雨{precip_cats.get('大雨(25-50mm)', 0)}天，"
        f"暴雨{precip_cats.get('暴雨(50-100mm)', 0)}天，"
        f"大暴雨{precip_cats.get('大暴雨(>=100mm)', 0)}天。"
        if any(precip_cats.values()) else None
    )

    # ----- 6. 耦合分析（含 SSD 体感舒适度联动）-----
    if len(hot) > 0:
        hot_dates = list(hot.index)
        hot_rh = davg_rh.loc[[d for d in hot_dates if d in davg_rh.index]]
        if len(hot_rh) > 0 and hot_rh.mean() > 60:
            # 计算 SSD 体感舒适度
            hot_ws = dmax_ws.loc[[d for d in hot_dates if d in dmax_ws.index]]
            ssd_hot = _calc_ssd(hot.max(), hot_rh.mean(), hot_ws.mean() if len(hot_ws) > 0 else 2)
            ssd_note = f"，体感舒适度 SSD={ssd_hot:.1f}（炎热不舒适）" if ssd_hot >= 29 else ""
            results["coupling"].append({
                "type": "热应激风险", "severity": "危险",
                "detail": f"高温({hot.max():.1f}C)叠加高湿({hot_rh.mean():.0f}%)，体感温度显著升高{ssd_note}，户外活动需防范中暑。",
                "icon": "[热]",
            })
    if len(windy) > 0 and len(heavy) > 0:
        overlap = set(windy.index) & set(heavy.index)
        if overlap:
            results["coupling"].append({
                "type": "风雨耦合", "severity": "危险",
                "detail": f"{len(overlap)} 天同时出现大风和强降水，出行风险加剧。",
                "icon": "[风]",
            })
    # 昼夜温差过大
    if diurnal.max() >= 15:
        results["coupling"].append({
            "type": "温差过大", "severity": "注意",
            "detail": f"日较差最大达 {diurnal.max():.1f}C ({diurnal.idxmax()})，昼夜温差显著，注意适时增减衣物。",
            "icon": "[差]",
        })
    # 热带夜
    warm_nights = int((dmin_t >= 25).sum())
    if warm_nights > 0:
        results["coupling"].append({
            "type": "夜间闷热", "severity": "注意",
            "detail": f"{warm_nights} 天夜间最低温 >=25C（热带夜），影响睡眠质量，注意通风降温。",
            "icon": "[夜]",
        })

    # ----- 7. 总述（更精准） -----
    parts = [f"未来{ndays}天气温{t_trend} ({diff_mean:+.1f}C, 波动 {t_volatility}, 标准差 {overall_std:.1f}C)"]
    if precip_days > 0:
        parts.append(f"共{precip_days}个降水日，累计{results['extremes']['total_precip']:.0f} mm")
        if max_consec_rain >= 3:
            parts.append(f"最长连续{max_consec_rain}天有降水")
    else:
        parts.append("全程无明显降水")
    if len(results["warnings"]) > 0:
        types = set(w["type"] for w in results["warnings"])
        parts.append(f"触发{'/'.join(types)}预警信号")
    else:
        parts.append("无预警风险")
    results["summary"] = "。".join(parts) + "。"

    # ----- 8. 建议（比原有更细） -----
    t = {"travel": results["recommendations"]["travel"],
         "agri": results["recommendations"]["agri"]}

    if len(hot) > 0:
        t["travel"].append(f"未来{len(hot)}天有高温 ({hot.max():.0f}C)，外出避开 11:00-15:00 时段，备足饮水。")
        t["agri"].append(f"高温天气 ({len(hot)} 天 >=35C, 连续最多{max_consec_hot}天)：及时灌溉降温；设施大棚覆盖遮阳网；禽畜采取喷淋降温。")

    if max_consec_hot >= 5:
        t["travel"].append(f"连续{max_consec_hot}天高温将形成热浪，老人/儿童/慢性病患者避免户外活动。")
        t["agri"].append(f"热浪持续{max_consec_hot}天：增加灌溉频次至每日2-3次；大棚强制通风降温。")

    if len(heavy) > 0:
        t["travel"].append("强降水日外出备雨具，低洼路段注意内涝；涉水谨慎。")
        t["agri"].append("注意清沟排水；加固大棚基础；鱼塘检查防逃设施。")

    if precip_cats.get("大暴雨(>=100mm)", 0) > 0:
        t["travel"].append("预报有大暴雨：尽量避免出行；远离河道和低洼地区。")

    if len(windy) > 0:
        t["travel"].append("大风天气远离广告牌/临时搭建物；高空作业暂停。")
        t["agri"].append("加固设施农业骨架；收起晾晒物；检查禽畜舍牢固性。")

    if precip_days == 0 and len(hot) > 0:
        t["agri"].append("高温少雨天气：增加灌溉频次，严防干旱；旱地作物覆盖保墒。")

    if warm_nights > 0:
        t["travel"].append(f"{warm_nights}天热带夜(夜间>=25C)：睡前通风，空调温度不宜过低。")

    if diurnal.max() >= 15:
        t["travel"].append(f"昼夜温差大 ({diurnal.max():.0f}C)：早晚凉午间热，建议叠穿方便增减。")

    if len(results["coupling"]) > 0:
        for c in results["coupling"]:
            if c["severity"] == "危险":
                t["travel"].append(f"[{c['type']}] {c['detail']}")

    # 去重 + 限制条数
    for k in ("travel", "agri"):
        seen = set()
        uniq = []
        for s in t[k]:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        results["recommendations"][k] = uniq[:8]

    return results


def _render_forecast_advice(analysis, life_indices=None):
    """渲染预报智能分析结果。life_indices 传入后作为子节嵌入到『预报精度详情』之前。"""
    from config import WARN_STYLES

    st.write("---")
    st.write("### 智能分析与建议")

    # 总述
    st.markdown(f"**总结**：{analysis['summary']}")

    # 极端值卡片（统一卡片样式）
    ex = analysis["extremes"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(_uni_card("最高气温", f"{ex['max_temp'][0]:.0f}", "C",
                               delta=ex["max_temp"][1], color="#ef4444"), unsafe_allow_html=True)
    with c2:
        st.markdown(_uni_card("最低气温", f"{ex['min_temp'][0]:.0f}", "C",
                               delta=ex["min_temp"][1], color="#3b82f6"), unsafe_allow_html=True)
    with c3:
        st.markdown(_uni_card("累计降水", f"{ex['total_precip']:.0f}", " mm",
                               color="#22c55e"), unsafe_allow_html=True)
    with c4:
        st.markdown(_uni_card("最大风速", f"{ex['max_wind'][0]:.1f}", "m/s",
                               delta=ex["max_wind"][1], color="#f59e0b"), unsafe_allow_html=True)

    # 预警
    if analysis["warnings"]:
        st.write("#### 预警信号")
        sorted_w = sorted(analysis["warnings"], key=lambda w: WARN_LEVEL_ORDER.get(w["level"], 4))
        cols = st.columns(min(len(sorted_w), 2))
        dark_ws = {
            "蓝色": {"color": "#60a5fa", "bg": "#1e3a5f"},
            "黄色": {"color": "#f59e0b", "bg": "#3d2e0c"},
            "橙色": {"color": "#fb923c", "bg": "#3d1f0c"},
            "红色": {"color": "#ef4444", "bg": "#3d0c0c"},
        }
        for i, warn in enumerate(sorted_w):
            style = dark_ws.get(warn["level"], dark_ws["蓝色"]) if _is_dark() else WARN_STYLES.get(warn["level"], WARN_STYLES["蓝色"])
            detail_color = "#94a3b8" if _is_dark() else "#555"
            with cols[i % 2]:
                st.markdown(f"""<div style="background:{style['bg']};border-left:4px solid {style['color']};padding:10px 12px;border-radius:4px;margin-bottom:6px;font-size:13px">
<b style="color:{style['color']};font-size:15px">{warn['icon']} {warn['type']}{warn['level']}</b>
<br><span style="color:{detail_color}">{warn['level_num']} | {warn['detail']}</span></div>""", unsafe_allow_html=True)
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
                                       delta=f"±{tt['diff_std']:.1f}C", color="#8b5cf6"), unsafe_allow_html=True)
            with c2:
                st.markdown(_uni_card("波动程度", tt.get("volatility", ""), "",
                                       delta=f"标准差 {tt['overall_std']:.1f}C", color="#06b6d4"), unsafe_allow_html=True)
            with c3:
                hot_days = prec.get("consecutive_hot", 0)
                d = f"最长 {hot_days} 天" if hot_days > 0 else None
                st.markdown(_uni_card("连续高温", f"{hot_days}", " 天",
                                       delta=d, color="#ef4444"), unsafe_allow_html=True)
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
    """按当前真实时间在 fdf 中查找对应小时行，session 内跨小时会推进。
    缓存策略不变（仍是 fetch 时的预报），仅切换"当前小时"指针。
    """
    if fdf is None or fdf.empty:
        return None
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    if "timestamp" in fdf.columns:
        mask = fdf["timestamp"] >= now
        if mask.any():
            return fdf[mask].iloc[0]
    return fdf.iloc[-1]


# ============================================================
# 通用统计卡片（统一视觉语言，替代 st.metric）
# ============================================================
def _uni_card(label, value, unit="", delta=None, color="#3b82f6", dark=None):
    """通用统计卡片：彩色左边框 + 标签/大值/副文本，统一替代 st.metric()"""
    if dark is None:
        dark = _is_dark()
    bg = "#1e293b" if dark else "#ffffff"
    border = "#334155" if dark else "#e2e8f0"
    label_c = "#94a3b8" if dark else "#64748b"
    val_c = "#e2e8f0" if dark else "#1e293b"

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

    # 实时空气质量（国标 HJ 633-2012）
    aq_aqi, aq_level, aq_primary, aq_color = None, "—", "—", "#94a3b8"
    if lat is not None and lon is not None:
        try:
            _, _aq_cur, _aq_err = fetch_air_quality(lat, lon, 1)
            if _aq_cur:
                aq_aqi, aq_level, aq_primary, aq_color = _compute_cn_aqi(_aq_cur)
        except Exception:  # noqa: BLE001
            pass

    bf_level, bf_name = get_beaufort_level(wind)
    dark = _is_dark()

    # --- 干湿描述 ---
    if humid >= 80:
        humid_desc = "潮湿"
        humid_color = "#3b82f6"
    elif humid >= 60:
        humid_desc = "湿润"
        humid_color = "#06b6d4"
    elif humid >= 40:
        humid_desc = "舒适"
        humid_color = "#22c55e"
    else:
        humid_desc = "干燥"
        humid_color = "#f59e0b"

    # --- 降水概率描述 ---
    if precip_prob >= 70:
        prob_desc = "很可能下雨"
        prob_color = "#3b82f6"
    elif precip_prob >= 40:
        prob_desc = "有可能下雨"
        prob_color = "#06b6d4"
    elif precip_prob >= 10:
        prob_desc = "基本无雨"
        prob_color = "#22c55e"
    else:
        prob_desc = "晴朗"
        prob_color = "#f59e0b"

    bg = "#1e293b" if dark else "#ffffff"
    border = "#334155" if dark else "#e2e8f0"
    label_color = "#94a3b8" if dark else "#64748b"
    val_color = "#e2e8f0" if dark else "#1e293b"

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
                         f"体感 {app_temp:.1f}C", "#ef4444"), unsafe_allow_html=True)
    with c2:
        st.markdown(_card("[W]", f"风力 {bf_level}级", f"{wind:.1f}", "m/s",
                         bf_name, "#f39c12"), unsafe_allow_html=True)
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
                             "暂无数据", "#94a3b8"), unsafe_allow_html=True)


# ============================================================
# 五-3、生活指标计算 + 渲染
# ============================================================

def _calc_ssd(temp, humidity, wind_speed):
    """体感舒适度指数 (Thom Discomfort Index)
    SSD = T - 0.55*(1-RH)*(T-14) - V^(1/3)*(T-10)/20
    高值(>=29)表示炎热不舒适，低值(<10)表示寒冷不舒适，15-19为舒适区。
    """
    T = float(temp)
    RH = float(humidity) / 100.0
    V = max(float(wind_speed), 0.1)  # 防除零
    return T - 0.55 * (1 - RH) * (T - 14) - (V ** (1/3)) * (T - 10) / 20


def _calc_life_indices(fdf):
    """计算 7 项生活指标，返回 dict。优先用 Open-Meteo current= 真实时数据。"""
    if fdf is None or fdf.empty:
        return {}

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
        humid = float(cur.get("humidity") or 50)
        wind = float(cur.get("wind_speed") or 2)
        precip = float(cur.get("precipitation") or 0)
        precip_prob = float(cur.get("precipitation_probability") or 0)
        wcode = float(cur.get("weather_code") or 0)
    else:
        # Fallback: fdf 当前小时行
        now_row = _get_now_row(fdf)
        if now_row is None:
            return {}
        temp = float(now_row.get("temperature", 20))
        app_temp = float(now_row.get("apparent_temperature", temp))
        humid = float(now_row.get("humidity", 50))
        wind = float(now_row.get("wind_speed", 2))
        precip = float(now_row.get("precipitation", 0))
        precip_prob = float(now_row.get("precipitation_probability", 0))
        wcode = float(now_row.get("weather_code", 0))

    # 取未来 72h 数据用于部分指标(始终从 fdf 取,不受真实时接口影响)
    h72 = fdf.head(72) if len(fdf) >= 72 else fdf

    avg_temp_72 = float(h72["temperature"].mean())
    total_precip_72 = float(h72["precipitation"].sum())
    avg_humid_72 = float(h72["humidity"].mean())
    avg_wind_72 = float(h72["wind_speed"].mean())

    ssd = _calc_ssd(temp, humid, wind)

    indices = {}

    # 1. 穿衣指数
    ref_temp = app_temp if abs(app_temp - temp) > 2 else temp
    if ref_temp < 5:
        indices["clothing"] = {"level": "厚冬装", "score": 5, "advice": "羽绒/棉服+毛衣+保暖内衣", "color": "#3b82f6"}
    elif ref_temp < 12:
        indices["clothing"] = {"level": "初冬装", "score": 4, "advice": "风衣/外套+毛衣或薄羽绒", "color": "#06b6d4"}
    elif ref_temp < 18:
        indices["clothing"] = {"level": "春秋装", "score": 3, "advice": "薄外套/夹克+长裤", "color": "#22c55e"}
    elif ref_temp < 25:
        indices["clothing"] = {"level": "轻便", "score": 2, "advice": "长袖/薄衫+单裤", "color": "#84cc16"}
    elif ref_temp < 30:
        indices["clothing"] = {"level": "夏装", "score": 1, "advice": "短袖/短裤/短裙", "color": "#f59e0b"}
    else:
        indices["clothing"] = {"level": "酷热", "score": 0, "advice": "透气浅色衣物，注意防晒", "color": "#ef4444"}

    # 2. 带伞建议
    rain_codes = set(range(50, 70)) | set(range(80, 87)) | set(range(95, 100))
    has_rain_code = wcode in rain_codes
    if total_precip_72 > 10 or (has_rain_code and precip > 0.5):
        indices["umbrella"] = {"level": "必带伞", "score": 3, "advice": "未来72h有明显降水，出门务必带伞", "color": "#3b82f6"}
    elif total_precip_72 > 0.1 or precip_prob >= 40 or has_rain_code:
        indices["umbrella"] = {"level": "建议备伞", "score": 2, "advice": "有降水可能，建议随身携带雨具", "color": "#06b6d4"}
    else:
        indices["umbrella"] = {"level": "无需带伞", "score": 0, "advice": "未来72h无明显降水", "color": "#22c55e"}

    # 3. 体感舒适度 (Thom 不适指数: 高值=炎热, 低值=寒冷, 15-19=舒适)
    if ssd >= 29:
        indices["comfort"] = {"level": "炎热不舒适", "score": round(ssd, 1), "advice": "体感闷热，减少户外停留，注意防暑", "color": "#ef4444"}
    elif ssd >= 24:
        indices["comfort"] = {"level": "偏热", "score": round(ssd, 1), "advice": "多数人感到偏热，注意通风降温", "color": "#f59e0b"}
    elif ssd >= 20:
        indices["comfort"] = {"level": "较舒适", "score": round(ssd, 1), "advice": "少部分人可能感觉微热", "color": "#eab308"}
    elif ssd >= 15:
        indices["comfort"] = {"level": "舒适", "score": round(ssd, 1), "advice": "体感舒适宜人，适合户外活动", "color": "#22c55e"}
    elif ssd >= 10:
        indices["comfort"] = {"level": "偏凉", "score": round(ssd, 1), "advice": "体感偏凉，适当添衣", "color": "#06b6d4"}
    else:
        indices["comfort"] = {"level": "寒冷不舒适", "score": round(ssd, 1), "advice": "体感寒冷，注意保暖防寒", "color": "#3b82f6"}

    # 4. 运动指数
    exercise_score = 100
    # 偏离舒适区(15-19)越远越不适合运动
    if ssd >= 29:
        exercise_score -= min(40, (ssd - 29) * 8)  # 炎热扣分
    elif ssd < 10:
        exercise_score -= min(40, (10 - ssd) * 8)  # 寒冷扣分
    exercise_score -= min(30, total_precip_72 * 2)
    exercise_score -= min(20, max(0, (avg_wind_72 - 10.8) * 3))
    if exercise_score >= 70:
        indices["exercise"] = {"level": "适宜", "score": int(exercise_score), "advice": "天气适合户外运动", "color": "#22c55e"}
    elif exercise_score >= 50:
        indices["exercise"] = {"level": "较适宜", "score": int(exercise_score), "advice": "可适度户外活动", "color": "#84cc16"}
    elif exercise_score >= 30:
        indices["exercise"] = {"level": "一般", "score": int(exercise_score), "advice": "建议室内运动为主", "color": "#f59e0b"}
    else:
        indices["exercise"] = {"level": "不适宜", "score": int(exercise_score), "advice": "天气条件差，避免户外运动", "color": "#ef4444"}

    # 5. 紫外线指数 (天气码近似推断)
    sunny_codes = set(range(0, 3))
    cloudy_codes = set(range(3, 6)) | {45, 48}
    if wcode in sunny_codes and avg_temp_72 > 15:
        indices["uv"] = {"level": "很强", "score": 4, "advice": "紫外线强，外出涂防晒霜、戴帽子和太阳镜", "color": "#ef4444"}
    elif wcode in sunny_codes:
        indices["uv"] = {"level": "强", "score": 3, "advice": "紫外线较强，注意防晒", "color": "#f59e0b"}
    elif wcode in cloudy_codes:
        indices["uv"] = {"level": "中等", "score": 2, "advice": "紫外线中等，可适当防护", "color": "#eab308"}
    else:
        indices["uv"] = {"level": "低", "score": 1, "advice": "紫外线弱，无需特别防护", "color": "#22c55e"}

    # 6. 洗车指数 (72h 累计降水)
    if total_precip_72 < 0.1:
        indices["carwash"] = {"level": "适宜", "score": 3, "advice": "未来三天基本无雨，放心洗车", "color": "#22c55e"}
    elif total_precip_72 < 5:
        indices["carwash"] = {"level": "较适宜", "score": 2, "advice": "小雨可能，影响不大", "color": "#84cc16"}
    elif total_precip_72 < 15:
        indices["carwash"] = {"level": "一般", "score": 1, "advice": "有降水，建议暂缓洗车", "color": "#f59e0b"}
    else:
        indices["carwash"] = {"level": "不适宜", "score": 0, "advice": "雨水较多，别洗了", "color": "#ef4444"}

    # 7. 晾晒指数
    dry_score = 100
    dry_score -= min(40, total_precip_72 * 3)
    dry_score -= min(30, max(0, (avg_humid_72 - 70) * 2))
    dry_score += min(20, avg_wind_72 * 2)  # 微风有利晾晒
    if dry_score >= 70:
        indices["drying"] = {"level": "非常适宜", "score": int(dry_score), "advice": "天气干燥有风，适合晾晒衣物", "color": "#22c55e"}
    elif dry_score >= 50:
        indices["drying"] = {"level": "适宜", "score": int(dry_score), "advice": "可以晾晒，但注意天气变化", "color": "#84cc16"}
    elif dry_score >= 30:
        indices["drying"] = {"level": "一般", "score": int(dry_score), "advice": "湿度偏大，晾晒较慢", "color": "#f59e0b"}
    else:
        indices["drying"] = {"level": "不适宜", "score": int(dry_score), "advice": "潮湿多雨，不宜室外晾晒", "color": "#ef4444"}

    return indices


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

    dark = _is_dark()
    bg = "#1e293b" if dark else "#ffffff"
    border = "#334155" if dark else "#e2e8f0"
    label_color = "#94a3b8" if dark else "#64748b"
    val_color = "#e2e8f0" if dark else "#1e293b"

    def _card(key, info):
        icon, name = _LIFE_INDEX_META.get(key, ("[?]", key))
        level = info["level"]
        score = info["score"]
        advice = info["advice"]
        color = info["color"]
        score_text = f"{score}" if isinstance(score, int) else f"{score:.1f}"
        return f"""
        <div style="background:{bg};border:1px solid {border};border-radius:10px;
                    padding:14px 12px;position:relative;overflow:hidden;">
            <div style="position:absolute;left:0;top:0;bottom:0;width:4px;background:{color};"></div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
                <span style="font-size:0.82rem;color:{label_color};">{icon} {name}</span>
                <span style="font-size:0.75rem;font-weight:600;color:{color};background:{color}22;
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
    else:
        safe_chart(air_quality_aqi_chart(aq_df), "空气质量 AQI 预报", key="fc_aqi")
    st.caption(
        "数据来源：CAMS 全球大气成分预报（Open-Meteo Air Quality API，最长 7 天）。"
        "国标等级按 HJ 633-2012 计算，PM2.5/PM10 采用逐时近似。"
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

    # ---- 降水预报 ----
    st.write("### 降水预报")
    total_precip = float(fdf["precipitation"].sum())
    st.markdown(_uni_card("预报期累计降水", f"{total_precip:.1f}", " mm", color="#22c55e"), unsafe_allow_html=True)
    daily_fig = _daily_precip_chart(fdf)
    safe_chart(daily_fig, "逐日降水预报", key="fc_daily_precip")

    # ---- 空间图 ----
    st.write("---")
    st.write("### 空间图：区域预报场")
    st.caption("多模式视图：单时次热力图 + 等值线 | 多时次快照 | 距平异常检测 (无需 Mapbox Token)")

    # 视图模式选择
    spatial_mode = st.radio(
        "视图模式",
        ["single", "panel", "anomaly"],
        format_func=lambda m: {"single": "单时次 (等值线)", "panel": "多时次快照", "anomaly": "距平模式"}[m],
        horizontal=True, key="fc_spatial_mode",
    )

    scol1, scol2, scol3 = st.columns(3)
    with scol1:
        variable = st.selectbox("空间变量", list(SPATIAL_VAR_LABELS.keys()),
                                format_func=lambda v: SPATIAL_VAR_LABELS[v], key="fc_spatial_var")
    with scol2:
        step = st.slider("网格步长 (度)", 0.10, 1.0, 0.25, 0.05, key="fc_step")
    with scol3:
        half = st.slider("半宽 (度)", 0.5, 3.0, 1.0, 0.25, key="fc_half")

    if st.button("[空间] 生成空间预报场", use_container_width=True, key="fc_spatial"):
        with st.spinner("正在抓取网格预报..."):
            lats, lons, times, field3d, err = fetch_gfs_spatial_grid(
                lat, lon, step=step, half=half, days=days, model=model, variable=variable
            )
        if err:
            st.error(err)
        else:
            st.session_state["fc_grid"] = (lats, lons, times, field3d)
            st.session_state["fc_hour"] = 0
            n_total = len(lats) * len(lons)
            st.success(f"[OK] 网格 {len(lats)}x{len(lons)}={n_total} 点，共 {len(times)} 个时次")

    if "fc_grid" in st.session_state:
        lats, lons, times, field3d = st.session_state["fc_grid"]
        if spatial_mode == "single":
            hour_idx = st.slider("选择预报时次", 0, len(times) - 1,
                                 st.session_state.get("fc_hour", 0), key="fc_hour")
        else:
            hour_idx = 0  # panel/anomaly 模式不使用滑块
        try:
            map_fig, grid_stats = _spatial_heatmap(
                lats, lons, times, field3d, lat, lon, hour_idx, variable,
                mode=spatial_mode,
            )
        except Exception as e:  # noqa: BLE001
            st.error(f"空间图数据构建失败: {e}")
        else:
            safe_chart(map_fig, "区域预报场", key="fc_spatial_map")
            # 统计量（panel 模式无单一时次统计数据）
            if grid_stats is not None:
                sc1, sc2, sc3, sc4 = st.columns(4)
                with sc1:
                    st.markdown(_uni_card("最小值", f"{grid_stats['min']:+.1f}" if spatial_mode == "anomaly" else f"{grid_stats['min']:.1f}", color="#3b82f6"), unsafe_allow_html=True)
                with sc2:
                    st.markdown(_uni_card("最大值", f"{grid_stats['max']:+.1f}" if spatial_mode == "anomaly" else f"{grid_stats['max']:.1f}", color="#ef4444"), unsafe_allow_html=True)
                with sc3:
                    st.markdown(_uni_card("平均值", f"{grid_stats['mean']:+.1f}" if spatial_mode == "anomaly" else f"{grid_stats['mean']:.1f}", color="#f59e0b"), unsafe_allow_html=True)
                with sc4:
                    st.markdown(_uni_card("网格规模", f"{grid_stats['n_points']}", f" {grid_stats['grid_shape']}", color="#6b7280"), unsafe_allow_html=True)

    # ---- 智能分析与建议 ----
    with st.spinner("正在生成预报智能分析..."):
        analysis = _analyze_forecast(fdf)
    st.session_state["fc_analysis"] = analysis

    # 生活指南计算提前到此处(将作为子节嵌入智能分析节)
    life_indices = _calc_life_indices(fdf)
    st.session_state["life_indices"] = life_indices

    _render_forecast_advice(analysis, life_indices=life_indices)

    # ---- 预报验证（内置运行）----
    st.write("---")
    st.write("### [验证] 预报验证 (GFS vs 实况)")
    with st.expander("展开预报验证", expanded=False):
        _render_forecast_verification()
