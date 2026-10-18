"""自定义阈值的会话隔离：两个 AppTest 会话互不影响。

模块级全局会把一个用户的阈值扩散到全部在线会话，这里用两个真实
Streamlit 会话验证 current_thresholds() 读取的是各自的 session_state。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402


def _threshold_page():
    """AppTest 脚本入口，函数体只依赖内部导入。"""
    import streamlit as st
    from modules.analyzer import current_thresholds
    st.text("阈值:%s" % current_thresholds().get("gale", {}).get("蓝色"))


def _run_with(value):
    at = AppTest.from_function(_threshold_page, default_timeout=30)
    at.session_state["_custom_thresholds"] = {"gale": {"蓝色": value}}
    at.run()
    assert not at.exception
    return at.text[0].value


def test_thresholds_are_isolated_between_sessions():
    assert _run_with(99.0) == "阈值:99.0"
    assert _run_with(11.0) == "阈值:11.0"


def test_thresholds_do_not_leak_into_module_global():
    from modules import analyzer
    saved = dict(analyzer.CUSTOM_THRESHOLDS)
    try:
        _run_with(99.0)
        assert analyzer.CUSTOM_THRESHOLDS == saved
    finally:
        analyzer.set_custom_thresholds(saved)
