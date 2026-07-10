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

# ============================================================
# 通用 UI 辅助函数
# ============================================================

def _render_data_summary_card():
    """P0: 数据导入完成后显示摘要卡片 + 快捷跳转"""
    df = st.session_state.get("df")
    if df is None or df.empty:
        return

    n = len(df)
    time_info = ""
    if "timestamp" in df.columns and not df["timestamp"].dropna().empty:
        ts = df["timestamp"].dropna()
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

    src = st.session_state.get("source", "未知来源")

    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #f0f7ff 0%, #e8f4e8 100%);
        border: 1px solid #b8d4e8;
        border-radius: 12px;
        padding: 16px 20px;
        margin: 8px 0 16px 0;
    ">
        <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 24px;">&#x2705;</span>
            <div style="flex: 1;">
                <div style="font-weight: 700; font-size: 0.95rem; color: #1a365d; margin-bottom: 4px;">
                    数据已就绪 — {src}
                </div>
                <div style="font-size: 0.85rem; color: #4a6a8a;">
                    {time_info} | {n}条 | {weather_text}{pollution_text}
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


def _render_progress_bar():
    """P3: 任务流进度条（面包屑风格）"""
    steps = [
        ("[导入]", "f0"),
        ("[质控]", "f1"),
        ("[图表]", "f2"),
        ("[预警]", "f3"),
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
        hints.append(("&#x26A1;", "数值预报已生成，前往 [预警] 查看预报驱动的智能分析建议"))

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
        .stApp { background: #0f172a; }
        .main-header { color: #e2e8f0 !important; }
        .sub-header { color: #94a3b8 !important; }
        h1, h2, h3, h4 { color: #e2e8f0 !important; }
        p, span, label, .stMarkdown { color: #cbd5e1 !important; }
        [data-testid="stExpander"] { background: #1e293b; border-color: #334155; }
        [data-testid="stMetric"] { background: #1e293b; border-color: #334155; }
        [data-testid="stMetric"] label { color: #94a3b8 !important; }
        [data-testid="stMetricValue"] { color: #e2e8f0 !important; }
        [data-testid="stDataFrame"] { border-color: #334155; }
        [data-testid="stDataFrame"] thead th { background: #1e3a5f !important; }
        [data-testid="stDataFrame"] tbody tr:nth-child(even) { background: #1a2332; }
        [data-testid="stDataFrame"] tbody td { color: #cbd5e1 !important; }
        .stTabs [data-baseweb="tab"] { color: #94a3b8 !important; }
        .stTabs [data-baseweb="tab"][aria-selected="true"] { color: #60a5fa !important; }
        .stTabs [data-baseweb="tab-list"] { border-bottom-color: #334155; }
        [data-testid="stSidebar"] { background: #0a0f1a; }
        button[kind="primary"] { background: #2563eb !important; }
        ::-webkit-scrollbar-thumb { background: #475569; }
    </style>
    """, unsafe_allow_html=True)

# 头部
st.markdown('<div class="main-header">[天气] 气象数据交互分析平台</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">数据导入 · 可视化分析 · 国家预警标准检测 · 智能建议 · 数值预报 · 报告导出</div>',
            unsafe_allow_html=True)

# 使用手册（标题行右侧链接）
with st.expander("📖 使用手册", expanded=False):
    st.markdown("""
### 快速入门
1. **导入数据**：支持 CSV / Excel / NetCDF 格式，或通过 API 获取在线气象/空气质量数据
2. **列名自动识别**：系统支持中英文别名，如 `SO2`→`so2`、`二氧化硫`→`so2`、`时间`→`timestamp`
3. **可视化**：7 个子面板，覆盖时间序列、双轴对比、散点矩阵、相关性热力图、风场分析
4. **智能分析**：基于国家预警标准（第16号令）及 GB 3095-2026 空气质量标准生成建议

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
    dark = st.checkbox("[显示] 暗色模式", value=st.session_state.get("dark_mode", False), key="dark_toggle",
                       help="切换深色/浅色主题")
    if dark != st.session_state.get("dark_mode", False):
        st.session_state["dark_mode"] = dark
        st.rerun()
    st.divider()
    st.caption("[资料] 中国气象局第16号令 · 气象灾害预警信号发布与传播办法")
    st.caption("© 气象数据交互分析平台 v1.0")
    st.divider()
    st.caption("※ 本平台分析结果仅供学习参考，不替代国家气象部门权威预报。")

# ============================================================
# 主内容区：进度条 + 下一步提示 + Tab 导航
# ============================================================
_render_progress_bar()
_render_next_step_hint()
_render_data_summary_card()

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

    # P1: 预报完成后自动传递到智能分析
    fc_df = st.session_state.get("fc_df", None)
    fc_analysis = st.session_state.get("fc_analysis", "")
    if fc_df is not None:
        st.write("---")
        st.write("### [联动] 预报驱动的智能分析")
        if st.button("[分析] 基于预报数据生成智能建议", use_container_width=True, key="nwp_analyze"):
            # 将预报数据转为分析用的 DataFrame
            if "temperature" not in fc_df.columns and "temperature_2m" in fc_df.columns:
                fc_df = fc_df.rename(columns={"temperature_2m": "temperature",
                                               "precipitation_sum": "precipitation"})
            st.session_state["nwp_combined"] = True
            st.session_state["nwp_forecast_for_analysis"] = fc_df
            st.success("预报数据已传递给智能分析模块！请前往 [预警] Tab 查看基于预报的建议。")
            st.info("提示：在 [预警] Tab 中，系统将自动结合预报数据生成：\n"
                    "- 未来气温趋势与高温预警\n"
                    "- 降水量预测与暴雨风险评估\n"
                    "- 风速预报与大风预警")

        if fc_analysis:
            with st.expander("[报告] 预报分析摘要", expanded=True):
                st.markdown(fc_analysis)
