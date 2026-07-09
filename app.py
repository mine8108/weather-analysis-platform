"""
气象数据交互分析平台 - 主入口
基于 Streamlit 的全功能气象数据导入、可视化、预警分析、报告导出平台
"""

import sys
import os
import streamlit as st
import pandas as pd

# 确保模块路径可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PAGE_CONFIG
from modules.data_loader import (
    render_file_upload_section,
    render_manual_input_section,
    render_api_section,
    render_template_download,
)
from modules.data_quality import render_quality_report
from modules.visualizer import render_visualization_tab
from modules.analyzer import (
    render_analysis_tab,
    set_custom_thresholds,
    check_high_temperature,
    check_cold_wave,
    check_gale,
    check_fog,
    check_rainstorm,
    check_frost,
    check_thunderstorm,
    check_haze,
    multi_factor_coupling,
)
from modules.climate_ref import render_climate_ref_tab
from modules.codec import render_codec_tab
from modules.reporter import render_export_tab
from modules.nwp_forecast import render_forecast_tab

# 页面配置
st.set_page_config(**PAGE_CONFIG)

# 自定义CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #888;
        margin-bottom: 1.5rem;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 4px 4px 0 0;
    }
</style>
""", unsafe_allow_html=True)

# 头部
st.markdown('<div class="main-header">[天气] 气象数据交互分析平台</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">数据导入 · 可视化分析 · 国家预警标准检测 · 智能建议 · 数值预报 · 报告导出</div>',
            unsafe_allow_html=True)


# 初始化 session_state
def init_session():
    defaults = {
        "df": None,
        "source": "",
        "quality_score": 0.0,
        "warnings_list": [],
        "manual_data": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()

# ============================================================
# 侧边栏：自定义预警阈值
# ============================================================
with st.sidebar:
    st.header("[设置] 自定义预警阈值")

    with st.expander("[工具] 调整阈值（覆盖国家标准）", expanded=False):
        st.caption("留空则使用国家预警标准")

        custom = {}

        st.write("**高温预警 (℃)**")
        col_a, col_b = st.columns(2)
        with col_a:
            ht_y = st.number_input("黄色 ≥", value=35.0, step=0.5, key="ht_y")
        with col_b:
            ht_o = st.number_input("橙色 ≥", value=37.0, step=0.5, key="ht_o")
        ht_r = st.number_input("红色 ≥", value=40.0, step=0.5, key="ht_r")
        custom["high_temp"] = {"黄色": ht_y, "橙色": ht_o, "红色": ht_r}

        st.write("**大风预警 (m/s)**")
        col_c, col_d = st.columns(2)
        with col_c:
            gw_b = st.number_input("蓝色 ≥", value=10.8, step=0.5, key="gw_b")
        with col_d:
            gw_y = st.number_input("黄色 ≥", value=17.2, step=0.5, key="gw_y")
        col_e, col_f = st.columns(2)
        with col_e:
            gw_o = st.number_input("橙色 ≥", value=24.5, step=0.5, key="gw_o")
        with col_f:
            gw_r = st.number_input("红色 ≥", value=32.7, step=0.5, key="gw_r")
        custom["gale"] = {"蓝色": gw_b, "黄色": gw_y, "橙色": gw_o, "红色": gw_r}

        st.write("**大雾预警 (m)**")
        fg_y = st.number_input("黄色 <", value=500, step=50, key="fg_y")
        fg_o = st.number_input("橙色 <", value=200, step=50, key="fg_o")
        fg_r = st.number_input("红色 <", value=50, step=10, key="fg_r")
        custom["fog"] = {"黄色": fg_y, "橙色": fg_o, "红色": fg_r}

        if st.button("[OK] 应用自定义阈值", use_container_width=True):
            set_custom_thresholds(custom)
            st.success("自定义阈值已应用！")

    st.divider()
    st.checkbox("[调试] 显示详细错误信息", value=False, key="debug_mode",
                help="开启后，图表渲染失败时会展示完整的 Python 报错堆栈，便于排查问题。")
    st.divider()
    st.caption("[资料] 中国气象局第16号令 · 气象灾害预警信号发布与传播办法")
    st.caption("© 气象数据交互分析平台 v1.0")

# ============================================================
# 主内容区：Tab 导航
# ============================================================
tabs = st.tabs([
    "[导入] 数据导入",
    "[实验] 数据质控",
    "[图表] 可视化分析",
    "[预警] 智能分析与建议",
    "[导出] 报告导出",
    "[日期] 气候态参照",
    "[雷达] 报文解码",
    "[预报] 数值预报",
])

# ---- Tab 1: 数据导入 ----
with tabs[0]:
    sub_tab1, sub_tab2, sub_tab3 = st.tabs(["[文件] 文件导入", "[编辑] 手动录入", "[网络] API 获取"])

    with sub_tab1:
        df_file, source_file = render_file_upload_section()
        if df_file is not None:
            st.session_state["df"] = df_file
            st.session_state["source"] = source_file
        render_template_download()

    with sub_tab2:
        df_manual = render_manual_input_section()
        if df_manual is not None:
            try:
                df_manual["timestamp"] = pd.to_datetime(df_manual["timestamp"])
            except Exception:
                pass
            if st.session_state["df"] is not None:
                st.session_state["df"] = pd.concat(
                    [st.session_state["df"], df_manual], ignore_index=True
                )
                st.session_state["df"] = st.session_state["df"].sort_values("timestamp").reset_index(drop=True)
            else:
                st.session_state["df"] = df_manual

    with sub_tab3:
        df_api, source_api = render_api_section()
        if df_api is not None:
            st.session_state["df"] = df_api
            st.session_state["source"] = source_api

    # 在导入 Tab 底部显示合并后的数据概览
    if st.session_state["df"] is not None:
        st.divider()
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("当前数据", f"{len(st.session_state['df'])} 条记录")
        with col_b:
            st.metric("数据来源", st.session_state.get("source", "多源"))

# ---- Tab 2: 数据质控 ----
with tabs[1]:
    result = render_quality_report(st.session_state["df"])
    if result:
        score, issues = result
        st.session_state["quality_score"] = score

# ---- Tab 3: 可视化分析 ----
with tabs[2]:
    render_visualization_tab(st.session_state["df"])

# ---- Tab 4: 智能分析与建议 ----
with tabs[3]:
    warnings_result = render_analysis_tab(st.session_state["df"])
    # 收集预警列表（从 session state 间接获取）
    if st.session_state["df"] is not None:
        all_w = []
        all_w += check_high_temperature(st.session_state["df"])
        all_w += check_cold_wave(st.session_state["df"])
        all_w += check_gale(st.session_state["df"])
        all_w += check_fog(st.session_state["df"])
        all_w += check_rainstorm(st.session_state["df"])
        all_w += check_frost(st.session_state["df"])
        all_w += check_thunderstorm(st.session_state["df"])
        all_w += check_haze(st.session_state["df"])
        st.session_state["warnings_list"] = all_w

# ---- Tab 5: 报告导出 ----
with tabs[4]:
    render_export_tab(
        st.session_state["df"],
        st.session_state.get("warnings_list", []),
        st.session_state.get("quality_score", 0.0),
        st.session_state.get("source", ""),
    )

# ---- Tab 6: 气候态参照 ----
with tabs[5]:
    render_climate_ref_tab(st.session_state["df"])

# ---- Tab 7: 报文解码 ----
with tabs[6]:
    render_codec_tab()

# ---- Tab 8: 数值预报 ----
with tabs[7]:
    render_forecast_tab()
