"""设计 token 单一真相源（Single Source of Truth）。

背景与本模块的职责
------------------
改造前项目里存在 **三套互不感知的配色定义**：

1. ``app.py`` 的 ``<style>`` 内 ``:root`` 亮色变量块；
2. ``modules/theme_aether.py`` 的 ``LIGHT_TOKENS`` / ``DARK_TOKENS``，注入在
   (1) 之后，靠「后定义者覆盖」压掉 (1)；
3. 各业务模块（``analyzer`` / ``nwp_forecast`` / ``visualizer`` /
   ``ai_narrative`` / ``verify``）里的硬编码 hex 与 ``_is_dark()`` 三元分支。

结果是同一个语义色在不同页面上取值不同，暗色模式永远补齐不了。
本模块把 (2) 提升为唯一来源，并让 (1)(3) 改为从这里取值。

token 分层
----------
- ``surfaces``  表面层：页面 / 卡片 / 下沉 / 悬停 / 侧边栏
- ``ink``       文字层：主 / 次 / 弱 / 反色
- ``lines``     描边层：常规 / 强调
- ``brand``     品牌强调色与柔光
- ``status``    语义状态色（成功 / 警告 / 错误 / 信息）
- ``data``      数据可视化色板
- ``wx``        天气墙七场景天空

对比度
------
所有 ``ink`` 与 ``line-strong`` 取值都经 ``research/darkmode_contrast_probe.py``
的 WCAG 2.1 审计。改造前亮色主题的 ``text-muted`` 只有 2.58:1、
``accent`` 只有 3.67:1，均低于 AA 正文 4.5:1 门槛，本版已修正。
"""

from __future__ import annotations

from typing import Dict

