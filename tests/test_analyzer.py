"""预警检测引擎回归测试（风险清单 R-12）。

覆盖 modules/analyzer.py 的 8 个事件检测函数与 multi_factor_coupling：

    check_high_temperature / check_cold_wave / check_gale / check_fog /
    check_rainstorm / check_frost / check_thunderstorm / check_haze /
    multi_factor_coupling

每个检测函数至少覆盖三类情形：触发、不触发、数据不足或字段缺失时安全返回空列表。
全部数据由 pandas 现场构造（逐时 timestamp + 各要素列），不读文件、不联网。

本机无 pytest，因此本文件同时支持 pytest 收集与直接运行：

    python -B tests\\test_analyzer.py

已知实现偏差（R-14）在本文件中以 `# 已知偏差 R-14：...` 注释固定，断言的是
「当前实际行为」，目的是把问题钉在文档里，而不是让测试变红。

其余在测试过程中确认的实现缺陷以 `# 现状记录（缺陷 D-x）` 注释标注，并汇总在
交付报告的缺陷清单中（附 analyzer.py 行号与复现输入）。源码一行未改。
"""
import os
import re
import sys
from contextlib import contextmanager

# 让本文件既能被 pytest 收集，也能直接 `python tests/test_analyzer.py` 运行
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import numpy as np
import pandas as pd

from config import (
    COLD_WAVE_WARNING,
    FOG_WARNING,
    FROST_WARNING,
    GALE_WARNING,
    HAZE_WARNING,
    HIGH_TEMP_WARNING,
    RAINSTORM_WARNING,
    THUNDER_WARNING,
    WARN_LEVEL_ORDER,
)
from modules import analyzer

# 事件检测函数集合（用于跨函数的一致性测试）
DETECTORS = (
    analyzer.check_high_temperature,
    analyzer.check_cold_wave,
    analyzer.check_gale,
    analyzer.check_fog,
    analyzer.check_rainstorm,
    analyzer.check_frost,
    analyzer.check_thunderstorm,
    analyzer.check_haze,
)

WARNING_KEYS = {"type", "level", "level_num", "detail", "icon"}
COUPLING_KEYS = {"type", "severity", "detail", "icon"}

# 事件类型 → 对应 config 阈值表（用于校验 level / level_num 未与配置漂移）
CONFIG_BY_TYPE = {
    "高温": HIGH_TEMP_WARNING,
    "寒潮": COLD_WAVE_WARNING,
    "大风": GALE_WARNING,
    "大雾": FOG_WARNING,
    "暴雨": RAINSTORM_WARNING,
    "霜冻": FROST_WARNING,
    "雷电": THUNDER_WARNING,
    "霾": HAZE_WARNING,
}


# ============================================================
# 构造与断言辅助（不使用 pytest fixture / 参数化 / monkeypatch）
# ============================================================
def _hours(n, start="2024-07-01 00:00"):
    """n 条逐时 timestamp。"""
    return pd.date_range(start, periods=n, freq="h")


def _frame(n, start="2024-07-01 00:00", **columns):
    """逐时 timestamp + 指定要素列的合成 DataFrame。"""
    data = {"timestamp": _hours(n, start)}
    data.update(columns)
    return pd.DataFrame(data)


def _const(n, value):
    """长度为 n 的常数序列（float）。"""
    return np.full(n, float(value))


@contextmanager
def _custom_thresholds(payload):
    """临时覆盖 analyzer.CUSTOM_THRESHOLDS，退出时恢复，避免测试间全局状态污染。"""
    saved = dict(analyzer.CUSTOM_THRESHOLDS)
    analyzer.set_custom_thresholds(payload)
    try:
        yield
    finally:
        analyzer.set_custom_thresholds(saved)


def _assert_empty(result, label):
    """断言返回结构为 list 且为空。"""
    assert isinstance(result, list), f"{label}: 应返回 list，实际 {type(result).__name__}"
    assert result == [], f"{label}: 应返回空列表，实际 {result!r}"


def _assert_warning_shape(warn, label=""):
    """预警 dict 结构：type/level/level_num/detail/icon，且均为非空字符串。"""
    assert isinstance(warn, dict), f"{label}: 元素应为 dict，实际 {type(warn).__name__}"
    assert set(warn) == WARNING_KEYS, f"{label}: 字段集应为 {sorted(WARNING_KEYS)}，实际 {sorted(warn)}"
    for key, value in warn.items():
        assert isinstance(value, str), f"{label}: 字段 {key} 应为 str，实际 {type(value).__name__}"
        assert value.strip(), f"{label}: 字段 {key} 不应为空串"
    assert warn["level"] in WARN_LEVEL_ORDER, f"{label}: 未知预警等级 {warn['level']!r}"


def _assert_coupling_shape(alert, label=""):
    """耦合告警 dict 结构：type/severity/detail/icon。"""
    assert isinstance(alert, dict), f"{label}: 元素应为 dict，实际 {type(alert).__name__}"
    assert set(alert) == COUPLING_KEYS, f"{label}: 字段集应为 {sorted(COUPLING_KEYS)}，实际 {sorted(alert)}"
    for key, value in alert.items():
        assert isinstance(value, str), f"{label}: 字段 {key} 应为 str，实际 {type(value).__name__}"
        assert value.strip(), f"{label}: 字段 {key} 不应为空串"


def _levels(warnings):
    return [w["level"] for w in warnings]


def _types(warnings):
    return [w["type"] for w in warnings]


# ============================================================
# check_high_temperature
# ============================================================
def test_high_temperature_three_day_yellow_trigger():
    """连续 3 天日最高气温≥35℃ → 黄色/Ⅲ级。"""
    ts = _hours(96)  # 4 个完整日
    temps = np.where((ts.hour >= 12) & (ts.hour <= 15), 36.0, 30.0)
    warnings = analyzer.check_high_temperature(pd.DataFrame({"timestamp": ts, "temperature": temps}))

    assert len(warnings) == 1, f"应只报 1 条高温预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_high_temperature")
    assert warn["type"] == "高温"
    assert warn["level"] == "黄色"
    assert warn["level_num"] == HIGH_TEMP_WARNING["黄色"]["level"] == "Ⅲ级"
    assert "连续 4 天" in warn["detail"]
    assert warn["icon"] == HIGH_TEMP_WARNING["黄色"]["icon"]  # 修复 R-14：图标改读 config


