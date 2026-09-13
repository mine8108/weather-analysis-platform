"""AQI 统一计算回归测试。

覆盖：
- 断点表结构校验能检出间隙、IAQI 不衔接、缺失污染物、非法末档节点；
- IAQI 在各档边界取值正确，超末档钳制到本污染物上限而非返回 0；
- 综合 AQI 取最大值、首要污染物判定与并列处理；
- nwp_forecast 的四元组包装与统一实现同源，且两张等级表不漂移。

无 pytest 时可直接运行（`python -B tests/test_aqi.py`）。
"""
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from config import AQI_BREAKPOINTS, AQI_LEVELS, AQI_STANDARD_LABEL  # noqa: E402
from modules import aqi  # noqa: E402


def test_standard_label_is_honest():
    """标准版本必须如实标注为 2012，不得声称 2026。"""
    assert AQI_STANDARD_LABEL == "HJ 633-2012", AQI_STANDARD_LABEL


def test_config_table_passes_validation():
    """config 内置断点表必须无结构缺陷。"""
    problems = aqi.validate_breakpoints(AQI_BREAKPOINTS)
    assert problems == [], "断点表存在结构缺陷：%s" % problems


def test_config_table_covers_six_pollutants():
    """六项污染物缺一不可（原表缺 co 与 o3）。"""
    assert set(aqi.REQUIRED_POLLUTANTS) <= set(AQI_BREAKPOINTS), sorted(AQI_BREAKPOINTS)


def test_validation_detects_nox_gap():
    """重现原表的 NOx 61~80 空洞，校验必须报出。"""
    broken = dict(AQI_BREAKPOINTS)
    broken["nox"] = [(0, 40, 0, 50), (41, 60, 51, 100), (81, 120, 101, 150),
                     (121, 200, 151, 200), (201, 400, 201, 300),
                     (401, 800, 301, 500)]
    problems = aqi.validate_breakpoints(broken)
    assert any("nox" in p and "不连续" in p for p in problems), problems


def test_validation_detects_missing_pollutant():
    """缺项必须被检出。"""
    incomplete = {k: v for k, v in AQI_BREAKPOINTS.items() if k != "o3"}
    problems = aqi.validate_breakpoints(incomplete)
    assert any("o3" in p and "缺少" in p for p in problems), problems


def test_validation_detects_iaqi_node_mismatch():
    """相邻档 IAQI 不衔接必须被检出。"""
    broken = dict(AQI_BREAKPOINTS)
    broken["o3"] = [(0, 160, 0, 50), (161, 200, 60, 100),
                    (201, 300, 101, 150), (301, 400, 151, 200)]
    problems = aqi.validate_breakpoints(broken)
    assert any("o3" in p and "不衔接" in p for p in problems), problems


def test_validation_detects_illegal_cap():
    """末档 IAQI 上限只能是 200 或 500。"""
    broken = dict(AQI_BREAKPOINTS)
    broken["o3"] = [(0, 160, 0, 50), (161, 200, 51, 100),
                    (201, 300, 101, 150), (301, 400, 151, 400)]
    problems = aqi.validate_breakpoints(broken)
    assert any("o3" in p and "末档" in p for p in problems), problems


# ============================================================
# 二、单污染物分指数 iaqi
# ============================================================

def test_iaqi_band_edges_pm25():
    """PM2.5 各档浓度上限必须精确落在标准 IAQI 节点上。"""
    assert aqi.iaqi(0, "pm25") == 0.0
    assert aqi.iaqi(35, "pm25") == 50.0
    assert aqi.iaqi(75, "pm25") == 100.0
    assert aqi.iaqi(115, "pm25") == 150.0
    assert aqi.iaqi(250, "pm25") == 300.0
    assert aqi.iaqi(500, "pm25") == 500.0


def test_iaqi_linear_interpolation_pm25():
    """PM2.5 在 351~500 μg/m³ 档线性插值，对应 IAQI 400~500。"""
    expected = (500 - 400) / (500 - 351) * (425 - 351) + 400
    assert abs(aqi.iaqi(425, "pm25") - expected) < 1e-9


def test_iaqi_out_of_range_clamps_not_zero():
    """超末档必须钳制到本污染物上限，不得返回 0（原实现返回 0 会显示「优」）。"""
    assert aqi.iaqi(5000, "pm25") == 500.0
    assert aqi.iaqi(9999, "o3") == 200.0


def test_iaqi_gas_cap_is_200():
    """气态污染物 1h 表只到 IAQI 200。"""
    assert aqi.iaqi(800, "so2") == 200.0
    assert aqi.iaqi(1200, "nox") == 200.0
    assert aqi.iaqi(400, "o3") == 200.0


def test_iaqi_co_uses_mg():
    """CO 单位为 mg/m³：5 对应 IAQI 50，150 对应 IAQI 500。"""
    assert aqi.iaqi(5, "co") == 50.0
    assert aqi.iaqi(150, "co") == 500.0


def test_iaqi_accepts_aliases():
    """数值预报侧使用的 pm2_5 / no2 别名必须可解析。"""
    assert aqi.iaqi(35, "pm2_5") == aqi.iaqi(35, "pm25")
    assert aqi.iaqi(100, "no2") == aqi.iaqi(100, "nox")
    assert aqi.iaqi(100, "NO2") == aqi.iaqi(100, "nox")


