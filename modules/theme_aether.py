"""Aether 主题系统：天空渐变 + 手绘感的双色板视觉语言。

设计要点：
- 默认浅色「清透天空」(light)，备选暗色「梦幻夜空」(dark)，侧边栏手动切换。
- 本模块输出的是「覆盖层 CSS」：注入在 app.py 旧版样式表之后，
  同名 CSS 变量以后定义者为准，旧组件样式自动跟随新 token，
  避免重写既有 300+ 行样式，改动风险最小。
- 主题选择持久化（重启保持）：
  · 未登录：写本地文件 ~/.aether_theme.json；
  · 已登录：写 Supabase user_metadata.theme（auth.py 登录时读回）。
"""

import json
from pathlib import Path

import streamlit as st

# ---- 本地偏好文件（未登录用户的持久化通道） ----
_PREF_FILE = Path.home() / ".aether_theme.json"

THEME_NAMES = {"light": "清透天空", "dark": "梦幻夜空"}


# ============================================================
# 一、双色板 token
# ============================================================
# 浅色：清透天空，浅蓝 #eaf4ff 过渡奶油 #fdf3ec，正文 #34435e
LIGHT_TOKENS = {
    "bg-primary": "#fffdfb",
    "bg-secondary": "rgba(255,255,255,0.68)",
    "bg-tertiary": "#f7f2ec",
    "bg-hover": "#edf3fb",
    "text-primary": "#34435e",
    "text-secondary": "#55648a",
    "text-muted": "#8b97b4",
    "border-color": "#e7e3ef",
    "border-hover": "#9db8e0",
    "accent": "#4a7ec2",
    "accent-hover": "#3a68ab",
    "accent-soft": "rgba(142,202,230,0.20)",
    "success-bg": "#eefaf1",
    "warning-bg": "#fdf6e3",
    "error-bg": "#fdeeee",
    # 页面背景：多层径向光晕叠在天空渐变上，营造梦幻透光感
    "app-bg": (
        "radial-gradient(620px 420px at 85% -5%, rgba(255,214,130,0.35), transparent 70%),"
        "radial-gradient(520px 400px at 8% 110%, rgba(180,200,255,0.30), transparent 70%),"
        "linear-gradient(168deg, #eaf4ff 0%, #f3edfb 48%, #fdf3ec 100%)"
    ),
    "shadow-sm": "0 1px 3px rgba(80,100,150,0.07)",
    "shadow-md": "0 6px 16px -4px rgba(80,100,150,0.12)",
    "shadow-lg": "0 16px 32px -8px rgba(80,100,150,0.16)",
    # 天气墙七场景天空（浅色主题：白天场景为主，晴夜场景保持深蓝）
    "ww-sunny": "linear-gradient(180deg,#6fb8ee 0%,#b5dcf7 70%,#d9edfb 100%)",
    "ww-cloudy": "linear-gradient(180deg,#a9bcd4 0%,#ccd9e9 100%)",
    "ww-rain": "linear-gradient(180deg,#7d94b0 0%,#b3c4d8 100%)",
    "ww-snow": "linear-gradient(180deg,#a8bdd8 0%,#e6edf7 100%)",
    "ww-thunder": "linear-gradient(180deg,#4d5c7d 0%,#7c8ba8 100%)",
    "ww-fog": "linear-gradient(180deg,#b7c1cd 0%,#dde3ea 100%)",
    "ww-night": "linear-gradient(180deg,#25315b 0%,#4a5a8f 100%)",
}

