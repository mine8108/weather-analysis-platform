"""主题样式资源契约。

批次 4 把 500 行 CSS 从 theme_css.py 外置到 theme_assets/base.css。
这里验证资源可读、变量块结构正确，防止打包时漏文件导致样式整体丢失。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import theme_css  # noqa: E402


def test_base_css_asset_is_loaded():
    assert len(theme_css.BASE_CSS) > 10000
    assert "{" in theme_css.BASE_CSS and "--" in theme_css.BASE_CSS


def test_asset_file_exists_next_to_module():
    from pathlib import Path
    assets = Path(theme_css.__file__).resolve().parent / "theme_assets" / "base.css"
    assert assets.is_file()
    assert assets.read_text(encoding="utf-8").strip()


def test_light_root_vars_include_fallback_selector():
    css = theme_css.root_vars_css(False)
    assert ":root {" in css
    assert 'html[data-dsh-theme="light"]' in css
    assert "--" in css


def test_dark_vars_are_scoped():
    css = theme_css.root_vars_css(True)
    assert css.startswith('html[data-dsh-theme="dark"] {')


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
