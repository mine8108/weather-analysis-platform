"""
NWP 数值预报模块：GFS 预报接入、高温/体感指数、时间图与空间图渲染

数据来源：Open-Meteo 数值预报 API (https://api.open-meteo.com/v1/forecast)
- 免注册、免费、支持 GFS 模式 (models=gfs / gfs_seamless)
- 单点逐时预报最长 16 天
- 支持多坐标点单次请求（用于空间网格预报场，避免多次调用）

说明：本模块刻意不使用非 BMP emoji（如 surrograge pair），以兼容
Streamlit Cloud 的标签编码要求。
"""

import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import COLORS

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

# 单点预报返回的变量 -> 标准字段映射
_FC_HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "surface_pressure",
    "cloud_cover",
    "weather_code",
]


# ============================================================
# 二、数据获取
# ============================================================
def fetch_gfs_forecast(lat, lon, days=7, model="gfs_seamless"):
    """获取 GFS 单点逐时预报 (Open-Meteo, 免注册)。

    返回 (DataFrame, error_msg)。成功时 error_msg 为 None。
    DataFrame 含标准字段：timestamp, temperature, humidity,
    apparent_temperature, precipitation, wind_speed, wind_direction,
    pressure, cloud_cover, weather_code, station_id。
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": _FC_HOURLY,
        "forecast_days": int(days),
        "timezone": "Asia/Shanghai",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
    }
    if model:
        params["models"] = model

    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return None, f"请求失败: {e}"

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
        "wind_direction": h["wind_direction_10m"],
        "pressure": h["surface_pressure"],
        "cloud_cover": h["cloud_cover"],
        "weather_code": h["weather_code"],
    })
    df["station_id"] = f"GFS({lat:.2f},{lon:.2f})"
    return df, None


def fetch_gfs_spatial_grid(center_lat, center_lon, step=0.5, half=1.5,
                           days=1, model="gfs_seamless", variable="temperature_2m"):
    """抓取以 center 为中心、步长 step、半宽 half 的网格点 GFS 预报。

    通过 Open-Meteo 的多坐标点单次请求实现，避免逐点调用。
    返回 (lats, lons, times, field3d, error_msg)。
      - lats / lons: 一维 np.ndarray（网格坐标，lat 为主序）
      - times: DatetimeIndex
      - field3d: shape (n_lat, n_lon, n_time) 的预报场
    失败时 field3d 为 None，error_msg 含错误信息。

    注：Open-Meteo 多坐标点返回的是「坐标点列表」结构
    [{latitude, longitude, hourly:{time:[...], <var>:[...]}}, ...]，
    每个点的变量为扁平数组；本函数按输入顺序重组为网格。
    """
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

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": ",".join(str(x) for x in lat_coords),
        "longitude": ",".join(str(x) for x in lon_coords),
        "hourly": [variable],
        "forecast_days": int(days),
        "timezone": "Asia/Shanghai",
    }
    if model:
        params["models"] = model

    try:
        resp = requests.get(url, params=params, timeout=90)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        return None, None, None, None, f"请求失败: {e}"

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
    return lats_arr, lons_arr, times, field3d, None


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
    """时间图：气温 + 体感温度(左轴) + 降水(右轴) 双 Y 轴序列

    T1: 底部 rangeslider 支持缩放到具体时段
    T2: X 轴 dtick=43200000(12h) 避免逐时标签重叠
    T3: hovertemplate 含格式化日期时间
    T4: 当前时刻竖线标注（醒目红色虚线）
    """
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(x=fdf["timestamp"], y=fdf["temperature"], mode="lines",
                   name="气温", line=dict(color=COLORS["temp_color"], width=2),
                   hovertemplate="%{x|%m-%d %H:%M}<br>气温: %{y:.1f}C<extra></extra>"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=fdf["timestamp"], y=fdf["apparent_temperature"], mode="lines",
                   name="体感温度", line=dict(color="#e67e22", width=2, dash="dot"),
                   hovertemplate="%{x|%m-%d %H:%M}<br>体感: %{y:.1f}C<extra></extra>"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(x=fdf["timestamp"], y=fdf["precipitation"], name="降水",
               marker_color=COLORS["rain_color"], opacity=0.5,
               hovertemplate="%{x|%m-%d %H:%M}<br>降水: %{y:.1f} mm<extra></extra>"),
        secondary_y=True,
    )
    # T4: 醒目的当前时刻竖线
    t_min = fdf["timestamp"].min()
    t_max = fdf["timestamp"].max()
    if t_min <= now <= t_max:
        fig.add_vline(x=now, line_width=2, line_dash="dash",
                      line_color="#d0021b",
                      annotation_text="现在",
                      annotation_position="top left",
                      annotation_font=dict(size=11, color="#d0021b"))
    fig.update_yaxes(title_text="温度 (C)", secondary_y=False)
    fig.update_yaxes(title_text="降水 (mm)", secondary_y=True)
    # T1+T2: rangeslider + 稀疏刻度
    fig.update_xaxes(
        rangeselector=dict(
            buttons=list([
                dict(count=3, label="3d", step="day", stepmode="backward"),
                dict(count=7, label="7d", step="day", stepmode="backward"),
                dict(count=14, label="14d", step="day", stepmode="backward"),
                dict(step="all"),
            ])
        ),
        rangeslider=dict(visible=True, thickness=35),
        dtick=43200000,
        tickformat="%m-%d %H:%M",
    )
    fig.update_layout(
        title="GFS 温度 / 体感温度 / 降水 预报",
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=20, t=40, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
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
        title="未来 72 小时高温与体感温度",
        xaxis_title="时间", yaxis_title="温度 (℃)",
        hovermode="x unified", height=380,
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
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


def _spatial_heatmap(lats, lons, times, field3d, lat, lon, hour_idx, variable):
    """空间图：给定时次渲染经纬度热力图，并标记目标点

    S2: 增大轴标签字号
    S4+S5: 优化 colorbar（加厚/更多tick/标题侧置）
    S3 返回值扩展：同时返回 (fig, stats_dict) 供调用方展示统计量
    """
    field2d = field3d[:, :, hour_idx]
    vname = SPATIAL_VAR_LABELS.get(variable, variable)

    # S3: 预计算网格统计量
    valid = field2d[~np.isnan(field2d)]
    stats = {
        "min": float(np.min(valid)) if len(valid) > 0 else float("nan"),
        "max": float(np.max(valid)) if len(valid) > 0 else float("nan"),
        "mean": float(np.mean(valid)) if len(valid) > 0 else float("nan"),
        "n_points": int(field2d.size),
        "grid_shape": f"{field2d.shape[0]}x{field2d.shape[1]}",
        "time_str": str(times[hour_idx]),
    }

    fig = go.Figure(go.Heatmap(
        z=field2d,
        x=lons, y=lats,
        colorscale="RdYlBu_r",
        # S5: 加厚 colorbar + 更多 tick + 标题侧置
        colorbar=dict(
            title=dict(text=vname, side="right", font=dict(size=13)),
            thickness=15,
            len=0.95,
            tickfont=dict(size=11),
        ),
        hovertemplate="经度 %{x:.2f}E<br>纬度 %{y:.2f}N<br>" + vname + ": %{z:.1f}<extra></extra>",
    ))
    # 目标点标记（更大更醒目）
    fig.add_trace(go.Scatter(
        x=[lon], y=[lat], mode="markers+text", name="目标点",
        marker=dict(color="black", size=16, symbol="x", line=dict(width=2)),
        text=["目标"], textposition="middle right",
        textfont=dict(size=11, color="#333"),
        hovertemplate="目标点 (%.2fN, %.2fE)<extra></extra>" % (lat, lon),
    ))
    # S2: 轴标题字号增大 + 刻度格式
    fig.update_layout(
        title=f"{vname} 空间分布 @ {times[hour_idx]}",
        xaxis_title=dict(text="经度 (E)", font=dict(size=13)),
        yaxis_title=dict(text="纬度 (N)", font=dict(size=13)),
        xaxis=dict(tickfont=dict(size=11), tickformat=".2f"),
        yaxis=dict(scaleanchor="x", scaleratio=1, tickfont=dict(size=11), tickformat=".2f"),
        height=520, margin=dict(l=50, r=50, t=45, b=50),
    )
    return fig, stats


# ============================================================
# 五、主渲染入口
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
            st.success(f"[OK] 获取 {len(fdf)} 条逐时预报 (未来 {days} 天)")

    fdf = st.session_state.get("fc_df", None)
    if fdf is None:
        st.info("点击上方按钮获取 GFS 预报数据")
        return

    # ---- 时间图 ----
    st.write("### 时间图：逐时预报序列")
    ts_fig = _forecast_time_series(fdf)
    st.plotly_chart(ts_fig, use_container_width=True, key="fc_ts")

    # ---- 72h 高温panel ----
    st.write("### 72 小时高温预报面板")
    hh = fdf.head(72)
    panel_fig = _high_temp_72h_panel(hh)
    st.plotly_chart(panel_fig, use_container_width=True, key="fc_72h")

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
    st.metric("预报期累计降水", f"{total_precip:.1f} mm")
    daily_fig = _daily_precip_chart(fdf)
    st.plotly_chart(daily_fig, use_container_width=True, key="fc_daily_precip")

    # ---- 空间图 ----
    st.write("---")
    st.write("### 空间图：区域预报场")
    st.caption("给定预报时次，抓取目标点周边网格的 GFS 预报并渲染空间分布 (无需 Mapbox Token)")

    scol1, scol2, scol3 = st.columns(3)
    with scol1:
        variable = st.selectbox("空间变量", list(SPATIAL_VAR_LABELS.keys()),
                                format_func=lambda v: SPATIAL_VAR_LABELS[v], key="fc_spatial_var")
    # S1: 默认步长更细、半宽适中 → 至少 9x9=81 点（而非旧版 3x3~7x7）
    with scol2:
        step = st.slider("网格步长 (度)", 0.10, 1.0, 0.25, 0.05, key="fc_step")
    with scol3:
        half = st.slider("半宽 (度)", 0.5, 3.0, 1.0, 0.25, key="fc_half")

    if st.button("[空间] 生成空间预报场", use_container_width=True, key="fc_spatial"):
        with st.spinner("正在抓取网格预报 (单次多站点请求)..."):
            lats, lons, times, field3d, err = fetch_gfs_spatial_grid(
                lat, lon, step=step, half=half, days=days, model=model, variable=variable
            )
        if err:
            st.error(err)
        else:
            st.session_state["fc_grid"] = (lats, lons, times, field3d)
            st.session_state["fc_hour"] = 0
            st.success(f"[OK] 网格 {len(lats)}x{len(lons)} 点，共 {len(times)} 个时次")

    if "fc_grid" in st.session_state:
        lats, lons, times, field3d = st.session_state["fc_grid"]
        hour_idx = st.slider("选择预报时次", 0, len(times) - 1,
                             st.session_state.get("fc_hour", 0), key="fc_hour")
        map_fig, grid_stats = _spatial_heatmap(lats, lons, times, field3d, lat, lon, hour_idx, variable)
        st.plotly_chart(map_fig, use_container_width=True, key="fc_spatial_map")

        # S3: 网格统计量展示
        sc1, sc2, sc3, sc4 = st.columns(4)
        with sc1:
            st.metric("最小值", f"{grid_stats['min']:.1f}")
        with sc2:
            st.metric("最大值", f"{grid_stats['max']:.1f}")
        with sc3:
            st.metric("平均值", f"{grid_stats['mean']:.1f}")
        with sc4:
            st.metric("网格规模", grid_stats["grid_shape"])
