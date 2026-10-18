"""GFS 预报纯计算层的契约。

纯计算层必须能脱离 Streamlit 导入与运行；预警文案的等级串必须是全角罗马
数字；自定义阈值在预报侧同样生效。
"""
import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules import warn_rules  # noqa: E402
from modules.nwp import calc  # noqa: E402


def _forecast(days=3, peak=38.0, precip=0.5, wind=18.0):
    ts = pd.date_range("2026-07-01", periods=days * 24, freq="h")
    return pd.DataFrame({
        "timestamp": ts,
        "temperature": [peak if t.hour == 14 else 30.0 for t in ts],
        "precipitation": [precip] * len(ts),
        "wind_speed": [wind] * len(ts),
        "humidity": [70.0] * len(ts),
        "weather_code": [0] * len(ts),
        "cloud_cover": [40] * len(ts),
        "visibility": [10.0] * len(ts),
        "pressure": [1000] * len(ts),
    })


def test_calc_module_imports_without_streamlit():
    code = ("import sys; sys.path.insert(0, %r); import modules.nwp.calc; "
            "assert 'streamlit' not in sys.modules, 'pure layer pulled in streamlit'; "
            "print('ok')" % ROOT)
    out = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-800:]
    assert "ok" in out.stdout


def test_three_day_hot_streak_does_not_crash():
    """连续 3 天高温会在文案里拼日期；日期对象必须先转字符串。"""
    result = calc._analyze_forecast(_forecast(days=3))
    hot = [w for w in result["warnings"] if w["type"] == "高温"]
    assert hot, result["warnings"]
    assert "连续3天高温" in hot[0]["detail"]


def test_warning_labels_use_full_width_roman_numerals():
    result = calc._analyze_forecast(_forecast())
    assert result["warnings"]
    for warn in result["warnings"]:
        assert warn["level_num"] in {"Ⅰ级", "Ⅱ级", "Ⅲ级", "Ⅳ级"}, warn
        assert warn["level"] in {"红色", "橙色", "黄色", "蓝色"}


def test_custom_thresholds_apply_to_forecast(monkeypatch):
    monkeypatch.setattr(warn_rules, "current_custom", lambda: {
        "high_temp": {"黄色": 45.0, "橙色": 47.0, "红色": 49.0},
    })
    result = calc._analyze_forecast(_forecast(peak=38.0))
    assert not [w for w in result["warnings"] if w["type"] == "高温"]


def test_life_indices_have_seven_entries():
    indices = calc._calc_life_indices(_forecast())
    assert set(indices) == {"clothing", "umbrella", "comfort", "exercise",
                            "uv", "carwash", "drying"}
    for item in indices.values():
        assert {"level", "score", "advice", "color"} <= set(item)


def test_life_indices_accept_injected_current():
    current = {"temperature": 25.0, "humidity": 60.0, "wind_speed": 3.0,
               "precipitation": 0.0, "weather_code": 0}
    indices = calc._calc_life_indices(_forecast(), current=current)
    assert indices["umbrella"]["score"] >= 0
    assert indices["comfort"]["level"]


def test_get_now_row_returns_future_row():
    df = _forecast(days=2)
    row = calc._get_now_row(df)
    assert row is not None
    assert "temperature" in row.index


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
