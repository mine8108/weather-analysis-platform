"""Word / CSV 报告导出的行为契约。

批次 4 把 reporter 拆成 base / professional / plain 三个模块，
这里用真实 docx 生成验证拆分后两条报告路径仍可用。
"""
import io
import os
import sys
import zipfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.reporter import export_data_csv, export_report_word  # noqa: E402


def _df():
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-07-01 08:00", periods=6, freq="h"),
        "temperature": [30.0, 31.0, 32.0, 33.0, 34.0, 35.0],
        "humidity": [60, 61, 62, 63, 64, 65],
        "wind_speed": [3.0] * 6,
        "precipitation": [0.0] * 6,
        "pressure": [1000.0] * 6,
    })


WARNINGS = [{
    "type": "高温", "level": "橙色", "level_num": "Ⅱ级",
    "detail": "24h 内最高气温 ≥37℃", "icon": "[火]",
}]


def _document_xml(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def test_csv_export_has_header_and_rows():
    text = export_data_csv(_df()).decode("utf-8-sig")
    assert "temperature" in text
    assert "2026-07-01" in text


def test_professional_report_contains_warning_section():
    blob = export_report_word(_df(), WARNINGS, 85.0, source="测试数据")
    assert blob and blob[:2] == b"PK"
    xml = _document_xml(blob)
    assert "高温" in xml
    assert "Ⅱ级" in xml


def test_plain_report_generates_docx():
    blob = export_report_word(_df(), WARNINGS, 85.0, source="测试数据",
                              plain_language=True)
    assert blob and blob[:2] == b"PK"
    assert len(blob) > 4000


def test_report_without_data_still_returns_docx():
    blob = export_report_word(pd.DataFrame(), [], 0.0, source="")
    assert blob and blob[:2] == b"PK"


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
