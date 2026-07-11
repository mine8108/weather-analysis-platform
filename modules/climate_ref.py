"""
气候态背景参照模块：通过 Open-Meteo API 获取 ERA5 气候态数据
"""

import pandas as pd
import streamlit as st
from datetime import datetime


def fetch_climate_normal(lat, lon, month):
    """
    获取指定月份的气候态统计（均值 + 历史极值）。
    Open-Meteo 不直接提供气候态，使用多年平均作为替代。
    返回 (climate_stats, extreme_dict) 或 (None, None)
    """
    import requests

    current_year = datetime.now().year
    years_range = range(current_year - 5, current_year)

    all_data = []
    for year in years_range:
        start = f"{year}-{month:02d}-01"
        end = f"{year}-12-31" if month == 12 else f"{year}-{month:02d}-28"

        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": start, "end_date": end,
            "daily": [
                "temperature_2m_max", "temperature_2m_min",
                "temperature_2m_mean", "precipitation_sum",
                "wind_speed_10m_max",
            ],
            "timezone": "Asia/Shanghai",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
            if "daily" in data:
                df = pd.DataFrame(data["daily"])
                df["year"] = year
                all_data.append(df)
        except Exception:
            continue

    if not all_data:
        return None, None

    combined = pd.concat(all_data, ignore_index=True)

    climate_stats = {
        "月均最高气温": combined["temperature_2m_max"].mean(),
        "月均最低气温": combined["temperature_2m_min"].mean(),
        "月均气温": combined["temperature_2m_mean"].mean(),
        "月总降水量": combined["precipitation_sum"].mean() * 30,
        "最大风速均值": combined["wind_speed_10m_max"].mean(),
        "数据年份范围": f"{years_range[0]}-{years_range[-1]}",
    }

    # 历史极值
    extreme = {
        "历史最高气温": {"value": combined["temperature_2m_max"].max(),
                         "year": int(combined.loc[combined["temperature_2m_max"].idxmax(), "year"])},
        "历史最低气温": {"value": combined["temperature_2m_min"].min(),
                         "year": int(combined.loc[combined["temperature_2m_min"].idxmin(), "year"])},
        "历史最大日降水": {"value": combined["precipitation_sum"].max(),
                          "year": int(combined.loc[combined["precipitation_sum"].idxmax(), "year"])},
        "历史最大风速": {"value": combined["wind_speed_10m_max"].max(),
                         "year": int(combined.loc[combined["wind_speed_10m_max"].idxmax(), "year"])},
    }

    return climate_stats, extreme


def compute_anomalies(df, climate_stats):
    """计算当前数据与气候态的距平"""
    if climate_stats is None:
        return {}

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
    """渲染气候态参考 Tab"""
    st.subheader("[日期] 气候态背景参照")

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

    # 防御：确保 inferred_month 是 1-12 的有效整数
    if not isinstance(inferred_month, int) or not (1 <= inferred_month <= 12):
        inferred_month = datetime.now().month

    month = st.selectbox("选择参考月份", range(1, 13), index=inferred_month - 1, key="climate_month")

    if st.button("[导入] 获取气候态数据", use_container_width=True, key="fetch_climate"):
        with st.spinner("正在获取气候态数据（过去5年均值）..."):
            climate, extreme = fetch_climate_normal(lat, lon, month)

        if climate:
            st.session_state["climate_data"] = climate
            st.session_state["climate_extreme"] = extreme
            st.rerun()

    if "climate_data" not in st.session_state:
        st.info("点击上方按钮获取气候态参考数据")
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
            st.caption(f"{key}: {data['value']:.1f} {labels.get(key, '')} ({data['year']}年)")