# 暗色：梦幻夜空，深蓝紫渐变，月光金点缀，全程避开纯黑与高饱和刺眼色
DARK_TOKENS = {
    "bg-primary": "#1a2138",
    "bg-secondary": "rgba(35,42,61,0.72)",
    "bg-tertiary": "#2a3350",
    "bg-hover": "#39425e",
    "text-primary": "#e6e9f2",
    "text-secondary": "#b7bfd4",
    "text-muted": "#8a93ab",
    "border-color": "#333d5a",
    "border-hover": "#7f96c9",
    "accent": "#8ecae6",
    "accent-hover": "#aedcf2",
    "accent-soft": "rgba(142,202,230,0.14)",
    "success-bg": "rgba(46,125,90,0.25)",
    "warning-bg": "rgba(160,120,40,0.25)",
    "error-bg": "rgba(160,60,60,0.28)",
    "app-bg": (
        "radial-gradient(560px 420px at 82% -5%, rgba(196,210,255,0.14), transparent 70%),"
        "radial-gradient(700px 500px at 10% 110%, rgba(120,90,180,0.16), transparent 70%),"
        "linear-gradient(168deg, #131a2e 0%, #1b2340 52%, #2b2a44 100%)"
    ),
    "shadow-sm": "0 1px 3px rgba(0,0,0,0.35)",
    "shadow-md": "0 6px 16px -4px rgba(0,0,0,0.45)",
    "shadow-lg": "0 16px 32px -8px rgba(0,0,0,0.55)",
    # 天气墙七场景天空（暗色主题：整体压深一档，避免刺眼）
    "ww-sunny": "linear-gradient(180deg,#3d6b9e 0%,#6f97c2 100%)",
    "ww-cloudy": "linear-gradient(180deg,#49566f 0%,#6d7c97 100%)",
    "ww-rain": "linear-gradient(180deg,#39496a 0%,#57698a 100%)",
    "ww-snow": "linear-gradient(180deg,#4f5f7d 0%,#8b9bb8 100%)",
    "ww-thunder": "linear-gradient(180deg,#272f4b 0%,#47537a 100%)",
    "ww-fog": "linear-gradient(180deg,#4e5966 0%,#75808d 100%)",
    "ww-night": "linear-gradient(180deg,#0f1430 0%,#2a3560 100%)",
}


# ============================================================
# 二、字体（Google Fonts，Streamlit Cloud 可直连）
# ============================================================
FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Fraunces:ital,opsz,wght@1,9..144,300..700&"  # 展示标题（斜体衬线）
    "family=Quicksand:wght@400;500;600;700&"             # 正文
    "family=Baloo+2:wght@500;700;800&"                   # 温度大数字
    "family=ZCOOL+KuaiLe&display=swap"                   # 中文手绘点缀
)


