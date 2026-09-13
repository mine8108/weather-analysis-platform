"""AI 解读报告层：多模态读图调用 + 报告排版与导出。

职责边界：
- ``resolve_vision_config`` / ``call_vision_llm``：OpenAI 兼容的多模态调用，provider 无关。
- ``parse_sections`` / ``build_report_meta`` / ``_report_html`` / ``_build_docx`` /
  ``display_report``：把模型输出渲染为报告卡片，并导出 .docx（含原图）与 .md。

设计约束：
- 视觉模型密钥走 ``st.secrets``，绝不进代码与前端。
- ``LLM_VISION_MODEL`` 未配置即视为「未配置」，**不回落** ``LLM_MODEL``：默认的
  ``deepseek-chat`` 无视觉能力，回落会造成「配了却一直失败」的隐性故障。
- 调用失败**不做文本降级**：文本模型读不了图，编造摘要等同幻觉。失败由调用方
  展示可读错误并保留原图，本模块只抛异常，不产出替代文本。
"""

import html
import io
import json
from datetime import datetime

import requests
import streamlit as st

DEFAULT_BASE_URL = "https://api.deepseek.com"
VISION_TIMEOUT_SECONDS = 90
# 输出预算。读图要求六段式长回答，且推理型模型的思考过程也从这里扣额度：
# 线上实测 deepseek-flash 对两张真实天气图先写了 2784 字 reasoning_content，
# 原 1600 的上限被思考吃光，正文未开始即结束。可用 LLM_VISION_MAX_TOKENS 覆盖。
VISION_MAX_TOKENS = 4096
_MAX_TOKENS_FLOOR = 256
_MAX_TOKENS_CEILING = 32000

_VISION_SYSTEM_PROMPT = (
    "你是严谨的气象分析助手，只依据用户提供的图像与说明进行判读，"
    "不做无根据的推测，中文输出。"
)


# ============================================================
# 一、视觉模型配置与调用
# ============================================================

def _secret(name, default=""):
    """读取 st.secrets，缺文件时兜底。

    ``st.secrets.get`` 在 secrets 文件完全不存在时会抛
    ``StreamlitSecretNotFoundError``（而不是返回默认值），必须在唯一入口兜住，
    否则未配置密钥的环境会整页崩溃而不是给出配置指引。
    """
    try:
        value = st.secrets.get(name, default)
    except Exception:  # noqa: BLE001 - 缺密钥文件、解析失败等都按未配置处理
        return default
    return default if value is None else value


def resolve_vision_config():
    """解析视觉模型配置。缺少模型名或密钥时返回 None（视为未配置）。

    模型名必须显式配置 ``LLM_VISION_MODEL``；密钥与地址可回落文本模型的值。
    """
    model = str(_secret("LLM_VISION_MODEL") or "").strip()
    if not model:
        return None
    api_key = str(_secret("LLM_VISION_API_KEY")
                  or _secret("LLM_API_KEY") or "").strip()
    if not api_key:
        return None
    base_url = str(_secret("LLM_VISION_BASE_URL")
                   or _secret("LLM_BASE_URL")
                   or DEFAULT_BASE_URL).strip().rstrip("/")
    return {"api_key": api_key, "base_url": base_url, "model": model,
            "max_tokens": _resolve_max_tokens()}


def _resolve_max_tokens():
    """输出预算：可选键 LLM_VISION_MAX_TOKENS，非法或越界一律回落默认值。

    一个可选的调优键不该有能力把读图功能整个弄坏，故此处只接受合法整数。
    """
    raw = str(_secret("LLM_VISION_MAX_TOKENS") or "").strip()
    if not raw:
        return VISION_MAX_TOKENS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return VISION_MAX_TOKENS
    if _MAX_TOKENS_FLOOR <= value <= _MAX_TOKENS_CEILING:
        return value
    return VISION_MAX_TOKENS


# 空正文的处置提示。三种常见原因的处置完全不同，只报「空内容」等于丢掉现场。
_FINISH_HINTS = {
    "length": "输出预算被耗尽（推理型模型的思考过程也从这里扣额度）。"
              "可精简补充说明，或把 LLM_VISION_MAX_TOKENS 调大。",
    "content_filter": "内容被服务商安全策略拦截，请更换图片或模型。",
    "stop": "模型正常结束却没输出正文，最常见的原因是该模型不支持图像输入。",
}


