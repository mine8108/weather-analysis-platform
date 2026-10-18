"""会话状态注册表的完整性与 CI 校验。

注册表是唯一清单：源码里任何字面量会话键或 widget key 必须登记，
否则 research/check_state_registry.py 失败，CI 随之失败。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

from modules import app_state


def test_every_key_has_valid_policy():
    for name, spec in app_state.KEYS.items():
        assert spec["scope"] == "session", name
        assert spec["reset"] in {"keep", "global", "tab"}, (name, spec)
        if spec["reset"] == "tab":
            assert spec["tab"] in app_state.TAB_NAMES, (name, spec["tab"])


def test_prefix_rules_are_prefixed():
    for prefix in app_state.KNOWN_PREFIXES:
        assert prefix.endswith("_"), prefix


def test_registry_does_not_conflict_with_clients():
    assert not (set(app_state.KEYS) & set(app_state.SESSION_CLIENT_KEYS))


def test_logout_keep_is_minimal():
    assert app_state.LOGOUT_KEEP == {"_nav_stack"}


def test_source_literals_are_all_registered():
    import check_state_registry
    assert check_state_registry.main() == 0


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
