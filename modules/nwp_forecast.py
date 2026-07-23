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

from config import COLORS, safe_chart, _is_dark, WARN_LEVEL_ORDER

# ---- 工具导入 ----
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import retry_with_backoff


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
@retry_with_backoff(max_retries=3, base_delay=3, backoff_factor=2)
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

    # ----- 6. 耦合分析（同前）-----
    if len(hot) > 0:
        hot_dates = list(hot.index)
        hot_rh = davg_rh.loc[[d for d in hot_dates if d in davg_rh.index]]
        if len(hot_rh) > 0 and hot_rh.mean() > 60:
            results["coupling"].append({
                "type": "热应激风险", "severity": "危险",
                "detail": f"高温({hot.max():.1f}C)叠加高湿({hot_rh.mean():.0f}%)，体感温度显著升高，户外活动需防范中暑。",
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

    # 精度增强面板
    prec = analysis.get("precision", {})
    if prec:
        st.write("#### 预报精度详情")
        # 趋势数值
        tt = prec.get("temp_trend", {})
        if tt:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("趋势变化", f"{tt['diff_mean']:+.1f}C", f"±{tt['diff_std']:.1f}C")
            with c2:
                st.metric("波动程度", tt.get("volatility", ""), f"标准差 {tt['overall_std']:.1f}C")
            with c3:
                st.metric("连续高温", f"{prec.get('consecutive_hot', 0)} 天",
                          f"最长 {prec.get('consecutive_hot', 0)} 天" if prec.get('consecutive_hot', 0) > 0 else None)
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