# ============================================================
# 二·五、暗色专属覆盖 CSS（Streamlit 原生组件 + 硬编码色）
# ============================================================
# 暗色模式是 CSS 变量覆盖，但 Streamlit 原生前端组件（selectbox 下拉、
# 日期选择日历、toast、弹窗等）底色由前端主题决定，默认仍是亮色，须逐一覆盖。
DARK_EXTRA_CSS = """
/* ===== 暗色专属：primary 按钮（旧样式硬编码亮米色 #faf6ef） ===== */
button[kind="primary"] {
    background: #2a3350 !important;
    color: #e6e9f2 !important;
    border-color: #39425e !important;
    box-shadow: var(--shadow-sm) !important;
}
button[kind="primary"]:hover {
    background: #39425e !important;
    border-color: #7f96c9 !important;
}

/* ===== Streamlit 原生弹层/控件暗色覆盖 ===== */
/* toast 通知 */
[data-testid="stToast"] {
    background: #232a3d !important;
    border: 1px solid #333d5a !important;
    color: #e6e9f2 !important;
}
[data-testid="stToast"] div { color: #e6e9f2 !important; }
/* selectbox / multiselect 下拉面板 */
[data-baseweb="popover"], [data-baseweb="menu"], [data-baseweb="listbox"] {
    background: #232a3d !important;
}
[data-baseweb="popover"] li, [data-baseweb="menu"] li,
[data-baseweb="listbox"] li, [data-baseweb="popover"] div {
    color: #e6e9f2 !important;
}
[data-baseweb="popover"] li:hover, [data-baseweb="menu"] li:hover,
[data-baseweb="listbox"] li:hover { background: #39425e !important; }
/* 日期选择日历 */
[data-baseweb="calendar"], [data-baseweb="calendar"] * {
    background: #232a3d !important;
    color: #e6e9f2 !important;
}
[data-baseweb="calendar"] button:hover { background: #39425e !important; }
/* 弹窗 / dialog / modal */
[data-testid="stDialog"] [data-baseweb="modal"],
[data-baseweb="modal"] { background: #232a3d !important; }
[data-testid="stDialog"] [data-baseweb="modal"] * { color: #e6e9f2 !important; }
/* popover（st.popover） */
[data-testid="stPopover"] [data-baseweb="popover"] {
    background: #232a3d !important;
}
/* tooltip */
[data-testid="stTooltip"] {
    background: #232a3d !important;
    color: #e6e9f2 !important;
    border: 1px solid #333d5a !important;
}
/* 数据表格编辑器 / 代码块 / 进度条 */
[data-testid="stDataEditor"] { background: #1a2138 !important; }
[data-testid="stCode"] { background: #141b2e !important; }
[data-testid="stProgress"] [role="progressbar"] > div > div {
    background: var(--accent) !important;
}
/* 数据表格（st.dataframe，前端主题白底，暗色必覆盖） */
[data-testid="stDataFrame"] { background: #1a2138 !important; }
[data-testid="stDataFrame"] thead th {
    background: #232a3d !important;
    color: #cbd5e8 !important;
    border-bottom-color: #39425e !important;
}
[data-testid="stDataFrame"] tbody tr,
[data-testid="stDataFrame"] tbody td {
    background: #1a2138 !important;
    color: #dbe2f0 !important;
    border-top-color: #2a3350 !important;
}
[data-testid="stDataFrame"] tbody tr:hover { background: #2a3350 !important; }
/* spinner 覆盖层 */
[data-testid="stSpinner"] { background: #232a3d !important; }
[data-testid="stSpinner"] div { color: #e6e9f2 !important; }
/* 文件上传 dropzone 与下载按钮 */
[data-testid="stFileUploaderDropzone"] {
    background: #1a2138 !important;
    border-color: #39425e !important;
}
[data-testid="stFileUploaderDropzone"] * { color: #dbe2f0 !important; }
[data-testid="stFileUploaderDropzone"]:hover { background: #232a3d !important; }
/* plotly 图表悬停提示（tooltip）默认白底，暗色下覆盖 */
[data-testid="stPlotlyChart"] .hoverlayer .hovertext rect { fill: #232a3d !important; }
[data-testid="stPlotlyChart"] .hoverlayer .hovertext text { fill: #e6e9f2 !important; }
"""


# ============================================================
# 三、持久化：本地文件 + Supabase user_metadata
# ============================================================
def _load_pref_local() -> str | None:
    """读取本地主题偏好，返回 'light' / 'dark' / None。"""
    try:
        if _PREF_FILE.exists():
            theme = json.loads(_PREF_FILE.read_text(encoding="utf-8")).get("theme")
            if theme in THEME_NAMES:
                return theme
    except Exception:
        pass  # 偏好文件损坏时静默回退默认浅色
    return None


def _save_pref_local(theme: str) -> None:
    """写本地主题偏好。失败不影响主流程。"""
    try:
        _PREF_FILE.write_text(json.dumps({"theme": theme}), encoding="utf-8")
    except Exception:
        pass


def _cloud_available() -> bool:
    """Supabase 密钥已配置且当前已登录时，才走云端持久化。

    先做 secrets 预检：get_supabase() 在缺密钥时会 st.stop() 中断渲染，
    这里必须避免误触发。
    """
    try:
        has_secrets = bool(str(st.secrets.get("SUPABASE_URL", "")).strip())
    except Exception:
        has_secrets = False
    return has_secrets and bool(st.session_state.get("auth_user"))


def _save_pref_cloud(theme: str) -> None:
    """把主题写进 Supabase user_metadata（登录用户跨设备持久化）。

    注意：不调用 auth.get_supabase——它在 DNS 失败/缺密钥时会 st.stop()
    （StopException 继承 BaseException），主题持久化是尽力而为的写入，
    不允许中断页面渲染。改为轻量 create_client + 全量捕获。
    """
    if not _cloud_available():
        return
    try:
        from supabase import create_client
        url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        key = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()
        if not url or not key:
            return
        sb = create_client(url, key)
        sb.auth.update_user({"data": {"theme": theme}})
    except Exception:
        pass  # 云端写入失败仅丢失跨设备同步，本地文件仍兜底


