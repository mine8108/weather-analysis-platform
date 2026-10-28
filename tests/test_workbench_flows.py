"""UI state contracts for the redesigned modules, without external services."""
from datetime import date

from streamlit.testing.v1 import AppTest


def test_all_seven_visualization_modes_keep_the_selected_data_range():
    at = AppTest.from_string('''
import streamlit as st
from tools.workbench_fixtures import forecast_frame
from modules.visualizer import render_visualization_tab
render_visualization_tab(forecast_frame(days=3)[0], "test dataset")
''', default_timeout=60).run()
    assert not at.exception
    at.date_input(key="_filter_date_range_input").set_value((date(2026, 10, 27), date(2026, 10, 27))).run()
    selected = at.session_state["_filter_date_range"]
    for mode in ["综合看板", "风场分析", "要素关系", "统计摘要", "要素分布", "空气质量", "时序双要素"]:
        at.session_state["viz_subtab"] = mode
        at.run()
        assert not at.exception, mode
        assert at.session_state["_filter_date_range"] == selected
        assert any("24 / 72 条记录" in element.value for element in at.markdown)
    at.date_input(key="_filter_date_range_input").set_value((date(2026, 10, 26),)).run()
    assert not at.exception
    assert at.session_state["_filter_date_range"] == selected
    assert any("24 / 72 条记录" in element.value for element in at.markdown)


def test_ai_evidence_selection_and_edited_inputs_keep_frozen_originals():
    at = AppTest.from_string('''
from unittest.mock import patch
import streamlit as st
from tools.workbench_fixtures import image_and_report
from modules.ai_report_model import input_fingerprint
from modules.chart_reader import render_chart_reader_tab
if "chart_reader_result" not in st.session_state:
    images, originals, model = image_and_report()
    st.session_state.update(chart_reader_images=images, chart_reader_report_images=originals,
        chart_reader_result=model, chart_reader_text=model["raw_response"],
        chart_reader_input_fingerprint=input_fingerprint(images), chart_reader_meta={"scope":"fixture", "generated":"2026-10-26 12:00 UTC+8"})
with patch("modules.ai_narrative.resolve_vision_config", lambda: None):
    render_chart_reader_tab()
''', default_timeout=60).run()
    assert not at.exception
    original = at.session_state["chart_reader_report_images"][0]["sha256"]
    response = at.session_state["chart_reader_text"]
    at.button(key="ai_source_E2").click().run()
    assert not at.exception
    assert at.session_state["chart_reader_selected_evidence"] == "E2"
    assert at.session_state["chart_reader_source_image"] == "img_1"
    at.text_area(key="chart_reader_note").set_value("请另外关注图例").run()
    assert not at.exception
    assert any("待解析图片或关注点已改变" in item.value for item in at.info)
    assert at.session_state["chart_reader_report_images"][0]["sha256"] == original
    assert at.session_state["chart_reader_text"] == response
    assert at.button(key="chart_reader_generate").disabled


def test_report_preview_and_download_use_identical_bytes_and_invalidate_on_style_change():
    at = AppTest.from_string('''
from tools.workbench_fixtures import forecast_frame
from modules.reporter import render_export_tab
render_export_tab(forecast_frame(days=3)[0], [], 0, "fixture")
''', default_timeout=60).run()
    assert not at.exception
    first = at.session_state["_report_preview_bytes"]
    at.button(key="gen_report").click().run()
    assert at.session_state["report_data"] == first
    at.radio(key="report_style").set_value("💬 通俗版").run()
    assert not at.exception
    assert "report_data" not in at.session_state
    assert at.session_state["_report_preview_bytes"] != first
    at.button(key="gen_report").click().run()
    assert at.session_state["report_data"] == at.session_state["_report_preview_bytes"]


def test_codec_edited_draft_preserves_result_and_source_snapshot():
    at = AppTest.from_string("from modules.codec import render_codec_tab\nrender_codec_tab()", default_timeout=60).run()
    at.radio(key="codec_type").set_value("METAR (航空气象报告)")
    at.text_area(key="codec_input").set_value("METAR ZBAA 260800Z 18005MPS 9999 SCT030 24/12 Q1018")
    at.button(key="decode_btn").click().run()
    assert not at.exception
    before = at.session_state["codec_snapshot"]["raw"]
    at.text_area(key="codec_input").set_value("METAR ZSSS 260800Z 20003MPS 9999 SCT030 20/12 Q1015").run()
    assert at.session_state["codec_result"]["station_id"] == "ZBAA"
    assert at.session_state["codec_snapshot"]["raw"] == before
    assert any("输入已调整" in item.value for item in at.info)
