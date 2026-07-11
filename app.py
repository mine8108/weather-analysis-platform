"""
气象数据交互分析平台 - 主入口
基于 Streamlit 的全功能气象数据导入、可视化、事件检测、报告导出平台
"""

import sys
import os
import streamlit as st
import pandas as pd
from datetime import datetime

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
from utils import df_fingerprint as _df_fingerprint

# ============================================================
# 通用 UI 辅助函数
# ============================================================

def _navigate_to(tab_idx):
    """统一跳转入口，避免 session state 不同步"""
    st.session_state["active_tab"] = tab_idx
    st.rerun()


def _render_data_summary_card():
    """P0: 数据导入完成后显示摘要卡片 + 快捷跳转按钮"""
    df = st.session_state.get("df")
    if df is None or df.empty:
        return

    n = len(df)
    src = st.session_state.get("source", "未知来源")

    # 时间范围
    time_info = ""
    if "timestamp" in df.columns and not df["timestamp"].dropna().empty:
        ts = df["timestamp"].dropna()
        is_synthetic = st.session_state.get("_date_is_synthetic", False)
        if is_synthetic:
            time_info = f"{ts.min().strftime('%H:%M')} ~ {ts.max().strftime('%H:%M')}"
        else:
            time_info = f"{ts.min().strftime('%Y-%m-%d %H:%M')} ~ {ts.max().strftime('%Y-%m-%d %H:%M')}"
    else:
        time_info = f"{n} 条记录"

    # 字段分类
    weather_fields = ["temperature", "pressure", "humidity", "wind_speed",
                       "wind_direction", "precipitation", "visibility", "cloud_cover"]
    pollution_fields = ["so2", "nox", "tsp", "pm25", "pm10"]
    weather_present = [f for f in weather_fields if f in df.columns]
    pollution_present = [f for f in pollution_fields if f in df.columns]

    weather_labels = {"temperature": "气温", "pressure": "气压", "humidity": "湿度",
                       "wind_speed": "风速", "wind_direction": "风向", "precipitation": "降水",
                       "visibility": "能见度", "cloud_cover": "云量"}
    pollution_labels = {"so2": "SO₂", "nox": "NOx", "tsp": "TSP", "pm25": "PM2.5", "pm10": "PM10"}

    weather_text = " · ".join([weather_labels.get(f, f) for f in weather_present[:5]])
    if len(weather_present) > 5:
        weather_text += f" 等{len(weather_present)}项"
    if not weather_text:
        weather_text = "—"

    pollution_text = ""
    if pollution_present:
        pollution_text = " · ".join([pollution_labels.get(f, f) for f in pollution_present])
        pollution_text = f" | 污染物: {pollution_text}"

    # 使用原生 Streamlit 组件确保刷新正确
    with st.container(border=True):
        c1, c2 = st.columns([6, 4])
        with c1:
            st.success(f"数据已就绪 — {src}")
            st.caption(f"{time_info} | {n}条 | {weather_text}{pollution_text}")
        with c2:
            st.write("")
            # 按钮组：根据当前 Tab 智能隐藏（不显示当前所在页的跳转按钮）
            cur_tab = st.session_state.get("active_tab", 0)
            b_col1, b_col2, b_col3 = st.columns(3)
            with b_col1:
                if cur_tab != 2 and st.button("📊 图表", use_container_width=True, key="jump_viz"):
                    _navigate_to(2)
            with b_col2:
                if cur_tab != 3 and st.button("🔔 检测", use_container_width=True, key="jump_alert"):
                    _navigate_to(3)
            with b_col3:
                if cur_tab != 4 and st.button("📤 导出", use_container_width=True, key="jump_export"):
                    _navigate_to(4)

    # 日期范围筛选器
    if "timestamp" in df.columns:
        ts = df["timestamp"].dropna()
        if len(ts) > 1:
            dmin = ts.min().to_pydatetime() if hasattr(ts.min(), "to_pydatetime") else ts.min()
            dmax = ts.max().to_pydatetime() if hasattr(ts.max(), "to_pydatetime") else ts.max()
            date_range = st.date_input(
                "📅 数据时间范围筛选",
                value=(dmin.date(), dmax.date()),
                key="_filter_date_range_input",
            )
            if len(date_range) == 2:
                st.session_state["_filter_date_range"] = date_range
                filtered_n = len(_get_filtered_df())
                if filtered_n != n:
                    st.caption(f"当前筛选：{filtered_n} 条 / 共 {n} 条")

    # 记录导入历史（首次检测到新数据时）
    fp_key = "_last_df_fp"
    current_fp = _df_fingerprint(df)
    if st.session_state.get(fp_key) != current_fp:
        st.session_state[fp_key] = current_fp
        _record_import(src, df)

