"""Aether 主题系统：天空渐变 + 手绘感的双色板视觉语言。

设计要点
--------
- 默认浅色「清透天空」(light)，备选暗色「梦幻夜空」(dark)，侧边栏手动切换。
- **token 定义全部搬到 ``modules/design_tokens.py``**，本模块只负责
  「读偏好 → 生成 CSS → 注入 DOM」。改造前 token、CSS、业务模块三处各写一份
  配色，是暗色模式无法收敛的根本原因。
- 主题选择持久化（重启保持）：
  · 未登录：写本地文件 ``~/.aether_theme.json``；
  · 已登录：写 Supabase ``user_metadata.theme``（``auth.py`` 登录时读回）。

暗色实现方式说明
----------------
``.streamlit/config.toml`` 的 ``[theme]`` 是**进程级配置，无法按会话切换**，
因此这里采用「config.toml 固定亮色基线 + CSS 层按会话覆盖」：

- 变量块同时包含 ``html[data-dsh-theme="light"]`` 与 ``[data-dsh-theme="dark"]``
  两套取值，切换时只需改 ``<html>`` 的 ``data-dsh-theme`` 属性，
  不重建样式文本、不触发重排，因此切换无闪烁；
- 暗色专属的 Streamlit 原生组件覆盖规则只生成一次（见 ``theme_css.py``），
  不再每次渲染都往 ``<head>`` 追加重复样式。
"""

import json
from pathlib import Path

import streamlit as st

from modules import theme_css
from modules.design_tokens import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    STATIC_TOKENS,
    THEME_NAMES,
    tokens_for,
)

# 向后兼容：历史上 token 定义在本模块，测试与业务代码从 ``theme_aether`` 读取。
__all__ = [
    "DARK_TOKENS",
    "LIGHT_TOKENS",
    "STATIC_TOKENS",
    "THEME_NAMES",
    "init_theme",
    "set_theme",
    "apply_cloud_theme",
    "is_dark",
    "get_tokens",
    "inject_theme",
    "theme_attr_js",
    "FONTS_URL",
]

# ---- 本地偏好文件（未登录用户的持久化通道） ----
_PREF_FILE = Path.home() / ".aether_theme.json"

# ---- 标记 DOM 当前主题的属性名。CSS 变量块与所有暗色覆盖规则都挂在它下面。 ----
THEME_ATTR = "data-dsh-theme"

# ============================================================
# 一、字体（Google Fonts，Streamlit Cloud 可直连）
# ============================================================
FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Fraunces:ital,opsz,wght@1,9..144,300..700&"  # 展示标题（斜体衬线）
    "family=Quicksand:wght@400;500;600;700&"             # 正文
    "family=Baloo+2:wght@500;700;800&"                   # 温度大数字
    "family=ZCOOL+KuaiLe&display=swap"                   # 中文手绘点缀
)


