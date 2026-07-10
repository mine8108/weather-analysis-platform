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

from config import PAGE_CONFIG, DESIGN_TOKENS
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

# ---- 自定义 CSS：Level 1+2 视觉升级 ----
# 设计方向：技术风气象站 — 深海军蓝权威感 + 冰蓝数据色 + 琥珀警示
# 美学选择：高对比度浅色主题、bento-grid 布局、玻璃态卡片、流体间距
st.markdown(f"""
<style>
    /* ========== 0. Google Fonts 注入 ========== */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ========== 1. CSS 设计 tokens ========== */
    :root {{
        --navy-900: {DESIGN_TOKENS["navy_900"]};
        --navy-700: {DESIGN_TOKENS["navy_700"]};
        --navy-500: {DESIGN_TOKENS["navy_500"]};
        --ice-600: {DESIGN_TOKENS["ice_600"]};
        --ice-500: {DESIGN_TOKENS["ice_500"]};
        --ice-100: {DESIGN_TOKENS["ice_100"]};
        --ice-50: {DESIGN_TOKENS["ice_50"]};
        --amber-500: {DESIGN_TOKENS["amber_500"]};
        --emerald-500: {DESIGN_TOKENS["emerald_500"]};
        --coral-500: {DESIGN_TOKENS["coral_500"]};
        --surface: {DESIGN_TOKENS["surface"]};
        --card: {DESIGN_TOKENS["card"]};
        --text: {DESIGN_TOKENS["text"]};
        --text-muted: {DESIGN_TOKENS["text_muted"]};
        --border: {DESIGN_TOKENS["border"]};
        --shadow-sm: {DESIGN_TOKENS["shadow_sm"]};
        --shadow-md: {DESIGN_TOKENS["shadow_md"]};
        --shadow-lg: {DESIGN_TOKENS["shadow_lg"]};
        --radius-sm: 8px;
        --radius-md: 12px;
        --radius-lg: 20px;
        --radius-xl: 28px;
    }}

    /* ========== 2. 全局排版与背景 ========== */
    .stApp {{
        background: var(--surface);
    }}

    html, body, [class*="st-"], .stMarkdown, p, span, div {{
        font-family: 'Noto Sans SC', 'Outfit', -apple-system, sans-serif !important;
    }}

    h1, h2, h3, h4, .main-header {{
        font-family: 'Outfit', 'Noto Sans SC', -apple-system, sans-serif !important;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: var(--navy-900);
    }}

    code, pre, .stCodeBlock, [data-testid="stCodeBlock"] {{
        font-family: 'JetBrains Mono', 'Consolas', monospace !important;
    }}

    /* ========== 3. 顶部装饰栏 ========== */
    [data-testid="stDecoration"] {{
        background: linear-gradient(90deg, var(--navy-900) 0%, var(--navy-700) 40%, var(--ice-600) 100%);
        height: 3px;
    }}

    /* ========== 4. 主头部 ========== */
    .main-header {{
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, var(--navy-900) 0%, var(--ice-600) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.4rem;
        letter-spacing: -0.03em;
    }}

    .sub-header {{
        font-size: 0.95rem;
        color: var(--text-muted);
        margin-bottom: 1.5rem;
        font-weight: 400;
        letter-spacing: 0.01em;
    }}

    /* ========== 5. 侧边栏：深色主题 ========== */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, #0f1a2e 0%, #162544 100%);
        border-right: 1px solid rgba(255,255,255,0.06);
    }}

    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4 {{
        color: #e8ecf1 !important;
    }}

    [data-testid="stSidebar"] .stMarkdown p {{
        color: #94a3b8 !important;
    }}

    [data-testid="stSidebar"] [data-testid="stExpander"] {{
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: var(--radius-md);
    }}

    [data-testid="stSidebar"] .stButton button {{
        background: var(--ice-600) !important;
        color: white !important;
        border: none !important;
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        transition: all 0.2s ease;
    }}

    [data-testid="stSidebar"] .stButton button:hover {{
        background: var(--ice-500) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
    }}

    [data-testid="stSidebar"] input[type="number"] {{
        background: rgba(255,255,255,0.06) !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        color: #e8ecf1 !important;
        border-radius: var(--radius-sm) !important;
    }}

    [data-testid="stSidebar"] hr {{
        border-color: rgba(255,255,255,0.08);
    }}

    /* ========== 6. Tab 导航栏 ========== */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 2px;
        background: transparent;
        border-bottom: 2px solid var(--border);
        padding: 0;
    }}

    .stTabs [data-baseweb="tab"] {{
        padding: 10px 20px;
        border-radius: var(--radius-sm) var(--radius-sm) 0 0;
        font-size: 0.9rem;
        font-weight: 500;
        color: var(--text-muted);
        background: transparent;
        transition: all 0.2s ease;
        border: none;
        position: relative;
    }}

    .stTabs [data-baseweb="tab"]:hover {{
        color: var(--navy-700);
        background: var(--ice-50);
    }}

    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        color: var(--ice-600) !important;
        font-weight: 600;
        background: transparent;
    }}

    .stTabs [data-baseweb="tab"][aria-selected="true"]::after {{
        content: '';
        position: absolute;
        bottom: -2px;
        left: 0;
        right: 0;
        height: 2.5px;
        background: linear-gradient(90deg, var(--navy-700), var(--ice-600));
        border-radius: 2px 2px 0 0;
    }}

    /* ========== 7. 卡片容器 ========== */
    [data-testid="stExpander"] {{
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-sm);
        transition: box-shadow 0.2s ease;
    }}

    [data-testid="stExpander"]:hover {{
        box-shadow: var(--shadow-md);
    }}

    /* ========== 8. 指标卡 ========== */
    [data-testid="stMetric"] {{
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: 16px 20px;
        box-shadow: var(--shadow-sm);
        transition: all 0.25s ease;
        border-left: 3px solid var(--ice-500);
    }}

    [data-testid="stMetric"]:hover {{
        transform: translateY(-2px);
        box-shadow: var(--shadow-md);
        border-left-color: var(--ice-600);
    }}

    [data-testid="stMetric"] label {{
        font-size: 0.8rem;
        font-weight: 500;
        color: var(--text-muted);
        letter-spacing: 0.02em;
        text-transform: uppercase;
    }}

    [data-testid="stMetric"] [data-testid="stMetricValue"] {{
        font-size: 1.8rem;
        font-weight: 700;
        color: var(--text);
        font-family: 'Outfit', 'Noto Sans SC', sans-serif;
    }}

    /* ========== 9. 按钮 ========== */
    .stButton button {{
        font-weight: 600 !important;
        border-radius: var(--radius-sm) !important;
        transition: all 0.2s ease !important;
        letter-spacing: 0.01em;
    }}

    .stButton button[kind="primary"] {{
        background: var(--ice-600) !important;
        border: none !important;
        color: white !important;
    }}

    .stButton button[kind="primary"]:hover {{
        background: var(--navy-500) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
    }}

    .stButton button[kind="secondary"] {{
        background: var(--card) !important;
        border: 1px solid var(--border) !important;
        color: var(--text) !important;
    }}

    .stButton button[kind="secondary"]:hover {{
        border-color: var(--ice-500) !important;
        color: var(--ice-600) !important;
    }}

    /* ========== 10. 数据表格 ========== */
    [data-testid="stDataFrame"] {{
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        overflow: hidden;
        box-shadow: var(--shadow-sm);
    }}

    [data-testid="stDataFrame"] thead th {{
        background: var(--navy-700) !important;
        color: white !important;
        font-weight: 600;
        font-size: 0.82rem;
        letter-spacing: 0.02em;
        padding: 10px 14px !important;
    }}

    [data-testid="stDataFrame"] tbody tr:nth-child(even) {{
        background: var(--surface);
    }}

    [data-testid="stDataFrame"] tbody tr:hover {{
        background: var(--ice-50);
    }}

    [data-testid="stDataFrame"] tbody td {{
        padding: 8px 14px !important;
        font-size: 0.88rem;
    }}

    /* ========== 11. 提示框 ========== */
    .stAlert {{
        border-radius: var(--radius-md) !important;
        border: none !important;
        font-weight: 400;
    }}

    [data-testid="stSuccess"] {{
        background: {DESIGN_TOKENS["emerald_100"]} !important;
        color: {DESIGN_TOKENS["emerald_500"]} !important;
    }}

    [data-testid="stWarning"] {{
        background: {DESIGN_TOKENS["amber_100"]} !important;
        color: #92400e !important;
    }}

    [data-testid="stError"] {{
        background: {DESIGN_TOKENS["coral_100"]} !important;
        color: {DESIGN_TOKENS["coral_500"]} !important;
    }}

    [data-testid="stInfo"] {{
        background: var(--ice-50) !important;
        color: var(--ice-600) !important;
    }}

    /* ========== 12. 滚动条 ========== */
    ::-webkit-scrollbar {{
        width: 6px;
        height: 6px;
    }}

    ::-webkit-scrollbar-track {{
        background: transparent;
    }}

    ::-webkit-scrollbar-thumb {{
        background: #cbd5e1;
        border-radius: 3px;
    }}

    ::-webkit-scrollbar-thumb:hover {{
        background: #94a3b8;
    }}

    /* ========== 13. Bento-Grid 仪表盘容器 ========== */
    .bento-grid {{
        display: grid;
        grid-template-columns: 1.2fr 0.8fr;
        grid-template-rows: auto auto;
        gap: clamp(12px, 2vw, 20px);
        margin: 0 0 1rem 0;
    }}

    .bento-tile {{
        background: var(--card);
        border: 1px solid var(--border);
        border-radius: var(--radius-lg);
        padding: clamp(14px, 2vw, 22px);
        box-shadow: var(--shadow-sm);
        transition: box-shadow 0.25s ease;
    }}

    .bento-tile:hover {{
        box-shadow: var(--shadow-md);
    }}

    .bento-tile.large {{
        grid-row: span 2;
    }}

    .bento-tile-header {{
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 12px;
        padding-bottom: 10px;
        border-bottom: 1px solid var(--border);
    }}

    .bento-tile-header h4 {{
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--navy-700);
        margin: 0;
    }}

    .bento-tile-header .tile-icon {{
        width: 28px;
        height: 28px;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
    }}

    /* ========== 14. 预警卡片 ========== */
    .warn-card {{
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 14px 16px;
        border-radius: var(--radius-md);
        margin-bottom: 8px;
        border-left: 4px solid;
        transition: transform 0.15s ease;
    }}

    .warn-card:hover {{
        transform: translateX(4px);
    }}

    .warn-card .warn-icon {{
        font-size: 1.5rem;
        line-height: 1;
    }}

    .warn-card .warn-content h5 {{
        margin: 0 0 3px 0;
        font-size: 0.9rem;
        font-weight: 600;
    }}

    .warn-card .warn-content p {{
        margin: 0;
        font-size: 0.82rem;
        color: var(--text-muted);
    }}

    /* ========== 15. 响应式 ========== */
    @media (max-width: 768px) {{
        .bento-grid {{
            grid-template-columns: 1fr;
            grid-template-rows: auto;
        }}
        .bento-tile.large {{
            grid-row: span 1;
        }}
    }}
</style>
""", unsafe_allow_html=True)

# 头部
st.markdown("""
<div class="main-header">气象数据交互分析平台</div>
<div class="sub-header">数据导入 · 可视化分析 · 国家预警标准检测 · 智能建议 · 数值预报 · 报告导出</div>
""", unsafe_allow_html=True)


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
