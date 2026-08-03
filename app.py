"""
气象数据交互分析平台 - 主入口
基于 Streamlit 的全功能气象数据导入、可视化、事件检测、报告导出平台
"""

import sys
import os
from datetime import datetime

import streamlit as st
import pandas as pd

# 确保模块路径可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PAGE_CONFIG, FIELD_LABELS, APP_VERSION
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
    check_against_extremes,
    multi_factor_coupling,
)
from modules.codec import render_codec_tab
from modules.reporter import render_export_tab
from modules.nwp_forecast import render_forecast_tab
from utils import df_fingerprint as _df_fingerprint, go_back as _go_back
from auth import render_auth_page, is_authenticated, sign_out_user
from modules import theme_aether
from modules.weather_wall import render_wall

# 主题初始化：必须在任何读取 dark_mode 的代码（CSS 注入、_is_dark）之前执行。
# 优先级：session_state > 云端(登录时写入) > 本地文件 > 默认浅色。
theme_aether.init_theme()

# 天气墙显示开关初始化：从持久化读回（用户上次选择，刷新/重启保持）
if "_wall_show" not in st.session_state:
    from modules.city_prefs import load_show_wall
    st.session_state["_wall_show"] = load_show_wall()

# ============================================================
# 通用 UI 辅助函数
# ============================================================

# 导航栈初始化
if "_nav_stack" not in st.session_state:
    st.session_state["_nav_stack"] = []


def _tab_error(name, exc):
    """顶层错误边界：单 tab 异常隔离，显示友好提示而非整页白屏。"""
    st.error("⚠️「%s」页面加载出现异常，已隔离处理，不影响其他功能。" % name)
    with st.expander("查看错误详情（可截图反馈开发者）"):
        st.exception(exc)
    st.caption("💡 可点击上方导航切换到其他页面继续操作。")
    if st.button("🔄 重置会话并回到首页", key="reset_%s" % name):
        _safe_reset()


def _safe_render(name, fn, *args, **kwargs):
    """包裹 tab 渲染调用，异常时走 _tab_error 而非抛出白屏。"""
    try:
        return fn(*args, **kwargs)
    except Exception as _exc:
        _tab_error(name, _exc)
        return None


def _safe_reset():
    """错误恢复：清除应用数据，保留导航默认值和登录态，回到导入页。"""
    keep = {"active_tab", "import_step", "import_method", "_nav_stack", "auth_user"}
    keep |= {k for k in st.session_state if k.startswith(("auth_", "invite_", "admin_"))}
    for _k in list(st.session_state.keys()):
        if _k not in keep:
            del st.session_state[_k]
    st.session_state["active_tab"] = 0
    st.session_state["import_step"] = 0
    st.session_state["import_method"] = None


# Tab 名称映射(用于重置按钮显示当前 Tab 名)
_TAB_NAMES = ["导入", "可视化", "数值预报", "智能分析", "报告导出", "报文解码"]

# 每个 Tab 重置时清理的 session_state key(精确匹配 + "_" 前缀动态匹配)
_RESET_KEYS_BY_TAB = {
    "导入": ["df", "source", "import_step", "import_method", "manual_data", "raw_df",
             "import_warnings", "_template_cache", "era5_data", "era5_lat", "era5_lon",
             # 天气墙状态（首页=导入 Tab 顶部）：重置后彻底清理，含一次性提示与定位组件值
             "wall_cities", "wall_query", "wall_geo", "wall_candidate_pick",
             "_resolve_candidates", "_wall_notice", "_geo_consumed", "_relocate"],
    "数值预报": ["fc_df", "fc_analysis", "fc_grid", "fc_hour", "life_indices",
                 "nwp_forecast_for_analysis", "nwp_combined"],
    "可视化": ["multi_station_selected"],
    "智能分析": ["warnings_list", "quality_score", "_warn_fp"],
    "报告导出": ["report_data"],
    "报文解码": ["manual_data"],
}