# ============================================================
# 四、主题状态入口
# ============================================================
def init_theme() -> None:
    """会话初始化时确定主题。必须在任何读取 dark_mode 的代码之前调用。

    优先级：session_state（本次已设定）> 登录时读回的云端值 > 本地文件 > 默认浅色。
    云端值在 auth.py 登录成功处写入 session_state["_theme_cloud"] 并直接生效，
    因此这里只需处理「未登录」与「本地文件」两条路径。
    """
    if "dark_mode" in st.session_state:
        return
    theme = _load_pref_local() or "light"  # 需求：浅色为默认主题
    st.session_state["dark_mode"] = (theme == "dark")


def set_theme(dark: bool) -> None:
    """侧边栏切换主题：写 session_state + 双通道持久化。"""
    theme = "dark" if dark else "light"
    st.session_state["dark_mode"] = dark
    _save_pref_local(theme)
    _save_pref_cloud(theme)


def apply_cloud_theme(theme: str | None) -> None:
    """登录成功后由 auth.py 调用：云端偏好覆盖当前会话，并同步到本地文件。"""
    if theme in THEME_NAMES:
        st.session_state["dark_mode"] = (theme == "dark")
        _save_pref_local(theme)


def is_dark() -> bool:
    return bool(st.session_state.get("dark_mode", False))


def get_tokens() -> dict:
    """当前主题的 token 表，供 weather_wall 等模块取色。"""
    return DARK_TOKENS if is_dark() else LIGHT_TOKENS


# ============================================================
# 四·五、无边框覆盖层 CSS（纯 CSS，无 f-string 占位符）
# ============================================================
# 同时用于 markdown 初始注入与 JS 强插 <head>，确保单一真相源。
_BORDERLESS_CSS = """
/* 卡片容器 */
[data-testid="stVerticalBlockBorderWrapper"] { border: none !important; box-shadow: var(--shadow-sm) !important; }
/* 指标卡片 */
[data-testid="stMetric"] { border: none !important; box-shadow: var(--shadow-sm) !important; }
[data-testid="stMetric"]:hover { box-shadow: var(--shadow-md) !important; border: none !important; }
/* 按钮 */
.stButton > button { border: none !important; box-shadow: var(--shadow-sm) !important; }
.stButton > button:hover { border: none !important; box-shadow: var(--shadow-md) !important; }
button[kind="primary"] { border: none !important; box-shadow: var(--shadow-sm) !important; }
button[kind="primary"]:hover { border: none !important; box-shadow: var(--shadow-md) !important; }
/* 输入框 */
.stTextInput input, .stNumberInput input, .stSelectbox [data-baseweb="select"] {
    border: none !important;
    box-shadow: 0 0 0 1px var(--border-color) inset !important;
    transition: box-shadow var(--transition) !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border: none !important;
    box-shadow: 0 0 0 2px var(--accent), 0 0 0 4px rgba(74,126,194,0.15) !important;
}
.stNumberInput button { border: none !important; background: transparent !important; }
/* 展开器 */
[data-testid="stExpander"] { border: none !important; box-shadow: var(--shadow-sm) !important; }
/* 提示框 */
div[data-testid="stAlert"] { border: none !important; box-shadow: var(--shadow-sm) !important; }
/* 数据表格 */
[data-testid="stDataFrame"] { border: none !important; box-shadow: var(--shadow-sm) !important; }
[data-testid="stDataFrame"] thead th { border-bottom: none !important; }
/* Tab 导航栏 */
.stTabs [data-baseweb="tab-list"] { border-bottom: none !important; }
/* 侧边栏 */
[data-testid="stSidebar"] { border-right: none !important; }
/* 分割线 */
hr { border-top: none !important; height: 1px; background: var(--border-color); }
/* 文件上传 */
[data-testid="stFileUploader"] section { border: none !important; background: var(--bg-secondary) !important; box-shadow: var(--shadow-sm) !important; }
[data-testid="stFileUploader"] section:hover { border: none !important; box-shadow: var(--shadow-md) !important; }
"""