def test_high_temperature_orange_trigger():
    """24h 内最高气温 37~40℃ → 橙色/Ⅱ级。"""
    temps = np.r_[_const(47, 20.0), [38.0]]
    warnings = analyzer.check_high_temperature(_frame(48, temperature=temps))

    assert len(warnings) == 1, f"应只报 1 条高温预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_high_temperature")
    assert warn["level"] == "橙色"
    assert warn["level_num"] == HIGH_TEMP_WARNING["橙色"]["level"] == "Ⅱ级"
    assert "38.0℃" in warn["detail"] and "≥37℃" in warn["detail"]


def test_high_temperature_returns_yellow_and_orange_together():
    """连续 3 天≥35℃ 且 24h 内≥37℃ 时，两条预警同时返回。"""
    ts = _hours(72)
    temps = np.where((ts.hour >= 12) & (ts.hour <= 15), 38.0, 30.0)
    warnings = analyzer.check_high_temperature(pd.DataFrame({"timestamp": ts, "temperature": temps}))

    assert _levels(warnings) == ["黄色", "橙色"], f"实际 {warnings!r}"


def test_high_temperature_red_trigger():
    """修复 R-30：24h 内最高气温≥40℃ → 红色/Ⅰ级（原实现红色分支不可达）。"""
    temps = np.r_[_const(47, 20.0), [41.0]]
    warnings = analyzer.check_high_temperature(_frame(48, temperature=temps))

    assert HIGH_TEMP_WARNING["红色"]["temp"] == 40, "config 中红色阈值为 40℃"
    assert _levels(warnings) == ["红色"], f"41℃ 应报红色，实际 {warnings!r}"
    assert warnings[0]["level_num"] == HIGH_TEMP_WARNING["红色"]["level"] == "Ⅰ级"


def test_high_temperature_no_trigger_below_thresholds():
    """最高 34℃，既不满足 3 天≥35℃ 也不满足 24h≥37℃ → 空列表。"""
    ts = _hours(96)
    temps = np.where((ts.hour >= 12) & (ts.hour <= 15), 34.0, 20.0)
    _assert_empty(
        analyzer.check_high_temperature(pd.DataFrame({"timestamp": ts, "temperature": temps})),
        "check_high_temperature(34℃)",
    )


def test_high_temperature_two_hot_days_is_not_consecutive_three():
    """仅 2 个≥35℃ 的日 → 不触发黄色。"""
    ts = _hours(96)
    temps = np.full(96, 20.0)
    temps[12] = 36.0
    temps[36] = 36.0
    _assert_empty(
        analyzer.check_high_temperature(pd.DataFrame({"timestamp": ts, "temperature": temps})),
        "check_high_temperature(2 个高温日)",
    )


def test_high_temperature_insufficient_data_returns_empty():
    """不足 24 条小时数据 → 空列表。"""
    temps = np.r_[_const(9, 20.0), [41.0]]
    _assert_empty(
        analyzer.check_high_temperature(_frame(10, temperature=temps)),
        "check_high_temperature(10 条)",
    )


def test_high_temperature_missing_temperature_column_returns_empty():
    """缺 temperature 列 → 空列表。"""
    _assert_empty(
        analyzer.check_high_temperature(_frame(48)),
        "check_high_temperature(无 temperature 列)",
    )


