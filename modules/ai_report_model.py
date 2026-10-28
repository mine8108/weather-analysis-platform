"""Validated presentation contract for one vision response and its frozen inputs.

Validation checks structure and references, not the scientific truth of a model claim.
There is no repair request, extra model call, or inferred evidence in this module.
"""
from __future__ import annotations

import hashlib
import json
import re

SECTION_TITLES = ("图像信息", "图面要素识别", "主要分布特征", "关键数值与极值", "趋势与演变", "风险提示与结论")


def freeze_images(images):
    frozen = []
    for item in images or []:
        data = item.get("data_bytes")
        if not data or item.get("ok") is False:
            continue
        frozen.append({"id": f"img_{len(frozen) + 1}", "name": str(item.get("name") or "未命名"),
                       "sha256": hashlib.sha256(data).hexdigest(), "data_bytes": bytes(data),
                       "mime": item.get("mime"), "width": item.get("width"), "height": item.get("height")})
    return frozen


def input_fingerprint(images, note=""):
    pieces = [(str(item.get("name", "")), hashlib.sha256(item.get("data_bytes") or b"").hexdigest())
              for item in images or [] if item.get("data_bytes")]
    return hashlib.sha256(json.dumps([pieces, note], ensure_ascii=False).encode()).hexdigest()


def _text(value, name, limit=6000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name}缺失或长度无效")
    return value.strip()


def _items(value, name, maximum, allow_empty=False):
    if not isinstance(value, list) or len(value) > maximum or (not value and not allow_empty):
        raise ValueError(f"{name}结构无效")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{name}条目无效")
    return value


def _identity(item, seen):
    identity = _text(item.get("id"), "引用编号", 32)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", identity) or identity in seen:
        raise ValueError("引用编号无效或重复")
    seen.add(identity)
    return identity


def decode_report(raw_response, source_images):
    """Return a complete structured model, or an explicit raw-text fallback."""
    from modules.ai_narrative import parse_sections
    raw = str(raw_response or "")
    source = [{k: v for k, v in item.items() if k != "data_bytes"} for item in source_images or []]
    fallback = {"schema_version": 1, "structured": False, "source_images": source,
                "findings": [], "evidence": [], "limitations": [], "sections": [], "raw_response": raw}
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    parsed = None
    try:
        if len(candidate) > 200000:
            raise ValueError("输出超过结构化展示长度")
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict) or type(parsed.get("schema_version")) is not int or parsed["schema_version"] != 1:
            raise ValueError("结果版本无效")
        source_ids = {i["id"] for i in source}
        seen = set()
        evidence = []
        for item in _items(parsed.get("evidence"), "原图依据", 15):
            identity = _identity(item, seen)
            if item.get("image_id") not in source_ids:
                raise ValueError("依据引用了本次上传之外的图片")
            evidence.append({"id": identity, "image_id": item["image_id"],
                             "location": _text(item.get("location"), "图中位置", 240),
                             "feature": _text(item.get("feature"), "可见特征", 1000)})
        evidence_ids = {i["id"] for i in evidence}
        limitations = []
        for item in _items(parsed.get("limitations"), "不确定性", 8):
            limitations.append({"id": _identity(item, seen),
                                "missing": _text(item.get("missing"), "缺失信息", 500),
                                "impact": _text(item.get("impact"), "影响", 800),
                                "next_input": _text(item.get("next_input"), "所需补充", 500)})
        limitation_ids = {i["id"] for i in limitations}
        findings = []
        for item in _items(parsed.get("findings"), "核心结论", 4):
            identity = _identity(item, seen)
            if item.get("kind") not in ("visible", "conditional"):
                raise ValueError("结论类型无效")
            refs, limits = item.get("evidence_ids"), item.get("limitation_ids")
            if not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in evidence_ids for r in refs):
                raise ValueError("结论缺少有效原图依据")
            if not isinstance(limits, list) or any(not isinstance(r, str) or r not in limitation_ids for r in limits):
                raise ValueError("结论的不确定性引用无效")
            if item["kind"] == "conditional" and not limits:
                raise ValueError("条件性推断未说明限制")
            findings.append({"id": identity, "text": _text(item.get("text"), "结论", 1000),
                             "kind": item["kind"], "evidence_ids": list(dict.fromkeys(refs)),
                             "limitation_ids": list(dict.fromkeys(limits))})
        sections = _items(parsed.get("sections"), "六段正文", 6)
        if [s.get("title") for s in sections] != list(SECTION_TITLES):
            raise ValueError("六段正文标题或顺序无效")
        sections = [{"title": s["title"], "body": _text(s.get("body"), "正文")} for s in sections]
        return {**fallback, "structured": True, "findings": findings, "evidence": evidence,
                "limitations": limitations, "sections": sections, "format_notice": ""}
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        # Preserve readable sections even when only a reference is invalid; never promote unvalidated claims.
        readable = []
        if isinstance(parsed, dict) and isinstance(parsed.get("sections"), list):
            for item in parsed["sections"][:12]:
                if isinstance(item, dict) and isinstance(item.get("title"), str) and isinstance(item.get("body"), str):
                    readable.append({"title": item["title"][:100], "body": item["body"][:20000]})
        if not readable:
            readable = [{"title": t, "body": b} for t, b in parse_sections(raw)]
        return {**fallback, "sections": readable,
                "format_notice": f"结构化展示不可用，保留原始解读。{str(exc)[:120]}"}


def report_sections(model):
    """One ordered content model for display, Markdown and Word export."""
    sections = []
    if model.get("structured"):
        sections.append(("核心结论（AI 提取，待核查）", "\n".join(
            f"{f['id']} · {'图面描述' if f['kind'] == 'visible' else '条件性推断'}：{f['text']}\n依据：{', '.join(f['evidence_ids'])}；限制：{', '.join(f['limitation_ids']) or '见全局不确定性'}"
            for f in model["findings"])))
        names = {i["id"]: i["name"] for i in model["source_images"]}
        sections.append(("原图依据", "\n".join(f"{e['id']} · {names[e['image_id']]} · {e['location']}：{e['feature']}" for e in model["evidence"])))
        sections.append(("不确定性与补充信息", "\n".join(
            f"{l['id']} · 缺失信息：{l['missing']}\n影响：{l['impact']}\n建议补充：{l['next_input']}" for l in model["limitations"])))
    else:
        sections.append(("展示说明", model.get("format_notice", "旧版结果未提供结构化原图依据。")))
    sections.extend((s["title"], s["body"]) for s in model.get("sections", []))
    return sections


def report_markdown(model, meta):
    pieces = [f"# {meta.get('title', '气象读图解析报告')}",
              f"生成时间 {meta.get('generated', '')} · {meta.get('scope', '')}"]
    pieces.extend(f"## {title}\n\n{body}" for title, body in report_sections(model))
    return "\n\n".join(pieces)
