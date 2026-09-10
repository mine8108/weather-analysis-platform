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
BASE_CSS = """
/* ===== 页面底色：天空渐变 + 光晕 ===== */
/* body 也必须一起上色：Streamlit 的根节点是白底，暗色下在滚动到底、
   iframe 区域或 overscroll 时会从 .stApp 之外露出白边。 */
html, body { background: var(--app-base) !important; }
.stApp {
    background: var(--app-bg);
    background-attachment: fixed;
}

/* ===== 布局 ===== */
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
h1, h2, h3, h4, h5, h6 { color: var(--text-primary) !important; letter-spacing: -0.01em; }
h1 { font-size: 1.5rem !important; font-weight: 700 !important; }
h2 { font-size: 1.2rem !important; font-weight: 600 !important; }
h3 { font-size: 1.05rem !important; font-weight: 600 !important; }

/* ===== 文本 ===== */
p, span, label, .stMarkdown { color: var(--text-secondary); line-height: 1.6; }
.stCaption, [data-testid="stCaptionContainer"] { color: var(--text-muted) !important; font-size: 0.8rem; }

/* ===== 卡片 / 指标 ===== */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--bg-secondary) !important;
    border: none !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stMetric"] {
    background: var(--bg-secondary) !important;
    border: none !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
    padding: 14px !important;
}
[data-testid="stMetric"]:hover { box-shadow: var(--shadow-md) !important; }
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
[data-testid="stMetricDelta"] { font-size: 0.8rem; }

/* ===== 按钮 ===== */
/* 选择器用 [data-testid^="stBaseButton"] 而不是 .stButton > button：
   Streamlit 1.59 里带了 help= 的按钮会被 <div class="st-emotion-..."> 再包一层，
   按钮不再是 .stButton 的直接子级，于是 `>` 组合器失配——表现为
   「有帮助提示的按钮（📍定位 / 🔄刷新 / 🔍解析并添加）在暗色下仍是白底」。
   按 data-testid 匹配与层级无关，且覆盖 primary / secondary / 表单提交等全部变体。 */
[data-testid^="stBaseButton"] {
    background: var(--bg-secondary) !important;
    color: var(--text-primary) !important;
    border: none !important;
    border-radius: 12px !important;
    font-family: var(--font-ui);
    font-size: 0.875rem;
    font-weight: 500;
    padding: 6px 16px !important;
    transition: background var(--transition), box-shadow var(--transition), transform var(--transition);
    box-shadow: var(--shadow-sm) !important;
}
[data-testid^="stBaseButton"]:hover {
    background: var(--bg-hover) !important;
    box-shadow: var(--shadow-md) !important;
    transform: translateY(-2px);
}
[data-testid^="stBaseButton"]:active { transform: translateY(0); }
[data-testid^="stBaseButton"]:focus-visible {
    outline: 2px solid var(--accent) !important;
    outline-offset: 2px;
}
/* 按钮内部文本节点也要显式上色：部分变体的 <p>/<span> 继承了主题 textColor */
[data-testid^="stBaseButton"] p, [data-testid^="stBaseButton"] span,
[data-testid^="stBaseButton"] div { color: inherit; }
/* 纯图标按钮（如顶栏的菜单/折叠）保持透明，不套用卡片式外观 */
[data-testid="stBaseButton-header"],
[data-testid="stBaseButton-headerNoPadding"],
[data-testid="stMainMenuButton"] {
    background: transparent !important;
    box-shadow: none !important;
    padding: 4px !important;
}
[data-testid="stBaseButton-header"]:hover,
[data-testid="stBaseButton-headerNoPadding"]:hover,
[data-testid="stMainMenuButton"]:hover { background: var(--bg-hover) !important; transform: none; }

/* primary 按钮：不再硬编码米色，改用强调色 + accent-contrast 前景 */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"],
button[kind="primary"], button[kind="primaryFormSubmit"] {
    background: var(--accent) !important;
    color: var(--accent-contrast) !important;
    border: none !important;
    font-weight: 600 !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover,
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
    background: var(--accent-hover) !important;
    box-shadow: var(--shadow-md) !important;
}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primary"] span,
[data-testid="stBaseButton-primary"] div,
[data-testid="stBaseButton-primaryFormSubmit"] p, [data-testid="stBaseButton-primaryFormSubmit"] span,
button[kind="primary"] p, button[kind="primary"] span, button[kind="primary"] div,
button[kind="primaryFormSubmit"] p, button[kind="primaryFormSubmit"] span {
    color: var(--accent-contrast) !important;
}

/* ===== 输入控件 ===== */
/* Streamlit 1.59 的真实结构（已用 DOM 诊断确认）：
     [data-testid="stTextInput"] > .react-aria-TextField
       > [data-testid="stTextInputRootElement"]   ← 承载底色与描边的是这一层，
                                                    取值来自 config.toml 的
                                                    secondaryBackgroundColor
       > [data-baseweb="base-input"] > input      ← 真正可输入的元素
   改造前只给 <input> 设 box-shadow，外层 rootElement 仍是 #f8fafc，
   于是在深色页面上留下一圈刺眼浅色描边。这里按真实层级逐层收口。 */
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputRootElement"],
[data-testid="stTextAreaRootElement"],
[data-testid="stDateInputRootElement"],
[data-testid="stTimeInputRootElement"],
[data-testid="stNumberInputContainer"] {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-sm) !important;
    transition: border-color var(--transition), box-shadow var(--transition);
}
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stNumberInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stDateInputRootElement"]:focus-within,
[data-testid="stTimeInputRootElement"]:focus-within,
[data-testid="stNumberInputContainer"]:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent) !important;
}
/* 数字输入框的步进按钮 */
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
    background: transparent !important;
    color: var(--text-secondary) !important;
    box-shadow: none !important;
    padding: 0 !important;
}
[data-testid="stNumberInputStepUp"]:hover, [data-testid="stNumberInputStepDown"]:hover {
    background: var(--bg-hover) !important;
    color: var(--text-primary) !important;
    transform: none !important;
}
[data-testid="stNumberInputStepUp"] svg, [data-testid="stNumberInputStepDown"] svg {
    fill: currentColor !important;
}
.stTextInput input, .stNumberInput input, .stTextArea textarea,
.stDateInput input, .stTimeInput input,
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {
    background: transparent !important;
    color: var(--text-primary) !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: var(--radius-sm) !important;
    font-family: var(--font-ui);
}
/* 日期/时间输入的 BaseWeb 包裹层（本机实测为 <div class="st-af"><div class="st-ae">），
   自带 secondaryBackgroundColor(#f8fafc) 底色，在深色下是一条亮色长条。 */
[data-testid="stDateInput"] [data-baseweb="input"],
[data-testid="stDateInput"] [data-baseweb="base-input"],
[data-testid="stTimeInput"] [data-baseweb="input"],
[data-testid="stTimeInput"] [data-baseweb="base-input"],
[data-testid="stDateInput"] > div > div,
[data-testid="stTimeInput"] > div > div {
    background: var(--bg-secondary) !important;
    border-color: var(--border-color) !important;
    border-radius: var(--radius-sm) !important;
    color: var(--text-primary) !important;
}
[data-testid="stDateInput"] > div > div:focus-within,
[data-testid="stTimeInput"] > div > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent) !important;
}
[data-testid="stDateInput"] svg, [data-testid="stTimeInput"] svg { fill: var(--text-muted) !important; }
.stTextInput input::placeholder, .stNumberInput input::placeholder,
.stTextArea textarea::placeholder, .stDateInput input::placeholder,
.stTimeInput input::placeholder {
    color: var(--text-muted) !important;
    opacity: 1;
}
/* 密码框的「显示密码」按钮：默认是浅色胶囊，暗色下会糊成一块白 */
.stTextInput button[aria-label*="password" i],
.stTextInput button[title*="password" i] {
    background: transparent !important;
    color: var(--text-secondary) !important;
}
.stTextInput button[aria-label*="password" i]:hover,
.stTextInput button[title*="password" i]:hover {
    background: var(--bg-hover) !important;
    color: var(--text-primary) !important;
}
.stTextInput button[aria-label*="password" i] svg { fill: var(--text-secondary) !important; }

/* ===== 控件标签：Streamlit 用主题 textColor(#0f172a) 画标签，暗色下几乎不可见 ===== */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] label, [data-testid="stWidgetLabel"] span {
    color: var(--text-secondary) !important;
}
/* 复选框/单选标签 */
[data-testid="stRadioOption"] span, [data-testid="stRadioOption"] p,
[data-testid="stCheckbox"] span, [data-testid="stCheckbox"] p { color: var(--text-secondary) !important; }
.stNumberInput button { background: transparent !important; color: var(--text-secondary) !important; border: none !important; }
.stNumberInput button:hover { background: var(--bg-hover) !important; color: var(--text-primary) !important; }
/* selectbox / multiselect 内的值文本 */
.stSelectbox [data-baseweb="select"] div[role="button"],
.stMultiSelect [data-baseweb="select"] div[role="button"] { color: var(--text-primary) !important; }
/* 下拉箭头与清除图标 */
[data-baseweb="select"] svg { fill: var(--text-muted) !important; color: var(--text-muted) !important; }

/* ===== React-Aria 版 selectbox（Streamlit 1.59 起改用 react-aria，不再走 BaseWeb）=====
   实测结构：[stSelectbox] > .react-aria-ComboBox > <div class="st-emotion-...">
   该外壳底色取自主题 secondaryBackgroundColor(#f8fafc)，且 input/button 的文字色
   仍是主题 textColor(#0f172a)——在深色页面上表现为「浅色长条 + 几乎看不见的文字」。
   这两条规则是暗色下拉框可读性的关键。 */
[data-testid="stSelectbox"] .react-aria-ComboBox > div,
[data-testid="stMultiSelect"] .react-aria-ComboBox > div,
[data-testid="stSelectbox"] .react-aria-Select > div {
    background: var(--bg-secondary) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: var(--radius-sm) !important;
}
[data-testid="stSelectbox"] .react-aria-ComboBox > div:focus-within,
[data-testid="stMultiSelect"] .react-aria-ComboBox > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 1px var(--accent) !important;
}
[data-testid="stSelectbox"] .react-aria-ComboBox input,
[data-testid="stSelectbox"] .react-aria-ComboBox button,
[data-testid="stMultiSelect"] .react-aria-ComboBox input,
[data-testid="stMultiSelect"] .react-aria-ComboBox button {
    background: transparent !important;
    color: var(--text-primary) !important;
    border: none !important;
}
[data-testid="stSelectbox"] .react-aria-ComboBox input::placeholder { color: var(--text-muted) !important; opacity: 1; }
[data-testid="stSelectbox"] .react-aria-ComboBox svg,
[data-testid="stMultiSelect"] .react-aria-ComboBox svg { fill: var(--text-muted) !important; color: var(--text-muted) !important; }

/* ===== 复选框 / 单选框 ===== */
/* Streamlit 1.59 的勾选指示器是一个**兄弟 div**（不是原生 input 的外观），
   其底色来自前端主题 secondaryBackgroundColor，在深色侧边栏里表现为纯白小方块
   （本机实测：侧边栏复选框 16x16、主 Tab 导航圆点 14x14 均为纯白）。
   这里直接给指示器 div 指定底色，并区分选中态。 */
[data-testid="stCheckbox"] label > div:first-of-type,
[data-testid="stRadioOption"] div[class*="st-emotion-cache"]:not(:has(*)):not([class*="iqhgxh"]) {
    background: var(--bg-primary) !important;
    border: 1.5px solid var(--border-hover) !important;
    border-radius: 4px;
}
[data-testid="stRadioOption"] div[class*="st-emotion-cache"]:not(:has(*)):not([class*="iqhgxh"]) {
    border-radius: 50%;
}
[data-testid="stCheckbox"] input:checked + div,
[data-testid="stRadio"] input:checked + div {
    background-color: var(--accent) !important;
    border-color: var(--accent) !important;
}
[data-testid="stCheckbox"] input[type="checkbox"],
[data-testid="stRadio"] input[type="radio"] { accent-color: var(--accent); }

/* ===== 滑块 / 开关 ===== */
/* Streamlit 1.59 的滑块是 react-aria 的 <input type="range">，其自身背景在
   部分浏览器里呈默认白色，会在深色页面上留下一条细白长条（本机实测
   129x16 白条）。把 input 本体设为透明，只留主题绘制的轨道与滑钮。 */
[data-testid="stSlider"] input[type="range"] {
    background: transparent !important;
    -webkit-appearance: none;
    appearance: none;
    box-shadow: none !important;
    border: none !important;
}
[data-testid="stSlider"] [role="slider"] { background: var(--accent) !important; }
[data-testid="stSlider"] [data-baseweb="slider"] div[style*="background"] { background: var(--accent) !important; }
[data-testid="stToggle"] span[aria-checked="true"] { background: var(--accent) !important; }

/* ===== 展开器 ===== */
[data-testid="stExpander"] {
    background: var(--bg-secondary) !important;
    border: none !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stExpander"] summary { color: var(--text-primary) !important; font-weight: 500; transition: color var(--transition); }
[data-testid="stExpander"] summary:hover { color: var(--accent) !important; }
[data-testid="stExpander"] summary svg { fill: var(--text-muted) !important; color: var(--text-muted) !important; }
/* stExpanderDetails 自带 rgba(15,23,42,.2) 的描边，在深底上是一条突兀的暗线 */
[data-testid="stExpanderDetails"] { border-color: var(--border-color) !important; }
[data-testid="stExpander"] p, [data-testid="stExpander"] span,
[data-testid="stExpander"] li, [data-testid="stExpander"] div { color: inherit; }

/* ===== 提示框：统一用语义色前景，不再让正文掉到不可读的灰 ===== */
div[data-testid="stAlert"] {
    border: none !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
}
div[data-testid="stAlert"] [data-testid="stAlertContentInfo"],
div[data-testid="stAlert"] [data-testid="stAlertContentSuccess"],
div[data-testid="stAlert"] [data-testid="stAlertContentWarning"],
div[data-testid="stAlert"] [data-testid="stAlertContentError"] {
    color: var(--text-primary) !important;
}
div[data-testid="stAlert"] [data-testid="stAlertContentInfo"] p { color: var(--info-ink) !important; }
div[data-testid="stAlert"] [data-testid="stAlertContentSuccess"] p { color: var(--success-ink) !important; }
div[data-testid="stAlert"] [data-testid="stAlertContentWarning"] p { color: var(--warning-ink) !important; }
div[data-testid="stAlert"] [data-testid="stAlertContentError"] p { color: var(--error-ink) !important; }
div[data-testid="stAlert"] svg { fill: currentColor !important; }

/* ===== 数据表格 ===== */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
    border: none !important;
    border-radius: var(--radius-md) !important;
    overflow: hidden;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stDataFrame"] thead th {
    background: var(--bg-tertiary) !important;
    color: var(--text-secondary) !important;
    font-weight: 600;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    border-bottom: none !important;
}
[data-testid="stDataFrame"] tbody td { color: var(--text-secondary) !important; font-family: var(--font-mono); font-size: 0.85rem; }

/* ===== Tab ===== */
.stTabs [data-baseweb="tab-list"] { border-bottom: none !important; gap: 0; background: transparent !important; }
.stTabs [data-baseweb="tab"] { color: var(--text-muted) !important; font-weight: 500; transition: color var(--transition); background: transparent !important; }
.stTabs [data-baseweb="tab"]:hover { color: var(--text-primary) !important; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color: var(--accent) !important; font-weight: 600; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { background: var(--accent) !important; }

/* ===== 主 Tab 导航（radio 胶囊） ===== */
[data-testid="stRadio"] [role="radiogroup"] { gap: 4px; }
[data-testid="stRadio"] [role="radiogroup"] label {
    color: var(--text-secondary) !important;
    font-weight: 500;
    font-size: 0.875rem;
    padding: 8px 18px;
    border: none !important;
    border-radius: 999px;
    transition: background var(--transition), color var(--transition);
}
[data-testid="stRadio"] [role="radiogroup"] label:hover { background: var(--bg-hover); color: var(--text-primary) !important; }
[data-testid="stRadio"] [data-baseweb="radio"]:has(input:checked) + div label {
    background: var(--accent-soft);
    color: var(--accent) !important;
    font-weight: 600;
}
/* 主导航隐藏原生圆点，保留胶囊选中态 */
[data-testid="stRadio"] [role="radiogroup"] > label > div:first-child { display: none !important; }

/* ===== 侧边栏 ===== */
[data-testid="stSidebar"] { background: var(--bg-sidebar) !important; border-right: none !important; }
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span { color: var(--text-secondary) !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 { color: var(--text-primary) !important; }
[data-testid="stSidebar"] a { color: var(--accent) !important; }
[data-testid="stSidebarHeader"], [data-testid="stSidebarUserContent"] { background: transparent !important; }

/* ===== 分割线 ===== */
hr { border: none !important; height: 1px; background: var(--border-color); margin: 1rem 0; }

/* ===== 文件上传 ===== */
[data-testid="stFileUploader"] section,
[data-testid="stFileUploaderDropzone"] {
    background: var(--bg-secondary) !important;
    border: none !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid="stFileUploader"] section:hover,
[data-testid="stFileUploaderDropzone"]:hover { box-shadow: var(--shadow-md) !important; }
[data-testid="stFileUploader"] section p,
[data-testid="stFileUploaderDropzone"] p,
[data-testid="stFileUploaderDropzoneInstructions"] div,
[data-testid="stFileUploaderDropzoneInstructions"] span { color: var(--text-muted) !important; }
[data-testid="stFileUploader"] small { color: var(--text-muted) !important; }
[data-testid="stFileUploaderFileName"] { color: var(--text-primary) !important; }
[data-testid="stFileUploaderDeleteBtn"] button { background: transparent !important; color: var(--text-secondary) !important; }

/* ===== 进度条 ===== */
[data-testid="stProgress"] [role="progressbar"] > div { background: var(--bg-tertiary) !important; }
[data-testid="stProgress"] [role="progressbar"] > div > div { background: var(--accent) !important; }
[data-testid="stProgress"] p { color: var(--text-secondary) !important; }

/* ===== 代码块 / 行内代码 ===== */
/* Streamlit 的 <code> 由前端主题给底色（本机实测为 #f8f9fb），
   暗色下会在正文里留下亮色小方块。 */
[data-testid="stCode"], [data-testid="stCodeBlock"] { background: var(--bg-tertiary) !important; border-radius: var(--radius-sm) !important; }
[data-testid="stCode"] code, [data-testid="stCodeBlock"] code { color: var(--text-primary) !important; background: transparent !important; }
code { background: var(--bg-tertiary) !important; color: var(--accent) !important; border-radius: 4px; padding: 1px 5px; }
[data-testid="stMarkdownContainer"] code { background: var(--bg-tertiary) !important; color: var(--accent) !important; }
pre code { background: transparent !important; color: var(--text-primary) !important; }

/* ===== JSON / 文本输出 ===== */
[data-testid="stJson"], [data-testid="stText"], [data-testid="stMarkdownContainer"] { color: var(--text-secondary); }

/* ===== 滚动条 ===== */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ===== Plotly 容器 ===== */
.js-plotly-plot, .plot-container { border-radius: var(--radius-md) !important; }
.js-plotly-plot .plotly .main-svg { border-radius: var(--radius-md); }
/* 图表右上角的 modebar（下载 PNG / 缩放 / 框选）默认是半透明白底 + 深色图标，
   在深色背景上是一块发亮的贴片。让底色跟随主题、图标用当前色。 */
.js-plotly-plot .modebar { background: transparent !important; }
.js-plotly-plot .modebar-group { background: var(--bg-tertiary) !important; border-radius: 6px; }
.js-plotly-plot .modebar-btn path { fill: var(--text-secondary) !important; }
.js-plotly-plot .modebar-btn:hover path { fill: var(--accent) !important; }
.js-plotly-plot .modebar-btn.active path { fill: var(--accent) !important; }

/* ===== 多选标签 ===== */
[data-testid="stMultiSelect"] [data-baseweb="tag"] { background-color: var(--accent-soft) !important; border-radius: 8px !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"] span { color: var(--accent) !important; }
[data-testid="stMultiSelect"] [data-baseweb="tag"] svg { fill: var(--accent) !important; }

/* ===== 消息 / 聊天元素 ===== */
[data-testid="stChatMessage"] { background: var(--bg-secondary) !important; border-radius: var(--radius-md) !important; }

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

/* ===== 无边框安全网 ===== */
[data-testid="stVerticalBlock"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stColumn"],
.stSelectbox [data-baseweb="select"],
[data-testid="stRadio"] [role="radiogroup"] label,
[data-testid="stCheckbox"] label,
button[kind="secondary"],
.stDownloadButton button,
div[data-baseweb="popover-content"] { border: none !important; }
/* 同理排除 .stButton > button 与 [data-testid^="stBaseButton"]：
   它们的外观（底色、圆角、阴影）已在上方按 token 定义，
   这里再用 border:none 兜底会连带清掉 focus 轮廓所需的 border 基础。 */
/* 注意：这里刻意**不包含** `.stTextInput > div > div` / `.stNumberInput > div > div`。
   改造前这两条会把 BaseWeb 内层容器（承载边框的那一层）的边框清成 none，
   于是只剩 <input> 的自绘描边；一旦主题切换导致内层背景色与页面接近，
   输入框就会"看起来没有边界"。去掉后由上面的 base-input 规则统一负责。 */
"""


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