# ============================================================
# 一、亮色主题「清透天空」
# ============================================================
LIGHT_TOKENS: Dict[str, str] = {
    # ---- 表面层 ----
    # 页面底色不单独设，由 app-base 渐变的中间色承担，避免渐变与实底打架
    "surface": "#fffdfb",
    "surface-2": "#f7f3ee",
    "surface-3": "#f0ece7",
    "surface-hover": "#eceef5",
    "canvas": "#f4f1f8",
    "sidebar": "#f9f5f0",
    # ---- 文字层（全部 ≥ 4.5:1）----
    "text-primary": "#2b3a52",
    "text-secondary": "#4d5c7d",
    # 改造前为 #8b97b4，在浅色卡片上只有 2.88:1；这里压到刚好过 AA 的
    # 最浅值，既满足无障碍又保留「弱化」的视觉层级。
    "text-muted": "#5b688a",
    # ---- 描边层 ----
    "line": "#e4e0ec",
    "line-strong": "#9db8e0",
    # ---- 品牌强调 ----
    "accent": "#2f61a8",
    "accent-hover": "#24508f",
    "accent-soft": "rgba(142,202,230,0.22)",
    "accent-contrast": "#ffffff",
    # ---- 语义状态 ----
    "success-bg": "#e9f8ee",
    "success-ink": "#1c6b41",
    "warning-bg": "#fdf3dd",
    "warning-ink": "#7d5310",
    "error-bg": "#fdecec",
    "error-ink": "#9b2c2c",
    "info-bg": "#e8f1fd",
    "info-ink": "#1e4b8a",
    # ---- 阴影 ----
    "shadow-sm": "0 1px 3px rgba(80,100,150,0.07)",
    "shadow-md": "0 6px 16px -4px rgba(80,100,150,0.12)",
    "shadow-lg": "0 16px 32px -8px rgba(80,100,150,0.16)",
    # ---- 数据可视化 ----
    "chart-grid": "#e0e0e0",
    "chart-axis": "#6b7896",
    "chart-title": "#2b3a52",
    "chart-tip-bg": "rgba(255,255,255,0.94)",
    "chart-tip-line": "#d6d3e0",
    # 数据点描边：让标记从填充色带上"浮"起来
    "chart-marker-line": "#ffffff",
    # 图表上的参考线（"现在"竖线、阈值横线）
    "chart-ref-line": "#6b7896",
    "temp": "#c0392b",
    "pres": "#1f7a4d",
    "humid": "#1f6fb2",
    # 改造前为 #f39c12，在浅色卡片上只有 3.76:1，作为数值正文色不达标
    "wind": "#8a5a0a",
    "vis": "#7d4fa8",
    "rain": "#1f6fa8",
    "pm25": "#4a6b8f",
    "pm10": "#5f5578",
    "so2": "#a37a10",
    "nox": "#a8443f",
    "tsp": "#7a6549",
    # ---- 严重度梯度（生活指数 / 紫外线 / 舒适度分级共用一个梯度）----
    "sev-best": "#1f7a4d",
    "sev-good": "#4f7a12",
    "sev-mid": "#8a6410",
    "sev-warn": "#b4541a",
    "sev-bad": "#b32d2d",
    # ---- AQI 六级（GB 3095 优→严重污染；config.AQI_LEVELS 与本表同源）----
    "aqi-1": "#2f7d4f",
    "aqi-2": "#7d6210",
    "aqi-3": "#a85f1e",
    "aqi-4": "#a8443f",
    "aqi-5": "#7d3d60",
    "aqi-6": "#8a3040",
    # ---- 气象预警四级（蓝/黄/橙/红，中国气象局第16号令）----
    "warn-4": "#1f5c9e",   # 蓝色
    "warn-3": "#8a6410",   # 黄色
    "warn-2": "#a8561f",   # 橙色
    "warn-1": "#a82c22",   # 红色
    # ---- 蒲福风级配色带（静风 → 大风及以上，9 档）----
    # 亮暗各一套：浅色主题用浅蓝起手（与清透天空一致），
    # 暗色主题整体压深，否则 #dceef5 这类极浅色在深底上"发光"。
    "beaufort-1": "#dceef5",
    "beaufort-2": "#a8d2e8",
    "beaufort-3": "#74b4d9",
    "beaufort-4": "#4592c8",
    "beaufort-5": "#2b6cb0",
    "beaufort-6": "#d99a20",
    "beaufort-7": "#e2662f",
    "beaufort-8": "#c0392b",
    "beaufort-9": "#8f8f96",
    # ---- 页面底色渐变 ----
    "app-base": "#f4f1f8",
    "app-bg": (
        "radial-gradient(620px 420px at 85% -5%, rgba(255,214,130,0.35), transparent 70%),"
        "radial-gradient(520px 400px at 8% 110%, rgba(180,200,255,0.30), transparent 70%),"
        "linear-gradient(168deg, #eaf4ff 0%, #f3edfb 48%, #fdf3ec 100%)"
    ),
    # ---- 天气墙七场景天空（浅色：白天场景为主，晴夜保持深蓝）----
    "ww-sunny": "linear-gradient(180deg,#6fb8ee 0%,#b5dcf7 70%,#d9edfb 100%)",
    "ww-cloudy": "linear-gradient(180deg,#a9bcd4 0%,#ccd9e9 100%)",
    "ww-rain": "linear-gradient(180deg,#7d94b0 0%,#b3c4d8 100%)",
    "ww-snow": "linear-gradient(180deg,#a8bdd8 0%,#e6edf7 100%)",
    "ww-thunder": "linear-gradient(180deg,#4d5c7d 0%,#7c8ba8 100%)",
    "ww-fog": "linear-gradient(180deg,#b7c1cd 0%,#dde3ea 100%)",
    "ww-night": "linear-gradient(180deg,#25315b 0%,#4a5a8f 100%)",
}

