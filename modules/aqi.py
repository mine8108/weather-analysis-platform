"""环境空气质量指数（AQI）统一计算模块。

口径：HJ 633-2012 分指数表——气态污染物（SO₂/NO₂/CO/O₃）用 1 小时均值表，
颗粒物（PM2.5/PM10）用 24 小时均值表。实际所用标准版本由
``config.AQI_STANDARD_LABEL`` 单一标注，页面与手册如实渲染该常量。

本模块是全项目唯一的 IAQI / 综合 AQI 实现。此前散落在
``analyzer._calc_single_aqi`` 与 ``nwp_forecast._compute_cn_aqi`` 的两套实现已删除。

已知局限：气态污染物分指数按 1 小时表计算。``nwp_forecast.fetch_air_quality``
传入逐时浓度，口径正确；``analyzer.check_air_quality`` 传入时段均值，会高估
气态污染物的分指数。评价时段口径的重新定义不在本次范围内。

本模块不 import streamlit 与 design_tokens：颜色解析是调用方的职责。
"""

from math import isfinite

from config import AQI_BREAKPOINTS, AQI_LEVELS

# 标准 IAQI 节点。每个污染物的节点序列必须是它的前缀，且相邻档首尾相接。
IAQI_NODES = (0, 50, 100, 150, 200, 300, 400, 500)

# 允许的末档节点：气态污染物的 1 小时表仅定义到 200
ALLOWED_IAQI_CAPS = (200, 500)

# 必须提供断点表的污染物
REQUIRED_POLLUTANTS = ("pm25", "pm10", "so2", "nox", "co", "o3")

# 各污染物显示标签
POLLUTANT_LABELS = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "so2": "SO₂",
    "nox": "NO₂",
    "co": "CO",
    "o3": "O₃",
}


def validate_breakpoints(table=None):
    """校验断点表结构，返回缺陷描述列表；空列表表示合法。

    不抛异常：缺陷以返回值交给调用方决定如何处理。
    """
    table = AQI_BREAKPOINTS if table is None else table
    problems = []

    for key in REQUIRED_POLLUTANTS:
        if key not in table:
            problems.append("%s: 缺少该污染物的断点表" % key)

    for key, bands in table.items():
        if not bands:
            problems.append("%s: 断点表为空" % key)
            continue
        prev_hi = None
        prev_iaqi_hi = None
        malformed = False
        for idx, band in enumerate(bands):
            if len(band) != 4:
                problems.append("%s: 第 %d 档不是四元组 %r" % (key, idx, band))
                malformed = True
                break
            lo, hi, i_lo, i_hi = band
            if lo > hi:
                problems.append("%s: 第 %d 档浓度区间倒置 %r" % (key, idx, band))
            if i_lo >= i_hi:
                problems.append("%s: 第 %d 档 IAQI 区间非递增 %r" % (key, idx, band))
            if i_lo not in IAQI_NODES or i_hi not in IAQI_NODES:
                problems.append("%s: 第 %d 档 IAQI 节点不在 %r 内 %r"
                                % (key, idx, IAQI_NODES, band))
            if idx == 0:
                if lo != 0:
                    problems.append("%s: 首档浓度下限必须为 0，实际 %r" % (key, lo))
                if i_lo != 0:
                    problems.append("%s: 首档 IAQI 下限必须为 0，实际 %r" % (key, i_lo))
            else:
                if lo != prev_hi + 1:
                    problems.append("%s: 第 %d 档与上一档不连续（上一档上限 %r，本档下限 %r）"
                                    % (key, idx, prev_hi, lo))
                if i_lo != prev_iaqi_hi:
                    problems.append("%s: 第 %d 档 IAQI 与上一档不衔接（上一档 %r，本档 %r）"
                                    % (key, idx, prev_iaqi_hi, i_lo))
            prev_hi, prev_iaqi_hi = hi, i_hi
        if malformed:
            continue
        if bands[-1][3] not in ALLOWED_IAQI_CAPS:
            problems.append("%s: 末档 IAQI 上限应为 %r 之一，实际 %r"
                            % (key, ALLOWED_IAQI_CAPS, bands[-1][3]))

    return problems


# 别名归一化：数值预报侧使用 pm2_5 / no2 作为列名
POLLUTANT_ALIASES = {
    "pm2_5": "pm25",
    "pm25": "pm25",
    "pm10": "pm10",
    "so2": "so2",
    "no2": "nox",
    "nox": "nox",
    "co": "co",
    "o3": "o3",
}


def normalize_key(raw_key):
    """把别名归一化为规范污染物键；无法识别时返回 None。"""
    if raw_key is None:
        return None
    return POLLUTANT_ALIASES.get(str(raw_key).strip().lower())


def iaqi(conc, pollutant):
    """单污染物分指数。无法计算时返回 None。

    超末档按末档斜率线性外推后钳制到该污染物自身的最大 IAQI 节点
    （颗粒物与 CO 为 500，气态污染物为 200）——**不返回 0**。
    """
    key = normalize_key(pollutant)
    if key is None or key not in AQI_BREAKPOINTS:
        return None
    if conc is None:
        return None
    try:
        value = float(conc)
    except (TypeError, ValueError):
        return None
    if not isfinite(value):
        return None
    if value <= 0:
        return 0.0

    bands = AQI_BREAKPOINTS[key]
    cap = bands[-1][3]
    for lo, hi, i_lo, i_hi in bands:
        if value <= hi:
            # 表若有间隙，把落点收进本档下限（防御性；合法表不会触发）
            point = value if value >= lo else lo
            return (i_hi - i_lo) / (hi - lo) * (point - lo) + i_lo

    lo, hi, i_lo, i_hi = bands[-1]
    extrapolated = (i_hi - i_lo) / (hi - lo) * (value - lo) + i_lo
    return float(min(extrapolated, cap))