def test_high_temperature_all_nan_temperature_returns_empty():
    """temperature 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.check_high_temperature(_frame(48, temperature=[np.nan] * 48)),
        "check_high_temperature(全 NaN)",
    )


def test_high_temperature_without_timestamp_column_still_checks_24h():
    """缺 timestamp 列时跳过「连续 3 天」判据，24h 极值判据仍生效。"""
    temps = np.r_[_const(23, 20.0), [38.0]]
    warnings = analyzer.check_high_temperature(pd.DataFrame({"temperature": temps}))

    assert _levels(warnings) == ["橙色"], f"实际 {warnings!r}"


def test_high_temperature_single_hour_day_counts_as_hot_day_current_behaviour():
    """现状记录（缺陷 D-7）：3 个各含 1 小时 36℃ 的日期即被判为「连续 3 天」。

    日最高值直接取自当日任何一条记录，没有「日样本数」完整性校验。
    """
    ts = _hours(73)  # 覆盖 2024-07-01 ~ 07-04
    temps = np.full(73, 20.0)
    temps[12], temps[36], temps[60] = 36.0, 36.0, 36.0  # 三天各 1 小时
    warnings = analyzer.check_high_temperature(pd.DataFrame({"timestamp": ts, "temperature": temps}))

    assert _levels(warnings) == ["黄色"], f"实际 {warnings!r}"
    assert "连续 3 天" in warnings[0]["detail"]


def test_high_temperature_string_timestamp_is_tolerated():
    """修复 R-32：timestamp 为字符串（CSV 未解析）时不再抛 AttributeError。"""
    ts = _hours(48)
    temps = np.r_[_const(47, 20.0), [38.0]]
    frame = pd.DataFrame({"timestamp": ts.astype(str), "temperature": temps})

    warnings = analyzer.check_high_temperature(frame)  # 不应抛异常
    assert _levels(warnings) == ["橙色"], f"实际 {warnings!r}"


def test_high_temp_yellow_threshold_honours_custom_config():
    """修复 R-14：黄色阈值改读自定义配置后，黄色判据同样受其约束。"""
    ts = _hours(72)
    temps = np.where((ts.hour >= 12) & (ts.hour <= 15), 36.0, 30.0)
    frame = pd.DataFrame({"timestamp": ts, "temperature": temps})

    with _custom_thresholds({"high_temp": {"黄色": 45.0, "橙色": 46.0, "红色": 47.0}}):
        warnings = analyzer.check_high_temperature(frame)

    _assert_empty(warnings, "check_high_temperature(黄色自定义 45℃)")


def test_high_temperature_yellow_icon_matches_config():
    """修复 R-14：黄色图标改读 config，与橙/红分支风格一致。"""
    ts = _hours(72)
    temps = np.where((ts.hour >= 12) & (ts.hour <= 15), 36.0, 30.0)
    warn = analyzer.check_high_temperature(pd.DataFrame({"timestamp": ts, "temperature": temps}))[0]

    assert warn["level"] == "黄色"
    assert warn["icon"] == HIGH_TEMP_WARNING["黄色"]["icon"]


def test_high_temperature_orange_honours_custom_config():
    """橙色/红色分支确实读取自定义阈值（与黄色分支形成对照）。"""
    temps = np.r_[_const(47, 20.0), [41.0]]
    frame = _frame(48, temperature=temps)

    with _custom_thresholds({"high_temp": {"橙色": 45.0, "红色": 47.0}}):
        _assert_empty(analyzer.check_high_temperature(frame), "check_high_temperature(橙色自定义 45℃)")

    assert _levels(analyzer.check_high_temperature(frame)) == ["红色"], "默认阈值下 41℃ 应报红色"


# ============================================================
# check_cold_wave
# ============================================================
def test_cold_wave_blue_trigger_48h_drop():
    """48h 降温≥8℃ 且最低气温≤4℃ → 蓝色/Ⅳ级。"""
    temps = np.r_[_const(24, 13.0), _const(24, 8.0), _const(24, 4.0)]
    warnings = analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00", temperature=temps))

    assert len(warnings) == 1, f"应只报 1 条寒潮预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_cold_wave")
    assert warn["type"] == "寒潮"
    assert warn["level"] == "蓝色"
    assert warn["level_num"] == COLD_WAVE_WARNING["蓝色"]["level"] == "Ⅳ级"
    assert "降温 9.0℃" in warn["detail"] and "最低气温 4.0℃" in warn["detail"]


def test_cold_wave_yellow_trigger_24h_drop():
    """24h 降温≥10℃ 且最低气温≤4℃，同时 48h 降温不足 8℃ → 黄色/Ⅲ级。"""
    temps = np.r_[_const(24, -5.0), _const(24, 5.0), _const(24, -6.0)]
    warnings = analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00", temperature=temps))

    assert len(warnings) == 1, f"应只报 1 条寒潮预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_cold_wave")
    assert warn["level"] == "黄色"
    assert warn["level_num"] == COLD_WAVE_WARNING["黄色"]["level"] == "Ⅲ级"
    assert "降温 11.0℃" in warn["detail"]


def test_cold_wave_highest_level_wins():
    """修复 R-31：等级从高到低判定，降温 30℃、最低 -10℃ 报红色。"""
    temps = np.r_[_const(48, 20.0), _const(24, -10.0)]
    warnings = analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00", temperature=temps))

    assert COLD_WAVE_WARNING["红色"]["temp_drop"] == 16, "config 中红色降温阈值为 16℃"
    assert _levels(warnings) == ["红色"], f"实际 {warnings!r}"


def test_cold_wave_no_trigger():
    """无降温（恒温 20℃）→ 空列表。"""
    _assert_empty(
        analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00", temperature=_const(72, 20.0))),
        "check_cold_wave(恒温)",
    )


def test_cold_wave_warming_returns_empty():
    """升温 15℃ → 空列表。"""
    temps = np.r_[_const(48, 0.0), _const(24, 15.0)]
    _assert_empty(
        analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00", temperature=temps)),
        "check_cold_wave(升温)",
    )


def test_cold_wave_insufficient_data_returns_empty():
    """不足 48 条数据 → 空列表。"""
    temps = np.r_[_const(11, 20.0), _const(9, -10.0)]
    _assert_empty(
        analyzer.check_cold_wave(_frame(20, "2024-01-01 00:00", temperature=temps)),
        "check_cold_wave(20 条)",
    )


def test_cold_wave_exactly_48_rows_skips_blue_branch():
    """修复 R-34：恰好 48 条时 48h 口径的蓝色判据跳过，24h 口径正常判定。"""
    temps = np.r_[_const(24, 20.0), _const(24, -10.0)]
    warnings = analyzer.check_cold_wave(_frame(48, "2024-01-01 00:00", temperature=temps))

    assert _levels(warnings) == ["红色"], f"实际 {warnings!r}"


def test_cold_wave_missing_temperature_column_returns_empty():
    """缺 temperature 列 → 空列表。"""
    _assert_empty(
        analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00")),
        "check_cold_wave(无 temperature 列)",
    )


def test_cold_wave_all_nan_returns_empty():
    """temperature 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.check_cold_wave(_frame(72, "2024-01-01 00:00", temperature=[np.nan] * 72)),
        "check_cold_wave(全 NaN)",
    )


def test_cold_wave_custom_threshold_suppresses_blue():
    """寒潮自定义阈值生效（形如 {"cold_wave": {"蓝色": {"temp_drop": ...}}}）。"""
    temps = np.r_[_const(24, 13.0), _const(24, 8.0), _const(24, 4.0)]
    frame = _frame(72, "2024-01-01 00:00", temperature=temps)

    with _custom_thresholds({"cold_wave": {"蓝色": {"temp_drop": 100.0}}}):
        _assert_empty(analyzer.check_cold_wave(frame), "check_cold_wave(自定义蓝色 100℃)")

    assert _levels(analyzer.check_cold_wave(frame)) == ["蓝色"], "默认阈值下应报蓝色"


# ============================================================
# check_gale
# ============================================================
def test_gale_blue_trigger():
    """24h 内最大风速≥10.8 m/s → 蓝色/Ⅳ级，detail 含蒲福风级。"""
    warnings = analyzer.check_gale(_frame(24, wind_speed=_const(24, 11.0)))

    assert len(warnings) == 1, f"应只报 1 条大风预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_gale")
    assert warn["type"] == "大风"
    assert warn["level"] == "蓝色"
    assert warn["level_num"] == GALE_WARNING["蓝色"]["level"] == "Ⅳ级"
    assert "强风，6级" in warn["detail"] and "≥10.8 m/s" in warn["detail"]