def _render_progress_bar():
    """P3: 任务流进度条（面包屑风格）"""
    steps = [
        ("[导入]", "f0"),
        ("[质控]", "f1"),
        ("[图表]", "f2"),
        ("[检测]", "f3"),
        ("[导出]", "f4"),
    ]
    # 根据当前 session 数据状态判断进度
    has_data = st.session_state.get("df") is not None
    has_analysis = bool(st.session_state.get("warnings_list") or False)

    current = 0
    if has_data:
        current = 1
    if has_analysis:
        current = 3

    cols = st.columns(len(steps))
    for i, (label, icon) in enumerate(steps):
        with cols[i]:
            if i <= current:
                color = "#1a365d"
                bg = "#e8f0fe"
                mark = "✓"
            else:
                color = "#b0b8c4"
                bg = "#f5f6f8"
                mark = "·"
            st.markdown(f"""
            <div style="
                background: {bg};
                border-radius: 8px;
                padding: 6px 10px;
                text-align: center;
                font-size: 0.78rem;
                font-weight: {600 if i <= current else 400};
                color: {color};
            ">
                {mark} {label}
            </div>
            """, unsafe_allow_html=True)
    st.write("")


def _render_next_step_hint():
    """P2: 根据当前阶段显示下一步推荐"""
    df = st.session_state.get("df")
    has_data = df is not None and not df.empty
    has_forecast = st.session_state.get("fc_df") is not None

    hints = []

    if not has_data:
        hints.append(("&#x1F4C2;", "请先导入数据：上传 CSV/Excel 文件，或使用 API 获取在线数据"))
    elif has_forecast and "fc_analysis" in st.session_state:
        hints.append(("&#x26A1;", "数值预报已生成，前往 [检测] 查看预报驱动的智能分析建议"))

    # 只在有数据时显示
    if has_data and not has_forecast:
        hints.append(("&#x1F4CA;", "下一步推荐：进入 [图表] 查看数据可视化"))
    if has_data and has_forecast:
        hints.append(("&#x1F4CB;", "下一步推荐：进入 [导出] 生成分析报告"))

    for icon, text in hints:
        st.markdown(f"""
        <div style="
            background: #fef9e7;
            border-left: 3px solid #e8943a;
            padding: 8px 14px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 6px;
            font-size: 0.85rem;
            color: #5c4a1f;
        ">
            <span style="margin-right: 6px;">{icon}</span> {text}
        </div>
        """, unsafe_allow_html=True)