# ============================================================
# 二、暗色主题「梦幻夜空」
# ============================================================
# 表面层刻意做到不透明：改造前用 rgba(35,42,61,0.72) 叠在
# `background-attachment: fixed` 的径向渐变上，滚动时卡片明暗会漂移，
# 同一卡片在不同滚动位置呈现不同底色，是「割裂感」的主要来源之一。
DARK_TOKENS: Dict[str, str] = {
    # ---- 表面层 ----
    "surface": "#232b45",
    "surface-2": "#2a3350",
    "surface-3": "#1d2438",
    "surface-hover": "#39425e",
    "canvas": "#161c2e",
    "sidebar": "#1b2236",
    # ---- 文字层（全部 ≥ 4.5:1）----
    "text-primary": "#e8ebf5",
    "text-secondary": "#bcc5da",
    "text-muted": "#98a2ba",
    # ---- 描边层 ----
    "line": "#39435f",
    "line-strong": "#7f96c9",
    # ---- 品牌强调 ----
    "accent": "#8ecae6",
    "accent-hover": "#aedcf2",
    "accent-soft": "rgba(142,202,230,0.16)",
    "accent-contrast": "#101828",
    # ---- 语义状态 ----
    "success-bg": "rgba(46,125,90,0.22)",
    "success-ink": "#7ddca4",
    # 提示类底色比错误/警告更克制：整条横幅用 0.22 的琥珀底在深色页面上
    # 会变成一大块发亮的金棕，抢过正文注意力（本机实测确有此效果）
    "warning-bg": "rgba(176,132,44,0.12)",
    "warning-ink": "#f3c96b",
    "error-bg": "rgba(176,64,64,0.20)",
    "error-ink": "#ff9b9b",
    "info-bg": "rgba(64,120,200,0.18)",
    "info-ink": "#8fc0ff",
    # ---- 阴影 ----
    "shadow-sm": "0 1px 3px rgba(0,0,0,0.35)",
    "shadow-md": "0 6px 16px -4px rgba(0,0,0,0.45)",
    "shadow-lg": "0 16px 32px -8px rgba(0,0,0,0.55)",
    # ---- 数据可视化（相对 #161c2e 与 #232b45 均 ≥ 3:1）----
    "chart-grid": "#38415c",
    "chart-axis": "#98a2ba",
    "chart-title": "#e8ebf5",
    "chart-tip-bg": "rgba(35,43,69,0.96)",
    "chart-tip-line": "#39435f",
    "chart-marker-line": "#161c2e",
    "chart-ref-line": "#98a2ba",
    "temp": "#ff7b72",
    "pres": "#4ecb8f",
    "humid": "#5aa9e6",
    "wind": "#f0b429",
    "vis": "#b18cf0",
    "rain": "#4aa3df",
    "pm25": "#8fb3d9",
    "pm10": "#b3a3d1",
    "so2": "#e0b83c",
    "nox": "#e0857f",
    "tsp": "#c2a883",
    # ---- 严重度梯度（亮色下压深以便当正文色，暗色下提亮）----
    "sev-best": "#5fd39a",
    "sev-good": "#a8d94f",
    "sev-mid": "#f0c63f",
    "sev-warn": "#fb9a4c",
    "sev-bad": "#ff8080",
    # ---- AQI 六级（暗色下提亮，保证在深底上仍可读）----
    "aqi-1": "#5fd39a",
    "aqi-2": "#f0c63f",
    "aqi-3": "#fb9a4c",
    "aqi-4": "#ff8080",
    "aqi-5": "#d99bc9",
    "aqi-6": "#e87f96",
    # ---- 气象预警四级 ----
    "warn-4": "#6cb0f5",
    "warn-3": "#f0c63f",
    "warn-2": "#fb9a4c",
    "warn-1": "#ff8080",
    # ---- 蒲福风级配色带（暗色下整体压深并提高相邻档差异）----
    "beaufort-1": "#33455e",
    "beaufort-2": "#3f6c95",
    "beaufort-3": "#4a87b8",
    "beaufort-4": "#5aa3d8",
    "beaufort-5": "#7dc0ef",
    "beaufort-6": "#e0b23c",
    "beaufort-7": "#ef8a5c",
    "beaufort-8": "#e05a5a",
    "beaufort-9": "#9aa2b4",
    # ---- 页面底色渐变 ----
    "app-base": "#161c2e",
    "app-bg": (
        "radial-gradient(560px 420px at 82% -5%, rgba(196,210,255,0.14), transparent 70%),"
        "radial-gradient(700px 500px at 10% 110%, rgba(120,90,180,0.16), transparent 70%),"
        "linear-gradient(168deg, #131a2e 0%, #1b2340 52%, #2b2a44 100%)"
    ),
    # ---- 天气墙七场景天空（暗色：整体压深一档，避免刺眼）----
    "ww-sunny": "linear-gradient(180deg,#3d6b9e 0%,#6f97c2 100%)",
    "ww-cloudy": "linear-gradient(180deg,#49566f 0%,#6d7c97 100%)",
    "ww-rain": "linear-gradient(180deg,#39496a 0%,#57698a 100%)",
    "ww-snow": "linear-gradient(180deg,#4f5f7d 0%,#8b9bb8 100%)",
    "ww-thunder": "linear-gradient(180deg,#272f4b 0%,#47537a 100%)",
    "ww-fog": "linear-gradient(180deg,#4e5966 0%,#75808d 100%)",
    "ww-night": "linear-gradient(180deg,#0f1430 0%,#2a3560 100%)",
}