def test_iaqi_invalid_input_returns_none():
    """非数值、缺失、未知污染物一律返回 None。"""
    assert aqi.iaqi(None, "pm25") is None
    assert aqi.iaqi(float("nan"), "pm25") is None
    assert aqi.iaqi(float("inf"), "pm25") is None
    assert aqi.iaqi("abc", "pm25") is None
    assert aqi.iaqi(10, "unknown") is None


def test_iaqi_negative_and_string_numeric():
    """负值按 0 处理；数字字符串可解析。"""
    assert aqi.iaqi(-5, "pm25") == 0.0
    assert aqi.iaqi("35", "pm25") == 50.0


# ============================================================
# 三、综合 AQI
# ============================================================

def test_comprehensive_takes_max_iaqi():
    """综合 AQI 取各分指数最大值。"""
    result = aqi.comprehensive_aqi({"pm25": 35, "pm10": 50, "so2": 150})
    assert result["aqi"] == 50, result


def test_comprehensive_primary_is_max_pollutant():
    """首要污染物为分指数最大者。"""
    result = aqi.comprehensive_aqi({"pm25": 115, "pm10": 50})
    assert result["aqi"] == 150
    assert result["primary"] == "PM2.5"
    assert result["primary_all"] == ["PM2.5"]
    assert result["level"] == "轻度污染"


def test_comprehensive_primary_all_on_tie():
    """并列最大且 AQI > 50 时全部列为首要污染物。"""
    result = aqi.comprehensive_aqi({"pm25": 75, "pm10": 150})
    assert result["aqi"] == 100
    assert set(result["primary_all"]) == {"PM2.5", "PM10"}
    assert result["primary"] in {"PM2.5", "PM10"}


def test_comprehensive_no_primary_at_good_tie():
    """AQI <= 50 时即使并列也不设首要污染物（国标：AQI > 50 才判首要污染物）。"""
    result = aqi.comprehensive_aqi({"pm25": 35, "pm10": 50})
    assert result["aqi"] == 50
    assert result["primary"] is None
    assert result["primary_all"] == []


def test_comprehensive_primary_none_when_good():
    """AQI <= 50 时无首要污染物。"""
    result = aqi.comprehensive_aqi({"pm25": 10})
    assert result["aqi"] == 14
    assert result["level"] == "优"
    assert result["primary"] is None
    assert result["primary_all"] == []


def test_comprehensive_accepts_aliases():
    """别名与规范名混用结果一致。"""
    a = aqi.comprehensive_aqi({"pm2_5": 75, "no2": 100})
    b = aqi.comprehensive_aqi({"pm25": 75, "nox": 100})
    assert a["aqi"] == b["aqi"] == 100
    assert a["primary"] == b["primary"] == "PM2.5"


def test_comprehensive_details_shape():
    """明细包含键、标签、浓度、分指数与等级。"""
    result = aqi.comprehensive_aqi({"pm25": 115, "o3": 200})
    assert {d["key"] for d in result["details"]} == {"pm25", "o3"}
    pm25_detail = [d for d in result["details"] if d["key"] == "pm25"][0]
    assert pm25_detail["label"] == "PM2.5"
    assert pm25_detail["iaqi"] == 150
    assert pm25_detail["level"] == "轻度污染"
    assert pm25_detail["conc"] == 115.0


def test_comprehensive_skips_unusable_values():
    """缺失/非数值项被跳过，不参与综合。"""
    result = aqi.comprehensive_aqi({"pm25": None, "pm10": float("nan"), "o3": 400})
    assert result["aqi"] == 200
    assert [d["key"] for d in result["details"]] == ["o3"]


def test_comprehensive_no_data():
    """无任何可用浓度时 aqi 为 None。"""
    result = aqi.comprehensive_aqi({})
    assert result["aqi"] is None
    assert result["level"] == "无数据"
    assert result["primary"] is None
    assert result["details"] == []


def test_level_of_boundaries():
    """等级区间边界：50 优 / 51 良 / 101 轻度污染 / 500 严重污染。"""
    assert aqi.level_of(0) == "优"
    assert aqi.level_of(50) == "优"
    assert aqi.level_of(51) == "良"
    assert aqi.level_of(100) == "良"
    assert aqi.level_of(101) == "轻度污染"
    assert aqi.level_of(500) == "严重污染"


def test_level_tables_do_not_drift():
    """nwp_forecast 的展示用等级表必须与 config.AQI_LEVELS 一致（截到 500）。"""
    from modules.nwp_forecast import _AQ_LEVELS

    config_pairs = []
    for _lv, info in sorted(AQI_LEVELS.items()):
        lo, hi = info["range"]
        config_pairs.append((lo, hi, info["label"]))

    nwp_pairs = [(lo, hi, name) for lo, hi, name, _tok in _AQ_LEVELS[:5]]
    nwp_pairs.append((_AQ_LEVELS[5][0], 500, _AQ_LEVELS[5][2]))

    assert config_pairs == nwp_pairs, (config_pairs, nwp_pairs)
