"""解码结果的会话持久化契约。

解码结果原先只存在于点击分支的局部变量里，任何 rerun 都会丢失，写在
同一分支内的「添加到手动录入区」按钮因此永远渲染不出来，点击事件无法命中。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

SYNOP = "AAXX 29181 03969 12960 02703 10156 20103 30123 40145 60001"


def _codec_page():
    """AppTest 脚本入口。

    from_function 会把函数源码重新 exec 到独立命名空间，函数体里不能直接
    依赖测试模块的 import，因此在脚本内部显式导入。
    """
    from modules.codec import render_codec_tab
    render_codec_tab()


def test_decoded_result_renders_add_button_on_later_run():
    at = AppTest.from_function(_codec_page, default_timeout=30)
    at.session_state["codec_result"] = {"station_id": "03969", "temperature": 15.6}
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("手动录入" in label for label in labels), labels


def test_decode_click_persists_result():
    at = AppTest.from_function(_codec_page, default_timeout=30)
    at.run()
    at.text_area[0].set_value(SYNOP)
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["codec_result"] is not None


def test_add_button_appends_manual_data():
    at = AppTest.from_function(_codec_page, default_timeout=30)
    at.session_state["codec_result"] = {"station_id": "03969", "temperature": 15.6}
    at.run()
    at.button[1].click().run()
    assert not at.exception
    assert at.session_state["manual_data"][-1]["station_id"] == "03969"