# ============================================================
# 三、与主题无关的常量（圆角 / 过渡 / 字体栈）
# ============================================================
# 这些与配色无关，亮暗共用，放在这里避免 app.py 与 theme_aether 各写一份。
STATIC_TOKENS: Dict[str, str] = {
    "radius-sm": "10px",
    "radius-md": "16px",
    "radius-lg": "20px",
    "transition": "200ms cubic-bezier(0.22, 0.8, 0.36, 1)",
    "font-ui": (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, "
        "'PingFang SC', 'Microsoft YaHei', sans-serif"
    ),
    "font-mono": "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
    "font-aether-ui": "'Quicksand', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
    "font-display": "'Fraunces', 'ZCOOL KuaiLe', 'Songti SC', serif",
    "font-temp": "'Baloo 2', 'Quicksand', sans-serif",
}

THEME_NAMES = {"light": "清透天空", "dark": "梦幻夜空"}

# token 键 → CSS 变量名。显式映射而非字符串拼接，避免有人往 token 里塞
# 不带前缀语义的键时静默产出错误变量名。
_CSS_NAME_OVERRIDES = {
    "surface": "bg-primary",
    "surface-2": "bg-secondary",
    "surface-3": "bg-tertiary",
    "surface-hover": "bg-hover",
    "canvas": "bg-canvas",
    "sidebar": "bg-sidebar",
    "text-primary": "text-primary",
    "text-secondary": "text-secondary",
    "text-muted": "text-muted",
    "line": "border-color",
    "line-strong": "border-hover",
    "accent": "accent",
    "accent-hover": "accent-hover",
    "accent-soft": "accent-soft",
    "accent-contrast": "accent-contrast",
    "app-base": "app-base",
    "app-bg": "app-bg",
}


def css_var_name(token: str) -> str:
    """token 键 → CSS 自定义属性名（不含前导 ``--``）。"""
    return _CSS_NAME_OVERRIDES.get(token, token)


def css_var(token: str) -> str:
    """供 Python 侧拼接 ``style`` 用，返回 ``var(--xxx)``。

    内联样式一律走这个函数而不是取 hex：CSS 变量在客户端即时生效，
    主题切换不需要 Python 重新渲染，也不会出现「服务端算出一套、客户端贴一套」。
    """
    return f"var(--{css_var_name(token)})"


