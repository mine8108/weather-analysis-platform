"""
可视化模块：时间序列图、风向玫瑰图、散点矩阵、综合看板、多站点对比
"""

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from config import (
    COLORS, WIND_DIRECTIONS,
    get_beaufort_level, get_wind_direction_name, get_dominant_wind_direction,
    safe_chart,
)


def _safe_xaxis(df):
    """安全获取 X 轴数据：优先 timestamp 列，降级为 DataFrame 索引"""
    if "timestamp" in df.columns:
        return df["timestamp"]
    return df.index


def time_series_chart(df, field, title, color, y_label, unit=""):
    """通用时间序列折线图"""
    if field not in df.columns or df[field].dropna().empty:
        return None

    x_data = _safe_xaxis(df)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_data,
        y=df[field],
        mode="lines+markers",
        name=title,
        line=dict(color=color, width=2),
        marker=dict(size=4),
        hovertemplate=f"时间: %{{x}}<br>{title}: %{{y:.1f}}{unit}<extra></extra>",
    ))

    fig.update_layout(
        title=title,
        xaxis_title="时间",
        yaxis_title=f"{title}{f' ({unit})' if unit else ''}",
        hovermode="x unified",
        height=350,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig


def wind_rose_chart(df):
    """风向风速玫瑰图（Plotly 极坐标）"""
    if "wind_speed" not in df.columns or "wind_direction" not in df.columns:
        return None

    wd = df["wind_direction"].dropna()
    ws = df["wind_speed"].dropna()

    if len(wd) == 0 or len(ws) == 0:
        return None

    # 按16扇区分桶
    n_sectors = 16
    sector_width = 360 / n_sectors
    sectors = []
    for i in range(n_sectors):
        lo = i * sector_width
        hi = (i + 1) * sector_width
        if i == 0:
            mask = (wd >= 0) & (wd < hi)
        elif i == n_sectors - 1:
            mask = (wd >= lo) & (wd <= 360)
        else:
            mask = (wd >= lo) & (wd < hi)
        sectors.append(mask)

    # 风速分级
    speed_bins = [
        (0, 0.2, "静风"),
        (0.3, 1.5, "软风"),
        (1.6, 3.3, "轻风"),
        (3.4, 5.4, "微风"),
        (5.5, 7.9, "和风"),
        (8.0, 10.7, "清风"),
        (10.8, 13.8, "强风"),
        (13.9, 17.1, "劲风"),
        (17.2, 999, "大风及以上"),
    ]

    colors = ["#475569" if st.session_state.get("dark_mode", False) else "#e0e0e0", "#b0c4de", "#87ceeb", "#5cacee", "#3b8ed4", "#1e6bb8", "#ffa500", "#ff6347", "#cc0000"]

    fig = go.Figure()
    for j, (lo, hi, label) in enumerate(speed_bins):
        r = []
        theta = []
        for i in range(n_sectors):
            mask = sectors[i]
            count = ((ws >= lo) & (ws <= hi) & mask).sum()
            r.append(count)
            theta.append(i * sector_width + sector_width / 2)
        fig.add_trace(go.Barpolar(
            r=r,
            theta=theta,
            name=label,
            marker_color=colors[j],
            opacity=0.85,
            hovertemplate="%{theta}°<br>频次: %{r}<extra>%{fullData.name}</extra>",
        ))

    fig.update_layout(
        title="风向风速玫瑰图",
        polar=dict(
            radialaxis=dict(showticklabels=True, ticks=""),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                tickmode="array",
                tickvals=[i * sector_width for i in range(n_sectors)],
                ticktext=WIND_DIRECTIONS,
            ),
            bgcolor="rgba(0,0,0,0.03)",
        ),
        legend=dict(title="风速等级", y=0.5),
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


def dashboard_view(df):
    """综合看板：多要素 2x2 布局"""
    if "timestamp" not in df.columns:
        # 降级：无时间列仍可尝试用索引渲染
        pass

    x_data = _safe_xaxis(df)
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("气温 (℃)", "气压 (hPa)", "相对湿度 (%)", "风速 (m/s)"),
        vertical_spacing=0.18,
        horizontal_spacing=0.14,
    )

    # 气温
    if "temperature" in df.columns:
        fig.add_trace(
            go.Scatter(x=x_data, y=df["temperature"], mode="lines+markers",
                       line=dict(color=COLORS["temp_color"], width=2), marker=dict(size=3),
                       name="气温"),
            row=1, col=1,
        )

    # 气压
    if "pressure" in df.columns:
        fig.add_trace(
            go.Scatter(x=x_data, y=df["pressure"], mode="lines+markers",
                       line=dict(color=COLORS["pres_color"], width=2), marker=dict(size=3),
                       name="气压"),
            row=1, col=2,
        )

    # 湿度
    if "humidity" in df.columns:
        fig.add_trace(
            go.Scatter(x=x_data, y=df["humidity"], mode="lines+markers",
                       line=dict(color=COLORS["humid_color"], width=2), marker=dict(size=3),
                       name="湿度"),
            row=2, col=1,
        )

    # 风速
    if "wind_speed" in df.columns:
        fig.add_trace(
            go.Bar(x=x_data, y=df["wind_speed"],
                   marker_color=COLORS["wind_color"], name="风速", opacity=0.7),
            row=2, col=2,
        )

    fig.update_layout(
        title="气象要素综合看板",
        height=720,
        showlegend=False,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=90, b=60),
        title_y=0.98,
    )
    fig.update_xaxes(tickangle=-45, nticks=8)
    fig.update_xaxes(title_text="时间", row=2, col=1)
    fig.update_xaxes(title_text="时间", row=2, col=2)
    return fig


