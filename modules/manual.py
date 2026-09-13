"""用户使用手册：加载、章节解析、应用内渲染与独立 HTML 导出。

手册的唯一真相源是 ``docs/用户使用手册.md``（14 章，``## N. 标题`` 格式）。
本模块现场渲染与导出，不维护第二份文档，避免两份内容漂移。

设计取舍：应用内章节导航使用 selectbox 而非页内 ``#anchor`` 跳转——
Streamlit 为标题生成的 id 依版本变化，跨版本会静默失效；而导出 HTML 的锚点
由本模块自己写入，因此导出件内的目录链接在任何浏览器里都可用。
"""

import html as _html
import io
import os
import re
from datetime import datetime

import streamlit as st

from config import APP_VERSION

MANUAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "用户使用手册.md",
)

# 章标题：`## 3. 界面总览`（数字与标题之间允许任意空白）
CHAPTER_RE = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.M)

_CSS = """
:root{--accent:#1f6feb;--accent-dark:#123a6b;--ink:#2c3e50;--muted:#6b7c93;
  --bg:#f5f7fa;--card:#ffffff;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.8;
  font-family:"Microsoft YaHei","PingFang SC","Source Han Sans SC",sans-serif;}
.hero{background:linear-gradient(135deg,#1f6feb 0%,#2980b9 100%);
  color:#fff;padding:48px 24px;text-align:center;}
.hero h1{margin:0 0 8px;font-size:30px;}
.hero p{margin:0;font-size:16px;opacity:.92;}
.hero .version{display:inline-block;margin-top:14px;padding:4px 16px;font-size:13px;
  background:rgba(255,255,255,.2);border-radius:20px;}
.container{max-width:920px;margin:0 auto;padding:0 24px 80px;}
.toc{background:var(--card);border-radius:10px;padding:20px 24px;margin:24px 0;
  box-shadow:0 2px 8px rgba(0,0,0,.06);}
.toc h2{margin:0 0 12px;font-size:18px;color:var(--accent-dark);}
.toc ol{margin:0;padding-left:22px;}
.toc li{margin:4px 0;}
.toc a{color:var(--accent);text-decoration:none;}
.toc a:hover{text-decoration:underline;}
.chapter{background:var(--card);border-radius:10px;padding:24px 28px;margin:20px 0;
  box-shadow:0 2px 8px rgba(0,0,0,.06);}
.chapter h2{margin:0 0 14px;padding-bottom:8px;font-size:22px;color:var(--accent-dark);
  border-bottom:2px solid var(--accent);}
h3{font-size:17px;color:var(--accent);margin:22px 0 10px;}
p{margin:10px 0;}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px;}
th,td{border:1px solid #dbe3ec;padding:8px 10px;text-align:left;vertical-align:top;}
th{background:#eef4fb;}
code{background:#f0f3f5;padding:2px 6px;border-radius:4px;color:#b4293b;
  font-family:Consolas,"Courier New",monospace;font-size:13px;}
pre{background:#2c3e50;color:#ecf0f1;padding:14px 18px;border-radius:8px;
  overflow-x:auto;font-size:13px;line-height:1.6;}
pre code{background:none;color:inherit;padding:0;}
blockquote{margin:14px 0;padding:10px 16px;background:#eef4fb;
  border-left:4px solid var(--accent);}
ul,ol{padding-left:24px;}
.footer{text-align:center;color:var(--muted);font-size:13px;padding:24px 0;}
"""


def load_manual_markdown():
    """读取手册 Markdown。文件缺失或读取失败时返回空串，由调用方提示。"""
    try:
        with io.open(MANUAL_PATH, "r", encoding="utf-8") as handle:
            return handle.read()
    except (IOError, OSError):
        return ""


def parse_chapters(md_text):
    """按 `## N. 标题` 切分为章节列表。

    返回 [{"index", "title", "anchor", "body_md"}, ...]，按出现顺序排列。
    编号不连续、重复或缺失都不抛异常：文档的小错不该让整页不可用。
    """
    text = md_text or ""
    matches = list(CHAPTER_RE.finditer(text))
    chapters = []
    for pos, match in enumerate(matches):
        start = match.end()
        end = matches[pos + 1].start() if pos + 1 < len(matches) else len(text)
        index = int(match.group(1))
        chapters.append({
            "index": index,
            "title": match.group(2).strip(),
            "anchor": "ch-%d" % index,
            "body_md": text[start:end].strip(),
        })
    return chapters