# ============================================================
# 二、持久化：本地文件 + Supabase user_metadata
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

    安全修复：改用 auth.get_supabase()，即当前会话专属且已完成登录的客户端。
    原实现每次新建一个匿名客户端再调 update_user，客户端里没有会话，请求必然
    被拒；异常被静默吞掉，导致跨设备主题同步从未真正生效。
    """
    if not _cloud_available():
        return
    try:
        from auth import get_supabase

        sb = get_supabase()
        if sb is None:
            return
        sb.auth.update_user({"data": {"theme": theme}})
    except Exception:
        pass  # 云端写入失败仅丢失跨设备同步，本地文件仍兜底


# ============================================================
# 三、主题状态入口
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


def get_tokens(dark: bool | None = None) -> dict:
    """token 表，供 weather_wall 等模块取色。传入 dark 可显式取值。"""
    if dark is None:
        dark = is_dark()
    return tokens_for(dark)


# ============================================================
# 四、DOM 主题属性同步脚本
# ============================================================
def theme_attr_js() -> str:
    """把 ``data-dsh-theme`` 写到 ``<html>`` 上。

    必须用 ``st.html(..., unsafe_allow_javascript=True)`` 注入：
    **``st.markdown(unsafe_allow_html=True)`` 会把 ``<script>`` 剥掉**
    （Streamlit 用 DOMPurify 清洗 HTML）。改造前的 ``_inject_borderless_js``
    正是走 markdown 注入脚本，实际上从未执行过——这类「写了但没生效」的
    静默失效是暗色模式长期修不干净的重要原因。

    **这里刻意不使用 MutationObserver**（R-44）。曾经用观察者守 ``<html>`` 的属性
    以对抗「刷新后样式回弹」，但实测造成渲染进程主线程被占死：切换主题时页面
    完全无响应（点击后主线程阻塞 >8s，页面探测超时；关掉本脚本后同一操作
    4ms 内恢复响应）。原因是 Streamlit 的 React 根组件在每次 rerun 时持续改写
    ``<html>``/``<body>`` 的 class 与 style，观察者被高频触发，而 Streamlit 每次
    重渲染都会重新执行本脚本、**再挂一个新的观察者**，观察者数量随 rerun 累加，
    回调频率成倍上升，最终把主线程压死。

    替代方案依赖一个更稳的事实：本脚本随每次 rerun 重新执行，
    而样式块（含整套变量）是幂等注入的，因此**每次渲染都会重新把属性写正确**，
    不需要长期的观察者。另外把主题属性同时写到 ``<html>`` 与 ``<body>``：
    Streamlit 只会重写 ``body`` 上的 class，属性得以保留。
    """
    theme = "dark" if is_dark() else "light"
    # 外层 div 仅用于承载脚本，display:none 保证不影响布局
    return f"""<div style="display:none" aria-hidden="true"><script>
(function() {{
  var ATTR = "{THEME_ATTR}", WANT = "{theme}";
  function apply() {{
    var h = document.documentElement;
    if (h && h.getAttribute(ATTR) !== WANT) h.setAttribute(ATTR, WANT);
    var b = document.body;
    if (b && b.getAttribute(ATTR) !== WANT) b.setAttribute(ATTR, WANT);
  }}
  apply();
  if (document.readyState !== "complete") {{
    document.addEventListener("DOMContentLoaded", apply);
    window.addEventListener("load", apply);
  }}
}})();
</script></div>"""


# ============================================================
# 五、样式注入
# ============================================================
def inject_theme() -> None:
    """注入主题样式。必须在 ``st.set_page_config`` 之后、任何可见内容之前调用。

    改造前本函数只在**登录成功后**的 ``app.py`` 中被调用，未登录时直接
    ``st.stop()``，导致登录页完全没有样式、也不跟随用户保存的暗色偏好。
    现在由 ``app.py`` 在登录门禁之前调用。

    排障开关（仅用于定位渲染进程卡死，正常部署不要设置）：
    - ``DSH_THEME_NO_DARK_CSS=1``：不输出暗色覆盖层
    - ``DSH_THEME_NO_BASE_CSS=1``：不输出形状/排版基线
    - ``DSH_THEME_NO_JS=1``：不注入主题属性脚本
    """
    import os

    parts = [f"@import url('{FONTS_URL}');",
             "/* ===== 主题变量（亮/暗两套同时在场，靠 html[data-dsh-theme] 切换） ===== */",
             theme_css.root_vars_css(False),
             theme_css.root_vars_css(True)]
    if not os.environ.get("DSH_THEME_NO_BASE_CSS"):
        parts += ["/* ===== 形状与排版基线 ===== */", theme_css.BASE_CSS]
    if not os.environ.get("DSH_THEME_NO_DARK_CSS"):
        parts += ["/* ===== Streamlit 原生组件暗色覆盖 ===== */", theme_css.dark_extra_css()]

    st.markdown(f"<style>{chr(10).join(parts)}</style>", unsafe_allow_html=True)
    # 脚本必须走 st.html：markdown 的 unsafe_allow_html 会被 DOMPurify 剥掉 <script>
    if not os.environ.get("DSH_THEME_NO_JS"):
        st.html(theme_attr_js(), unsafe_allow_javascript=True)