def test_gale_yellow_trigger():
    """风速 18 m/s → 黄色/Ⅲ级。"""
    warnings = analyzer.check_gale(_frame(24, wind_speed=_const(24, 18.0)))

    assert _levels(warnings) == ["黄色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == GALE_WARNING["黄色"]["level"] == "Ⅲ级"


def test_gale_red_trigger_highest_level_wins():
    """风速 33 m/s → 红色/Ⅰ级（该函数按由高到低选择，与寒潮的顺序缺陷形成对照）。"""
    warnings = analyzer.check_gale(_frame(24, wind_speed=_const(24, 33.0)))

    assert _levels(warnings) == ["红色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == GALE_WARNING["红色"]["level"] == "Ⅰ级"


def test_gale_uses_window_max_not_mean_current_behaviour():
    """已知偏差 R-14：大风判据取区间最大值，与 config「平均风力」的措辞不符。

    24h 内仅 1 小时达 11 m/s、其余 5 m/s，窗口均值远低于 10.8 m/s，仍报蓝色。
    """
    wind = np.r_[_const(23, 5.0), [11.0]]
    frame = _frame(24, wind_speed=wind)
    warnings = analyzer.check_gale(frame)

    assert frame["wind_speed"].mean() < GALE_WARNING["蓝色"]["avg_wind"], "前提：窗口均值低于阈值"
    assert _levels(warnings) == ["蓝色"], f"实际 {warnings!r}"
    assert "11.0 m/s" in warnings[0]["detail"], "detail 记录的是窗口极值而非均值"


def test_gale_no_trigger():
    """风速 5 m/s → 空列表。"""
    _assert_empty(
        analyzer.check_gale(_frame(24, wind_speed=_const(24, 5.0))),
        "check_gale(5 m/s)",
    )


def test_gale_insufficient_data_returns_empty():
    """不足 6 条数据 → 空列表。"""
    _assert_empty(
        analyzer.check_gale(_frame(5, wind_speed=_const(5, 33.0))),
        "check_gale(5 条)",
    )


def test_gale_missing_wind_speed_column_returns_empty():
    """缺 wind_speed 列 → 空列表。"""
    _assert_empty(analyzer.check_gale(_frame(24)), "check_gale(无 wind_speed 列)")


def test_gale_all_nan_returns_empty():
    """wind_speed 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.check_gale(_frame(24, wind_speed=[np.nan] * 24)),
        "check_gale(全 NaN)",
    )


def test_gale_custom_threshold_honoured():
    """大风自定义阈值生效（app.py 侧边栏即写入这一形状）。"""
    frame = _frame(24, wind_speed=_const(24, 11.0))

    with _custom_thresholds({"gale": {"蓝色": 20.0}}):
        _assert_empty(analyzer.check_gale(frame), "check_gale(自定义蓝色 20 m/s)")

    assert _levels(analyzer.check_gale(frame)) == ["蓝色"], "默认阈值下应报蓝色"


# ============================================================
# check_fog
# ============================================================
def test_fog_yellow_trigger():
    """能见度 0.4 km（<500 m）→ 黄色/Ⅲ级。"""
    vis = np.r_[_const(23, 10.0), [0.4]]
    warnings = analyzer.check_fog(_frame(24, visibility=vis))

    assert len(warnings) == 1, f"应只报 1 条大雾预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_fog")
    assert warn["type"] == "大雾"
    assert warn["level"] == "黄色"
    assert warn["level_num"] == FOG_WARNING["黄色"]["level"] == "Ⅲ级"
    assert "400 m" in warn["detail"]


def test_fog_orange_trigger():
    """能见度 0.15 km（<200 m）→ 橙色/Ⅱ级。"""
    vis = np.r_[_const(23, 10.0), [0.15]]
    warnings = analyzer.check_fog(_frame(24, visibility=vis))

    assert _levels(warnings) == ["橙色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == FOG_WARNING["橙色"]["level"] == "Ⅱ级"
    assert "150 m" in warnings[0]["detail"]


def test_fog_red_trigger():
    """能见度 0.03 km（<50 m）→ 红色/Ⅰ级。"""
    warnings = analyzer.check_fog(_frame(24, visibility=_const(24, 0.03)))

    assert _levels(warnings) == ["红色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == FOG_WARNING["红色"]["level"] == "Ⅰ级"


def test_fog_no_trigger():
    """能见度 20 km → 空列表。"""
    _assert_empty(
        analyzer.check_fog(_frame(24, visibility=_const(24, 20.0))),
        "check_fog(20 km)",
    )


def test_fog_boundary_equal_to_threshold_is_not_triggered():
    """修复 R-36：能见度恰好等于阈值不再触发，与 config 的「能见度<500m」一致。"""
    warnings = analyzer.check_fog(_frame(24, visibility=_const(24, 0.5)))
    _assert_empty(warnings, "check_fog(能见度恰好 500 m)")

    below = analyzer.check_fog(_frame(24, visibility=_const(24, 0.49)))
    assert _levels(below) == ["黄色"], f"实际 {below!r}"


def test_fog_missing_visibility_column_returns_empty():
    """缺 visibility 列 → 空列表。"""
    _assert_empty(analyzer.check_fog(_frame(24)), "check_fog(无 visibility 列)")


def test_fog_all_nan_visibility_returns_empty():
    """visibility 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.check_fog(_frame(24, visibility=[np.nan] * 24)),
        "check_fog(全 NaN)",
    )


def test_fog_custom_threshold_honoured():
    """大雾自定义阈值生效（单位与 config 一致：米）。"""
    frame = _frame(24, visibility=_const(24, 0.3))

    with _custom_thresholds({"fog": {"黄色": 100}}):
        _assert_empty(analyzer.check_fog(frame), "check_fog(自定义黄色 100 m)")

    assert _levels(analyzer.check_fog(frame)) == ["黄色"], "默认阈值下应报黄色"


# ============================================================
# check_rainstorm
# ============================================================
def test_rainstorm_red_trigger_3h():
    """3h 累计 120 mm → 红色/Ⅰ级。"""
    precip = np.r_[np.zeros(21), _const(3, 40.0)]
    warnings = analyzer.check_rainstorm(_frame(24, precipitation=precip))

    assert len(warnings) == 1, f"应只报 1 条暴雨预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_rainstorm")
    assert warn["type"] == "暴雨"
    assert warn["level"] == "红色"
    assert warn["level_num"] == RAINSTORM_WARNING["红色"]["level"] == "Ⅰ级"
    assert "3h 降雨量 120.0 mm" in warn["detail"]


