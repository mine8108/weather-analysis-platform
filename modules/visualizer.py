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

    colors = ["#e0e0e0", "#b0c4de", "#87ceeb", "#5cacee", "#3b8ed4", "#1e6bb8", "#ffa500", "#ff6347", "#cc0000"]

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
    plot_fields = ["temperature", "pressure", "humidity", "wind_speed"]
    available = [f for f in plot_fields if f in df.columns and not df[f].dropna().empty]

    if len(available) < 2:
        return None

    labels = {
        "temperature": "气温 (℃)",
        "pressure": "气压 (hPa)",
        "humidity": "相对湿度 (%)",
        "wind_speed": "风速 (m/s)",
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
    """多站点对比分析"""
    if "station_id" not in df.columns or df["station_id"].nunique() < 2:
        return None

    stations = df["station_id"].unique()
    st.write(f"### [标签] 多站点对比 (共 {len(stations)} 个站点)")

    # 选择对比要素
    compare_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility"]
    available = [f for f in compare_fields if f in df.columns]

    if not available:
        return None

    field = st.selectbox("选择对比要素", available, key="multi_station_field")

    if field not in df.columns:
        return None

    fig = go.Figure()
    palette = px.colors.qualitative.Set1
    for idx, station in enumerate(stations):
        station_df = df[df["station_id"] == station]
        if station_df[field].dropna().empty:
            continue
        color = palette[idx % len(palette)]
        fig.add_trace(go.Scatter(
            x=_safe_xaxis(station_df),
            y=station_df[field],
            mode="lines+markers",
            name=str(station),
            line=dict(color=color, width=2),
            marker=dict(size=3),
        ))

    labels = {
        "temperature": "气温 (℃)",
        "pressure": "气压 (hPa)",
        "humidity": "相对湿度 (%)",
        "wind_speed": "风速 (m/s)",
        "visibility": "能见度 (km)",
    }

    fig.update_layout(
        title=f"多站点 {labels.get(field, field)} 对比",
        xaxis_title="时间",
        yaxis_title=labels.get(field, field),
        hovermode="x unified",
        height=400,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    safe_chart(fig, "多站点对比", use_container_width=True)
    return fig


def distribution_histogram(df):
    """要素分布直方图（默认含降水量），支持多选要素叠加对比"""
    fields = ["precipitation", "temperature", "humidity", "wind_speed",
              "pressure", "visibility", "cloud_cover"]
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
    }
    colors = {
        "precipitation": COLORS["rain_color"],
        "temperature": COLORS["temp_color"],
        "humidity": COLORS["humid_color"],
        "wind_speed": COLORS["wind_color"],
        "pressure": COLORS["pres_color"],
        "visibility": COLORS["vis_color"],
        "cloud_cover": COLORS["purple"],
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
    """时序降水图：柱状降水量 + 可选双y轴叠加折线要素"""
    if "timestamp" not in df.columns or "precipitation" not in df.columns:
        return None

    import numpy as np

    # ---- 聚合选项 ----
    agg_map = {"原始（不聚合）": None, "3小时": "3h", "6小时": "6h", "12小时": "12h", "日累积": "1D"}
    overlay_map = {
        "无（仅降水柱状图）": None, "气温 (℃)": "temperature",
        "气压 (hPa)": "pressure", "相对湿度 (%)": "humidity",
        "风速 (m/s)": "wind_speed",
    }
    # 过滤可用的叠加要素
    avail_overlay = {k: v for k, v in overlay_map.items() if v is None or v in df.columns}

    c1, c2 = st.columns(2)
    with c1:
        agg_sel = st.selectbox("时间聚合", list(agg_map.keys()), index=0, key="precip_agg")
    with c2:
        overlay_sel = st.selectbox("叠加要素（双y轴）", list(avail_overlay.keys()), index=0, key="precip_overlay")

    agg_freq = agg_map[agg_sel]
    overlay_field = avail_overlay.get(overlay_sel)

    # 只保留需要的数值列，避免非数值列导致 resample 聚合报错
    needed_cols = ["timestamp", "precipitation"]
    if overlay_field and overlay_field in df.columns:
        needed_cols.append(overlay_field)

    dff = df[needed_cols].set_index("timestamp").copy()

    if agg_freq:
        agg_dict = {"precipitation": "sum"}
        if overlay_field and overlay_field in dff.columns:
            agg_dict[overlay_field] = "mean"
        dff = dff.resample(agg_freq).agg(agg_dict).dropna(how="all").reset_index()
    else:
        dff = dff.reset_index()

    x_data = dff["timestamp"]
    y_precip = dff["precipitation"]
    has_overlay = overlay_field is not None and overlay_field in dff.columns

    # ---- 构建图形 ----
    if has_overlay:
        overlay_labels = {
            "temperature": ("气温", COLORS["temp_color"], "℃"),
            "pressure": ("气压", COLORS["pres_color"], "hPa"),
            "humidity": ("相对湿度", COLORS["humid_color"], "%"),
            "wind_speed": ("风速", COLORS["wind_color"], "m/s"),
        }
        ol_name, ol_color, ol_unit = overlay_labels.get(overlay_field, (overlay_field, COLORS["primary"], ""))

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        # 柱状降水（主y轴）
        fig.add_trace(
            go.Bar(x=x_data, y=y_precip, name="降水量 (mm)",
                   marker_color=COLORS["rain_color"], opacity=0.75,
                   hovertemplate="降水量: %{y:.1f} mm<extra></extra>"),
            secondary_y=False,
        )
        # 折线叠加要素（次y轴）
        fig.add_trace(
            go.Scatter(x=x_data, y=dff[overlay_field],
                       mode="lines+markers", name=f"{ol_name} ({ol_unit})",
                       line=dict(color=ol_color, width=2), marker=dict(size=3),
                       hovertemplate=f"{ol_name}: %{{y:.1f}} {ol_unit}<extra></extra>"),
            secondary_y=True,
        )
        fig.update_yaxes(title_text="降水量 (mm)", secondary_y=False, gridcolor="#e0e0e0")
        fig.update_yaxes(title_text=f"{ol_name} ({ol_unit})", secondary_y=True,
                         title_font_color=ol_color, tickfont_color=ol_color)
        title = f"时序降水 + {ol_name}（双轴）{agg_sel}"
    else:
        fig = go.Figure(
            go.Bar(x=x_data, y=y_precip, name="降水量 (mm)",
                   marker_color=COLORS["rain_color"], opacity=0.75,
                   hovertemplate="降水量: %{y:.1f} mm<extra></extra>"),
        )
        fig.update_yaxes(title_text="降水量 (mm)", gridcolor="#e0e0e0")
        title = f"时序降水量{agg_sel}"

    fig.update_layout(
        title=title,
        xaxis_title="时间",
        height=460,
        margin=dict(l=50, r=50, t=50, b=50),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(tickangle=-45, nticks=12)

    return fig


def render_visualization_tab(df):
    """渲染可视化 Tab 全部内容"""
    st.subheader("[图表] 可视化分析")

    if df is None or df.empty:
        st.info("请先导入数据")
        return

    # 子Tab
    viz_tab1, viz_tab2, viz_tab3, viz_tab4, viz_tab5, viz_tab6 = st.tabs([
        "[统计] 综合看板", "[风] 风场分析", "[实验] 要素关系", "[列表] 统计摘要", "[分布] 要素分布", "[降水] 时序降水"
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
        ts_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation"]
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
            }
            if selected_ts in ts_config:
                title, color, unit = ts_config[selected_ts]
                ts_fig = time_series_chart(df, selected_ts, f"{title}时间序列", color, title, unit)
                if ts_fig:
                    safe_chart(ts_fig, f"{title}时间序列", key="viz_ts_single")

    with viz_tab4:
        # 统计摘要
        stats_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation", "cloud_cover"]
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
        st.write("### [降水] 时序降水分析")
        st.caption("以柱状图展示降水量随时间变化，可选叠加折线要素形成双y轴对比")
        if "precipitation" in df.columns and "timestamp" in df.columns:
            precip_fig = precipitation_timeline(df)
            if precip_fig:
                safe_chart(precip_fig, "时序降水", key="viz_precip_time")
            else:
                st.info("暂无降水量数据可展示")
        else:
            st.info("当前数据中缺少降水量或时间戳字段，无法绘制时序降水图")
