"""
再分析数据处理模块（地基层 M1）

通过抽象层 modules.climate_source 获取再分析气候态：
- 本地 CSV（方案1，优先；支持网页上传或 Secrets 配置路径）
- Open-Meteo 近似兜底（已修复每月只取 28 天的 bug）
距平分析：当前导入数据相对气候态的偏离。
内嵌 ERA5 数据获取向导（modules.era5_wizard），生成可本地运行的下载/处理脚本。
"""

import pandas as pd
import streamlit as st
from datetime import datetime

from modules.climate_source import (
    get_climate_source, LocalFileSource, OpenMeteoSource,
    ClimateStats, ClimateExtreme, ClimateFileError,
)
from modules.era5_wizard import render_era5_wizard


def compute_anomalies(df, climate_stats):
    """计算当前数据与气候态的距平"""
    if climate_stats is None:
        return {}
    if isinstance(climate_stats, ClimateStats):
        climate_stats = climate_stats.to_dict()

    anomalies = {}

    if "temperature" in df.columns:
        current_mean = df["temperature"].dropna().mean()
        ref = climate_stats.get("月均气温")
        if ref is not None:
            anomalies["气温距平"] = {
                "current": current_mean,
                "climate": ref,
                "anomaly": current_mean - ref,
                "unit": "℃",
            }

    if "precipitation" in df.columns:
        current_total = df["precipitation"].dropna().sum()
        ref = climate_stats.get("月总降水量")
        if ref is not None and ref > 0:
            anomalies["降水距平"] = {
                "current": current_total,
                "climate": ref,
                "anomaly": current_total - ref,
                "unit": "mm",
                "pct": (current_total / ref - 1) * 100,
            }

    if "wind_speed" in df.columns:
        current_max = df["wind_speed"].dropna().max()
        ref = climate_stats.get("最大风速均值")
        if ref is not None:
            anomalies["最大风速距平"] = {
                "current": current_max,
                "climate": ref,
                "anomaly": current_max - ref,
                "unit": "m/s",
            }

    return anomalies


