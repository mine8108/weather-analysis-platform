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