def scatter_matrix(df):
    """散点矩阵分析要素间关系"""
    plot_fields = ["temperature", "pressure", "humidity", "wind_speed",
                  "so2", "nox", "pm25", "pm10"]
    available = [f for f in plot_fields if f in df.columns and not df[f].dropna().empty]

    if len(available) < 2:
        return None

    labels = {
        "temperature": "气温 (℃)",
        "pressure": "气压 (hPa)",
        "humidity": "相对湿度 (%)",
        "wind_speed": "风速 (m/s)",
        "so2": "SO₂ (μg/m³)",
        "nox": "NOx (μg/m³)",
        "pm25": "PM2.5 (μg/m³)",
        "pm10": "PM10 (μg/m³)",
    }

    n = len(available)
    fig = make_subplots(
        rows=n, cols=n,
        subplot_titles=[labels.get(f, f) for f in available],
        vertical_spacing=0.03,
        horizontal_spacing=0.03,
    )

    for i, fi in enumerate(available):
        for j, fj in enumerate(available):
            if i != j:
                fig.add_trace(
                    go.Scatter(
                        x=df[fj], y=df[fi],
                        mode="markers",
                        marker=dict(size=4, opacity=0.5, color=COLORS["primary"]),
                        showlegend=False,
                        hovertemplate=f"{labels.get(fj, fj)}: %{{x:.1f}}<br>{labels.get(fi, fi)}: %{{y:.1f}}<extra></extra>",
                    ),
                    row=i + 1, col=j + 1,
                )
            else:
                # 对角线：直方图
                fig.add_trace(
                    go.Histogram(
                        x=df[fi],
                        marker_color=COLORS["primary"],
                        showlegend=False,
                        nbinsx=20,
                    ),
                    row=i + 1, col=j + 1,
                )

    # 设置轴标签
    for i, f in enumerate(available):
        fig.update_xaxes(title_text=labels.get(f, f), row=n, col=i + 1)
        fig.update_yaxes(title_text=labels.get(f, f), row=i + 1, col=1)

    fig.update_layout(
        title="要素间散点矩阵",
        height=250 * n,
        margin=dict(l=60, r=20, t=60, b=60),
    )
    return fig


