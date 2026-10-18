"""会话重置的作用域契约：保留客户端与登录态，阻断自动载入。

本文件只测纯逻辑，不需要 Streamlit 运行时。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import app_state


class _Client:
    """替身：只要对象身份不变，就说明客户端没有被删掉。"""


def test_reset_keeps_clients_and_login():
    client = _Client()
    admin = _Client()
    state = {
        "_sb_client": client,
        "_sb_admin_client": admin,
        "auth_user": {"id": "u1"},
        "auth_error": "旧错误",
        "admin_unlocked": True,
        "df": object(),
        "warnings_list": [1],
        "active_tab": 4,
    }
    removed = app_state.reset_session(state, keep_prefixes=("auth_", "admin_"))
    assert state["_sb_client"] is client
    assert state["_sb_admin_client"] is admin
    assert state["auth_user"] == {"id": "u1"}
    assert state["auth_error"] == "旧错误"
    assert state["admin_unlocked"] is True
    assert "df" not in state and "warnings_list" not in state
    assert state["active_tab"] == 0
    assert state["import_step"] == 0
    assert state["import_method"] is None
    assert set(removed) == {"df", "warnings_list"}


def test_reset_blocks_auto_load():
    state = {"_auto_load_done": False, "df": object()}
    app_state.reset_session(state)
    assert state[app_state.AUTO_LOAD_KEY] is True


def test_reset_keeps_nav_stack_object():
    stack = [2, 1]
    state = {"_nav_stack": stack}
    app_state.reset_session(state)
    assert state["_nav_stack"] is stack


def test_reset_on_empty_state_is_safe():
    assert app_state.reset_session({}) == []


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
