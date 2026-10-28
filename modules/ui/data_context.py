"""Dataset identity and date filter shared by observation charts and exports."""
import pandas as pd
import streamlit as st


def _save_range():
    value = st.session_state.get("_filter_date_range_input")
    if value and len(value) == 2:
        st.session_state["_filter_date_range"] = value


def render_data_context(df, source=""):
    if df is None or df.empty:
        return df
    with st.container(border=True, key="data_context"):
        dataset, dates, count = st.columns([1.4, 1.4, 1])
        dataset.caption("当前数据集")
        dataset.write(source or st.session_state.get("source") or "当前观测数据")
        filtered = df
        if "timestamp" in df:
            times = pd.to_datetime(df["timestamp"], errors="coerce")
            valid = times.dropna()
            if not valid.empty:
                low, high = valid.min().date(), valid.max().date()
                saved = st.session_state.get("_filter_date_range")
                selected = saved if saved and len(saved) == 2 and low <= saved[0] <= saved[1] <= high else (low, high)
                current = st.session_state.get("_filter_date_range_input")
                if current is None or any(day < low or day > high for day in current):
                    st.session_state["_filter_date_range_input"] = selected
                value = dates.date_input("分析时间范围", min_value=low, max_value=high, key="_filter_date_range_input", on_change=_save_range)
                if len(value) == 2:
                    st.session_state["_filter_date_range"] = value
                    filtered = df.loc[times.dt.date.between(value[0], value[1])].copy()
                else:
                    filtered = df.loc[times.dt.date.between(selected[0], selected[1])].copy()
                    dates.caption("请选定结束日期；当前保留上一次完整选择的范围。")
        else:
            dates.caption("未提供时间字段，按原始记录顺序展示。")
        count.caption("当前范围")
        count.write(f"{len(filtered):,} / {len(df):,} 条记录")
    return filtered