def _extract_message_text(message):
    """取正文，兼容 content 为字符串与分片列表两种形态。

    部分 OpenAI 兼容服务商把 content 返回为
    ``[{"type": "text", "text": ...}, ...]``。只认字符串会把这类正常响应误判为空正文。
    """
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        pieces = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                pieces.append(item["text"])
            elif isinstance(item, str):
                pieces.append(item)
        return "\n".join(piece.strip() for piece in pieces if piece.strip())
    return ""


def _response_snippet(data, limit=300):
    """原始响应片段，把服务商的实际返回带进错误信息，便于直接判因。"""
    try:
        raw = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = str(data)
    return raw if len(raw) <= limit else raw[:limit] + "…"


def _empty_content_reason(choice, message, model, data):
    """空正文的错误文本：finish_reason、模型名、响应片段一并带出。"""
    finish = str(choice.get("finish_reason") or "未提供")
    detail = "finish_reason=%s，model=%s" % (finish, model)
    reasoning = str(message.get("reasoning_content") or "").strip()
    if reasoning:
        detail += "；响应只有 reasoning_content（%d 字），正文为空" % len(reasoning)
    return ("视觉模型返回空正文（%s）。%s响应片段：%s"
            % (detail, _FINISH_HINTS.get(finish, ""), _response_snippet(data)))


def call_vision_llm(prompt, images_b64, api_key, base_url=None, model=None,
                    max_tokens=None):
    """调用多模态模型生成读图解读。失败抛异常，由调用方处理。

    images_b64 为 data URL 列表（``data:image/jpeg;base64,...``）。
    ``max_tokens`` 省略时用模块默认值（4096）。
    """
    if not model:
        raise ValueError("未指定视觉模型（LLM_VISION_MODEL）")
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    content = [{"type": "text", "text": prompt}]
    for data_url in images_b64 or []:
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    resp = requests.post(
        base_url + "/chat/completions",
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0.3,
            "max_tokens": int(max_tokens or VISION_MAX_TOKENS),
        },
        timeout=VISION_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("视觉模型返回结构异常，未取到 choices/message。响应片段：%s"
                         % _response_snippet(data))

    text = _extract_message_text(message)
    if not text:
        raise ValueError(_empty_content_reason(choice, message, model, data))
    return text


# ============================================================
# 二、报告排版与导出
# ============================================================

def parse_sections(text):
    """按 【标题】 切片为 [(title, body), ...]；无标记则整体作为「解读摘要」。"""
    import re
    parts = re.split(r"【([^】]{1,24})】", text or "")
    sections = []
    preamble = parts[0].strip()
    if preamble:
        sections.append(("解读摘要", preamble))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if title:
            sections.append((title, body))
    return sections


def build_report_meta(scope, title="气象读图解析报告"):
    """构造报告元信息。版本号由页面注入，正文不硬编码。"""
    return {"scope": scope, "title": title,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}


_CSS = """
/* 屏幕预览用 token 取色，跟随明暗主题；.docx 导出仍保持学术白底版式
   （见 _build_docx），因此两者视觉不再强绑定。 */
.report-card{background:var(--bg-primary);color:var(--text-primary);
  border:1px solid var(--border-color);
  border-radius:10px;padding:20px 24px;margin:10px 0;
  box-shadow:var(--shadow-sm);
  font-family:"Microsoft YaHei","PingFang SC","Source Han Sans SC",sans-serif;
  line-height:1.75;}
.report-head{border-bottom:2px solid var(--accent);padding-bottom:8px;margin-bottom:14px;}
.report-title{font-size:20px;font-weight:700;color:var(--accent);letter-spacing:1px;}
.report-sub{font-size:12px;color:var(--text-muted);margin-top:4px;}
.sec{margin:14px 0;}
.sec-h{font-size:15px;font-weight:700;color:var(--accent);
  border-left:4px solid var(--accent);padding-left:10px;margin-bottom:6px;}
.report-card p{margin:4px 0;font-size:14px;color:var(--text-secondary);}
"""


