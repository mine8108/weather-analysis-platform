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


def test_gate_scripts_have_standalone_runners():
    """CI 用 `python -B <file>` 直跑；缺 __main__ 运行器会退出 0 却什么都不跑。"""
    for rel in ("tests/test_aqi.py", "tests/test_era5_guide.py",
                "tests/test_manual.py", "tests/test_chart_reader.py",
                "tests/test_release_surface.py", "tests/test_analyzer.py",
                "tests/test_data_quality.py", "tests/test_codec.py",
                "tests/test_auth_session.py"):
        assert "__main__" in _read(rel), rel


# ============================================================
# 二、标准标注与报告技术说明的一致性
# ============================================================

def test_no_unverifiable_standard_years_in_user_facing_text():
    """用户可见文案不得声称无法核实的标准年份。"""
    for rel in ("app.py", "modules/visualizer.py", "modules/analyzer.py",
                "modules/nwp_forecast.py", "modules/reporter.py"):
        text = _read(rel)
        for bad in ("GB 3095-2026", "HJ 633-2026"):
            assert bad not in text, "%s 含 %s" % (rel, bad)


def test_concentration_limit_label_is_honest():
    """浓度达标限值的标准名不得声称无法核实的年份。"""
    from config import LIMIT_STANDARD_LABEL
    assert "2026" not in LIMIT_STANDARD_LABEL
    assert "GB 3095" in LIMIT_STANDARD_LABEL


def test_visualizer_renders_config_labels():
    assert "LIMIT_STANDARD_LABEL" in _read("modules/visualizer.py")


def test_visualizer_wind_rose_states_radius_meaning():
    """两处风玫瑰口径不同（频次 vs 频率%），观测页须显式标注半径含义。"""
    assert "频次" in _read("modules/visualizer.py")


def test_reporter_does_not_reference_missing_constants():
    """报告技术说明不得指向不存在的 config 常量。"""
    assert "WARN_RULES" not in _read("modules/reporter.py")


def test_reporter_algorithm_notes_match_implementation():
    """技术说明里的算法描述必须与实现一致。"""
    text = _read("modules/reporter.py")
    assert "分 5 级" not in text          # 穿衣指数实现为 6 档
    assert "24h 降水概率" not in text      # 带伞依据 72h 累计降水 + 天气码


def test_no_stale_tab_reference_in_docs():
    for rel in ("docs/同类项目核心介绍.md", "README.md"):
        text = _read(rel)
        for bad in ("气候态", "再分析数据处理"):
            assert bad not in text, "%s 含 %s" % (rel, bad)


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
