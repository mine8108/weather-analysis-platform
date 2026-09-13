"""用户使用手册回归测试。

分两部分：
- 解析器与 HTML 生成：用合成夹具，不依赖真实手册内容；
- 内容契约：校验 docs/用户使用手册.md 的章节结构、事实锚点与禁用词。

无 pytest 时可直接运行（`python -B tests/test_manual.py`）。
"""
import io
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

FIXTURE = """# 手册

导言段落。

## 1. 第一章

正文一。

### 1.1 小节

小节正文。

| 列 A | 列 B |
|---|---|
| 1 | 2 |

## 2. 第二章

正文二。
"""


# ============================================================
# 一、解析器与 HTML 生成（合成夹具）
# ============================================================

def test_parse_chapters_extracts_index_title_body():
    from modules.manual import parse_chapters
    chapters = parse_chapters(FIXTURE)
    assert [c["index"] for c in chapters] == [1, 2]
    assert [c["title"] for c in chapters] == ["第一章", "第二章"]
    assert "正文一" in chapters[0]["body_md"]
    assert "1.1 小节" in chapters[0]["body_md"]
    assert chapters[0]["anchor"] == "ch-1"


def test_parse_chapters_tolerates_gaps_without_raising():
    """编号不连续只返回实际章节，不抛异常（文档小错不应让整页不可用）。"""
    from modules.manual import parse_chapters
    text = "## 1. 甲\n\nA\n\n## 3. 丙\n\nC\n"
    chapters = parse_chapters(text)
    assert [c["index"] for c in chapters] == [1, 3]


def test_parse_chapters_ignores_h3_headings():
    from modules.manual import parse_chapters
    text = "## 1. 甲\n\n### 1.1 子节\n\nA\n"
    chapters = parse_chapters(text)
    assert len(chapters) == 1
    assert "### 1.1 子节" in chapters[0]["body_md"]


def test_parse_chapters_empty_text_returns_empty_list():
    from modules.manual import parse_chapters
    assert parse_chapters("") == []
    assert parse_chapters("# 只有一级标题\n") == []


def test_build_manual_html_embeds_anchors_and_toc():
    from modules.manual import build_manual_html
    text = build_manual_html(FIXTURE).decode("utf-8")
    assert "<!DOCTYPE html>" in text
    assert 'id="ch-1"' in text and 'id="ch-2"' in text
    assert 'href="#ch-1"' in text and 'href="#ch-2"' in text
    assert "第一章" in text
    assert "<style>" in text


def test_build_manual_html_renders_tables():
    from modules.manual import build_manual_html
    text = build_manual_html(FIXTURE).decode("utf-8")
    assert "<table>" in text
    assert "<th>" in text


def test_build_manual_html_reports_version():
    from config import APP_VERSION
    from modules.manual import build_manual_html
    text = build_manual_html(FIXTURE).decode("utf-8")
    assert APP_VERSION in text


def test_build_manual_html_escapes_html_in_content():
    """正文里的裸 HTML 必须被转义，避免导出文件被注入。"""
    from modules.manual import build_manual_html
    text = build_manual_html("## 1. 甲\n\n<script>alert(1)</script>\n").decode("utf-8")
    assert "<script>alert(1)</script>" not in text


def test_build_manual_html_is_utf8_bytes():
    from modules.manual import build_manual_html
    raw = build_manual_html(FIXTURE)
    assert isinstance(raw, bytes)
    assert "手册" in raw.decode("utf-8")


def test_load_manual_markdown_returns_empty_when_missing():
    """文件缺失时返回空串而不是抛异常，由页面负责提示。"""
    from modules import manual
    original = manual.MANUAL_PATH
    try:
        manual.MANUAL_PATH = os.path.join(_APP_DIR, "docs", "__not_exist__.md")
        assert manual.load_manual_markdown() == ""
    finally:
        manual.MANUAL_PATH = original


# ============================================================
# 二、app.py 接线
# ============================================================

