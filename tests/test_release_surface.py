"""发布面契约测试：版本号、依赖声明、Secrets 模板、CI 门禁、标准标注、旧文件清理。

这些是「容易漂移但不该漂移」的声明类事实，集中锁定。测试按批次 5 的四个任务
分批加入，本文件最终覆盖全部四项。

无 pytest 时可直接运行（`python -B tests/test_release_surface.py`）。
"""
import io
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)


def _read(rel):
    with io.open(os.path.join(_APP_DIR, rel), encoding="utf-8") as handle:
        return handle.read()


# ============================================================
# 一、版本、依赖、Secrets 模板、CI
# ============================================================

def test_version_bumped():
    from config import APP_VERSION
    assert APP_VERSION == "2.4.0", APP_VERSION


def test_requirements_declare_image_and_markdown_deps():
    """Pillow 与 markdown-it-py 此前只是 streamlit 的传递依赖，现须显式声明。"""
    text = _read("requirements.txt")
    assert "Pillow" in text
    assert "markdown-it-py" in text


def test_secrets_example_lists_vision_keys():
    text = _read(".streamlit/secrets.toml.example")
    for key in ("LLM_VISION_MODEL", "LLM_VISION_API_KEY", "LLM_VISION_BASE_URL"):
        assert key in text, key
    assert "回落到 LLM_MODEL" in text or "回落到 `LLM_MODEL`" in text


def test_ci_runs_all_gate_scripts():
    text = _read(".github/workflows/tests.yml")
    for script in ("test_analyzer.py", "test_data_quality.py",
                   "test_auth_session.py", "test_codec.py",
                   "test_aqi.py", "test_era5_guide.py", "test_manual.py",
                   "test_chart_reader.py"):
        assert script in text, script


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {name}")
                traceback.print_exc()
            else:
                print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} failures)")
    sys.exit(1 if failed else 0)
