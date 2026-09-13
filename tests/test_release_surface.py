"""发布面契约测试：版本号、依赖声明、Secrets 模板、CI 门禁、标准标注、旧文件清理。

这些是「容易漂移但不该漂移」的声明类事实，集中锁定。测试按批次 5 的四个任务
分批加入，本文件最终覆盖全部四项。

无 pytest 时可直接运行（`python -B tests/test_release_surface.py`）。
"""
import importlib.util
import io
import os
import re
import subprocess
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
    assert APP_VERSION == "2.3.2", APP_VERSION


def test_live_artifacts_carry_current_version():
    """CI 步骤名与 Secrets 模板里曾写着旧发布号 2.4.0。

    这类漂移此前逃过了全仓扫描，因为 ripgrep 默认跳过 `.github/`、`.streamlit/`
    这类隐藏目录。规则收窄为：这两个「活」文件里出现的任何 x.y.z 版本串都必须
    等于 APP_VERSION。README 的 v2.3.0 属历史案例叙述，不在此列，故不纳入。
    """
    import re
    from config import APP_VERSION
    pattern = re.compile(r"\b\d+\.\d+\.\d+\b")
    for rel in (".github/workflows/tests.yml", ".streamlit/secrets.toml.example"):
        found = set(pattern.findall(_read(rel)))
        assert found <= {APP_VERSION}, (rel, sorted(found), APP_VERSION)


def test_readme_state_counts_match_repo():
    """README 逐文件声明了用例条数，曾把本文件写成 12 条（实为 14）。

    只锁「README 里带 `N 条` 的文件级计数」，不锁 pytest 总数——总数受参数化
    影响，与 `def test_*` 个数不等，硬锁会变成误报源。
    """
    import re
    readme = _read("README.md")
    hits = re.findall(r"(test_\w+\.py)\s*#[^\n]*?(\d+)\s*条", readme)
    assert hits, "README 未找到任何逐文件用例条数声明"
    for name, claimed in hits:
        path = os.path.join(_APP_DIR, "tests", name)
        assert os.path.isfile(path), name
        with io.open(path, encoding="utf-8") as handle:
            actual = len(re.findall(r"^def test_\w+", handle.read(), re.M))
        assert int(claimed) == actual, (name, claimed, actual)


def test_readme_pytest_total_matches_collection():
    """README 声称了 pytest 总数（曾写 350，实际 352，现已 355）。

    总数受参数化展开影响，无法由 `def test_*` 个数推出，只能真实收集一次。
    无 pytest 的环境直接跳过——本文件设计上要能脱离 pytest 直跑。
    """
    if importlib.util.find_spec("pytest") is None:
        return
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "tests", "-q", "--collect-only"],
        cwd=_APP_DIR, capture_output=True,
    )
    text = (proc.stdout or b"").decode("utf-8", "replace")
    match = re.search(r"(\d+) tests? collected", text)
    assert match, text[-800:]
    claimed = re.search(r"当前共 \*\*(\d+)\*\* 项", _read("README.md"))
    assert claimed, "README 未声明 pytest 总数"
    assert int(claimed.group(1)) == int(match.group(1)), \
        "README 声称 %s 项，实际收集 %s 项" % (claimed.group(1), match.group(1))


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


# ============================================================
# 三、旧文件清理
# ============================================================

def test_legacy_html_removed():
    """根目录旧手册 HTML 已被 docs/用户使用手册.md 取代。

    注意：manual.py 里的 ``file_name="用户使用手册.html"`` 是**导出文件名**，
    不是对仓库内文件的引用，不受本断言约束。
    """
    assert not os.path.exists(os.path.join(_APP_DIR, "用户使用手册.html"))


def test_manual_module_does_not_read_legacy_html():
    text = _read("modules/manual.py")
    assert "MANUAL_PATH" in text
    assert "用户使用手册.md" in text


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