def _inject_borderless_js() -> None:
    """把 _BORDERLESS_CSS 强插 document.head 末尾，并对 head 的 childList 设
    MutationObserver：Streamlit React 组件 hydration 完成后会追加自身带 !important
    的 <style>（晚于 markdown 注入），用此法在每次 head 变动后重新抢占末位，
    消除「刷新 1~2s 后边框重现」的现象。"""
    js = """
<script>
(function() {
  var CSS = `__BORDERLESS__`;
  function apply() {
    var s = document.getElementById("aether-borderless");
    if (s && s.parentNode) s.parentNode.removeChild(s);
    s = document.createElement("style");
    s.id = "aether-borderless";
    s.textContent = CSS;
    document.head.appendChild(s);
  }
  apply();
  if (window.addEventListener) window.addEventListener("load", apply);
  if (window.MutationObserver) {
    var obs = new MutationObserver(function(muts) {
      for (var i = 0; i < muts.length; i++) {
        var nodes = muts[i].addedNodes;
        for (var j = 0; j < nodes.length; j++) {
          var n = nodes[j];
          if (n.nodeType === 1 && n.tagName === "STYLE" && n.id !== "aether-borderless") {
            apply();
            return;
          }
        }
      }
    });
    obs.observe(document.head, {childList: true});
  }
})();
</script>
"""
    st.markdown(js.replace("__BORDERLESS__", _BORDERLESS_CSS), unsafe_allow_html=True)


# ============================================================
# 五、覆盖层 CSS 注入
# ============================================================
def inject_theme() -> None:
    """输出主题覆盖层。调用位置必须在 app.py 旧版样式表之后。

    旧亮色 :root 变量块与旧暗色变量块由此函数统一接管：
    按当前主题输出一套变量，旧组件样式自动跟随。
    """
    t = get_tokens()
    vars_css = "\n".join(f"    --{k}: {v};" for k, v in t.items() if k != "app-bg")
    st.markdown(f"""
<style>
@import url('{FONTS_URL}');

/* ===== Aether 主题变量（覆盖旧版同名变量） ===== */
:root {{
{vars_css}
    /* 功能模块字体还原：恢复 Aether 改造前的系统 UI 字体栈（用户要求）
       封面/天气墙专属字体走 --font-aether-ui / --font-display / --font-temp */
    --font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif;
    --font-aether-ui: 'Quicksand', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
    --font-display: 'Fraunces', 'ZCOOL KuaiLe', 'Songti SC', serif;
    --font-temp: 'Baloo 2', 'Quicksand', sans-serif;
    --radius-sm: 10px;
    --radius-md: 16px;
    --radius-lg: 20px;
    --transition: 200ms cubic-bezier(0.22, 0.8, 0.36, 1);
}}

/* ===== 页面背景：天空渐变 + 光晕（非字体规则，保持不动） ===== */
.stApp {{
    background: {t["app-bg"]};
    background-attachment: fixed;
}}

/* ===== 按钮：圆角加大 + hover 上浮（指数缓动，非字体规则） ===== */
.stButton > button {{
    border-radius: 12px !important;
}}
.stButton > button:hover {{
    transform: translateY(-2px);
}}

/* ===== 卡片容器：更大圆角 + 柔阴影（非字体规则） ===== */
[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: var(--radius-md) !important;
}}

/* ===== 主 Tab 导航：胶囊选中态（非字体规则） ===== */
[data-testid="stRadio"] [role="radiogroup"] label {{
    border-radius: 999px;
}}
</style>
""", unsafe_allow_html=True)

    # 第一段：无边框覆盖层（初始渲染即生效）
    st.markdown(f"<style>{_BORDERLESS_CSS}</style>", unsafe_allow_html=True)
    # 第二段：JS 强插 <head> 末尾 + MutationObserver，对抗 hydration 后样式重注
    _inject_borderless_js()

    # 暗色专属覆盖：Streamlit 原生组件（下拉/日历/toast/弹窗）与硬编码色
    if is_dark():
        st.markdown(f"<style>{DARK_EXTRA_CSS}</style>", unsafe_allow_html=True)
        # DARK_EXTRA_CSS 之后再次注入无边框层，消除其硬编码边框；
        # MutationObserver 会在 head 变动时自动重新抢占末位
        st.markdown(f"<style>{_BORDERLESS_CSS}</style>", unsafe_allow_html=True)