def multi_station_comparison(df):
    """多站点对比分析（增强版：站点筛选 + 统计摘要表）"""
    if "station_id" not in df.columns or df["station_id"].nunique() < 2:
        return None

    stations = sorted(df["station_id"].dropna().unique())
    st.write(f"### [标签] 多站点对比 (共 {len(stations)} 个站点)")

    # 站点选择面板
    if "multi_station_selected" not in st.session_state:
        st.session_state["multi_station_selected"] = list(stations)

    with st.expander("站点管理", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("✓ 全选", use_container_width=True, key="ms_all"):
                st.session_state["multi_station_selected"] = list(stations)
                st.rerun()
        with c2:
            if st.button("✗ 取消", use_container_width=True, key="ms_none"):
                st.session_state["multi_station_selected"] = []
                st.rerun()
        with c3:
            if st.button("↻ 反选", use_container_width=True, key="ms_invert"):
                sel = set(st.session_state["multi_station_selected"])
                st.session_state["multi_station_selected"] = [s for s in stations if s not in sel]
                st.rerun()
        st.session_state["multi_station_selected"] = st.multiselect(
            "选择站点", stations,
            default=st.session_state["multi_station_selected"],
            key="ms_select"
        )

    selected = st.session_state["multi_station_selected"]
    if len(selected) < 2:
        st.info("请至少选择 2 个站点进行对比")
        return None

    # 选择对比要素
    compare_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility"]
    available = [f for f in compare_fields if f in df.columns]
    if not available:
        return None

    field = st.selectbox("选择对比要素", available, key="multi_station_field")

    station_df_filtered = df[df["station_id"].isin(selected)]

    fig = go.Figure()
    palette = px.colors.qualitative.Set1
    for idx, station in enumerate(selected):
        sdf = station_df_filtered[station_df_filtered["station_id"] == station]
        if sdf[field].dropna().empty:
            continue
        color = palette[idx % len(palette)]
        fig.add_trace(go.Scatter(
            x=_safe_xaxis(sdf), y=sdf[field],
            mode="lines+markers", name=str(station),
            line=dict(color=color, width=2), marker=dict(size=3),
        ))

    labels = {
        "temperature": "气温 (℃)", "pressure": "气压 (hPa)",
        "humidity": "相对湿度 (%)", "wind_speed": "风速 (m/s)",
        "visibility": "能见度 (km)",
    }
    fig.update_layout(
        title=f"多站点 {labels.get(field, field)} 对比",
        xaxis_title="时间", yaxis_title=labels.get(field, field),
        hovermode="x unified", height=420,
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    safe_chart(fig, "多站点对比", use_container_width=True, key="multi_station_chart")

    # 统计摘要表
    st.write("**站点统计摘要**")
    stats_rows = []
    for station in selected:
        sdf = station_df_filtered[station_df_filtered["station_id"] == station][field].dropna()
        if len(sdf) == 0:
            continue
        stats_rows.append({
            "站点": str(station), "均值": f"{sdf.mean():.1f}",
            "最大": f"{sdf.max():.1f}", "最小": f"{sdf.min():.1f}",
            "记录数": len(sdf),
        })
    if stats_rows:
        st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

    return fig


def distribution_histogram(df):
    """要素分布直方图（默认含降水量），支持多选要素叠加对比"""
    fields = ["precipitation", "temperature", "humidity", "wind_speed",
              "pressure", "visibility", "cloud_cover",
              "so2", "nox", "tsp", "pm25", "pm10"]
    available = [f for f in fields if f in df.columns and not df[f].dropna().empty]
    if not available:
        return None

    labels = {
        "precipitation": "降水量 (mm)",
        "temperature": "气温 (℃)",
        "humidity": "相对湿度 (%)",
        "wind_speed": "风速 (m/s)",
        "pressure": "气压 (hPa)",
        "visibility": "能见度 (km)",
        "cloud_cover": "总云量",
        "so2": "SO₂ (μg/m³)",
        "nox": "NOx (μg/m³)",
        "tsp": "TSP (μg/m³)",
        "pm25": "PM2.5 (μg/m³)",
        "pm10": "PM10 (μg/m³)",
    }
    colors = {
        "precipitation": COLORS["rain_color"],
        "temperature": COLORS["temp_color"],
        "humidity": COLORS["humid_color"],
        "wind_speed": COLORS["wind_color"],
        "pressure": COLORS["pres_color"],
        "visibility": COLORS["vis_color"],
        "cloud_cover": COLORS["purple"],
        "so2": COLORS["so2_color"],
        "nox": COLORS["nox_color"],
        "tsp": COLORS["tsp_color"],
        "pm25": COLORS["pm25_color"],
        "pm10": COLORS["pm10_color"],
    }

    default = ["precipitation"] if "precipitation" in available else [available[0]]
    selected = st.multiselect(
        "选择要素（可多选，叠加对比）",
        available,
        default=default,
        format_func=lambda f: labels.get(f, f),
        key="hist_fields",
    )
    if not selected:
        return None

    fig = go.Figure()
    for f in selected:
        fig.add_trace(go.Histogram(
            x=df[f].dropna(),
            name=labels.get(f, f),
            opacity=0.6,
            nbinsx=30,
            marker_color=colors.get(f, COLORS["primary"]),
            hovertemplate=labels.get(f, f) + ": %{x:.2f}<br>频次 %{y}<extra></extra>",
        ))

    fig.update_layout(
        barmode="overlay",
        title="要素分布直方图",
        xaxis_title="数值",
        yaxis_title="频次",
        height=420,
        margin=dict(l=40, r=20, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def precipitation_timeline(df):
    """时序双要素对比：自由选择两个要素，图表类型自动适配，支持双y轴"""
    if "timestamp" not in df.columns:
        return None

    # ---- 要素配置 ----
    field_config = {
        "precipitation": ("降水量 (mm)", COLORS["rain_color"], "mm", "bar", "sum"),
        "temperature":   ("气温 (℃)",    COLORS["temp_color"], "℃",  "line", "mean"),
        "pressure":      ("气压 (hPa)",  COLORS["pres_color"], "hPa", "line", "mean"),
        "humidity":      ("相对湿度 (%)", COLORS["humid_color"], "%",  "line", "mean"),
        "wind_speed":    ("风速 (m/s)",  COLORS["wind_color"], "m/s", "bar", "mean"),
        "visibility":    ("能见度 (km)", COLORS["vis_color"],   "km",  "line", "mean"),
        "cloud_cover":   ("总云量",      COLORS["purple"],     "",    "line", "mean"),
        "so2":           ("SO₂ (μg/m³)", COLORS["so2_color"],  "μg/m³", "line", "mean"),
        "nox":           ("NOx (μg/m³)", COLORS["nox_color"],  "μg/m³", "line", "mean"),
        "tsp":           ("TSP (μg/m³)", COLORS["tsp_color"],  "μg/m³", "line", "mean"),
        "pm25":          ("PM2.5 (μg/m³)", COLORS["pm25_color"], "μg/m³", "line", "mean"),
        "pm10":          ("PM10 (μg/m³)", COLORS["pm10_color"], "μg/m³", "line", "mean"),
    }

    available_fields = [f for f in field_config if f in df.columns and not df[f].dropna().empty]
    if not available_fields:
        return None

    # 构建选择列表
    field_options = {"无（单轴显示）": None}
    for f in available_fields:
        name = field_config[f][0]
        field_options[name] = f

    # ---- 聚合 ----
    agg_map = {"原始（不聚合）": None, "3小时": "3h", "6小时": "6h", "12小时": "12h", "日累积": "1D"}

    c1, c2, c3 = st.columns(3)
    with c1:
        agg_sel = st.selectbox("时间聚合", list(agg_map.keys()), index=0, key="dual_agg")
    with c2:
        left_sel = st.selectbox("左轴要素", list(field_options.keys()),
                                index=0 if "降水量" in field_options else 0, key="dual_left")
    with c3:
        right_sel = st.selectbox("右轴要素", list(field_options.keys()),
                                 index=list(field_options.keys()).index("降水量 (mm)") if "降水量 (mm)" in field_options else 0,
                                 key="dual_right")

    agg_freq = agg_map[agg_sel]
    left_field = field_options[left_sel]
    right_field = field_options[right_sel]

    if left_field is None and right_field is None:
        st.info("请至少选择一个要素")
        return None

    # ---- 聚合 ----
    needed_cols = ["timestamp"]
    agg_dict = {}
    for f in [left_field, right_field]:
        if f:
            needed_cols.append(f)
            agg_mode = field_config[f][4]  # "sum" or "mean"
            agg_dict[f] = agg_mode

    dff = df[needed_cols].set_index("timestamp").copy()
    if agg_freq:
        dff = dff.resample(agg_freq).agg(agg_dict).dropna(how="all").reset_index()
    else:
        dff = dff.reset_index()

    x_data = dff["timestamp"]

    # ---- 构建图形 ----
    has_left = left_field is not None
    has_right = right_field is not None

    # 左右轴不能选择同一要素（会导致 DataFrame 列名重复）
    if has_left and has_right and left_field == right_field:
        st.warning("左轴和右轴不能选择同一要素，请选择两个不同的气象要素进行对比")
        return None

    use_dual = has_left and has_right

    if use_dual:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        # 左轴
        l_name, l_color, l_unit, l_chart, l_agg = field_config[left_field]
        _add_dual_trace(fig, dff, left_field, l_name, l_color, l_unit, l_chart, False)
        # 右轴
        r_name, r_color, r_unit, r_chart, r_agg = field_config[right_field]
        _add_dual_trace(fig, dff, right_field, r_name, r_color, r_unit, r_chart, True)
        fig.update_yaxes(title_text=f"{l_name} ({l_unit})", secondary_y=False, gridcolor="#334155" if st.session_state.get("dark_mode", False) else "#e0e0e0")
        fig.update_yaxes(title_text=f"{r_name} ({r_unit})", secondary_y=True,
                         title_font_color=r_color, tickfont_color=r_color)
        title = f"{l_name} + {r_name}（双轴）{agg_sel}"
    else:
        active = left_field or right_field
        a_name, a_color, a_unit, a_chart, a_agg = field_config[active]
        fig = go.Figure()
        _add_dual_trace(fig, dff, active, a_name, a_color, a_unit, a_chart)
        fig.update_yaxes(title_text=f"{a_name} ({a_unit})", gridcolor="#334155" if st.session_state.get("dark_mode", False) else "#e0e0e0")
        title = f"{a_name} 时序{agg_sel}"

    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor="center", y=0.97, yanchor="top", font=dict(size=14)),
        xaxis_title="时间",
        height=460,
        margin=dict(l=50, r=50, t=50, b=80),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.22, xanchor="center", x=0.5),
    )
    fig.update_xaxes(tickangle=-45, nticks=12)

    return fig


def _add_dual_trace(fig, dff, field, name, color, unit, chart_type, secondary_y=None):
    """添加双要素 trace：bar 或 line，自动选择合适的图表类型
    secondary_y: 仅在 make_subplots 双轴图时传入 True/False，单轴图不传
    """
    x_data = dff["timestamp"]
    y_data = dff[field]

    if chart_type == "bar":
        trace = go.Bar(x=x_data, y=y_data, name=f"{name} ({unit})",
                       marker_color=color, opacity=0.75,
                       hovertemplate=f"{name}: %{{y:.1f}} {unit}<extra></extra>")
    else:
        trace = go.Scatter(x=x_data, y=y_data, mode="lines+markers",
                           name=f"{name} ({unit})",
                           line=dict(color=color, width=2), marker=dict(size=3),
                           hovertemplate=f"{name}: %{{y:.1f}} {unit}<extra></extra>")

    if secondary_y is not None:
        fig.add_trace(trace, secondary_y=secondary_y)
    else:
        fig.add_trace(trace)


def _render_pollution_panel(df):
    """空气质量专用可视化面板"""
    st.write("### [大气] 空气质量分析")
    st.caption("基于 GB 3095-2026 标准评估 PM2.5/PM10/SO₂/NOx 浓度趋势与达标率")

    pollutants = {
        "pm25": ("PM2.5", COLORS["pm25_color"], "μg/m³", 50),
        "pm10": ("PM10",   COLORS["pm10_color"], "μg/m³", 100),
        "so2":  ("SO₂",    COLORS["so2_color"],  "μg/m³", 100),
        "nox":  ("NOx",    COLORS["nox_color"],  "μg/m³", 60),
    }
    available = [(k, v) for k, v in pollutants.items()
                 if k in df.columns and not df[k].dropna().empty]

    if not available:
        st.info("当前数据中未检测到大气污染物字段，请导入含 PM2.5/PM10/SO₂/NOx 的数据。")
        return

    # ---- 污染物时间序列 ----
    x_data = _safe_xaxis(df)
    fig = make_subplots(
        rows=len(available), cols=1,
        subplot_titles=[f"{v[0]} ({v[2]})" for _, v in available],
        vertical_spacing=0.08,
    )

    for i, (field, (label, color, unit, limit)) in enumerate(available, 1):
        # 添加浓度线
        fig.add_trace(
            go.Scatter(x=x_data, y=df[field], mode="lines",
                       line=dict(color=color, width=2),
                       name=label,
                       hovertemplate=f"{label}: %{{y:.1f}} {unit}"),
            row=i, col=1,
        )
        # 添加标准限值虚线
        fig.add_trace(
            go.Scatter(x=[x_data.min(), x_data.max()], y=[limit, limit],
                       mode="lines", line=dict(color=color, width=1.5, dash="dash"),
                       name=f"{label} 标准限值", showlegend=False,
                       hovertemplate=f"GB 3095-2026 限值: {limit} {unit}"),
            row=i, col=1,
        )

    fig.update_layout(
        title=dict(text="污染物浓度时间序列（虚线 = GB 3095-2026 二级日均限值）",
                   font=dict(size=14), x=0),
        height=220 * len(available) + 80,
        showlegend=False,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=40, b=40),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    grid_c = "#334155" if st.session_state.get("dark_mode", False) else "#e0e0e0"
    fig.update_xaxes(gridcolor=grid_c, zeroline=False)
    fig.update_yaxes(gridcolor=grid_c, zeroline=False)
    safe_chart(fig, "污染物浓度时序", key="viz_pollution_ts")

    # ---- 污染物统计表 ----
    st.write("---")
    st.write("**污染物统计摘要**")
    rows = []
    for field, (label, color, unit, limit) in available:
        vals = df[field].dropna()
        if len(vals) == 0:
            continue
        exceed_count = (vals > limit).sum()
        rows.append({
            "污染物": label,
            "均值": f"{vals.mean():.1f} {unit}",
            "峰值": f"{vals.max():.1f} {unit}",
            "标准限值": f"{limit} {unit}",
            "超标次数": f"{exceed_count}/{len(vals)}",
            "超标率": f"{exceed_count/len(vals)*100:.1f}%",
            "达标状态": "⚠️ 超标" if exceed_count > 0 else "✓ 达标",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def correlation_heatmap(df):
    """全要素 Pearson 相关性热力图"""
    # 选取所有数值型标准字段
    num_fields = [
        "temperature", "pressure", "humidity", "wind_speed", "visibility",
        "precipitation", "cloud_cover", "so2", "nox", "pm25", "pm10"
    ]
    available = [f for f in num_fields if f in df.columns and not df[f].dropna().empty]
    if len(available) < 2:
        return None

    corr = df[available].corr()
    labels_map = {
        "temperature": "气温", "pressure": "气压", "humidity": "湿度",
        "wind_speed": "风速", "visibility": "能见度", "precipitation": "降水",
        "cloud_cover": "云量", "so2": "SO₂", "nox": "NOx", "pm25": "PM2.5", "pm10": "PM10",
    }
    display_labels = [labels_map.get(f, f) for f in available]

    fig = go.Figure(data=go.Heatmap(
        z=corr.values,
        x=display_labels,
        y=display_labels,
        colorscale="RdBu_r",
        zmid=0,
        text=[[f"{v:.2f}" for v in row] for row in corr.values],
        texttemplate="%{text}",
        textfont={"size": 11},
        hoverongaps=False,
        colorbar=dict(title="Pearson r"),
    ))

    fig.update_layout(
        title=dict(text="要素相关性矩阵 | 红=正相关 蓝=负相关", font=dict(size=14), x=0),
        height=480,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(side="top"),
    )
    return fig


def render_visualization_tab(df):
    """渲染可视化 Tab 全部内容"""
    st.subheader("[图表] 可视化分析")

    if df is None or df.empty:
        st.info("请先导入数据")
        return

    # 子Tab
    viz_tab1, viz_tab2, viz_tab3, viz_tab4, viz_tab5, viz_tab6, viz_tab7 = st.tabs([
        "[统计] 综合看板", "[风] 风场分析", "[实验] 要素关系", "[列表] 统计摘要",
        "[分布] 要素分布", "[大气] 空气质量", "[双轴] 时序双要素"
    ])

    with viz_tab1:
        # 显示缺失字段提示
        dashboard_fields = ["temperature", "pressure", "humidity", "wind_speed"]
        missing = [f for f in dashboard_fields if f not in df.columns or df[f].dropna().empty]
        if missing:
            field_names = {
                "temperature": "气温", "pressure": "气压",
                "humidity": "湿度", "wind_speed": "风速"
            }
            missing_names = [field_names.get(f, f) for f in missing]
            st.info(f"当前数据中缺少以下字段，对应图表将显示为空白：{', '.join(missing_names)}")
        
        dashboard = dashboard_view(df)
        if dashboard:
            safe_chart(dashboard, "综合看板", key="viz_dashboard")
        else:
            st.warning("缺少可视化所需的时间序列数据")

    with viz_tab2:
        col_a, col_b = st.columns(2)
        with col_a:
            wind_rose = wind_rose_chart(df)
            if wind_rose:
                safe_chart(wind_rose, "风向玫瑰图", key="viz_wind_rose")
            else:
                st.info("缺少风向风速数据，无法绘制玫瑰图")

        with col_b:
            if "wind_speed" in df.columns and "wind_direction" in df.columns:
                # 风速时间序列
                ts_wind = time_series_chart(
                    df, "wind_speed", "风速时间序列",
                    COLORS["wind_color"], "风速", "m/s"
                )
                if ts_wind:
                    safe_chart(ts_wind, "风速时间序列", key="viz_ts_wind")

            # 风要素统计
            if "wind_speed" in df.columns:
                ws = df["wind_speed"].dropna()
                if len(ws) > 0:
                    avg_ws = ws.mean()
                    bf_level, bf_name = get_beaufort_level(avg_ws)
                    dom_dir = "N/A"
                    if "wind_direction" in df.columns:
                        wd = df["wind_direction"].dropna()
                        if len(wd) > 0:
                            dom_dir, dom_freq, dom_count = get_dominant_wind_direction(wd)
                            dom_pct = dom_freq * 100
                            dom_dir_label = f"{dom_dir} ({dom_count}/{len(wd)}={dom_pct:.0f}%)"
                    st.metric("平均风速", f"{avg_ws:.1f} m/s", f"{bf_name} ({bf_level}级)")
                    st.metric("主导风向", dom_dir_label)

    with viz_tab3:
        scatter = scatter_matrix(df)
        if scatter:
            safe_chart(scatter, "要素关系散点矩阵", key="viz_scatter")
        else:
            st.info("至少需要两个以上有效要素字段")

        # 单要素时间序列选择
        st.write("---")
        st.write("**单要素时间序列**")
        ts_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation",
                    "so2", "nox", "tsp", "pm25", "pm10"]
        available_ts = [f for f in ts_fields if f in df.columns and not df[f].dropna().empty]
        if available_ts:
            selected_ts = st.selectbox("选择要素", available_ts, key="ts_select")
            ts_config = {
                "temperature": ("气温", COLORS["temp_color"], "℃"),
                "pressure": ("气压", COLORS["pres_color"], "hPa"),
                "humidity": ("相对湿度", COLORS["humid_color"], "%"),
                "wind_speed": ("风速", COLORS["wind_color"], "m/s"),
                "visibility": ("能见度", COLORS["vis_color"], "km"),
                "precipitation": ("降水量", COLORS["rain_color"], "mm"),
                "so2": ("SO₂", COLORS["so2_color"], "μg/m³"),
                "nox": ("NOx", COLORS["nox_color"], "μg/m³"),
                "tsp": ("TSP", COLORS["tsp_color"], "μg/m³"),
                "pm25": ("PM2.5", COLORS["pm25_color"], "μg/m³"),
                "pm10": ("PM10", COLORS["pm10_color"], "μg/m³"),
            }
            if selected_ts in ts_config:
                title, color, unit = ts_config[selected_ts]
                ts_fig = time_series_chart(df, selected_ts, f"{title}时间序列", color, title, unit)
                if ts_fig:
                    safe_chart(ts_fig, f"{title}时间序列", key="viz_ts_single")

        # 相关性热力图
        st.write("---")
        st.write("**全要素相关性热力图**")
        heatmap = correlation_heatmap(df)
        if heatmap:
            safe_chart(heatmap, "相关性热力图", key="viz_corr_heatmap")
        else:
            st.info("至少需要两个以上有效数值要素")

    with viz_tab4:
        # 统计摘要
        stats_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility",
                       "precipitation", "cloud_cover", "so2", "nox", "tsp", "pm25", "pm10"]
        available_stats = [f for f in stats_fields if f in df.columns]

        if available_stats:
            stats = df[available_stats].describe()
            stats.index = ["总数", "均值", "标准差", "最小值", "25%分位", "50%分位", "75%分位", "最大值"]
            st.dataframe(stats.round(2), use_container_width=True)

        # 多站点对比
        multi_station_comparison(df)

    with viz_tab5:
        st.write("### [分布] 要素分布直方图")
        st.caption("用于查看各气象要素的取值分布，默认展示降水量（可叠加其他要素对比）")
        hist_fig = distribution_histogram(df)
        if hist_fig:
            safe_chart(hist_fig, "要素分布直方图", key="viz_hist")
        else:
            st.info("当前数据中缺少可用于分布统计的要素字段")

    with viz_tab6:
        _render_pollution_panel(df)

    with viz_tab7:
        st.write("### [双轴] 时序双要素对比")
        st.caption("自由选择两个气象要素，系统自动适配图表类型（柱状/折线），支持双y轴独立缩放")
        if "timestamp" in df.columns:
            precip_fig = precipitation_timeline(df)
            if precip_fig:
                safe_chart(precip_fig, "时序双要素", key="viz_precip_time")
            else:
                st.info("暂无可用要素，请导入包含温度/降水/气压/湿度/风速等字段的数据")
        else:
            st.info("当前数据中缺少时间戳字段")