def test_rainstorm_orange_trigger_3h():
    """3h 累计 60 mm → 橙色/Ⅱ级。"""
    precip = np.r_[np.zeros(21), _const(3, 20.0)]
    warnings = analyzer.check_rainstorm(_frame(24, precipitation=precip))

    assert _levels(warnings) == ["橙色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == RAINSTORM_WARNING["橙色"]["level"] == "Ⅱ级"


def test_rainstorm_yellow_trigger_6h():
    """6h 累计 54 mm 且 3h 不足 50 mm → 黄色/Ⅲ级。"""
    precip = np.r_[np.zeros(18), _const(6, 9.0)]
    warnings = analyzer.check_rainstorm(_frame(24, precipitation=precip))

    assert _levels(warnings) == ["黄色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == RAINSTORM_WARNING["黄色"]["level"] == "Ⅲ级"
    assert "6h 降雨量 54.0 mm" in warnings[0]["detail"]


def test_rainstorm_blue_trigger_12h():
    """12h 累计 60 mm 且 6h/3h 不足 50 mm → 蓝色/Ⅳ级。"""
    precip = np.r_[np.zeros(12), _const(12, 5.0)]
    warnings = analyzer.check_rainstorm(_frame(24, precipitation=precip))

    assert _levels(warnings) == ["蓝色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == RAINSTORM_WARNING["蓝色"]["level"] == "Ⅳ级"


def test_rainstorm_no_trigger_light_rain():
    """小雨（12h 累计 12 mm）→ 空列表。"""
    precip = np.r_[np.zeros(12), _const(12, 1.0)]
    _assert_empty(
        analyzer.check_rainstorm(_frame(24, precipitation=precip)),
        "check_rainstorm(小雨)",
    )


def test_rainstorm_all_zero_precipitation_returns_empty():
    """降水全为 0 → 空列表（提前返回）。"""
    _assert_empty(
        analyzer.check_rainstorm(_frame(24, precipitation=np.zeros(24))),
        "check_rainstorm(全 0)",
    )


def test_rainstorm_missing_precipitation_column_returns_empty():
    """缺 precipitation 列 → 空列表。"""
    _assert_empty(analyzer.check_rainstorm(_frame(24)), "check_rainstorm(无 precipitation 列)")


def test_rainstorm_honours_custom_thresholds():
    """修复 R-14：暴雨阈值改读 config 与自定义配置。"""
    precip = np.r_[np.zeros(21), _const(3, 40.0)]
    frame = _frame(24, precipitation=precip)

    with _custom_thresholds({"rainstorm": {"红色": 999.0, "橙色": 999.0, "黄色": 999.0, "蓝色": 999.0}}):
        warnings = analyzer.check_rainstorm(frame)

    _assert_empty(warnings, "check_rainstorm(自定义阈值 999 mm)")


def test_rainstorm_short_series_is_rejected():
    """修复 R-37：暴雨检测要求至少 3 条记录（原实现 2 条即报橙色）。"""
    warnings = analyzer.check_rainstorm(pd.DataFrame({"precipitation": [30.0, 30.0]}))
    _assert_empty(warnings, "check_rainstorm(2 条数据)")


# ============================================================
# check_frost
# ============================================================
def test_frost_blue_trigger_zero():
    """最低气温 0℃ → 蓝色/Ⅳ级。"""
    warnings = analyzer.check_frost(_frame(24, temperature=_const(24, 0.0)))

    assert len(warnings) == 1, f"应只报 1 条霜冻预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_frost")
    assert warn["type"] == "霜冻"
    assert warn["level"] == "蓝色"
    assert warn["level_num"] == FROST_WARNING["蓝色"]["level"] == "Ⅳ级"
    assert "0.0℃（≤0℃" in warn["detail"]
    assert "以气温近似地温" in warn["detail"]  # 修复 R-38：把近似口径写进结论


def test_frost_yellow_trigger_minus_three_point_five():
    """最低气温 -3.5℃ → 黄色/Ⅲ级。"""
    warnings = analyzer.check_frost(_frame(24, temperature=_const(24, -3.5)))

    assert _levels(warnings) == ["黄色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == FROST_WARNING["黄色"]["level"] == "Ⅲ级"


def test_frost_orange_trigger_minus_six():
    """最低气温 -6℃ → 橙色/Ⅱ级。"""
    warnings = analyzer.check_frost(_frame(24, temperature=_const(24, -6.0)))

    assert _levels(warnings) == ["橙色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == FROST_WARNING["橙色"]["level"] == "Ⅱ级"


def test_frost_no_trigger_above_zero():
    """最低气温 5℃ → 空列表。"""
    _assert_empty(
        analyzer.check_frost(_frame(24, temperature=_const(24, 5.0))),
        "check_frost(5℃)",
    )


def test_frost_missing_temperature_column_returns_empty():
    """缺 temperature 列 → 空列表。"""
    _assert_empty(analyzer.check_frost(_frame(24)), "check_frost(无 temperature 列)")


def test_frost_all_nan_returns_empty():
    """temperature 全为 NaN → 空列表（min 为 NaN，各分支均不成立）。"""
    _assert_empty(
        analyzer.check_frost(_frame(24, temperature=[np.nan] * 24)),
        "check_frost(全 NaN)",
    )


def test_frost_honours_custom_thresholds():
    """修复 R-14：霜冻阈值改读 config 与自定义配置。"""
    frame = _frame(24, temperature=_const(24, -6.0))

    with _custom_thresholds({"frost": {"橙色": -50.0, "黄色": -50.0, "蓝色": -50.0}}):
        warnings = analyzer.check_frost(frame)

    _assert_empty(warnings, "check_frost(自定义阈值 -50℃)")


def test_frost_uses_air_temperature_as_ground_proxy_current_behaviour():
    """现状记录（缺陷 D-10）：用气温近似地温，而 config 的判据写的是「地面最低温度」。

    analyzer.py:234 docstring 已自认「用气温近似地温」，detail 文案也写「最低气温」，
    与 FROST_WARNING 的 condition 措辞不一致。
    """
    warnings = analyzer.check_frost(_frame(24, temperature=_const(24, -6.0)))

    assert "最低气温" in warnings[0]["detail"]
    assert "地面最低温度" in FROST_WARNING["橙色"]["condition"]


# ============================================================
# check_thunderstorm
# ============================================================
def test_thunderstorm_yellow_trigger_code_95():
    """天气码 95（雷暴）→ 黄色/Ⅲ级。"""
    warnings = analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [0, 0, 0, 0, 0, 95]}))

    assert len(warnings) == 1, f"应只报 1 条雷电预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_thunderstorm")
    assert warn["type"] == "雷电"
    assert warn["level"] == "黄色"
    assert warn["level_num"] == "Ⅲ级"
    assert "95-99" in warn["detail"]