def _report_html(sections, meta):
    """生成学术风报告 HTML（配色走 token，跟随应用主题）。"""
    body_html = ""
    for title, body in sections:
        paras = [p for p in body.split("\n") if p.strip()]
        if not paras:
            continue
        p_html = "".join("<p>%s</p>" % html.escape(p) for p in paras)
        body_html += ('<div class="sec"><div class="sec-h">%s</div>%s</div>'
                      % (html.escape(title), p_html))
    return (
        '<div class="report-card">'
        '<div class="report-head">'
        '<div class="report-title">%s</div>'
        '<div class="report-sub">生成时间：%s　｜　数据范围：%s</div>'
        "</div>%s</div>"
        "<style>%s</style>"
        % (html.escape(meta.get("title", "气象读图解析报告")),
           html.escape(meta["generated"]), html.escape(meta["scope"]),
           body_html, _CSS)
    )


def _set_cjk(run, font="Microsoft YaHei"):
    """为 run 设置中日韩字体（解决 docx 中文宋体回退问题）。"""
    from docx.oxml.ns import qn
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font)
    rfonts.set(qn("w:ascii"), font)
    rfonts.set(qn("w:hAnsi"), font)


def _build_docx(sections, meta, images=None):
    """导出 .docx（学术白底版式）。images 非空时把原图嵌入报告，便于留档。"""
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.oxml.ns import qn

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.size = Pt(11)
    normal.font.name = "Microsoft YaHei"
    _rpr = normal.element.get_or_add_rPr()
    _rfonts = _rpr.find(qn("w:rFonts"))
    if _rfonts is None:
        _rfonts = _rpr.makeelement(qn("w:rFonts"), {})
        _rpr.append(_rfonts)
    _rfonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    _rfonts.set(qn("w:ascii"), "Microsoft YaHei")
    _rfonts.set(qn("w:hAnsi"), "Microsoft YaHei")

    title = doc.add_heading(meta.get("title", "气象读图解析报告"), level=0)
    for run in title.runs:
        _set_cjk(run)
    sub = doc.add_paragraph()
    srun = sub.add_run("生成时间：%s    数据范围：%s"
                       % (meta["generated"], meta["scope"]))
    srun.font.size = Pt(9)
    srun.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
    _set_cjk(srun)

    # 原图紧随页头，读图报告不带图会失去留档价值
    # 只可能是 PNG/JPEG：读图管线保证不输出 WebP（python-docx 不支持）
    for item in (images or []):
        data = item.get("data_bytes")
        if not data:
            continue
        picture = doc.add_paragraph()
        picture.alignment = 1  # 居中
        picture.add_run().add_picture(io.BytesIO(data), width=Cm(15))
        caption = doc.add_paragraph()
        crun = caption.add_run(item.get("name", "上传图片"))
        crun.font.size = Pt(8)
        crun.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
        _set_cjk(crun)

    for title_txt, body in sections:
        heading = doc.add_heading(title_txt, level=1)
        for run in heading.runs:
            _set_cjk(run)
        for para_text in body.split("\n"):
            if para_text.strip():
                para = doc.add_paragraph(para_text.strip())
                for run in para.runs:
                    _set_cjk(run)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def display_report(text, meta, images=None,
                   docx_name="气象读图解析报告.docx",
                   md_name="气象读图解析报告.md"):
    """统一渲染：报告卡片 + .docx（含原图）+ .md 原文下载。"""
    sections = parse_sections(text)
    st.markdown(_report_html(sections, meta), unsafe_allow_html=True)

    try:
        docx_bytes = _build_docx(sections, meta, images)
        st.download_button(
            label="[下载] 解读报告 (.docx)",
            data=docx_bytes,
            file_name=docx_name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="report_download_docx",
        )
    except Exception as exc:  # noqa: BLE001 - 导出失败不影响展示
        st.warning("报告生成成功，但 .docx 导出失败：%s" % exc)

    st.download_button(
        label="[下载] 解读原文 (.md)",
        data=(text or "").encode("utf-8"),
        file_name=md_name,
        mime="text/markdown",
        key="report_download_md",
    )
