"""数据质控回归测试（R-09 接入 / R-16 修复）。

覆盖：
- range_check 对 object（字符串）数值列不再抛 TypeError；
- range_check 百分比以总行数为分母，与评分口径一致；
- temporal_consistency_check 按 station_id 分组，不把不同站点串成一条序列；
- temporal_consistency_check 只在真实 1 小时步长上判突跳；
- completeness_check 与 compute_quality_score 的边界行为。

无 pytest 时可直接运行（`python tests/test_data_quality.py`）。
"""
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import pandas as pd  # noqa: E402

from modules.data_quality import (  # noqa: E402
    completeness_check,
    compute_quality_score,
    range_check,
    temporal_consistency_check,
)


def _hourly(n=48, station="A", start="2026-07-01 00:00"):
    ts = pd.date_range(start, periods=n, freq="1h")
    return pd.DataFrame({
        "timestamp": ts,
        "station_id": station,
        "temperature": [20.0] * n,
        "pressure": [1010.0] * n,
        "humidity": [50.0] * n,
    })


def test_range_check_handles_string_columns():
    """object 类型的数值列不得抛异常（原实现会 TypeError）。"""
    df = _hourly()
    df["temperature"] = df["temperature"].astype(str)
    df.loc[0, "temperature"] = "999"  # 明显越界
    issues = range_check(df)
    assert any(i["field"] == "temperature" for i in issues), "字符串数值列未识别越界"


def test_range_check_percentage_uses_total_rows():
    """百分比分母应为总行数：48 行中 6 行越界 = 12.5%。"""
    df = _hourly(n=48)
    df.loc[:5, "temperature"] = 99.0
    issues = range_check(df)
    temp = [i for i in issues if i["field"] == "temperature"][0]
    assert "12.5%" in temp["detail"], temp["detail"]
    assert temp["count"] == 6


def test_temporal_check_groups_by_station():
    """两站交替行不得被判成突跳（原实现会跨站点比较）。"""
    a = _hourly(n=24, station="A")
    b = _hourly(n=24, station="B")
    b["temperature"] = b["temperature"] + 30.0  # 站间差异 30℃
    merged = pd.concat([a, b], ignore_index=True).sort_values("timestamp")
    issues = temporal_consistency_check(merged)
    assert not [i for i in issues if i["type"] == "数据突跳"], "跨站点误判为突跳"


def test_temporal_check_detects_hourly_spike():
    """同一站点 1 小时内温度跳变 ≥8℃ 应被检出。"""
    df = _hourly(n=24)
    df.loc[10, "temperature"] = 40.0
    issues = temporal_consistency_check(df)
    spikes = [i for i in issues if i["field"] == "temperature"]
    assert spikes, "1 小时内的 20℃ 跳变未被检出"
    assert spikes[0]["count"] >= 1


def test_temporal_check_ignores_non_hourly_steps():
    """3 小时步长数据不应按「1h 变化」规则判突跳。"""
    ts = pd.date_range("2026-07-01 00:00", periods=10, freq="3h")
    df = pd.DataFrame({
        "timestamp": ts,
        "station_id": "A",
        "temperature": [20.0] * 10,
    })
    df.loc[5, "temperature"] = 40.0
    issues = temporal_consistency_check(df)
    assert not [i for i in issues if i["type"] == "数据突跳"], "非逐时数据误判"


def test_temporal_check_flags_unsorted():
    df = _hourly(n=10)
    df = df.iloc[::-1].reset_index(drop=True)
    issues = temporal_consistency_check(df)
    assert any(i["type"] == "时间乱序" for i in issues)


def test_completeness_check_reports_missing():
    df = _hourly(n=10)
    df.loc[:2, "humidity"] = None
    issues = completeness_check(df)
    hum = [i for i in issues if i["field"] == "humidity"][0]
    assert hum["count"] == 3
    # 现状：pct > 30 才判 error，正好 30% 落在 warning 档
    assert hum["severity"] == "warning"

    df.loc[:5, "humidity"] = None
    issues = completeness_check(df)
    hum = [i for i in issues if i["field"] == "humidity"][0]
    assert hum["severity"] == "error"  # 60% 超过 30%


def test_quality_score_bounds():
    df = _hourly(n=10)
    assert compute_quality_score(df, []) == 100.0
    assert compute_quality_score(pd.DataFrame(), []) == 0.0
    issues = [{"type": "数据缺失", "field": "temperature",
               "count": 10, "severity": "error"}]
    assert compute_quality_score(df, issues) < 100.0


def test_empty_and_missing_columns_are_safe():
    empty = pd.DataFrame()
    assert range_check(empty) == []
    assert temporal_consistency_check(empty) == []
    assert completeness_check(empty) == []
    only_ts = pd.DataFrame({"timestamp": pd.date_range("2026-07-01", periods=3, freq="1h")})
    assert range_check(only_ts) == []


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