def test_thunderstorm_always_yellow():
    """天气码 95/96/97/99 均判黄色/Ⅲ级（WMO 码无法区分国标橙/红预报口径）。

    修复 R-14：等级与图标改读 THUNDER_WARNING，不再硬编码。
    """
    assert set(THUNDER_WARNING) == {"黄色", "橙色", "红色"}, "config 定义了三级雷电预警"

    for code in (95, 96, 97, 99):
        warnings = analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [0, 0, code]}))
        assert _levels(warnings) == ["黄色"], f"天气码 {code} 实际 {warnings!r}"
        assert warnings[0]["level_num"] == THUNDER_WARNING["黄色"]["level"]
        assert warnings[0]["icon"] == THUNDER_WARNING["黄色"]["icon"]


def test_thunderstorm_no_trigger_without_thunder_code():
    """非雷暴天气码 → 空列表。"""
    _assert_empty(
        analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [0, 1, 2, 3, 61, 80]})),
        "check_thunderstorm(无雷暴码)",
    )


def test_thunderstorm_missing_weather_code_returns_empty():
    """缺 weather_code 列 → 空列表。"""
    _assert_empty(analyzer.check_thunderstorm(_frame(24)), "check_thunderstorm(无 weather_code 列)")


def test_thunderstorm_only_last_six_records_considered_current_behaviour():
    """现状记录（缺陷 D-11）：只检查最后 6 条记录的天气码。

    analyzer.py:267 用 tail(6) 实现「6h 内」，但按记录条数而非时间差截取，
    采样间隔非 1 小时时该窗口的时间含义会失真；8 条数据中的早期雷暴码被忽略。
    """
    _assert_empty(
        analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [95, 0, 0, 0, 0, 0, 0, 0]})),
        "check_thunderstorm(雷暴码落在窗口之外)",
    )
    assert _levels(analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [0, 0, 0, 0, 0, 0, 0, 95]}))) == ["黄色"]


def test_thunderstorm_window_honours_custom_config():
    """R-14 补齐：雷电检测窗口可通过侧边栏自定义阈值调整。"""
    ts = pd.date_range("2026-07-01 00:00", periods=12, freq="1h")
    frame = pd.DataFrame({"timestamp": ts, "weather_code": [95] + [0] * 11})

    _assert_empty(analyzer.check_thunderstorm(frame), "check_thunderstorm(默认 6h 窗口)")
    with _custom_thresholds({"thunder": {"hours": 24}}):
        assert _levels(analyzer.check_thunderstorm(frame)) == ["黄色"]


def test_thunderstorm_single_record_is_rejected():
    """修复 R-37：雷电检测要求最小样本长度（≥3 条），1 条记录不再报警。"""
    _assert_empty(
        analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [95]})),
        "check_thunderstorm(1 条记录)",
    )
    assert _levels(
        analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [0, 0, 95]}))
    ) == ["黄色"]


def test_thunderstorm_all_nan_returns_empty():
    """weather_code 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.check_thunderstorm(pd.DataFrame({"weather_code": [np.nan] * 6})),
        "check_thunderstorm(全 NaN)",
    )


# ============================================================
# check_haze
# ============================================================
def test_haze_orange_trigger():
    """能见度 1.5 km（<2000 m）→ 橙色/Ⅱ级。"""
    vis = np.r_[_const(23, 10.0), [1.5]]
    warnings = analyzer.check_haze(_frame(24, visibility=vis))

    assert len(warnings) == 1, f"应只报 1 条霾预警，实际 {warnings!r}"
    warn = warnings[0]
    _assert_warning_shape(warn, "check_haze")
    assert warn["type"] == "霾"
    assert warn["level"] == "橙色"
    assert warn["level_num"] == HAZE_WARNING["橙色"]["level"] == "Ⅱ级"
    assert "1500 m" in warn["detail"]


def test_haze_yellow_trigger():
    """能见度 2.5 km（<3000 m 且 ≥2000 m）→ 黄色/Ⅲ级。"""
    vis = np.r_[_const(23, 10.0), [2.5]]
    warnings = analyzer.check_haze(_frame(24, visibility=vis))

    assert _levels(warnings) == ["黄色"], f"实际 {warnings!r}"
    assert warnings[0]["level_num"] == HAZE_WARNING["黄色"]["level"] == "Ⅲ级"


def test_haze_no_trigger():
    """能见度 20 km → 空列表。"""
    _assert_empty(analyzer.check_haze(_frame(24, visibility=_const(24, 20.0))), "check_haze(20 km)")


def test_haze_boundary_values_current_behaviour():
    """边界记录：2000 m 归入黄色（严格小于才升级），3000 m 不触发（严格小于才触发）。"""
    assert _levels(analyzer.check_haze(_frame(24, visibility=_const(24, 2.0)))) == ["黄色"]
    _assert_empty(analyzer.check_haze(_frame(24, visibility=_const(24, 3.0))), "check_haze(3000 m)")


def test_haze_missing_visibility_column_returns_empty():
    """缺 visibility 列 → 空列表。"""
    _assert_empty(analyzer.check_haze(_frame(24)), "check_haze(无 visibility 列)")


def test_haze_all_nan_visibility_returns_empty():
    """visibility 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.check_haze(_frame(24, visibility=[np.nan] * 24)),
        "check_haze(全 NaN)",
    )


