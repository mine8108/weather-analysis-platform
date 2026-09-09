"""报文解码回归测试（R-15 修复后新增）。

覆盖 SYNOP 与 METAR 两个解码器：
- SYNOP 报文头顺序（YYGGiw → IIiii）、Nddff 风组、iw 单位换算、符号规则、天气码来源；
- METAR 风组（含 VRB / 阵风）、能见度、云组、温度露点、气压组；
- 空报文与非法文本不抛异常。

无 pytest 时可直接运行（`python tests/test_codec.py`）。
"""
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from modules.codec import decode_metar, decode_synop  # noqa: E402


# ============================================================
# SYNOP
# ============================================================
def test_synop_standard_report():
    """标准 SYNOP：区站号、风组、云量、气温、露点、气压、降水全部解析。"""
    report = "AAXX 29181 03969 12960 02703 10156 20103 30123 40145 60001"
    result, errors = decode_synop(report)

    assert errors == [], f"不应有解析错误：{errors}"
    assert result["station_id"] == "03969", "修复 R-15：区站号应取 IIiii 组"
    assert result["timestamp"] is not None and result["timestamp"].hour == 18
    assert result["wind_direction"] == 270, "dd=27 → 270°"
    assert result["wind_speed"] == 3.0, "iw=1 时 ff 为 m/s"
    assert result["cloud_cover"] == 0, "Nddff 的 N 为总云量"
    assert result["temperature"] == 15.6
    assert result["dewpoint"] == 10.3
    assert result["pressure"] == 1012.3
    assert result["precipitation"] == 0


def test_synop_wind_in_knots():
    """iw=4 时风速单位为节，需换算为 m/s。"""
    report = "AAXX 29184 03969 12960 02715 10156"
    result, errors = decode_synop(report)

    assert errors == []
    assert result["wind_direction"] == 270
    assert result["wind_speed"] == 7.7, "15 节 ≈ 7.7 m/s（保留一位小数）"


def test_synop_negative_temperature_and_dewpoint():
    """s=1 表示负号（原实现把 0~4 都当正号）。"""
    report = "AAXX 29181 03969 12960 02703 11044 21055 30123"
    result, errors = decode_synop(report)

    assert errors == []
    assert result["temperature"] == -4.4, result["temperature"]
    assert result["dewpoint"] == -5.5, result["dewpoint"]


def test_synop_weather_code_comes_from_7wwWW():
    """天气现象码取自 7wwWW 组（原实现误用 iRixhVV 的 R+ix）。"""
    report = "AAXX 29181 03969 12960 02703 10156 20103 30123 40145 60001 79500"
    result, errors = decode_synop(report)

    assert errors == []
    assert result["weather_code"] == 95, result.get("weather_code")


def test_synop_visibility_vv_zero():
    """VV=0 表示能见度 <0.1 km。"""
    report = "AAXX 29181 03969 12960 02703 10156"
    result, _ = decode_synop(report)
    assert result["visibility"] == 0.05, result.get("visibility")


def test_synop_missing_date_group_does_not_raise():
    """缺日期组时不再抛 UnboundLocalError。"""
    result, errors = decode_synop("AAXX 03969 12960 02703")
    assert isinstance(result, dict)
    assert isinstance(errors, list)


def test_synop_empty_and_garbage_are_safe():
    result, errors = decode_synop("")
    assert errors == ["报文为空"]

    result, errors = decode_synop("这不是一条报文")
    assert isinstance(result, dict)
    assert isinstance(errors, list)


# ============================================================
# METAR
# ============================================================
def test_metar_standard_report():
    report = "METAR ZBAA 011200Z 27015KT 9999 FEW030 25/12 Q1013"
    result, errors = decode_metar(report)

    assert errors == [], f"不应有解析错误：{errors}"
    assert result["station_id"] == "ZBAA"
    assert result["timestamp"].hour == 12 and result["timestamp"].minute == 0
    assert result["wind_direction"] == 270
    assert abs(result["wind_speed"] - 15 * 0.5144) < 0.01, result["wind_speed"]
    assert result["visibility"] == 9.999
    assert result["cloud_cover"] == 2, "FEW → 2 成"
    assert result["temperature"] == 25
    assert result["dewpoint"] == 12
    assert result["pressure"] == 1013


def test_metar_negative_temperature():
    result, errors = decode_metar("METAR ZBAA 011200Z 27005KT 9999 M05/M10 Q1013")
    assert errors == []
    assert result["temperature"] == -5
    assert result["dewpoint"] == -10


def test_metar_variable_wind():
    result, _ = decode_metar("METAR ZBAA 011200Z VRB03KT 9999 20/10 Q1013")
    assert result["wind_direction"] is None, "VRB 风向不定"
    assert abs(result["wind_speed"] - 3 * 0.5144) < 0.01


def test_metar_gust_uses_mean_speed():
    result, _ = decode_metar("METAR ZBAA 011200Z 27015G25KT 9999 20/10 Q1013")
    assert abs(result["wind_speed"] - 15 * 0.5144) < 0.01, result["wind_speed"]


def test_metar_empty_is_safe():
    result, errors = decode_metar("")
    assert errors == ["报文为空"]

    result, errors = decode_metar("METAR ZZZZ")
    assert isinstance(result, dict) and isinstance(errors, list)


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {name}")
                traceback.print_exc()
            else:
                print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} failures)")
    sys.exit(1 if failed else 0)
