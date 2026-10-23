"""手动录入合并的幂等性契约。

旧流程每次渲染导入向导都会把手动记录重新并进 df，用户返回上一步再前进
就会看到重复行。merge_manual_rows 必须可重复调用且结果不变。
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.data_loader import merge_manual_rows


def _manual(temp=30.0):
    return pd.DataFrame([{"timestamp": "2026-07-08 14:00",
                          "temperature": temp,
                          "station_id": "ST01"}])


def test_merge_is_idempotent():
    once = merge_manual_rows(None, _manual())
    twice = merge_manual_rows(once, _manual())
    assert len(once) == 1
    assert len(twice) == 1


def test_merge_keeps_latest_value():
    existing = pd.DataFrame([{"timestamp": "2026-07-08 14:00",
                              "temperature": 28.0, "station_id": "ST01"}])
    merged = merge_manual_rows(existing, _manual(30.0))
    assert len(merged) == 1
    assert float(merged.iloc[0]["temperature"]) == 30.0


def test_merge_keeps_different_stations():
    existing = pd.DataFrame([{"timestamp": "2026-07-08 14:00",
                              "temperature": 28.0, "station_id": "ST02"}])
    merged = merge_manual_rows(existing, _manual())
    assert len(merged) == 2


def test_merge_without_timestamp_dedupes_whole_row():
    manual = pd.DataFrame([{"temperature": 30.0}])
    assert len(merge_manual_rows(manual, manual)) == 1


def test_merge_sorts_by_timestamp():
    late = pd.DataFrame([{"timestamp": "2026-07-08 15:00", "station_id": "ST01"}])
    early = pd.DataFrame([{"timestamp": "2026-07-08 14:00", "station_id": "ST01"}])
    merged = merge_manual_rows(late, early)
    assert merged.iloc[0]["timestamp"] == pd.Timestamp("2026-07-08 14:00")
    assert merged["timestamp"].is_monotonic_increasing


def test_merge_empty_manual_returns_input():
    existing = pd.DataFrame([{"timestamp": "2026-07-08 14:00"}])
    assert merge_manual_rows(existing, pd.DataFrame()).shape == existing.shape


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
