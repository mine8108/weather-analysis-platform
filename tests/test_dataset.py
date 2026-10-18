"""数据集契约：列名归一、版本化序列化、云端往返。

关键不变量：
- 归一幂等，`pm2_5` 与 `pm25` 只能存在一个规范列
- 序列化带 schema 版本头，读回后 timestamp 恢复为 datetime
- 历史裸 CSV（无头）按 v1 读入并迁移
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import dataset  # noqa: E402


def _raw():
    return pd.DataFrame({
        "time": ["2026-07-08 14:00", "2026-07-08 15:00"],
        "temperature": [30.0, 31.5],
        "pm2_5": [35.0, 40.0],
        "pressure": ["1000", "999"],
    })


def test_canonicalize_maps_time_and_pm25():
    out = dataset.canonicalize(_raw())
    assert "timestamp" in out.columns
    assert "pm25" in out.columns
    assert "pm2_5" not in out.columns
    assert str(out["timestamp"].dtype).startswith("datetime64")


def test_canonicalize_is_idempotent():
    once = dataset.canonicalize(_raw())
    twice = dataset.canonicalize(once)
    assert list(once.columns) == list(twice.columns)
    assert once.equals(twice)


def test_canonicalize_drops_duplicate_columns_after_rename():
    df = pd.DataFrame({"pm25": [1.0], "pm2_5": [2.0]})
    out = dataset.canonicalize(df)
    assert list(out.columns) == ["pm25"]


def test_prepare_import_carries_metadata():
    ds = dataset.prepare_import(_raw(), source="API 获取", quality_score=88.0)
    assert ds.source == "API 获取"
    assert ds.quality_score == 88.0
    assert ds.n_rows == 2
    assert ds.schema_version == dataset.SCHEMA_VERSION
    assert ds.units["temperature"] == "℃"


def test_round_trip_preserves_dtype_and_version():
    ds = dataset.prepare_import(_raw(), source="测试")
    text = dataset.to_text(ds)
    assert text.startswith(dataset.HEADER_PREFIX)

    loaded = dataset.from_text(text)
    assert loaded.schema_version == dataset.SCHEMA_VERSION
    assert str(loaded.df["timestamp"].dtype).startswith("datetime64")
    assert pd.api.types.is_numeric_dtype(loaded.df["pm25"])
    assert loaded.df["temperature"].tolist() == [30.0, 31.5]


def test_legacy_csv_without_header_migrates():
    legacy = _raw().to_csv(index=False)
    loaded = dataset.from_text(legacy, source="旧数据")
    assert loaded.schema_version == dataset.SCHEMA_VERSION
    assert "timestamp" in loaded.df.columns
    assert "pm25" in loaded.df.columns


def test_future_version_rejected():
    with pytest.raises(ValueError):
        dataset.from_text("%s99\na,b\n1,2\n" % dataset.HEADER_PREFIX)


def test_empty_dataset_round_trip():
    ds = dataset.prepare_import(pd.DataFrame())
    loaded = dataset.from_text(dataset.to_text(ds))
    assert loaded.df.empty
    assert loaded.n_rows == 0


def test_db_round_trip_uses_versioned_text(monkeypatch):
    """db.save_dataset 写入的必须是带版本头的文本，读回后时间列仍是 datetime。"""
    import types
    import db

    captured = {}

    class _Rpc:
        def __init__(self, data):
            self.data = data

        def execute(self):
            return self

    class _Table:
        def select(self, columns):
            return self

        def eq(self, column, value):
            return self

        def execute(self):
            return _Rpc([{"csv_text": captured["p_csv"], "name": "云端数据"}])

    class _Client:
        def rpc(self, name, params):
            captured.update(params)
            return _Rpc({"ok": True})

        def table(self, name):
            return _Table()

    monkeypatch.setattr(db, "_user_id", lambda: "u1")
    monkeypatch.setattr(db, "get_supabase", lambda: _Client())
    monkeypatch.setattr(db, "invalidate_dataset_cache", lambda: None)

    assert db.save_dataset(_raw(), "云端数据") is True
    assert captured["p_csv"].startswith(dataset.HEADER_PREFIX)

    df, name = db.load_dataset("id-1")
    assert name == "云端数据"
    assert "timestamp" in df.columns
    assert str(df["timestamp"].dtype).startswith("datetime64")
    assert "pm25" in df.columns and "pm2_5" not in df.columns


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