def _preamble(md_text):
    """第一个章标题之前的导言部分。"""
    match = CHAPTER_RE.search(md_text or "")
    return (md_text or "")[:match.start()].strip() if match else (md_text or "").strip()


def _renderer():
    """Markdown → HTML 渲染器。

    html=False 是刻意设置：commonmark 预设默认允许原始 HTML 透传，
    手册正文里的裸标签会原样进入导出文件。关掉它，正文中的 HTML 一律转义。
    """
    from markdown_it import MarkdownIt
    return MarkdownIt("commonmark", {"html": False}).enable("table")


def build_manual_html(md_text):
    """把手册 Markdown 渲染为可独立分发的 HTML（含内嵌样式与目录）。"""
    md = _renderer()
    chapters = parse_chapters(md_text)
    parts = []
    toc_items = []
    for chapter in chapters:
        toc_items.append('<li><a href="#%s">%d. %s</a></li>'
                         % (chapter["anchor"], chapter["index"],
                            _html.escape(chapter["title"])))
        parts.append(
            '<section class="chapter"><h2 id="%s">%d. %s</h2>%s</section>'
            % (chapter["anchor"], chapter["index"],
               _html.escape(chapter["title"]),
               md.render(chapter["body_md"]))
        )

    head_bits = []
    pre = _preamble(md_text)
    if pre:
        head_bits.append('<div class="chapter">%s</div>' % md.render(pre))
    if toc_items:
        head_bits.append('<nav class="toc"><h2>目录</h2><ol>%s</ol></nav>'
                         % "".join(toc_items))
    body = "".join(head_bits) + "".join(parts)
    if not chapters:
        body = '<div class="chapter">%s</div>' % md.render(md_text or "")

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        "<title>气象数据交互分析平台 · 用户使用手册</title>\n"
        "<style>%s</style>\n</head>\n<body>\n"
        '<div class="hero"><h1>气象数据交互分析平台</h1>'
        "<p>用户使用手册</p>"
        '<span class="version">版本 %s　·　导出于 %s</span></div>\n'
        '<div class="container">%s'
        '<div class="footer">本手册由平台从 docs/用户使用手册.md 现场生成，'
        "与页面内手册同源。</div></div>\n</body>\n</html>\n"
        % (_CSS, _html.escape(str(APP_VERSION)),
           datetime.now().strftime("%Y-%m-%d %H:%M"), body)
    )
    return html.encode("utf-8")


def render_sidebar_entry():
    """侧边栏手册入口按钮。"""
    if st.button("📖 用户使用手册", key="manual_open_btn", use_container_width=True,
                 help="打开详细使用手册：14 章，含 ERA5 下载全流程与常见问题"):
        st.session_state["_manual_open"] = True
        st.rerun()


def render_manual_page():
    """主区手册页。调用方在渲染后应立即 st.stop()。"""
    md_text = load_manual_markdown()

    top_left, top_right = st.columns([1, 2])
    with top_left:
        if st.button("← 返回应用", key="manual_back", use_container_width=True):
            st.session_state["_manual_open"] = False
            st.rerun()
    with top_right:
        if md_text.strip():
            st.download_button(
                "[下载] 用户使用手册 (HTML)",
                data=build_manual_html(md_text),
                file_name="用户使用手册.html",
                mime="text/html",
                use_container_width=True,
                key="manual_download",
            )

    st.markdown("## 📖 用户使用手册")

    if not md_text.strip():
        st.error("手册文件缺失或为空：`docs/用户使用手册.md`。"
                 "请确认仓库完整，或联系维护者。")
        return

    chapters = parse_chapters(md_text)
    if not chapters:
        st.warning("手册未解析出任何章节，请检查标题格式是否为 `## N. 标题`。"
                   "以下为原文渲染：")
        st.markdown(md_text)
        return

    indices = [chapter["index"] for chapter in chapters]
    if indices != list(range(1, len(chapters) + 1)):
        st.warning("手册章节编号不连续（实际：%s），请检查文档格式。" % indices)

    options = ["全部"] + ["%d. %s" % (c["index"], c["title"]) for c in chapters]
    picked = st.selectbox("章节导航", options, key="manual_chapter_pick",
                          help="选择单章可减少滚动；「全部」按顺序完整展示")
    show = chapters if picked == "全部" else [chapters[options.index(picked) - 1]]

    for chapter in show:
        st.markdown("### %d. %s" % (chapter["index"], chapter["title"]))
        st.markdown(chapter["body_md"])
        st.divider()