def alpha(token: str, value: float) -> str:
    """把某个 hex token 降成半透明色，用于填充、描边等需要弱化的场合。

    仅支持 ``#rrggbb``；渐变类 token 直接抛错，避免静默产出非法 CSS。
    """
    raw = tokens_for(False).get(token) or tokens_for(True)[token]
    if not raw.startswith("#") or len(raw) != 7:
        raise ValueError(f"token {token!r} 不是纯 hex 色，无法取 alpha")
    r, g, b = (int(raw[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{value})"


def tokens_for(dark: bool) -> Dict[str, str]:
    """按主题返回 token 表。"""
    return DARK_TOKENS if dark else LIGHT_TOKENS


# ============================================================
# 四、业务语义解析：等级名 → token
# ============================================================
# 改造前 AQI 六级色在 ``config.AQI_LEVELS`` 与 ``nwp_forecast._AQ_LEVELS`` 各写一份，
# 预警四级色在 ``config.WARN_STYLES`` 与两个模块的私有 ``dark_styles`` 字典里
# 各写一份，三处取值互不相同（同一「红色预警」在三个页面呈现三种红）。
# 这里提供唯一映射，各模块只保留「等级名 → token 名」的一次查表。
_AQI_TOKEN = {
    "优": "aqi-1",
    "良": "aqi-2",
    "轻度污染": "aqi-3",
    "中度污染": "aqi-4",
    "重度污染": "aqi-5",
    "严重污染": "aqi-6",
}

_WARN_TOKEN = {
    "蓝色": "warn-4",
    "黄色": "warn-3",
    "橙色": "warn-2",
    "红色": "warn-1",
}


def aqi_token(level: str) -> str:
    """AQI 等级名 → token 名（未知等级回退到「严重污染」）。"""
    return _AQI_TOKEN.get(level, "aqi-6")


def aqi_color(level: str, dark: bool | None = None) -> str:
    """AQI 等级名 → 可直接用于内联样式的颜色值。"""
    return tokens_for(is_dark() if dark is None else dark)[aqi_token(level)]


def warn_token(level: str) -> str:
    """气象预警级别名 → token 名（未知级别回退到「蓝色」）。"""
    return _WARN_TOKEN.get(level, "warn-4")


def warn_color(level: str, dark: bool | None = None) -> str:
    """气象预警级别名 → 可直接用于内联样式的颜色值。"""
    return tokens_for(is_dark() if dark is None else dark)[warn_token(level)]


def is_dark() -> bool:
    """当前是否暗色。独立于 ``theme_aether``，避免模块间循环导入。"""
    try:
        import streamlit as st

        return bool(st.session_state.get("dark_mode", False))
    except Exception:
        return False


# ============================================================
# 五、config.COLORS 键 → token 名
# ============================================================
# ``config.COLORS`` 是项目早期的图表配色表，键名（temp_color / so2_color …）
# 已被各模块大量引用。这里提供「键 → token」映射与解析函数，
# 让调用点保持原有写法的同时拿到随主题变化的颜色，
# 从而不必一次性重写全部引用。
COLOR_KEY_TO_TOKEN: Dict[str, str] = {
    # 气象要素
    "temp_color": "temp",
    "pres_color": "pres",
    "humid_color": "humid",
    "wind_color": "wind",
    "vis_color": "vis",
    "rain_color": "rain",
    # 大气污染物
    "so2_color": "so2",
    "nox_color": "nox",
    "tsp_color": "tsp",
    "pm25_color": "pm25",
    "pm10_color": "pm10",
    # 通用分类色
    "primary": "accent",
    "purple": "vis",
    "secondary": "wind",
    "info": "humid",
    "success": "pres",
    "danger": "temp",
}


def color_var(color_key: str) -> str:
    """``config.COLORS`` 的键 → 当前主题下的 ``var(--token)``。

    适用于 **HTML/CSS** 场景（内联 style、style 块）。
    未登记的键原样返回 ``config.COLORS`` 里的 hex，保证向后兼容：
    新增配色时不会因为忘记登记映射而直接报错，只是不跟随主题。
    """
    token = COLOR_KEY_TO_TOKEN.get(color_key)
    if token:
        return css_var(token)
    from config import COLORS

    return COLORS.get(color_key, css_var("accent"))


def color_value(color_key: str, dark: bool | None = None) -> str:
    """``config.COLORS`` 的键 → 当前主题下的**具体色值（hex/rgba）**。

    适用于 **Plotly 图表** 场景。图表由 plotly.js 在浏览器里绘制 SVG，
    对 SVG 的 `fill` / `stroke` 属性不会解析 CSS `var()`，必须给真实色值。
    纯 HTML 场景请改用 :func:`color_var`（可随主题即时切换）。
    """
    token = COLOR_KEY_TO_TOKEN.get(color_key)
    if token:
        return token_value(token, dark)
    from config import COLORS

    return COLORS.get(color_key, "#888888")


def token_value(token: str, dark: bool | None = None) -> str:
    """token 名 → 当前主题下的具体色值。"""
    table = tokens_for(is_dark() if dark is None else dark)
    return table.get(token, "#888888")


def _parity_guard() -> None:
    """两套 token 必须同键，否则某主题下变量会静默缺失。"""
    missing_dark = set(LIGHT_TOKENS) - set(DARK_TOKENS)
    missing_light = set(DARK_TOKENS) - set(LIGHT_TOKENS)
    if missing_dark or missing_light:
        raise AssertionError(
            f"token 键不一致：暗色缺少 {sorted(missing_dark)}，"
            f"亮色缺少 {sorted(missing_light)}"
        )


_parity_guard()
