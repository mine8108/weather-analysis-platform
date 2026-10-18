"""预警规则的单一出口：阈值解析与等级串。

此前阈值有四份（config 真相源、analyzer 读取并叠加自定义、nwp_forecast
硬编码、app 侧边栏默认值再抄一遍），等级串有两套（config 的 Ⅰ/Ⅱ/Ⅲ 与
nwp 的 I/II/III）。本模块把「取哪个数值」与「等级怎么写」收成函数：

- :func:`default_custom` 侧边栏默认值，全部来自 config
- :func:`high_temp_levels` 等按类别返回「颜色 → 数值」，自定义优先
- :func:`current_custom` 会话级自定义阈值（无 Streamlit 上下文时返回空）
- 等级串统一走 :func:`config.level_label`

本模块不 import streamlit，session 读取是函数内的惰性导入。
"""
from config import (
    COLD_WAVE_WARNING,
    FOG_WARNING,
    FROST_WARNING,
    GALE_WARNING,
    HAZE_WARNING,
    HIGH_TEMP_WARNING,
    RAINSTORM_WARNING,
    THUNDER_WARNING,
    level_label,
)

# 雷电判定的默认时间窗口（config 的雷电规则只定义等级，不定义窗口小时数）
THUNDER_WINDOW_HOURS = 6

# 预报侧按「日累计降水」判定，与国标的 12h/6h/3h 窗口不同，因此单列一份。
DAILY_RAIN_LEVELS = {"红色": 100.0, "橙色": 75.0, "黄色": 50.0, "大雨": 25.0}


def current_custom():
    """当前会话的自定义阈值；无 Streamlit 上下文时返回空 dict。"""
    try:
        import streamlit as st
        return st.session_state.get("_custom_thresholds") or {}
    except Exception:
        return {}


def _merged(kind, base, custom):
    """用自定义值覆盖默认值；None 视为未设置。"""
    custom = (custom if custom is not None else current_custom()).get(kind) or {}
    out = dict(base)
    for color, value in custom.items():
        if value is not None:
            out[color] = value
    return out


def high_temp_levels(custom=None):
    """高温阈值（℃），键为颜色。"""
    base = {color: rule["temp"] for color, rule in HIGH_TEMP_WARNING.items()}
    return _merged("high_temp", base, custom)


def gale_levels(custom=None):
    """大风阈值（m/s），键为颜色。"""
    base = {color: rule["avg_wind"] for color, rule in GALE_WARNING.items()}
    return _merged("gale", base, custom)


def fog_levels(custom=None):
    """大雾阈值（米），键为颜色。"""
    base = {color: rule["visibility"] for color, rule in FOG_WARNING.items()}
    return _merged("fog", base, custom)


def frost_levels(custom=None):
    """霜冻阈值（℃，地面最低温度），键为颜色。"""
    base = {color: rule["ground_temp"] for color, rule in FROST_WARNING.items()}
    return _merged("frost", base, custom)


def haze_levels(custom=None):
    """霾阈值（米），键为颜色。"""
    base = {color: rule["visibility"] for color, rule in HAZE_WARNING.items()}
    return _merged("haze", base, custom)


def rainstorm_levels(custom=None):
    """暴雨阈值（毫米），键为颜色。"""
    base = {color: rule["rain"] for color, rule in RAINSTORM_WARNING.items()}
    return _merged("rainstorm", base, custom)


def cold_wave_levels(custom=None):
    """寒潮阈值，返回每档的完整规则（温度降幅与最低温度组合判定）。"""
    custom = (custom if custom is not None else current_custom()).get("cold_wave") or {}
    out = {color: dict(rule) for color, rule in COLD_WAVE_WARNING.items()}
    for color, override in custom.items():
        if isinstance(override, dict):
            out.get(color, {}).update(override)
        elif override is not None and color in out:
            out[color]["temp_drop"] = override
    return out


def thunder_window_hours(custom=None):
    """雷电判定窗口（小时）。"""
    custom = (custom if custom is not None else current_custom()).get("thunder") or {}
    value = custom.get("hours")
    try:
        return float(value) if value is not None else float(THUNDER_WINDOW_HOURS)
    except (TypeError, ValueError):
        return float(THUNDER_WINDOW_HOURS)


def default_custom():
    """侧边栏默认值，结构与会话里的 _custom_thresholds 完全一致。

    数值类型与 Streamlit 控件保持一致（value 与 step 必须同类型）：
    高温/大风/暴雨/霜冻用 float，能见度与雷电窗口用 int。
    """
    return {
        "high_temp": {k: float(v) for k, v in high_temp_levels(custom={}).items()},
        "gale": {k: float(v) for k, v in gale_levels(custom={}).items()},
        "fog": {k: int(v) for k, v in fog_levels(custom={}).items()},
        "rainstorm": {k: float(v) for k, v in rainstorm_levels(custom={}).items()},
        "frost": {k: float(v) for k, v in frost_levels(custom={}).items()},
        "haze": {k: int(v) for k, v in haze_levels(custom={}).items()},
        "thunder": {"hours": THUNDER_WINDOW_HOURS},
    }


__all__ = [
    "DAILY_RAIN_LEVELS", "THUNDER_WINDOW_HOURS", "cold_wave_levels",
    "current_custom", "default_custom", "fog_levels", "frost_levels",
    "gale_levels", "haze_levels", "high_temp_levels", "level_label",
    "rainstorm_levels", "thunder_window_hours",
]