def test_haze_honours_custom_thresholds():
    """修复 R-14：霾阈值改读 config 与自定义配置。"""
    frame = _frame(24, visibility=_const(24, 1.5))

    with _custom_thresholds({"haze": {"橙色": 100.0, "黄色": 200.0}}):
        warnings = analyzer.check_haze(frame)

    _assert_empty(warnings, "check_haze(自定义阈值 100/200 m)")


def test_haze_and_fog_are_mutually_exclusive():
    """修复 R-33：能见度低于大雾黄色阈值时只报大雾，不再同时报霾。"""
    frame = _frame(24, visibility=_const(24, 0.3))

    assert _levels(analyzer.check_fog(frame)) == ["黄色"]
    _assert_empty(analyzer.check_haze(frame), "check_haze(0.3 km，应归大雾)")


# ============================================================
# multi_factor_coupling
# ============================================================
def test_multi_factor_coupling_heat_stress_trigger():
    """均温≥35℃ 且 均湿≥60% → 热应激（耦合）/危险。"""
    frame = _frame(24, temperature=_const(24, 36.0), humidity=_const(24, 70.0))
    alerts = analyzer.multi_factor_coupling(frame)

    assert len(alerts) == 1, f"应只报 1 条耦合告警，实际 {alerts!r}"
    alert = alerts[0]
    _assert_coupling_shape(alert, "multi_factor_coupling")
    assert alert["type"] == "热应激（耦合）"
    assert alert["severity"] == "危险"
    assert "36.0℃" in alert["detail"] and "70%" in alert["detail"]


def test_multi_factor_coupling_heat_index_uses_celsius_output():
    """修复 R-29：热指数按 °F 回归式计算再换算回 ℃，与参考值一致。"""
    frame = _frame(24, temperature=_const(24, 36.0), humidity=_const(24, 70.0))
    detail = analyzer.multi_factor_coupling(frame)[0]["detail"]
    engine_hi = float(re.search(r"热指数\s*(-?[\d.]+)", detail).group(1))

    def rothfusz(t_f, rh):
        return (-42.379 + 2.04901523 * t_f + 10.14333127 * rh
                - 0.22475541 * t_f * rh - 6.83783e-3 * t_f ** 2
                - 5.481717e-2 * rh ** 2 + 1.22874e-3 * t_f ** 2 * rh
                + 8.5282e-4 * t_f * rh ** 2 - 1.99e-6 * t_f ** 2 * rh ** 2)

    reference_c = (rothfusz(36.0 * 9 / 5 + 32, 70.0) - 32) * 5 / 9

    assert abs(engine_hi - reference_c) < 0.1, f"实现 {engine_hi}℃ 应等于参考值 {reference_c:.1f}℃"
    assert 40 < engine_hi < 60, f"36℃/70% 的热指数应在 40~60℃，实际 {engine_hi}℃"


def test_multi_factor_coupling_heat_stress_no_trigger():
    """均温 34℃ 或 均湿 50%，任一不达标 → 空列表。"""
    _assert_empty(
        analyzer.multi_factor_coupling(_frame(24, temperature=_const(24, 34.0), humidity=_const(24, 70.0))),
        "multi_factor_coupling(34℃/70%)",
    )
    _assert_empty(
        analyzer.multi_factor_coupling(_frame(24, temperature=_const(24, 36.0), humidity=_const(24, 50.0))),
        "multi_factor_coupling(36℃/50%)",
    )


def test_multi_factor_coupling_pressure_drop_trigger():
    """6h 气压下降≥3 hPa 且 均湿≥70% → 降水可能性（耦合）/注意。"""
    pressure = np.r_[_const(23, 1010.0), [1005.0]]
    frame = _frame(24, temperature=_const(24, 20.0), humidity=_const(24, 75.0), pressure=pressure)
    alerts = analyzer.multi_factor_coupling(frame)

    assert len(alerts) == 1, f"实际 {alerts!r}"
    _assert_coupling_shape(alerts[0], "multi_factor_coupling")
    assert alerts[0]["type"] == "降水可能性（耦合）"
    assert alerts[0]["severity"] == "注意"
    assert "气压骤降 5.0 hPa" in alerts[0]["detail"]


def test_multi_factor_coupling_small_pressure_drop_no_trigger():
    """6h 气压仅降 2 hPa → 空列表。"""
    pressure = np.r_[_const(23, 1010.0), [1008.0]]
    _assert_empty(
        analyzer.multi_factor_coupling(
            _frame(24, temperature=_const(24, 20.0), humidity=_const(24, 75.0), pressure=pressure)
        ),
        "multi_factor_coupling(气压降 2 hPa)",
    )


def test_multi_factor_coupling_wind_chill_trigger():
    """均温≤0℃ 且 平均风速≥10.8 m/s → 风寒效应（耦合）/注意。"""
    frame = _frame(
        24,
        temperature=_const(24, -5.0),
        humidity=_const(24, 60.0),
        wind_speed=_const(24, 12.0),
    )
    alerts = analyzer.multi_factor_coupling(frame)

    assert len(alerts) == 1, f"实际 {alerts!r}"
    assert alerts[0]["type"] == "风寒效应（耦合）"
    assert alerts[0]["severity"] == "注意"
    assert "-5.0℃" in alerts[0]["detail"] and "12.0 m/s" in alerts[0]["detail"]


def test_multi_factor_coupling_wind_chill_no_trigger():
    """低温但风速 5 m/s → 空列表。"""
    _assert_empty(
        analyzer.multi_factor_coupling(
            _frame(24, temperature=_const(24, -5.0), humidity=_const(24, 60.0), wind_speed=_const(24, 5.0))
        ),
        "multi_factor_coupling(低温小风)",
    )