def _reset_current_tab():
    """清空当前 Tab 的业务数据 key,保留登录态(auth_user)、导航栈、阈值设置。
    用于侧边栏「重置当前模块数据」按钮。
    """
    tab_idx = st.session_state.get("active_tab", 0)
    tab_name = _TAB_NAMES[tab_idx] if 0 <= tab_idx < len(_TAB_NAMES) else "当前模块"
    keys = _RESET_KEYS_BY_TAB.get(tab_name, [])
    removed = []
    for k in list(st.session_state.keys()):
        # 精确匹配 + "key_" 前缀动态匹配(如 api_data_xxx)
        if any(k == p or k.startswith(p + "_") for p in keys):
            del st.session_state[k]
            removed.append(k)
    # 天气墙状态被清理时，同步清空持久化文件：否则下次渲染 load_cities()
    # 会把重置前的城市从磁盘读回，"重置彻底清理"不生效
    if any(r.startswith("wall_") for r in removed):
        from modules.city_prefs import save_cities
        save_cities([])
    if removed:
        st.toast(f"[OK] {tab_name}已重置（清理 {len(removed)} 项）", icon="🧹")
    else:
        st.toast(f"[OK] {tab_name}无需清理", icon="✓")
    st.rerun()


def _navigate_to(tab_idx):
    """统一跳转入口：入栈当前 tab，跳转目标 tab"""
    cur = st.session_state.get("active_tab", 0)
    if cur != tab_idx:
        stack = st.session_state.get("_nav_stack", [])
        stack.append(cur)
        # 保留最近 10 层
        if len(stack) > 10:
            stack = stack[-10:]
        st.session_state["_nav_stack"] = stack
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

    weather_text = " · ".join([FIELD_LABELS.get(f, f).split(" (")[0] for f in weather_present[:5]])
    if len(weather_present) > 5:
        weather_text += f" 等{len(weather_present)}项"
    if not weather_text:
        weather_text = "—"

    pollution_text = ""
    if pollution_present:
        pollution_text = " · ".join([FIELD_LABELS.get(f, f).split(" (")[0] for f in pollution_present])
        pollution_text = f" | 污染物: {pollution_text}"

    # 日期范围筛选器（始终渲染，避免 widget 消失触发 DOM 不一致）
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
        else:
            # 单条记录：渲染禁用的空白 date_input 保持 key 稳定
            st.date_input(
                "📅 数据时间范围筛选（单条记录，不可用）",
                value=(),
                key="_filter_date_range_input",
                disabled=True,
            )
            st.session_state.pop("_filter_date_range", None)

    # 使用原生 Streamlit 组件确保刷新正确
    with st.container(border=False, key="summary_card"):
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
                # 图表 Tab 已互换至 index 1（数值预报之后是 index 2）
                if cur_tab != 1 and st.button("📊 图表", use_container_width=True, key="jump_viz"):
                    _navigate_to(1)
            with b_col2:
                if cur_tab != 3 and st.button("🔔 检测", use_container_width=True, key="jump_alert"):
                    _navigate_to(3)
            with b_col3:
                if cur_tab != 4 and st.button("📤 导出", use_container_width=True, key="jump_export"):
                    _navigate_to(4)

    # 保存当前数据集到用户私有云端（按 user_id 隔离）
    sc1, sc2 = st.columns([3, 1])
    with sc1:
        st.caption("数据仅保存在你自己的账号下，他人不可见。")
    with sc2:
        if st.button("💾 保存到云端", use_container_width=True, key="save_cloud"):
            from db import save_dataset
            _save_name = f"{src} @ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            if save_dataset(df, _save_name):
                st.success("已保存到云端 ✓")
                st.rerun()

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
            background: var(--warning-bg);
            border-left: 3px solid #e8943a;
            padding: 8px 14px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 6px;
            font-size: 0.85rem;
            color: var(--text-secondary);
        ">
            <span style="margin-right: 6px;">{icon}</span> {text}
        </div>
        """, unsafe_allow_html=True)


def _render_onboarding_page():
    """封面页：Aether 天气墙（未导入数据时展示，替换原三步引导页）。

    需求要点：默认预置 34 个省会级城市实时天气；导入数据后本封面随
    df is None 判定自动切换回数据摘要卡（见主渲染区分支）。
    """
    # ---- 老用户回封面后的返回入口：数据未丢，随时切回摘要卡视图 ----
    if st.session_state.get("df") is not None:
        _rc1, _rc2, _rc3 = st.columns([1, 2, 1])
        with _rc2:
            if st.button("📊 返回数据视图", key="wall_back_to_data",
                         use_container_width=True):
                st.session_state["_wall_cover"] = False
                st.rerun()

    # ---- 天气墙主体（搜索 / 分组卡片 / 增删 / toast） ----
    # 错误边界：天气服务或渲染异常时降级为文字提示，不影响下方快速开始入口
    try:
        if st.session_state.get("_wall_show", True):
            render_wall()
        else:
            # 用户通过侧边栏开关隐藏了天气墙：显示占位说明避免空白
            st.info("☁️ 天气墙已隐藏。可在侧边栏勾选「[显示] 天气墙」重新开启。")
    except Exception as _wall_exc:
        st.warning("⚠️ 天气墙加载异常，已降级显示。点击下方按钮可正常使用平台功能。")
        with st.expander("查看错误详情"):
            st.exception(_wall_exc)

    # ---- 快速开始入口（保留原跳转逻辑） ----
    st.write("")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("⚡ 快速开始 — 导入数据", use_container_width=True, type="primary",
                     key="onboard_quick"):
            # 进入导入流程后关闭封面标志：导入完成即回到数据摘要卡视图
            st.session_state["_wall_cover"] = False
            _navigate_to(0)
    st.caption("天气数据来自 Open-Meteo · 每 10 分钟自动更新 · 仅供学习参考")
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

# ============================================================
# 登录门禁：未登录只渲染登录页，已登录才进入主程序
# ============================================================
if not is_authenticated():
    render_auth_page()
    st.stop()

# ============================================================
# 视觉系统 — CSS 变量统一亮/暗模式
# ============================================================
st.markdown("""
<style>
/* ===== 变量: 亮色模式 ===== */
:root {
    --bg-primary: #ffffff;
    --bg-secondary: #f8fafc;
    --bg-tertiary: #f1f5f9;
    --bg-hover: #e2e8f0;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --border-color: #e2e8f0;
    --border-hover: #3b82f6;
    --accent: #1d4ed8;
    --accent-hover: #1e3a8a;
    --accent-soft: #eff6ff;
    --success-bg: #f0fdf4;
    --warning-bg: #fffbeb;
    --error-bg: #fef2f2;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 12px -2px rgba(0,0,0,0.06);
    --shadow-lg: 0 12px 24px -4px rgba(0,0,0,0.08);
    --transition: 150ms cubic-bezier(0.4, 0, 0.2, 1);
    --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
    --font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

/* ===== 布局基础 ===== */
.stApp {
    background: var(--bg-primary);
    font-family: var(--font-ui);
}
.block-container {
    padding: 3.5rem 2rem 1.5rem !important;
    max-width: 1200px !important;
}

/* ===== 标题层级 ===== */
.main-header {
    font-size: 1.6rem;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.02em;
    margin-top: 0;
    margin-bottom: 4px;
    padding-top: 0.5rem;
}
.sub-header {
    font-size: 0.85rem;
    color: var(--text-muted);
    letter-spacing: 0.01em;
    margin-bottom: 1.2rem;
}
h1, h2, h3 {
    color: var(--text-primary) !important;
    letter-spacing: -0.01em;
}
h1 { font-size: 1.5rem !important; font-weight: 700 !important; }
h2 { font-size: 1.2rem !important; font-weight: 600 !important; }
h3 { font-size: 1.05rem !important; font-weight: 600 !important; }

/* ===== 文本 ===== */
p, span, label, .stMarkdown {
    color: var(--text-secondary) !important;
    line-height: 1.6;
}
.stCaption {
    color: var(--text-muted) !important;
    font-size: 0.8rem;
}

/* ===== 卡片 (st.container border / stMetric / stAlert / stExpander) ===== */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
    transition: border-color var(--transition);
}
[data-testid="stMetric"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
    padding: 14px !important;
    transition: border-color var(--transition), box-shadow var(--transition);
}
[data-testid="stMetric"]:hover {
    border-color: var(--border-hover) !important;
    box-shadow: var(--shadow-md) !important;
}
[data-testid="stMetric"] label {
    color: var(--text-muted) !important;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-family: var(--font-mono);
    font-size: 1.5rem !important;
    font-weight: 700;
}

