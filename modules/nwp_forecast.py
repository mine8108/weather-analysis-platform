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

from config import COLORS, safe_chart

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
        rangeslider=dict(visible=True, thickness=0.15),
        dtick=43200000,
        tickformat="%m-%d %H:%M",
    )
    fig.update_layout(
        title=dict(
            text="GFS 温度/体感/降水 预报",
            y=0.01, x=0.5, xanchor="center", yanchor="bottom",
            font=dict(size=14),
        ),
        hovermode="x unified",
        height=480,
        margin=dict(l=40, r=20, t=20, b=80),
        legend=dict(
            x=0.01, y=0.98,
            xanchor="left", yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ddd", borderwidth=1,
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
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#ddd", borderwidth=1,
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
        textfont=dict(size=11, color="#333"),
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
                    if idx_pos < 3 and hasattr(trace, "colorbar"):
                        del trace.colorbar
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
            textfont=dict(size=11, color="#333"),
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
    """分析 GFS 预报数据，返回结构化分析结果。

    返回 dict：
      warnings: 预警信号列表（仿 analyzer.py 风格）
      extremes: 极端值摘要
      trends: 趋势描述
      coupling: 多要素耦合风险
      summary: 单行总述
      recommendations: {"travel": [...], "agri": [...]}
    """
    daily = fdf.copy()
    daily["date"] = fdf["timestamp"].dt.date
    # 日聚合
    dmax_t = daily.groupby("date")["temperature"].max()
    dmin_t = daily.groupby("date")["temperature"].min()
    dprecip = daily.groupby("date")["precipitation"].sum()
    dmax_ws = daily.groupby("date")["wind_speed"].max()
    # 日均湿度（用于耦合分析）
    davg_rh = daily.groupby("date")["humidity"].mean()

    ndays = len(dmax_t)
    results = {
        "warnings": [],
        "extremes": {},
        "trends": {},
        "coupling": [],
        "summary": "",
        "recommendations": {"travel": [], "agri": []},
    }

    # ----- 1. 高温预警 -----
    hot = dmax_t[dmax_t >= 35]
    if len(hot) > 0:
        peak = hot.max()
        peak_date = str(hot.idxmax())
        if peak >= 40:
            level, lv_num, icon_ = "红色", "I级", "[红]"
        elif peak >= 37:
            level, lv_num, icon_ = "橙色", "II级", "[橙]"
        else:
            level, lv_num, icon_ = "黄色", "III级", "[黄]"
        results["warnings"].append({
            "type": "高温", "level": level, "level_num": lv_num,
            "detail": f"未来{ndays}天中{len(hot)}天日最高气温>=35C，峰值{peak:.1f}C ({peak_date})。",
            "icon": icon_,
        })

    # ----- 2. 暴雨预警 -----
    heavy = dprecip[dprecip >= 50]
    for d, val in heavy.items():
        if val >= 100:
            lv, lnum = "红色", "I级"
        elif val >= 75:
            lv, lnum = "橙色", "II级"
        elif val >= 50:
            lv, lnum = "黄色", "III级"
        else:
            continue
        results["warnings"].append({
            "type": "暴雨", "level": lv, "level_num": lnum,
            "detail": f"{d} 日降水量 {val:.1f} mm，需关注短时强降水。",
            "icon": "[暴]",
        })

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

    # ----- 4. 极端值 -----
    results["extremes"] = {
        "max_temp": (float(dmax_t.max()), str(dmax_t.idxmax())),
        "min_temp": (float(dmin_t.min()), str(dmin_t.idxmin())),
        "max_daily_precip": (float(dprecip.max()), str(dprecip.idxmax())),
        "total_precip": float(dprecip.sum()),
        "max_wind": (float(dmax_ws.max()), str(dmax_ws.idxmax())),
        "ndays": ndays,
    }

    # ----- 5. 趋势 -----
    first3 = dmax_t.iloc[:min(3, ndays)].mean()
    last3 = dmax_t.iloc[-min(3, ndays):].mean()
    diff = last3 - first3
    if diff > 3:
        t_trend = "明显升温"
    elif diff > 1:
        t_trend = "小幅升温"
    elif diff < -3:
        t_trend = "明显降温"
    elif diff < -1:
        t_trend = "小幅降温"
    else:
        t_trend = "基本平稳"
    results["trends"]["temperature"] = t_trend
    # 降水趋势
    precip_days = int((dprecip > 0.1).sum())
    results["trends"]["precip_days"] = precip_days
    if precip_days == 0:
        results["trends"]["precip"] = "全程无有效降水"
    elif precip_days <= ndays * 0.3:
        results["trends"]["precip"] = "降水日数较少"
    else:
        results["trends"]["precip"] = "降水日数偏多"

    # ----- 6. 耦合分析 -----
    # 高温+高湿 → 热应激
    if len(hot) > 0:
        hot_dates = list(hot.index)
        hot_rh = davg_rh.loc[[d for d in hot_dates if d in davg_rh.index]]
        if len(hot_rh) > 0 and hot_rh.mean() > 60:
            results["coupling"].append({
                "type": "热应激风险", "severity": "危险",
                "detail": f"高温({hot.max():.1f}C)叠加高湿({hot_rh.mean():.0f}%)，体感温度显著升高，户外活动需防范中暑。",
                "icon": "[热]",
            })
    # 大风+降水
    if len(windy) > 0 and len(heavy) > 0:
        overlap = set(windy.index) & set(heavy.index)
        if overlap:
            results["coupling"].append({
                "type": "风雨耦合", "severity": "危险",
                "detail": f"{len(overlap)} 天同时出现大风和强降水，出行风险加剧。",
                "icon": "[风]",
            })

    # ----- 7. 总述 -----
    parts = [f"未来{ndays}天气温趋势{t_trend}"]
    if precip_days > 0:
        parts.append(f"共{precip_days}个降水日，累计{results['extremes']['total_precip']:.0f} mm")
    else:
        parts.append("全程无明显降水")
    if len(results["warnings"]) > 0:
        types = set(w["type"] for w in results["warnings"])
        parts.append(f"触发{'/'.join(types)}预警信号")
    else:
        parts.append("无预警风险")
    results["summary"] = "。".join(parts) + "。"

    # ----- 8. 建议 -----
    t = {"travel": results["recommendations"]["travel"],
         "agri": results["recommendations"]["agri"]}

    if len(hot) > 0:
        t["travel"].append(f"未来{len(hot)}天有高温 ({hot.max():.0f}C)，外出避开 11:00-15:00 时段，备足饮水。")
        t["agri"].append(f"高温天气 ({len(hot)} 天 ≥35C)：及时灌溉降温；设施大棚覆盖遮阳网；禽畜采取喷淋降温。")

    if len(heavy) > 0:
        t["travel"].append(f"强降水日外出备雨具，低洼路段注意内涝；涉水谨慎。")
        t["agri"].append(f"注意清沟排水；加固大棚基础；鱼塘检查防逃设施。")

    if len(windy) > 0:
        t["travel"].append("大风天气远离广告牌/临时搭建物；高空作业暂停。")
        t["agri"].append("加固设施农业骨架；收起晾晒物；检查禽畜舍牢固性。")

    if precip_days == 0 and len(hot) > 0:
        t["agri"].append("高温少雨天气：增加灌溉频次，严防干旱；旱地作物覆盖保墒。")

    if len(results["coupling"]) > 0:
        for c in results["coupling"]:
            t["travel"].append(f"[{c['type']}] {c['detail']}")

    # 去重 + 限制条数
    for k in ("travel", "agri"):
        seen = set()
        uniq = []
        for s in t[k]:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        results["recommendations"][k] = uniq[:6]

    return results


def _render_forecast_advice(analysis):
    """渲染预报智能分析结果"""
    from config import WARN_STYLES

    st.write("---")
    st.write("### 智能分析与建议")

    # 总述
    st.markdown(f"**总结**：{analysis['summary']}")

    # 极端值卡片
    ex = analysis["extremes"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("最高气温", f"{ex['max_temp'][0]:.0f}C", ex["max_temp"][1])
    with c2:
        st.metric("最低气温", f"{ex['min_temp'][0]:.0f}C", ex["min_temp"][1])
    with c3:
        st.metric("累计降水", f"{ex['total_precip']:.0f} mm")
    with c4:
        st.metric("最大风速", f"{ex['max_wind'][0]:.1f} m/s", ex["max_wind"][1])

    # 预警
    if analysis["warnings"]:
        st.write("#### 预警信号")
        level_order = {"红色": 0, "橙色": 1, "黄色": 2, "蓝色": 3}
        sorted_w = sorted(analysis["warnings"], key=lambda w: level_order.get(w["level"], 4))
        cols = st.columns(min(len(sorted_w), 2))
        for i, warn in enumerate(sorted_w):
            style = WARN_STYLES.get(warn["level"], WARN_STYLES["蓝色"])
            with cols[i % 2]:
                st.markdown(f"""<div style="background:{style['bg']};border-left:4px solid {style['color']};padding:10px 12px;border-radius:4px;margin-bottom:6px;font-size:13px">
<b style="color:{style['color']};font-size:15px">{warn['icon']} {warn['type']}{warn['level']}</b>
<br><span style="color:#555">{warn['level_num']} | {warn['detail']}</span></div>""", unsafe_allow_html=True)
    else:
        st.success("[OK] 未来预报期内未触发预警信号")

    # 耦合分析
    if analysis["coupling"]:
        st.write("#### 多要素耦合风险")
        for c in analysis["coupling"]:
            st.warning(f"{c['icon']} **{c['type']}** ({c['severity']}): {c['detail']}")

    # 建议
    c1, c2 = st.columns(2)
    with c1:
        st.write("#### 出行建议")
        for s in analysis["recommendations"]["travel"]:
            st.write(f"- {s}")
        if not analysis["recommendations"]["travel"]:
            st.info("天气状况良好，无特殊出行限制。")
    with c2:
        st.write("#### 农业建议")
        for s in analysis["recommendations"]["agri"]:
            st.write(f"- {s}")
        if not analysis["recommendations"]["agri"]:
            st.info("天气状况对农业生产无明显不利影响。")


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
            st.success(f"[OK] 获取 {len(fdf)} 条逐时预报 (未来 {days} 天)")

    fdf = st.session_state.get("fc_df", None)
    if fdf is None:
        st.info("点击上方按钮获取 GFS 预报数据")
        return

    # ---- 时间图 ----
    st.write("### 时间图：逐时预报序列")
    ts_fig = _forecast_time_series(fdf)
    safe_chart(ts_fig, "温度/体感/降水 预报", key="fc_ts")
    # D: 说明 rangeslider 的 Plotly 天然限制
    st.caption("提示：底部缩放滑块仅关联左侧「气温」坐标轴（右轴降水不随滑块缩放），这是 Plotly 原生行为。")
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
    st.metric("预报期累计降水", f"{total_precip:.1f} mm")
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
                    st.metric("最小值", f"{grid_stats['min']:+.1f}" if spatial_mode == "anomaly" else f"{grid_stats['min']:.1f}")
                with sc2:
                    st.metric("最大值", f"{grid_stats['max']:+.1f}" if spatial_mode == "anomaly" else f"{grid_stats['max']:.1f}")
                with sc3:
                    st.metric("平均值", f"{grid_stats['mean']:+.1f}" if spatial_mode == "anomaly" else f"{grid_stats['mean']:.1f}")
                with sc4:
                    st.metric("网格规模", f"{grid_stats['n_points']}点 ({grid_stats['grid_shape']})")

    # ---- 智能分析与建议 ----
    with st.spinner("正在生成预报智能分析..."):
        analysis = _analyze_forecast(fdf)
    st.session_state["fc_analysis"] = analysis
    _render_forecast_advice(analysis)
