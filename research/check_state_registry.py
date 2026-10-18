"""会话状态注册表校验（CI 门禁用）。

扫描源码里的三类字面量：
1. ``st.session_state["键"]``
2. ``st.session_state.get("键"``
3. ``st.session_state[...] = ...`` 写入点
4. Streamlit widget 的 ``key="键"``

与 ``modules/app_state.py`` 的 KEYS / PREFIX_RULES 对账。未登记的字面量一律
失败，动态键（f-string）由 PREFIX_RULES 覆盖。

用法：``python -B research/check_state_registry.py``
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", ".git", "tests", "research", ".venv", ".pytest_cache"}

# widget key= 只认这些调用
WIDGET_CALLS = {
    "button", "form_submit_button", "download_button", "checkbox", "radio",
    "selectbox", "multiselect", "text_input", "text_area", "number_input",
    "date_input", "time_input", "slider", "file_uploader", "color_picker",
    "toggle", "camera_input", "data_editor", "pills", "segmented_control",
}

SESSION_RE = re.compile(
    r"session_state(?:\[[\"']([^\"']+)[\"']\]|\.get\([\"']([^\"']+)[\"'])")
KEY_RE = re.compile(r"\bkey\s*=\s*[\"']([^\"']+)[\"']")


def iter_py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def literal_keys(path):
    """返回 (session 键集合, widget 键集合)。"""
    text = open(path, encoding="utf-8").read()
    session = set()
    for match in SESSION_RE.finditer(text):
        session.add(match.group(1) or match.group(2))
    widgets = set()
    tree = ast.parse(text, path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in WIDGET_CALLS:
            continue
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant) \
                    and isinstance(keyword.value.value, str):
                widgets.add(keyword.value.value)
    return session, widgets


def main():
    sys.path.insert(0, ROOT)
    from modules import app_state

    known = (set(app_state.KEYS) | set(app_state.WIDGET_KEYS)
             | set(app_state.SESSION_CLIENT_KEYS))
    prefixes = tuple(app_state.KNOWN_PREFIXES)
    missing = []
    for path in iter_py_files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        session, widgets = literal_keys(path)
        for key in sorted(session | widgets):
            if key in known or key.startswith(prefixes):
                continue
            missing.append((rel, key, "session" if key in session else "widget"))
    if missing:
        print("[FAIL] 以下会话状态键未在 modules/app_state.py 登记：")
        for rel, key, kind in missing:
            print("  %s  %s  (%s)" % (rel, key, kind))
        return 1
    print("[OK] 会话状态注册表与源码一致（%d 个键，%d 条前缀规则）"
          % (len(known), len(prefixes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