def _app_source():
    with io.open(os.path.join(_APP_DIR, "app.py"), encoding="utf-8") as handle:
        return handle.read()


def test_app_wires_manual_entry_and_interception():
    """app.py 必须提供侧边栏入口并在主区之前拦截手册页。"""
    source = _app_source()
    assert "render_sidebar_entry" in source
    assert "_manual_open" in source
    assert "render_manual_page" in source
    # 拦截必须发生在 Tab 导航之前，否则手册页会与 Tab 内容叠加
    assert source.index("render_manual_page") < source.index("tab_labels = [")


def test_app_manual_interception_stops_script():
    """拦截分支必须 st.stop()，否则手册页之后仍会渲染 Tab。"""
    source = _app_source()
    idx = source.index("render_manual_page")
    window = source[idx:idx + 400]
    assert "st.stop()" in window, window


def test_app_manual_entry_is_in_sidebar_block():
    """手册入口按钮必须渲染在 st.sidebar 上下文内。"""
    source = _app_source()
    sidebar_start = source.index("with st.sidebar:")
    entry_idx = source.index("render_sidebar_entry")
    # 入口位于侧边栏块内：在侧边栏开始之后、主内容区之前的范围内
    main_start = source.index("# 主内容区")
    assert sidebar_start < entry_idx < main_start


# ============================================================
# 三、手册内容契约（针对真实 docs/用户使用手册.md）
# ============================================================

EXPECTED_TITLES = ["这份手册怎么用", "平台能力与边界", "安装与启动", "界面总览",
                   "数据导入与质量控制", "可视化分析怎么读", "数值预报",
                   "AI 读图解析", "报告导出", "报文解码",
                   "ERA5 再分析数据获取", "侧边栏与自定义阈值",
                   "常见问题（FAQ）", "标准引用与术语表"]


def _manual_text():
    from modules.manual import load_manual_markdown
    return load_manual_markdown()


def test_manual_exists_and_is_readable():
    from modules.manual import MANUAL_PATH
    assert os.path.exists(MANUAL_PATH), MANUAL_PATH
    assert len(_manual_text()) > 6000, "手册正文过短，疑似未完成"


def test_manual_has_fourteen_contiguous_chapters():
    from modules.manual import parse_chapters
    chapters = parse_chapters(_manual_text())
    assert [c["index"] for c in chapters] == list(range(1, 15))
    assert [c["title"] for c in chapters] == EXPECTED_TITLES


def test_every_chapter_has_substance():
    from modules.manual import parse_chapters
    for chapter in parse_chapters(_manual_text()):
        assert len(chapter["body_md"].strip()) >= 300, \
            "第 %d 章内容过薄" % chapter["index"]


def test_manual_contains_no_placeholders():
    text = _manual_text()
    for bad in ("TODO", "TBD", "待补", "XXX", "待定"):
        assert bad not in text, bad


def test_manual_has_no_stale_tab_references():
    text = _manual_text()
    for bad in ("再分析数据处理", "气候态"):
        assert bad not in text, bad


def test_manual_states_actual_aqi_standard():
    """AQI 口径必须如实标注为实际所用版本，不得声称 2026。"""
    text = _manual_text()
    assert "HJ 633-2012" in text
    assert "HJ 633-2026" not in text


def test_manual_mentions_current_navigation():
    text = _manual_text()
    for need in ("数据导入", "可视化分析", "数值预报", "AI 读图解析",
                 "报告导出", "报文解码"):
        assert need in text, need


def test_manual_documents_upload_limits_and_terminal_path():
    """第 8 章需写明图片上限，第 11 章需写明手动打开终端与许可接受。"""
    text = _manual_text()
    assert "5 MB" in text
    assert "终端" in text
    assert "许可" in text


def test_manual_html_export_is_self_contained():
    from modules.manual import build_manual_html
    text = build_manual_html(_manual_text()).decode("utf-8")
    assert text.count('id="ch-') >= 14
    assert "<table>" in text
    for title in EXPECTED_TITLES:
        assert title in text, title
