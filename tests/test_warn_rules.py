"""预警规则单一出口的契约。

- 侧边栏默认值必须等于 config 的阈值（不再手抄一份数字）
- 等级串只有 config.level_label 一个生成方式，八张表全部一致
- 自定义阈值在预警规则层生效，预报侧与观测侧读同一份
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from modules import warn_rules  # noqa: E402

TABLES = {
    "high_temp": config.HIGH_TEMP_WARNING,
    "cold_wave": config.COLD_WAVE_WARNING,
    "gale": config.GALE_WARNING,
    "fog": config.FOG_WARNING,
    "rainstorm": config.RAINSTORM_WARNING,
    "frost": config.FROST_WARNING,
    "thunder": config.THUNDER_WARNING,
    "haze": config.HAZE_WARNING,
}


def test_level_labels_are_derived_not_handwritten():
    for name, table in TABLES.items():
        for color, rule in table.items():
            assert rule["level"] == config.level_label(color), (name, color)
    assert config.level_label("红色") == "Ⅰ级"
    assert config.level_label("蓝色") == "Ⅳ级"


def test_no_ascii_roman_levels_remain_in_config():
    for table in TABLES.values():
        for rule in table.values():
            assert rule["level"] not in {"I级", "II级", "III级", "IV级"}


def test_default_custom_matches_config_numbers():
    defaults = warn_rules.default_custom()
    assert defaults["high_temp"]["黄色"] == config.HIGH_TEMP_WARNING["黄色"]["temp"]
    assert defaults["high_temp"]["红色"] == config.HIGH_TEMP_WARNING["红色"]["temp"]
    assert defaults["gale"]["蓝色"] == config.GALE_WARNING["蓝色"]["avg_wind"]
    assert defaults["fog"]["橙色"] == config.FOG_WARNING["橙色"]["visibility"]
    assert defaults["rainstorm"]["红色"] == config.RAINSTORM_WARNING["红色"]["rain"]
    assert defaults["frost"]["橙色"] == config.FROST_WARNING["橙色"]["ground_temp"]
    assert defaults["haze"]["黄色"] == config.HAZE_WARNING["黄色"]["visibility"]
    assert defaults["thunder"]["hours"] == warn_rules.THUNDER_WINDOW_HOURS


def test_default_types_match_widget_steps():
    defaults = warn_rules.default_custom()
    assert all(isinstance(v, float) for v in defaults["high_temp"].values())
    assert all(isinstance(v, float) for v in defaults["gale"].values())
    assert all(isinstance(v, int) for v in defaults["fog"].values())
    assert all(isinstance(v, float) for v in defaults["rainstorm"].values())
    assert all(isinstance(v, int) for v in defaults["haze"].values())


def test_custom_thresholds_override_defaults():
    custom = {
        "high_temp": {"黄色": 30.0, "橙色": 33.0},
        "gale": {"蓝色": 5.0},
        "fog": {"黄色": 800},
        "thunder": {"hours": 24},
    }
    high = warn_rules.high_temp_levels(custom)
    assert high["黄色"] == 30.0 and high["橙色"] == 33.0
    assert high["红色"] == config.HIGH_TEMP_WARNING["红色"]["temp"]
    assert warn_rules.gale_levels(custom)["蓝色"] == 5.0
    assert warn_rules.fog_levels(custom)["黄色"] == 800
    assert warn_rules.thunder_window_hours(custom) == 24


def test_none_override_is_ignored():
    levels = warn_rules.high_temp_levels({"high_temp": {"黄色": None}})
    assert levels["黄色"] == config.HIGH_TEMP_WARNING["黄色"]["temp"]


def test_daily_rain_levels_are_ordered():
    levels = warn_rules.DAILY_RAIN_LEVELS
    assert levels["大雨"] < levels["黄色"] < levels["橙色"] < levels["红色"]


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
