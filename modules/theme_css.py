"""主题样式生成：把 token 表渲染成 CSS，并提供 Streamlit 原生组件的覆盖层。

为什么需要这个模块
------------------
Streamlit 的默认主题由 ``.streamlit/config.toml`` 的 ``[theme]`` 决定，而该配置
**是进程级、不可按会话切换的**。项目需要「侧边栏勾选即换肤」，因此采用
「config.toml 固定亮色基线 + 会话级 CSS 注入覆盖」的组合：

- 亮色：直接使用 config.toml 的原生亮色主题，样式层只做形状/圆角修正；
- 暗色：在 ``html[data-dsh-theme="dark"]`` 作用域下重写全部表面、文字、描边，
  并对 Streamlit 原生前端组件（弹层、日历、表格、toast、dialog、tooltip 等）
  逐一给出覆盖规则——这些组件的配色来自前端主题对象而非 CSS 变量，
  不覆盖就会在暗色下露白。

改造前的两个致命缺陷
--------------------
1. 暗色覆盖清单只覆盖了 15 个选择器，且全部写在 ``:root`` 作用域，**
   与另一套同样写在 ``:root`` 的亮色变量同权重**，靠「后定义者胜出」维持，
   任何一次注入顺序变动都会导致亮暗混排（页面上出现「深色侧边栏 + 浅灰主区」）。
   本版把暗色统一收进 ``html[data-dsh-theme="dark"]``，权重高于 ``:root``，
   注入顺序不再影响结果。
2. 覆盖清单是**静态字符串**，token 改动后不会同步。本版用 f-string 从 token
   表生成，改一处 token 全局生效。
"""

from __future__ import annotations

from modules.design_tokens import (
    STATIC_TOKENS,
    css_var_name,
    tokens_for,
)

# ============================================================
# 一、变量块
# ============================================================
def _var_lines(tokens: dict, indent: str = "    ") -> str:
    """把 token 表渲染成 CSS 变量声明行。"""
    lines = []
    for key, value in tokens.items():
        lines.append(f"{indent}--{css_var_name(key)}: {value};")
    for key, value in STATIC_TOKENS.items():
        lines.append(f"{indent}--{css_var_name(key)}: {value};")
    return "\n".join(lines)


def root_vars_css(dark: bool) -> str:
    """主题变量块。

    暗色走 ``html[data-dsh-theme="dark"]``（权重 0,1,1），亮色走
    ``html[data-dsh-theme="light"]`` 并附 ``:root`` 兜底（JS 未就绪时生效）。
    """
    tokens = tokens_for(dark)
    body = _var_lines(tokens)
    if dark:
        return f'html[data-dsh-theme="dark"] {{\n{body}\n}}'
    root_body = _var_lines(tokens)
    return (
        f":root {{\n{root_body}\n}}\n"
        f'html[data-dsh-theme="light"] {{\n{body}\n}}'
    )


# ============================================================
# 二、形状 / 排版基线（与配色无关，亮暗共用）
# ============================================================
from pathlib import Path

_THEME_ASSETS = Path(__file__).resolve().parent / "theme_assets"


def _read_asset(name: str) -> str:
    """从 theme_assets 读取静态样式文件，避免 Python 源文件里塞 500 行 CSS。"""
    return (_THEME_ASSETS / name).read_text(encoding="utf-8")


BASE_CSS = _read_asset("base.css")