/* ===== 按钮 ===== */
.stButton > button {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-sm) !important;
    font-family: var(--font-ui);
    font-size: 0.875rem;
    font-weight: 500;
    padding: 6px 16px !important;
    transition: all var(--transition);
    box-shadow: var(--shadow-sm);
}
.stButton > button:hover {
    background: var(--bg-hover) !important;
    border-color: var(--accent) !important;
    box-shadow: var(--shadow-md);
    transform: translateY(-1px);
}
.stButton > button:active {
    transform: translateY(0);
    box-shadow: var(--shadow-sm);
}
button[kind="primary"] {
    background: #faf6ef !important;
    color: #1e293b !important;
    border-color: #e8e0d0 !important;
    box-shadow: 0 1px 2px rgba(120, 90, 40, 0.08), var(--shadow-sm) !important;
    font-weight: 600 !important;
}
button[kind="primary"]:hover {
    background: #f3eddf !important;
    border-color: #d4c8a8 !important;
    box-shadow: 0 2px 4px rgba(120, 90, 40, 0.12), var(--shadow-md) !important;
}

/* ===== 输入框 ===== */
.stTextInput input, .stNumberInput input, .stSelectbox [data-baseweb="select"] {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-sm) !important;
    font-family: var(--font-ui);
    transition: border-color var(--transition), box-shadow var(--transition);
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1) !important;
}
.stNumberInput button {
    background: var(--bg-tertiary) !important;
    color: var(--text-secondary) !important;
    border-color: var(--border-color) !important;
}