def render_climate_ref_tab(df):
    """渲染再分析数据处理 Tab"""
    st.subheader("[日期] 再分析数据处理")

    col1, col2 = st.columns(2)
    with col1:
        lat = st.number_input("纬度", value=39.94, min_value=-90.0, max_value=90.0, step=0.01, key="climate_lat")
    with col2:
        lon = st.number_input("经度", value=116.85, min_value=-180.0, max_value=180.0, step=0.01, key="climate_lon")

    # 自动推断月份
    if df is not None and "timestamp" in df.columns:
        try:
            inferred_month = int(df["timestamp"].dt.month.mode().iloc[0])
        except Exception:
            inferred_month = datetime.now().month
    else:
        inferred_month = datetime.now().month

    if not isinstance(inferred_month, int) or not (1 <= inferred_month <= 12):
        inferred_month = datetime.now().month

    month = st.selectbox("选择参考月份", range(1, 13), index=inferred_month - 1, key="climate_month")

    # 可选：上传本地气候态文件 CSV 或 NetCDF（覆盖 Secrets 配置的文件源）
    uploaded = st.file_uploader(
        "上传气候态文件（CSV 或 NetCDF .nc，可选，覆盖默认文件源）",
        type=["csv", "nc"], key="climate_file_upload")
    local_df = None
    nc_bytes = None
    if uploaded is not None:
        if uploaded.name.lower().endswith(".nc"):
            try:
                nc_bytes = uploaded.getvalue()
                st.caption(f"已载入 NetCDF: {uploaded.name}（{len(nc_bytes)//1024} KB），将自动探测变量。")
            except Exception as e:
                st.error(f"上传 NetCDF 读取失败: {e}")
        else:
            try:
                local_df = pd.read_csv(uploaded)
            except Exception as e:
                st.error(f"上传 CSV 读取失败: {e}")

    if st.button("[导入] 获取气候态数据", use_container_width=True, key="fetch_climate"):
        with st.spinner("正在获取气候态数据..."):
            try:
                if nc_bytes is not None:
                    src = LocalFileSource(nc_bytes=nc_bytes)
                elif local_df is not None:
                    src = LocalFileSource(df=local_df)
                else:
                    src = get_climate_source()
                    if src.name == "localfile" and not src.available():
                        src = OpenMeteoSource()
                climate, extreme = src.fetch_climate_normal(lat, lon, month)
            except ClimateFileError as e:
                st.error(f"本地气候态文件错误: {e}")
                climate, extreme = None, None

        if climate:
            st.session_state["climate_data"] = climate.to_dict()
            st.session_state["climate_extreme"] = extreme.to_dict() if extreme else None
            st.rerun()
        elif nc_bytes is not None or local_df is not None:
            st.error("上传文件中未匹配到该坐标的气候态（请检查经纬度，或放宽 CLIMATE_MAX_RADIUS；NetCDF 请确认变量含气温/降水）")
        else:
            st.error("未能获取气候态数据（无本地文件且 Open-Meteo 不可用）")

    if "climate_data" not in st.session_state:
        st.info("点击上方按钮获取气候态参考数据。默认走 Open-Meteo 近似；可上传本地 CSV / NetCDF(.nc)，或在 Secrets 配置 CLIMATE_LOCAL_CSV / CLIMATE_LOCAL_NC。NetCDF 变量名自动探测（ERA5/CF 及常见命名）。")
        return

    climate = st.session_state["climate_data"]
    st.success(f"气候态数据已加载（{st.session_state.get('climate_lat', '?')}N, {st.session_state.get('climate_lon', '?')}E, {month}月）")

    # 气候态统计
    cols = st.columns(5)
    cols[0].metric("月均气温", f"{climate['月均气温']:.1f}℃")
    cols[1].metric("月均最高", f"{climate['月均最高气温']:.1f}℃")
    cols[2].metric("月均最低", f"{climate['月均最低气温']:.1f}℃")
    cols[3].metric("月总降水", f"{climate['月总降水量']:.0f} mm")
    cols[4].metric("最大风速均值", f"{climate['最大风速均值']:.1f} m/s")

    st.caption(f"参考时段: {climate['数据年份范围']}")

    # 距平分析
    st.write("---")
    st.write("### [统计] 距平分析")

    if df is not None and not df.empty:
        anomalies = compute_anomalies(df, climate)

        if anomalies:
            for name, data in anomalies.items():
                anomaly_val = data["anomaly"]
                direction = "偏高" if anomaly_val > 0 else "偏低" if anomaly_val < 0 else "持平"
                color = "red" if anomaly_val > 0 else "blue"

                detail = f"当前 {data['current']:.1f} {data['unit']}，气候态 {data['climate']:.1f} {data['unit']}，{direction} {abs(anomaly_val):.1f} {data['unit']}"

                if "pct" in data:
                    detail += f" ({data['pct']:+.0f}%)"

                st.markdown(f"**{name}**: <span style='color:{color}'>{detail}</span>", unsafe_allow_html=True)
        else:
            st.info("当前数据缺少可用于距平对比的要素字段")
    else:
        st.info("请先导入数据以进行距平对比")
        if st.button("← 返回导入", key="climate_back"):
            st.session_state["active_tab"] = 0
            st.rerun()

    # 历史极值面板
    extreme = st.session_state.get("climate_extreme")
    if extreme:
        st.write("---")
        st.write("### [极值] 历史同期极值")
        labels = {
            "历史最高气温": "℃", "历史最低气温": "℃",
            "历史最大日降水": "mm", "历史最大风速": "m/s",
        }
        for key, data in extreme.items():
            if data["value"] is not None and data["year"] is not None:
                st.caption(f"{key}: {data['value']:.1f} {labels.get(key, '')} ({data['year']}年)")
            else:
                st.caption(f"{key}: 数据暂缺")

    # ---- ERA5 数据获取向导（M0-M2 一期）----
    render_era5_wizard()