# ============================================================
# 三、暗色专属覆盖：Streamlit 原生前端组件
# ============================================================
def dark_extra_css() -> str:
    """暗色下必须覆盖的 Streamlit 原生组件。

    这些组件的底色来自前端主题对象（``.streamlit/config.toml`` 的 ``[theme]``），
    该配置是进程级、无法按会话切换，因此只能逐组件覆盖。
    全部规则挂在 ``html[data-dsh-theme="dark"]`` 下，权重高于亮色变量块。
    """
    return """
/* ===== 基础色方案：让原生控件（滚动条、表单、系统 UI）跟随暗色 ===== */
html[data-dsh-theme="dark"] { color-scheme: dark; }
html[data-dsh-theme="dark"] .stApp { color: var(--text-primary); }

/* ===== 侧边栏折叠按钮 / 顶栏 ===== */
html[data-dsh-theme="dark"] [data-testid="stSidebarCollapsedControl"],
html[data-dsh-theme="dark"] [data-testid="stSidebarCollapseButton"] button,
html[data-dsh-theme="dark"] [data-testid="stHeader"] { background: transparent !important; }
html[data-dsh-theme="dark"] [data-testid="stHeaderActionElements"] svg,
html[data-dsh-theme="dark"] [data-testid="stToolbar"] svg { fill: var(--text-secondary) !important; color: var(--text-secondary) !important; }

/* ===== 链接：Streamlit 默认主题蓝在深底上过暗 ===== */
html[data-dsh-theme="dark"] a,
html[data-dsh-theme="dark"] a:visited { color: var(--accent) !important; }
html[data-dsh-theme="dark"] [data-testid="stSidebar"] a,
html[data-dsh-theme="dark"] .stMarkdown a { color: var(--accent) !important; }

/* ===== 提示框底色 ===== */
/* stAlertContainer 由 Streamlit 用主题 primaryColor 调出的 rgba(28,131,255,.1)
   渲染；暗色下偏亮偏艳，这里改用本项目的 info-bg。 */
html[data-dsh-theme="dark"] div[data-testid="stAlert"][data-baseweb="notification"] { background: var(--bg-secondary) !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContainer"] { background: var(--info-bg) !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContentInfo"] { background: transparent !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContentSuccess"] { background: transparent !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContentWarning"] { background: transparent !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContentError"] { background: transparent !important; }
/* 语义色的左边框由 stAlert 的 icon 决定，这里统一按语义补一条左侧强调线 */
html[data-dsh-theme="dark"] [data-testid="stAlertContainer"] { border-left: 3px solid var(--info-ink) !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { border-left-color: var(--success-ink) !important; background: var(--success-bg) !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { border-left-color: var(--warning-ink) !important; background: var(--warning-bg) !important; }
html[data-dsh-theme="dark"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { border-left-color: var(--error-ink) !important; background: var(--error-bg) !important; }

/* ===== toast 通知 ===== */
html[data-dsh-theme="dark"] [data-testid="stToast"],
html[data-dsh-theme="dark"] [data-testid="stToastContainer"] > div {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    color: var(--text-primary) !important;
    box-shadow: var(--shadow-lg) !important;
}
html[data-dsh-theme="dark"] [data-testid="stToast"] *,
html[data-dsh-theme="dark"] [data-testid="stToastContainer"] * { color: var(--text-primary) !important; }

/* ===== selectbox / multiselect 下拉面板 ===== */
html[data-dsh-theme="dark"] [data-baseweb="popover"],
html[data-dsh-theme="dark"] [data-baseweb="popover"] > div,
html[data-dsh-theme="dark"] [data-baseweb="menu"],
html[data-dsh-theme="dark"] [data-baseweb="listbox"],
html[data-dsh-theme="dark"] ul[role="listbox"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    box-shadow: var(--shadow-lg) !important;
}
html[data-dsh-theme="dark"] [data-baseweb="popover"] li,
html[data-dsh-theme="dark"] [data-baseweb="menu"] li,
html[data-dsh-theme="dark"] [data-baseweb="listbox"] li,
html[data-dsh-theme="dark"] ul[role="listbox"] li,
html[data-dsh-theme="dark"] li[role="option"] {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
}
html[data-dsh-theme="dark"] li[role="option"]:hover,
html[data-dsh-theme="dark"] li[aria-selected="true"] {
    background: var(--bg-hover) !important;
    color: var(--text-primary) !important;
}
html[data-dsh-theme="dark"] [data-baseweb="popover"] input { background: var(--bg-tertiary) !important; color: var(--text-primary) !important; }

/* ===== 日期选择器日历 ===== */
html[data-dsh-theme="dark"] [data-baseweb="calendar"],
html[data-dsh-theme="dark"] [data-baseweb="calendar"] > div,
html[data-dsh-theme="dark"] [data-baseweb="datepicker"] { background: var(--bg-secondary) !important; }
html[data-dsh-theme="dark"] [data-baseweb="calendar"] * { color: var(--text-primary) !important; }
html[data-dsh-theme="dark"] [data-baseweb="calendar"] button {
    background: transparent !important;
    color: var(--text-primary) !important;
    border: none !important;
}
html[data-dsh-theme="dark"] [data-baseweb="calendar"] button:hover { background: var(--bg-hover) !important; }
html[data-dsh-theme="dark"] [data-baseweb="calendar"] [aria-selected="true"],
html[data-dsh-theme="dark"] [data-baseweb="calendar"] [aria-current="date"] {
    background: var(--accent) !important;
    color: var(--accent-contrast) !important;
}
html[data-dsh-theme="dark"] [data-baseweb="calendar"] [aria-disabled="true"] { color: var(--text-muted) !important; opacity: .5; }

/* ===== 弹窗 dialog / modal ===== */
html[data-dsh-theme="dark"] [data-testid="stDialog"] > div,
html[data-dsh-theme="dark"] [data-testid="stDialog"] [role="dialog"],
html[data-dsh-theme="dark"] [data-baseweb="modal"],
html[data-dsh-theme="dark"] [data-baseweb="modal"] > div {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    color: var(--text-primary) !important;
    box-shadow: var(--shadow-lg) !important;
}
html[data-dsh-theme="dark"] [data-testid="stDialog"] [role="dialog"] * { color: var(--text-primary) !important; }
html[data-dsh-theme="dark"] [data-baseweb="modal"] [aria-label="Close"] svg,
html[data-dsh-theme="dark"] [data-testid="stDialog"] button svg { fill: var(--text-secondary) !important; }

/* ===== popover（st.popover） ===== */
html[data-dsh-theme="dark"] [data-testid="stPopoverBody"],
html[data-dsh-theme="dark"] [data-testid="stPopover"] [data-baseweb="popover"] > div {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    box-shadow: var(--shadow-lg) !important;
}

/* ===== tooltip 与帮助气泡 ===== */
html[data-dsh-theme="dark"] [data-testid="stTooltipContent"],
html[data-dsh-theme="dark"] [data-testid="stTooltipHoverTarget"] + div,
html[data-dsh-theme="dark"] [role="tooltip"] {
    background: var(--bg-tertiary) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border-color) !important;
    box-shadow: var(--shadow-md) !important;
}
html[data-dsh-theme="dark"] [role="tooltip"] * { color: var(--text-primary) !important; }

/* ===== 数据表格：前端主题写死白底，必须连内部画布一起覆盖 ===== */
html[data-dsh-theme="dark"] [data-testid="stDataFrame"],
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] > div,
html[data-dsh-theme="dark"] [data-testid="stDataFrameResizable"],
html[data-dsh-theme="dark"] [data-testid="stDataEditor"] { background: var(--bg-primary) !important; }
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] thead th {
    background: var(--bg-secondary) !important;
    color: var(--text-secondary) !important;
    border-bottom: 1px solid var(--border-color) !important;
}
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] tbody tr,
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] tbody td {
    background: var(--bg-primary) !important;
    color: var(--text-secondary) !important;
    border-top: 1px solid var(--border-color) !important;
}
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] tbody tr:nth-child(even),
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] tbody tr:nth-child(even) td { background: var(--bg-secondary) !important; }
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] tbody tr:hover,
html[data-dsh-theme="dark"] [data-testid="stDataFrame"] tbody tr:hover td { background: var(--bg-hover) !important; }

/* ===== spinner ===== */
html[data-dsh-theme="dark"] [data-testid="stSpinner"] { background: transparent !important; }
html[data-dsh-theme="dark"] [data-testid="stSpinner"] div,
html[data-dsh-theme="dark"] [data-testid="stSpinner"] p { color: var(--text-primary) !important; }
html[data-dsh-theme="dark"] [data-testid="stSpinner"] svg { color: var(--accent) !important; }

/* ===== 状态组件（st.status） ===== */
html[data-dsh-theme="dark"] [data-testid="stStatusWidget"],
html[data-dsh-theme="dark"] [data-testid="stExpander"] [data-testid="stStatusWidget"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    color: var(--text-primary) !important;
}

/* ===== Plotly 悬停提示：图表内的 hoverlabel 由 Plotly 自己绘 canvas 背景，
       CSS 只能兜住 HTML 层；真正的暗色化在 chart_theme 的 layout 里完成 ===== */
html[data-dsh-theme="dark"] [data-testid="stPlotlyChart"] .hoverlayer .hovertext rect { fill: #232b45 !important; }
html[data-dsh-theme="dark"] [data-testid="stPlotlyChart"] .hoverlayer .hovertext text { fill: #e8ebf5 !important; }

/* ===== 上传文件列表 / 下载按钮细节 ===== */
html[data-dsh-theme="dark"] [data-testid="stFileUploaderFile"] { border-top: 1px solid var(--border-color) !important; }
html[data-dsh-theme="dark"] [data-testid="stFileUploaderFile"] svg { fill: var(--text-secondary) !important; }
html[data-dsh-theme="dark"] [data-testid="stFileUploaderDropzoneInstructions"] svg { fill: var(--text-muted) !important; }

/* ===== iframe（定位组件）容器 ===== */
html[data-dsh-theme="dark"] [data-testid="stCustomComponentV1"] { background: transparent !important; }

/* ===== 分段控件（st.segmented_control / st.pills） ===== */
html[data-dsh-theme="dark"] [data-testid="stSegmentedControl"] button,
html[data-dsh-theme="dark"] [data-testid="stPills"] button {
    background: var(--bg-secondary) !important;
    color: var(--text-secondary) !important;
    border: none !important;
}
html[data-dsh-theme="dark"] [data-testid="stSegmentedControl"] button[aria-checked="true"],
html[data-dsh-theme="dark"] [data-testid="stPills"] button[aria-checked="true"] {
    background: var(--accent-soft) !important;
    color: var(--accent) !important;
}

/* ===== 表单容器 ===== */
html[data-dsh-theme="dark"] [data-testid="stForm"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-md) !important;
}

/* ===== 元素悬浮工具条（图表/表格右上角的下载、全屏按钮）===== */
/* Streamlit 给每个元素挂了一个 stElementToolbarButtonContainer，
   底色来自前端主题，暗色下是一块白底药丸，悬停图表时非常突兀。 */
html[data-dsh-theme="dark"] [data-testid="stElementToolbar"],
html[data-dsh-theme="dark"] [data-testid="stElementToolbarButtonContainer"] {
    background: var(--bg-tertiary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 8px !important;
    box-shadow: var(--shadow-md) !important;
}
html[data-dsh-theme="dark"] [data-testid="stElementToolbar"] button,
html[data-dsh-theme="dark"] [data-testid="stElementToolbarButtonContainer"] button {
    background: transparent !important;
    color: var(--text-secondary) !important;
    box-shadow: none !important;
    border: none !important;
    padding: 2px !important;
}
html[data-dsh-theme="dark"] [data-testid="stElementToolbar"] button:hover,
html[data-dsh-theme="dark"] [data-testid="stElementToolbarButtonContainer"] button:hover {
    background: var(--bg-hover) !important;
    color: var(--text-primary) !important;
    transform: none !important;
}
html[data-dsh-theme="dark"] [data-testid="stElementToolbar"] svg,
html[data-dsh-theme="dark"] [data-testid="stElementToolbarButtonContainer"] svg {
    fill: currentColor !important;
}

/* ===== 下拉/选择控件的 BaseWeb 外壳 ===== */
html[data-dsh-theme="dark"] [data-baseweb="select"] > div,
html[data-dsh-theme="dark"] [data-baseweb="input"],
html[data-dsh-theme="dark"] [data-baseweb="base-input"] {
    background: var(--bg-secondary) !important;
    border-color: var(--border-color) !important;
    color: var(--text-primary) !important;
}
"""