def test_multi_factor_coupling_multiple_alerts():
    """气压骤降 + 低温大风同时成立 → 返回两条耦合告警，顺序与代码分支一致。"""
    pressure = np.r_[_const(23, 1010.0), [1005.0]]
    frame = _frame(
        24,
        temperature=_const(24, -5.0),
        humidity=_const(24, 75.0),
        pressure=pressure,
        wind_speed=_const(24, 12.0),
    )
    alerts = analyzer.multi_factor_coupling(frame)

    assert [a["type"] for a in alerts] == ["降水可能性（耦合）", "风寒效应（耦合）"], f"实际 {alerts!r}"
    for alert in alerts:
        _assert_coupling_shape(alert, "multi_factor_coupling")


def test_multi_factor_coupling_missing_required_columns_returns_empty():
    """缺 temperature 或 humidity 列 → 空列表。"""
    _assert_empty(
        analyzer.multi_factor_coupling(_frame(24, temperature=_const(24, 36.0))),
        "multi_factor_coupling(无 humidity)",
    )
    _assert_empty(
        analyzer.multi_factor_coupling(_frame(24, humidity=_const(24, 80.0))),
        "multi_factor_coupling(无 temperature)",
    )


def test_multi_factor_coupling_insufficient_data_returns_empty():
    """不足 6 条有效记录 → 空列表。"""
    _assert_empty(
        analyzer.multi_factor_coupling(_frame(5, temperature=_const(5, 36.0), humidity=_const(5, 80.0))),
        "multi_factor_coupling(5 条)",
    )


def test_multi_factor_coupling_empty_frame_returns_empty():
    """空 DataFrame → 空列表。"""
    _assert_empty(analyzer.multi_factor_coupling(pd.DataFrame()), "multi_factor_coupling(空表)")


def test_multi_factor_coupling_all_nan_returns_empty():
    """temperature / humidity 全为 NaN → 空列表。"""
    _assert_empty(
        analyzer.multi_factor_coupling(_frame(24, temperature=[np.nan] * 24, humidity=[np.nan] * 24)),
        "multi_factor_coupling(全 NaN)",
    )


# ============================================================
# 跨函数一致性
# ============================================================
def test_all_detectors_return_empty_on_empty_frame():
    """完全空的 DataFrame → 所有检测函数安全返回空列表。"""
    empty = pd.DataFrame()
    for detector in DETECTORS:
        _assert_empty(detector(empty), f"{detector.__name__}(空表)")


def test_all_detectors_return_empty_when_only_timestamp_present():
    """只有 timestamp 列（其余要素缺失）→ 所有检测函数安全返回空列表。"""
    frame = _frame(72)
    for detector in DETECTORS:
        _assert_empty(detector(frame), f"{detector.__name__}(仅 timestamp)")


def test_detectors_do_not_mutate_input_frame():
    """检测函数不得就地修改传入的 DataFrame。"""
    ts = _hours(72)
    frame = pd.DataFrame({
        "timestamp": ts,
        "temperature": np.where((ts.hour >= 12) & (ts.hour <= 15), 38.0, 30.0),
        "humidity": _const(72, 75.0),
        "pressure": _const(72, 1010.0),
        "wind_speed": _const(72, 12.0),
        "visibility": _const(72, 0.4),
        "precipitation": np.r_[np.zeros(69), _const(3, 40.0)],
        "weather_code": _const(72, 95),
    })
    before = frame.copy()

    for detector in DETECTORS:
        detector(frame)
    analyzer.multi_factor_coupling(frame)

    assert list(frame.columns) == list(before.columns), "列集合被修改"
    assert frame.equals(before), "输入 DataFrame 被就地修改"


def test_warning_schema_is_stable():
    """所有触发出来的预警 dict 结构与等级取值稳定。"""
    seen = []
    for frame in _sample_frames():
        for detector in DETECTORS:
            for warn in detector(frame):
                _assert_warning_shape(warn, detector.__name__)
                seen.append(warn)
    assert seen, "合成数据应至少触发一条预警，否则该用例失去意义"


def test_warning_level_num_matches_config():
    """每条预警的 level_num 必须与 config 对应等级表的 level 一致（防配置漂移）。"""
    seen = []
    for frame in _sample_frames():
        for detector in DETECTORS:
            for warn in detector(frame):
                table = CONFIG_BY_TYPE[warn["type"]]
                assert warn["level"] in table, f"{warn['type']} 等级 {warn['level']} 不在 config 中"
                assert warn["level_num"] == table[warn["level"]]["level"], (
                    f"{warn['type']}{warn['level']}: level_num={warn['level_num']} "
                    f"与 config={table[warn['level']]['level']} 不一致"
                )
                seen.append(warn)
    assert seen, "合成数据应至少触发一条预警"


def _sample_frames():
    """用于跨函数一致性检查的若干合成数据集。"""
    n = 48
    hot = pd.DataFrame({
        "timestamp": _hours(n),
        "temperature": _const(n, 41.0),
        "wind_speed": _const(n, 33.0),
        "visibility": _const(n, 0.03),
        "precipitation": np.r_[np.zeros(n - 3), _const(3, 40.0)],
        "weather_code": _const(n, 95),
        "humidity": _const(n, 80.0),
        "pressure": _const(n, 1000.0),
    })
    cold = pd.DataFrame({
        "timestamp": _hours(n, "2024-01-01 00:00"),
        "temperature": _const(n, -6.0),
        "humidity": _const(n, 60.0),
        "wind_speed": _const(n, 12.0),
    })
    cold_wave = pd.DataFrame({
        "timestamp": _hours(72, "2024-01-01 00:00"),
        "temperature": np.r_[_const(24, 13.0), _const(24, 8.0), _const(24, 4.0)],
    })
    return [hot, cold, cold_wave]


# ============================================================
# 无 pytest 时的入口
# ============================================================
if __name__ == "__main__":
    import traceback

    failed = 0
    cases = [(name, fn) for name, fn in list(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name, fn in cases:
        try:
            fn()
        except Exception:
            failed += 1
            print(f"[FAIL] {name}")
            traceback.print_exc()
        else:
            print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({len(cases)} 个用例，{failed} 个失败)")
    sys.exit(1 if failed else 0)