def _render_onboarding_page():
    """P4: 空数据时显示图形化三步引导页"""
    from config import ONBOARDING_STEPS

    col_center = st.columns([1, 6, 1])
    with col_center[1]:
        st.markdown("""
        <div style="text-align:center; padding: 30px 0 10px 0;">
            <div style="font-size: 3rem;">🌤️</div>
            <h2 style="margin: 8px 0;">气象数据交互分析平台</h2>
            <p style="color:#888; font-size:0.95rem;">
                三步上手，轻松完成气象数据导入、可视化分析与报告导出
            </p>
        </div>
        """, unsafe_allow_html=True)

        step_cols = st.columns(3)
        for i, step in enumerate(ONBOARDING_STEPS):
            with step_cols[i]:
                with st.container(border=True):
                    st.markdown(f"""
                    <div style="text-align:center; padding: 12px 0;">
                        <div style="font-size: 2.5rem;">{step['icon']}</div>
                        <h4 style="margin: 8px 0;">{step['title']}</h4>
                        <p style="color:#888; font-size:0.8rem;">{step['desc']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(step["action"], use_container_width=True, key=f"onboard_{i}"):
                        _navigate_to(step["tab_idx"])

        st.write("")
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            if st.button("⚡ 快速开始 — 导入数据", use_container_width=True, type="primary",
                         key="onboard_quick"):
                _navigate_to(0)
        st.divider()


def _apply_filter(df):
    """对 DataFrame 应用 session_state 中的筛选条件"""
    if df is None or df.empty:
        return df
    date_range = st.session_state.get("_filter_date_range", None)
    if date_range and len(date_range) == 2 and "timestamp" in df.columns:
        start, end = date_range
        # end 扩展为当天最后一秒，避免过滤掉有小时分钟的数据
        end = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[(df["timestamp"] >= pd.Timestamp(start)) &
                (df["timestamp"] <= end)]
    return df


def _get_filtered_df():
    """获取当前筛选后的 DataFrame"""
    return _apply_filter(st.session_state.get("df"))


def _record_import(source, df):
    """记录导入历史到 session_state"""
    record = {
        "source": source,
        "time": datetime.now().strftime("%H:%M:%S"),
        "n_rows": len(df),
    }
    history = st.session_state.get("_import_history", [])
    history.append(record)
    st.session_state["_import_history"] = history[-5:]


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

# ---- 暗色模式 CSS ----
if st.session_state.get("dark_mode", False):
    st.markdown("""
    <style>
        /* ===== 全局 ===== */
        .stApp { background: #0f172a; }
        .main-header { color: #e2e8f0 !important; }
        .sub-header { color: #94a3b8 !important; }
        h1, h2, h3, h4 { color: #e2e8f0 !important; }
        p, span, label, .stMarkdown { color: #cbd5e1 !important; }

        /* ===== 卡片/容器 (st.container border=True) ===== */
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #1e293b !important;
            border-color: #334155 !important;
        }

        /* ===== 按钮 ===== */
        .stButton > button {
            background: #1e293b !important;
            color: #e2e8f0 !important;
            border-color: #475569 !important;
        }
        .stButton > button:hover {
            background: #334155 !important;
            border-color: #60a5fa !important;
            color: #e2e8f0 !important;
        }
        button[kind="primary"] {
            background: #2563eb !important;
        }
        button[kind="primary"]:hover {
            background: #1d4ed8 !important;
        }

        /* ===== 输入框 ===== */
        .stTextInput input, .stNumberInput input {
            background: #1e293b !important;
            color: #e2e8f0 !important;
            border-color: #475569 !important;
        }
        .stNumberInput button {
            background: #334155 !important;
            color: #e2e8f0 !important;
        }

        /* ===== 展开器 ===== */
        [data-testid="stExpander"] {
            background: #1e293b !important;
            border-color: #334155 !important;
        }
        [data-testid="stExpander"] summary {
            color: #e2e8f0 !important;
        }
        [data-testid="stExpander"] summary:hover {
            color: #60a5fa !important;
        }

        /* ===== 提示框 ===== */
        div.stAlert {
            background: #1e293b !important;
            border-color: #334155 !important;
        }
        div[data-testid="stAlert"] {
            background: #1e293b !important;
        }

        /* ===== 指标 ===== */
        [data-testid="stMetric"] {
            background: #1e293b !important;
            border-color: #334155 !important;
        }
        [data-testid="stMetric"] label { color: #94a3b8 !important; }
        [data-testid="stMetricValue"] { color: #e2e8f0 !important; }

        /* ===== 数据表格 ===== */
        [data-testid="stDataFrame"] { border-color: #334155; }
        [data-testid="stDataFrame"] thead th { background: #1e3a5f !important; }
        [data-testid="stDataFrame"] tbody tr:nth-child(even) { background: #1a2332; }
        [data-testid="stDataFrame"] tbody td { color: #cbd5e1 !important; }

        /* ===== Tab ===== */
        .stTabs [data-baseweb="tab"] { color: #94a3b8 !important; }
        .stTabs [data-baseweb="tab"][aria-selected="true"] { color: #60a5fa !important; }
        .stTabs [data-baseweb="tab-list"] { border-bottom-color: #334155; }

        /* ===== Radio (Tab 导航) ===== */
        .stRadio label { color: #e2e8f0 !important; }
        [data-testid="stRadio"] [role="radiogroup"] label {
            color: #e2e8f0 !important;
        }

        /* ===== 侧边栏 ===== */
        [data-testid="stSidebar"] { background: #0a0f1a; }

        /* ===== 复选框 ===== */
        .stCheckbox label { color: #e2e8f0 !important; }
        .stCheckbox label span { color: #e2e8f0 !important; }

        /* ===== 分割线 ===== */
        hr { border-color: #334155 !important; }

        /* ===== 文件上传 ===== */
        [data-testid="stFileUploader"] section {
            background: #1e293b !important;
            border-color: #475569 !important;
        }
        [data-testid="stFileUploader"] section p {
            color: #94a3b8 !important;
        }

        /* ===== 滚动条 ===== */
        ::-webkit-scrollbar-thumb { background: #475569; }

        /* ===== st.caption + st.success ===== */
        .stCaption { color: #94a3b8 !important; }
        .stSuccess { background: #064e3b !important; }

        /* ===== 移动端适配 ===== */
        @media screen and (max-width: 768px) {
            .main-header { font-size: 1.3rem !important; }
            .sub-header { font-size: 0.8rem !important; }
            [data-testid="column"] { flex: 1 1 100% !important; min-width: 100% !important; }
            .stTabs [data-baseweb="tab"] { padding: 6px 8px !important; font-size: 0.75rem !important; }
            .stButton > button { width: 100% !important; }
            [data-testid="stRadio"] [role="radiogroup"] { flex-direction: column !important; }
            [data-testid="stMetric"] { padding: 8px !important; }
            .js-plotly-plot, .plot-container { max-height: 300px !important; }
            [data-testid="stDataFrame"] { overflow-x: auto !important; }
            .block-container { padding: 1rem 0.5rem !important; }
        }
        @media screen and (min-width: 769px) and (max-width: 1024px) {
            .main-header { font-size: 1.6rem !important; }
            .block-container { padding: 1.5rem 1rem !important; }
        }
    </style>
    """, unsafe_allow_html=True)

# 头部
st.markdown('<div class="main-header">[天气] 气象数据交互分析平台</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">数据导入 · 可视化分析 · 事件检测 · 智能建议 · 数值预报 · 报告导出</div>',
            unsafe_allow_html=True)

# 使用手册（标题行右侧链接）
with st.expander("📖 使用手册", expanded=False):
    st.markdown("""
### 快速入门
1. **导入数据**：支持 CSV / Excel 格式，或通过 API 获取在线气象/空气质量数据
2. **列名自动识别**：系统支持中英文别名，如 `SO2`→`so2`、`二氧化硫`→`so2`、`时间`→`timestamp`
3. **可视化**：7 个子面板，覆盖时间序列、双轴对比、散点矩阵、相关性热力图、风场分析
4. **智能分析**：基于国家预警阈值标准（第16号令）及 GB 3095-2026 空气质量标准生成建议

### 数据格式
- **气象站数据**：无名时间列（HHMMSS 格式）自动识别
- **污染物数据**：支持 `PM2.5 / pm2.5 / SO2 / so2 / NOx` 等 21 种别名
- **API 获取**：Open-Meteo 全球免费 API，无需注册

### 标准引用
- GB 3095-2026《环境空气质量标准》（2026年3月1日实施）
- HJ 633-2026《AQI 技术规定》
- 中国气象局第16号令《气象灾害预警信号发布与传播办法》
""")


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
    if "_import_history" not in st.session_state:
        st.session_state["_import_history"] = []


init_session()

# ============================================================
# 侧边栏：自定义检测阈值
# ============================================================
with st.sidebar:
    st.header("[设置] 自定义检测阈值")

    with st.expander("[工具] 调整阈值（覆盖国家标准）", expanded=False):
        st.caption("留空则使用国家预警阈值标准")

        custom = {}

        st.write("**高温检测阈值 (℃)**")
        col_a, col_b = st.columns(2)
        with col_a:
            ht_y = st.number_input("黄色 ≥", value=35.0, step=0.5, key="ht_y")
        with col_b:
            ht_o = st.number_input("橙色 ≥", value=37.0, step=0.5, key="ht_o")
        ht_r = st.number_input("红色 ≥", value=40.0, step=0.5, key="ht_r")
        custom["high_temp"] = {"黄色": ht_y, "橙色": ht_o, "红色": ht_r}

        st.write("**大风检测阈值 (m/s)**")
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

        st.write("**大雾检测阈值 (m)**")
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
    dark = st.checkbox("[显示] 暗色模式", value=st.session_state.get("dark_mode", False), key="dark_toggle",
                       help="切换深色/浅色主题")
    if dark != st.session_state.get("dark_mode", False):
        st.session_state["dark_mode"] = dark
        st.rerun()
    st.divider()
    # 导入历史
    history = st.session_state.get("_import_history", [])
    if history:
        st.caption("📋 导入历史")
        for h in reversed(history[-3:]):
            st.caption(f"{h['time']} | {h['source']} | {h['n_rows']}条")
    st.divider()
    st.caption("[资料] 中国气象局第16号令 · 气象灾害预警信号发布与传播办法")
    st.caption("© 气象数据交互分析平台 v1.0")
    st.divider()
    st.caption("※ 本平台分析结果仅供学习参考，不替代国家气象部门权威预报。")

# ============================================================
# 主内容区：无数据时显示引导页，有数据时显示提示+摘要
# ============================================================
has_any_data = st.session_state.get("df") is not None
if not has_any_data:
    _render_onboarding_page()
else:
    _render_next_step_hint()
    _render_data_summary_card()

# ---- 标签页导航（支持编程跳转） ----
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = 0

tab_labels = [
    "[导入] 数据导入",
    "[预报] 数值预报",
    "[图表] 可视化分析",
    "[检测] 智能分析与建议",
    "[导出] 报告导出",
    "[日期] 气候态参照",
    "[雷达] 报文解码",
]


# 使用 radio 替代 tabs，支持 index 参数实现编程跳转
# 注意：不使用 key 参数！否则 session_state 旧值会覆盖 index，
# 导致 active_tab 被反向重置，跳转失效
selected = st.radio(
    "",
    tab_labels,
    index=st.session_state["active_tab"],
    horizontal=True,
    label_visibility="collapsed",
)
# 同步：用户手动切换时更新 session_state
active_idx = tab_labels.index(selected) if selected in tab_labels else 0
if active_idx != st.session_state["active_tab"]:
    st.session_state["active_tab"] = active_idx
    st.rerun()

# ---- 导入向导初始化 ----
if "import_step" not in st.session_state:
    st.session_state["import_step"] = 0
if "import_method" not in st.session_state:
    st.session_state["import_method"] = None

# ---- Tab 0: 数据导入向导 ----
if st.session_state["active_tab"] == 0:
    step = st.session_state["import_step"]

    col_w, col_s = st.columns([5, 1])
    with col_s:
        if st.button("跳过向导", key="skip_wizard"):
            st.session_state["import_step"] = 999
            st.rerun()

    # ===== 向导模式 =====
    if step == 0:
        st.write("### 选择数据导入方式")
        st.caption("选择以下任一方式开始导入数据")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📁 上传文件\n\nCSV / Excel", use_container_width=True, key="wiz_file"):
                st.session_state["import_method"] = "file"
                st.session_state["import_step"] = 1
                st.rerun()
        with c2:
            if st.button("✏️ 手动录入\n\n逐条添加观测数据", use_container_width=True, key="wiz_manual"):
                st.session_state["import_method"] = "manual"
                st.session_state["import_step"] = 1
                st.rerun()
        with c3:
            if st.button("🌐 API获取\n\nOpen-Meteo在线数据", use_container_width=True, key="wiz_api"):
                st.session_state["import_method"] = "api"
                st.session_state["import_step"] = 1
                st.rerun()

    elif step == 1:
        method = st.session_state["import_method"]
        labels = {"file": "📁 上传文件", "manual": "✏️ 手动录入", "api": "🌐 API获取"}
        st.write(f"### Step 1: {labels.get(method, method)}")

        if method == "file":
            df_file, source_file = render_file_upload_section()
            render_template_download()
            if df_file is not None:
                st.session_state["df"] = df_file
                st.session_state["source"] = source_file
                st.session_state["import_step"] = 2
                st.rerun()
        elif method == "manual":
            df_manual = render_manual_input_section()
            if df_manual is not None:
                try:
                    df_manual["timestamp"] = pd.to_datetime(df_manual["timestamp"])
                except Exception:
                    pass
                if st.session_state["df"] is not None:
                    st.session_state["df"] = pd.concat([st.session_state["df"], df_manual], ignore_index=True)
                    st.session_state["df"] = st.session_state["df"].sort_values("timestamp").reset_index(drop=True)
                else:
                    st.session_state["df"] = df_manual
                st.session_state["import_step"] = 2
                st.rerun()
        elif method == "api":
            df_api, source_api = render_api_section()
            if df_api is not None:
                st.session_state["df"] = df_api
                if source_api:
                    st.session_state["source"] = source_api
                st.session_state["import_step"] = 2
                st.rerun()

    elif step == 2:
        st.write("### Step 2: 数据预览与质量检查")
        df = st.session_state.get("df")
        if df is not None:
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("记录数", f"{len(df)} 条")
            with col_b:
                na_ratio = df.isna().sum().sum() / (df.shape[0] * df.shape[1]) * 100 if df.shape[0] > 0 else 0
                st.metric("缺失率", f"{na_ratio:.1f}%")
            with col_c:
                outlier_count = 0
                if "temperature" in df.columns:
                    try:
                        temp = pd.to_numeric(df["temperature"], errors="coerce")
                        outlier_count += int(((temp > 55) | (temp < -50)).sum())
                    except Exception:
                        pass
                if "humidity" in df.columns:
                    try:
                        hum = pd.to_numeric(df["humidity"], errors="coerce")
                        outlier_count += int(((hum > 100) | (hum < 0)).sum())
                    except Exception:
                        pass
                st.metric("疑似异常值", f"{outlier_count} 个" if outlier_count > 0 else "0")

            st.dataframe(df.head(10), use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 确认数据，前往可视化分析", use_container_width=True, key="wiz_confirm"):
                    st.session_state["import_step"] = 0
                    _navigate_to(2)
            with c2:
                if st.button("🔄 重新导入", use_container_width=True, key="wiz_retry"):
                    st.session_state["import_step"] = 0
                    st.session_state["import_method"] = None
                    st.rerun()
        else:
            st.warning("未检测到数据，请返回重新导入")
            if st.button("← 返回", key="wiz_back"):
                st.session_state["import_step"] = 0
                st.rerun()

    else:
        # 跳过向导：传统多标签模式
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
                    st.session_state["df"] = pd.concat([st.session_state["df"], df_manual], ignore_index=True)
                    st.session_state["df"] = st.session_state["df"].sort_values("timestamp").reset_index(drop=True)
                else:
                    st.session_state["df"] = df_manual
        with sub_tab3:
            df_api, source_api = render_api_section()
            if df_api is not None:
                st.session_state["df"] = df_api
                st.session_state["source"] = source_api

        if st.session_state["df"] is not None:
            st.divider()
            c_a, c_b = st.columns(2)
            with c_a:
                st.metric("当前数据", f"{len(st.session_state['df'])} 条记录")
            with c_b:
                st.metric("数据来源", st.session_state.get("source", "多源"))
            if st.button("🔄 返回向导模式", key="back_to_wizard"):
                st.session_state["import_step"] = 0
                st.rerun()

# ---- Tab 2: 可视化 ----
if st.session_state["active_tab"] == 2:
    render_visualization_tab(_get_filtered_df())

# ---- Tab 3: 智能分析与建议 ----
if st.session_state["active_tab"] == 3:
    warnings_result = render_analysis_tab(st.session_state["df"])
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

# ---- Tab 4: 报告导出 ----
if st.session_state["active_tab"] == 4:
    render_export_tab(
        st.session_state["df"],
        st.session_state.get("warnings_list", []),
        st.session_state.get("quality_score", 0.0),
        st.session_state.get("source", ""),
    )

# ---- Tab 5: 气候态参照 ----
if st.session_state["active_tab"] == 5:
    render_climate_ref_tab(st.session_state["df"])

# ---- Tab 6: 报文解码 ----
if st.session_state["active_tab"] == 6:
    render_codec_tab()

# ---- Tab 1: 数值预报 ----
if st.session_state["active_tab"] == 1:
    # 预报完成后自动联动：跳转到检测 Tab
    if st.session_state.get("_fc_auto_link", False):
        st.session_state["_fc_auto_link"] = False
        fc_df = st.session_state.get("fc_df")
        if fc_df is not None:
            if "temperature" not in fc_df.columns and "temperature_2m" in fc_df.columns:
                fc_df = fc_df.rename(columns={
                    "temperature_2m": "temperature",
                    "precipitation_sum": "precipitation"
                })
            st.session_state["nwp_forecast_for_analysis"] = fc_df
            st.session_state["nwp_combined"] = True
            _navigate_to(3)

    render_forecast_tab()

    # P1: 预报完成后自动传递到智能分析（保留备用按钮）
    fc_df = st.session_state.get("fc_df", None)
    fc_analysis = st.session_state.get("fc_analysis", "")
    if fc_df is not None:
        st.write("---")
        st.write("### [联动] 预报驱动的智能分析")
        if st.button("[分析] 基于预报数据生成智能建议", use_container_width=True, key="nwp_analyze"):
            if "temperature" not in fc_df.columns and "temperature_2m" in fc_df.columns:
                fc_df = fc_df.rename(columns={"temperature_2m": "temperature",
                                               "precipitation_sum": "precipitation"})
            st.session_state["nwp_combined"] = True
            st.session_state["nwp_forecast_for_analysis"] = fc_df
            _navigate_to(3)

        if fc_analysis:
            pass  # 预报分析摘要已隐藏