/* ===== 展开器 ===== */
[data-testid="stExpander"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm);
}
[data-testid="stExpander"] summary {
    color: var(--text-primary) !important;
    font-weight: 500;
    transition: color var(--transition);
}
[data-testid="stExpander"] summary:hover {
    color: var(--accent) !important;
}

/* ===== 提示框 ===== */
div[data-testid="stAlert"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm);
}
.stSuccess { background: var(--success-bg) !important; border-left: 3px solid #22c55e !important; }
.stWarning { background: var(--warning-bg) !important; border-left: 3px solid #f59e0b !important; }
.stError   { background: var(--error-bg) !important;   border-left: 3px solid #ef4444 !important; }

/* ===== 数据表格 ===== */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden;
}
[data-testid="stDataFrame"] thead th {
    background: var(--bg-tertiary) !important;
    color: var(--text-secondary) !important;
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    border-bottom: 2px solid var(--border-color) !important;
}
[data-testid="stDataFrame"] tbody tr:nth-child(even) {
    background: var(--bg-secondary);
}
[data-testid="stDataFrame"] tbody td {
    color: var(--text-secondary) !important;
    font-family: var(--font-mono);
    font-size: 0.85rem;
}

/* ===== Tab ===== */
.stTabs [data-baseweb="tab"] {
    color: var(--text-muted) !important;
    font-weight: 500;
    transition: color var(--transition);
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: var(--accent) !important;
    font-weight: 600;
}
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 2px solid var(--border-color) !important;
    gap: 0;
}

/* ===== Radio (主 Tab 导航) ===== */
[data-testid="stRadio"] [role="radiogroup"] {
    gap: 4px;
}
[data-testid="stRadio"] [role="radiogroup"] label {
    color: var(--text-secondary) !important;
    font-weight: 500;
    font-size: 0.875rem;
    padding: 8px 18px;
    border-radius: var(--radius-sm);
    transition: all var(--transition);
}
[data-testid="stRadio"] [role="radiogroup"] label:hover {
    background: var(--bg-hover);
    color: var(--text-primary) !important;
}
[data-testid="stRadio"] [data-baseweb="radio"]:has(input:checked) + div label {
    background: var(--accent-soft);
    color: var(--accent) !important;
    font-weight: 600;
}

/* ===== 侧边栏 ===== */
[data-testid="stSidebar"] {
    background: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p {
    color: var(--text-secondary) !important;
}

/* ===== 分割线 ===== */
hr {
    border: none;
    border-top: 1px solid var(--border-color) !important;
    margin: 1rem 0;
}

/* ===== 文件上传 ===== */
[data-testid="stFileUploader"] section {
    background: var(--bg-secondary) !important;
    border: 1px dashed var(--border-color) !important;
    border-radius: var(--radius-md) !important;
    transition: border-color var(--transition);
}
[data-testid="stFileUploader"] section:hover {
    border-color: var(--accent) !important;
}
[data-testid="stFileUploader"] section p {
    color: var(--text-muted) !important;
}

/* ===== 滚动条 ===== */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb {
    background: var(--border-color);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ===== Plotly 图表容器 ===== */
.js-plotly-plot, .plot-container {
    border-radius: var(--radius-md) !important;
}
.js-plotly-plot .plotly .main-svg {
    border-radius: var(--radius-md);
}

/* ===== 移动端 ===== */
@media screen and (max-width: 768px) {
    .block-container { padding: 1rem 0.5rem !important; }
    .main-header { font-size: 1.3rem !important; }
    .sub-header { font-size: 0.75rem !important; }
    [data-testid="column"] { flex: 1 1 100% !important; min-width: 100% !important; }
    .stTabs [data-baseweb="tab"] { padding: 6px 10px !important; font-size: 0.75rem !important; }
    .stButton > button { width: 100% !important; }
    [data-testid="stRadio"] [role="radiogroup"] { flex-direction: column !important; gap: 2px; }
    [data-testid="stRadio"] [role="radiogroup"] label { padding: 6px 12px !important; font-size: 0.8rem !important; }
    [data-testid="stMetric"] { padding: 10px !important; }
    .js-plotly-plot, .plot-container { max-height: 280px !important; }
    [data-testid="stDataFrame"] { overflow-x: auto !important; font-size: 0.75rem !important; }
}
@media screen and (min-width: 769px) and (max-width: 1024px) {
    .block-container { padding: 1.2rem 1rem !important; }
    .main-header { font-size: 1.5rem !important; }
}

/* ===== MultiSelect 标签: 淡蓝色（亮暗模式自动适配变量） ===== */
[data-testid="stMultiSelect"] [data-baseweb="tag"] {
    background-color: var(--accent-soft) !important;
}
[data-testid="stMultiSelect"] [data-baseweb="tag"] span {
    color: var(--accent) !important;
}
</style>
""", unsafe_allow_html=True)

# ---- Aether 主题覆盖层（亮/暗统一由 theme_aether 按当前主题输出一套变量，
#      旧版亮/暗变量块由此接管，避免两套皮肤并存） ----
theme_aether.inject_theme()

# 头部
st.markdown('<div class="main-header">[天气] 气象数据交互分析平台</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">数据导入 · 可视化分析 · 数值预报 · 事件检测 · 智能建议 · 报告导出</div>',
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

# 登录后自动载入当前用户最近一次保存的数据集（仅当本次会话尚无数据，且每会话只尝试一次）
if st.session_state.get("df") is None and not st.session_state.get("_auto_load_done"):
    st.session_state["_auto_load_done"] = True
    from db import load_latest_dataset
    _auto_df, _auto_name = load_latest_dataset()
    if _auto_df is not None:
        st.session_state["df"] = _auto_df
        st.session_state["source"] = _auto_name or "云端数据"

# ============================================================
# 侧边栏：自定义检测阈值
# ============================================================
with st.sidebar:
    # ---- 用户面板（登录态） ----
    _auth_user = st.session_state.get("auth_user")
    if _auth_user:
        st.caption(f"👤 已登录：{_auth_user.get('email', '')}")
        if st.button("退出登录", key="logout_btn", use_container_width=True):
            sign_out_user()
            st.rerun()

        # 云存储用量
        from db import get_storage_usage_bytes, get_storage_quota_bytes
        _used = get_storage_usage_bytes()
        _quota = get_storage_quota_bytes()
        _ratio = (_used / _quota) if _quota else 0.0
        st.progress(min(1.0, _ratio),
                    text=f"☁️ 云存储 {_used / 1048576:.1f} / {_quota / 1048576:.0f} MB")

        with st.expander("📂 我的数据集", expanded=False):
            from db import list_datasets, load_dataset, delete_dataset
            _my_ds = list_datasets()
            if not _my_ds:
                st.caption("暂无保存的数据，导入后可点「保存到云端」。")
            for _d in _my_ds:
                _dc1, _dc2 = st.columns([4, 1])
                with _dc1:
                    if st.button(_d["name"], key=f"load_{_d['id']}",
                                 use_container_width=True):
                        _ldf, _lname = load_dataset(_d["id"])
                        if _ldf is not None:
                            st.session_state["df"] = _ldf
                            st.session_state["source"] = _lname
                            st.rerun()
                with _dc2:
                    if st.button("🗑", key=f"del_{_d['id']}"):
                        delete_dataset(_d["id"])
                        st.rerun()
        st.divider()

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
    # 老用户回封面入口：有数据时仍可随时回到天气墙封面（_wall_cover 控制主区分支）
    if st.session_state.get("df") is not None:
        if st.button("☁️ 天气墙封面", key="sb_wall_cover",
                     use_container_width=True,
                     help="回到首页天气墙（数据保留，返回后自动恢复摘要卡）"):
            st.session_state["_wall_cover"] = True
            st.rerun()
    dark = st.checkbox("[显示] 暗色模式", value=st.session_state.get("dark_mode", False), key="dark_toggle",
                       help="切换「梦幻夜空 / 清透天空」主题，选择自动保存，重启后保持")
    if dark != st.session_state.get("dark_mode", False):
        # 需求 3：切换写入持久化（本地文件 + 登录时 Supabase user_metadata）
        theme_aether.set_theme(dark)
        st.rerun()
    # 天气墙显示开关：用户可自主显示/隐藏首页天气墙，选择持久化（刷新保持）
    wall_show = st.checkbox("[显示] 天气墙", value=st.session_state.get("_wall_show", True),
                            key="wall_show_toggle",
                            help="显示/隐藏首页天气墙，选择自动保存")
    if wall_show != st.session_state.get("_wall_show", True):
        st.session_state["_wall_show"] = wall_show
        from modules.city_prefs import save_show_wall
        save_show_wall(wall_show)  # 持久化：本地文件 + 登录时 Supabase
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
    st.divider()
    if is_authenticated():
        if st.button("[刷新] 重置当前模块数据", use_container_width=True,
                     key="sidebar_reset_current_tab",
                     help="清空当前 Tab 的业务数据（导入数据/预报/分析结果等），保留登录态和阈值设置"):
            _reset_current_tab()
    st.caption("※ 本平台分析结果仅供学习参考，不替代国家气象部门权威预报。")
    # 版本号展示：线上版本肉眼可辨（排查部署问题的重要依据）
    st.caption(f"© 气象数据交互分析平台 {APP_VERSION}")

# ============================================================
# 主内容区：无数据时显示引导页，有数据时显示提示+摘要
# ============================================================
has_any_data = st.session_state.get("df") is not None
if not has_any_data or st.session_state.get("_wall_cover", False):
    _render_onboarding_page()
else:
    _render_next_step_hint()
    _render_data_summary_card()

# ---- 标签页导航（支持编程跳转） ----
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = 0

tab_labels = [
    "[导入] 数据导入",
    "[图表] 可视化分析",
    "[预报] 数值预报",
    "[检测] 智能分析与建议",
    "[导出] 报告导出",
    "[雷达] 报文解码",
]


# 使用 radio 替代 tabs，支持 index 参数实现编程跳转
# 注意：不使用 key 参数！否则 session_state 旧值会覆盖 index，
# 导致 active_tab 被反向重置，跳转失效
selected = st.radio(
    "导航",
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

        # 返回按钮
        if st.button("← 返回选择方式", key="wiz_back_step0"):
            st.session_state["import_step"] = 0
            st.session_state["import_method"] = None
            st.rerun()

        if method == "file":
            df_file, source_file = _safe_render("导入-文件", render_file_upload_section) or (None, None)
            _safe_render("导入-模板", render_template_download)
            if df_file is not None:
                st.session_state["df"] = df_file
                st.session_state["source"] = source_file
                st.session_state["import_step"] = 2
                st.rerun()
        elif method == "manual":
            df_manual = _safe_render("导入-手动", render_manual_input_section)
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
            df_api, source_api = _safe_render("导入-API", render_api_section) or (None, None)
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

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ 确认数据，前往可视化分析", use_container_width=True, key="wiz_confirm"):
                    st.session_state["import_step"] = 0
                    _navigate_to(1)  # 可视化 Tab 已互换至 index 1
            with c2:
                if st.button("← 返回上一步", use_container_width=True, key="wiz_back_step1"):
                    st.session_state["import_step"] = 1
                    st.rerun()
            with c3:
                if st.button("🔄 重新导入", use_container_width=True, key="wiz_retry"):
                    st.session_state["import_step"] = 0
                    st.session_state["import_method"] = None
                    st.session_state["df"] = None
                    st.session_state["source"] = ""
                    st.session_state["warnings_list"] = []
                    st.session_state["quality_score"] = 0.0
                    st.session_state["climate_data"] = None
                    st.session_state["climate_extreme"] = None
                    st.session_state["fc_df"] = None
                    st.session_state["fc_analysis"] = None
                    st.session_state["_import_history"] = []
                    st.session_state["_filter_date_range"] = None
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
            df_file, source_file = _safe_render("导入-文件", render_file_upload_section) or (None, None)
            if df_file is not None:
                st.session_state["df"] = df_file
                st.session_state["source"] = source_file
            _safe_render("导入-模板", render_template_download)
        with sub_tab2:
            df_manual = _safe_render("导入-手动", render_manual_input_section)
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
            df_api, source_api = _safe_render("导入-API", render_api_section) or (None, None)
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

# ---- Tab 1: 可视化分析 ----
if st.session_state["active_tab"] == 1:
    _viz_df = _safe_render("可视化-数据", _get_filtered_df)
    _safe_render("可视化", render_visualization_tab, _viz_df)

# ---- Tab 3: 智能分析与建议 ----
if st.session_state["active_tab"] == 3:
    # 数据指纹缓存：数据未变化时跳过重复检测
    if st.session_state["df"] is not None:
        fp = _df_fingerprint(st.session_state["df"])
        if st.session_state.get("_warn_fp") != fp:
            all_w = []
            checks = [
                ("高温", check_high_temperature), ("寒潮", check_cold_wave),
                ("大风", check_gale), ("大雾", check_fog),
                ("暴雨", check_rainstorm), ("霜冻", check_frost),
                ("雷电", check_thunderstorm), ("霾", check_haze),
                ("极值", check_against_extremes),
            ]
            for name, fn in checks:
                try:
                    all_w += fn(st.session_state["df"])
                except Exception as e:
                    st.warning(f"{name}检测因数据问题跳过: {e}")
            st.session_state["warnings_list"] = all_w
            st.session_state["_warn_fp"] = fp
    warnings_result = _safe_render("智能分析", render_analysis_tab, st.session_state["df"])

# ---- Tab 4: 报告导出 ----
if st.session_state["active_tab"] == 4:
    _safe_render(
        "报告导出",
        render_export_tab,
        st.session_state["df"],
        st.session_state.get("warnings_list", []),
        st.session_state.get("quality_score", 0.0),
        st.session_state.get("source", ""),
    )

# ---- Tab 5: 报文解码 ----
if st.session_state["active_tab"] == 5:
    _safe_render("报文解码", render_codec_tab)

# ---- Tab 2: 数值预报 ----
if st.session_state["active_tab"] == 2:
    _safe_render("数值预报", render_forecast_tab)
