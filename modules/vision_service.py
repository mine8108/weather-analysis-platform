"""OpenAI vision profiles and durable, single-submission background jobs.

Images remain in memory. Journals contain response IDs, visible reports and usage,
never credentials, image bytes or internal reasoning text. Retrieval never generates.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "qwen": {"label": "Qwen3.8 Flash（默认）", "model": "qwen3.8-flash", "reasoning_effort": "native"},
    "terra": {"label": "GPT-6.1 Terra", "model": "gpt-6.1-terra", "reasoning_effort": "xhigh"},
    "sol": {"label": "GPT-6.1 Sol（专业增强）", "model": "gpt-6.1-sol", "reasoning_effort": "high"},
}
DEFAULT_PROFILE = "qwen"
OUTPUT_CAP = 32768
WAIT_SECONDS = 180
ACTIVE_STATES = {"reserved", "submitting", "queued", "in_progress", "unknown"}
RESPONSE_ID = re.compile(r"resp_[A-Za-z0-9_-]{1,200}\Z")


def resolve_config(profile=DEFAULT_PROFILE, secret_getter=None, env_path=None):
    if profile not in PROFILES:
        raise ValueError("未知读图模型选项")
    def setting(name):
        value = os.environ.get(name, "")
        if not value and secret_getter:
            value = secret_getter(name, "")
        return str(value or "").strip()
    def local_value(name):
        path = Path(env_path) if env_path is not None else ROOT / ".env.local"
        if path.is_file() and not path.is_symlink():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                field, sep, value = line.partition("=")
                if sep and field.strip() == name:
                    return value.strip().strip("\"'")
        return ""
    if profile == "qwen":
        legacy_qwen = setting("LLM_VISION_MODEL").startswith("qwen")
        key = (setting("QWEN_VISION_API_KEY") or setting("BASELINE_VISION_API_KEY")
               or (setting("LLM_VISION_API_KEY") if legacy_qwen else "")
               or local_value("QWEN_VISION_API_KEY") or local_value("BASELINE_VISION_API_KEY"))
        if not key:
            return None
        base_url = (setting("QWEN_VISION_BASE_URL") or (setting("LLM_VISION_BASE_URL") if legacy_qwen else "")
                    or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        if not base_url.startswith("https://"):
            raise ValueError("Qwen服务地址必须使用HTTPS")
        return {**PROFILES[profile], "profile": profile, "api_key": key, "base_url": base_url.rstrip("/"),
                "api_format": "chat_completions", "output_cap": OUTPUT_CAP, "stream": True,
                "read_timeout_seconds": WAIT_SECONDS}
    key = setting("OPENAI_API_KEY") or local_value("OPENAI_API_KEY")
    if not key:
        return None
    base_url = setting("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    if not base_url.startswith("https://"):
        raise ValueError("OpenAI 服务地址必须使用 HTTPS")
    return {**PROFILES[profile], "profile": profile, "api_key": key,
            "base_url": base_url.rstrip("/"), "api_format": "responses_background",
            "output_cap": OUTPUT_CAP, "read_timeout_seconds": WAIT_SECONDS}


def report_schema(image_count):
    from modules.ai_report_model import SECTION_TITLES
    string = {"type": "string"}
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    def arr(item, minimum=0, maximum=8):
        return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}
    return obj({
        "schema_version": {"type": "integer", "enum": [1]},
        "findings": arr(obj({"id": string, "text": string,
            "kind": {"type": "string", "enum": ["visible", "conditional"]},
            "evidence_ids": arr(string, 1), "limitation_ids": arr(string)}), 1, 3),
        "evidence": arr(obj({"id": string, "image_id": {"type": "string", "enum": [f"img_{i+1}" for i in range(image_count)]},
            "location": string, "feature": string}), 1, 8),
        "limitations": arr(obj({"id": string, "missing": string, "impact": string, "next_input": string}), 1, 4),
        "sections": arr(obj({"title": {"type": "string", "enum": list(SECTION_TITLES)}, "body": string}), 6, 6),
    })


def build_prompt(images, note=""):
    from modules.chart_reader import build_chart_prompt
    return build_chart_prompt(images, note) + (
        "\n六段 sections 的 body 合计控制在800—2000字。以去除空白后的Unicode字符数计算，"
        "含标点、数字和字母，不计标题、JSON键名、findings、evidence和limitations。"
        "图中不可判读的信息如实说明，不编造数值或为凑字数重复。"
    )


def _count(value):
    return type(value) is int and value >= 0


def normalize_usage(native):
    if not isinstance(native, dict):
        return {}
    a, b = native.get("input_tokens"), native.get("output_tokens")
    if not (_count(a) and _count(b)):
        return {}
    total = native.get("total_tokens", a + b)
    if not _count(total) or total != a + b:
        return {}
    details = native.get("output_tokens_details") or {}
    if not isinstance(details, dict):
        return {}
    reasoning = details.get("reasoning_tokens", 0)
    if not _count(reasoning) or reasoning > b:
        return {}
    return {"prompt": a, "completion": b, "reasoning": reasoning, "total": total}


def _read_response(response):
    if not 200 <= response.status_code < 300:
        raise ValueError(f"服务返回 HTTP {response.status_code}")
    if len(response.content) > 2 * 1024 * 1024:
        raise ValueError("模型响应超过接收上限")
    data = response.json()
    if not isinstance(data, dict) or not RESPONSE_ID.fullmatch(str(data.get("id", ""))):
        raise ValueError("模型返回的任务编号无效")
    if data.get("status") not in {"queued", "in_progress", "completed", "incomplete", "failed", "cancelled"}:
        raise ValueError("模型返回的任务状态无效")
    return data


def _apply_response(job, data):
    if job.get("response_id") and data["id"] != job["response_id"]:
        raise ValueError("返回的任务编号与原请求不一致")
    job.update(response_id=data["id"], status=data["status"], updated_at=time.time(), last_error="")
    usage = normalize_usage(data.get("usage"))
    if usage:
        job["usage"] = usage
    if job["status"] in {"completed", "incomplete", "failed", "cancelled"}:
        job["text"] = "\n".join(
            p["text"] for item in data.get("output", []) if isinstance(item, dict) and item.get("type") == "message"
            for p in item.get("content", []) if isinstance(p, dict) and p.get("type") == "output_text" and isinstance(p.get("text"), str)
        ).strip()
        from modules.ai_report_model import decode_report
        report = decode_report(job["text"], job["sources"])
        count = len(re.sub(r"\s+", "", "".join(s["body"] for s in report["sections"]))) if report["structured"] else None
        job["body_chars"] = count
        job["output_contract"] = ("truncated" if job["status"] == "incomplete" else
            "response_failed" if job["status"] != "completed" else
            "invalid_structure" if not report["structured"] else
            "body_length_failed" if not 800 <= count <= 2000 else "ok")
    return job


class JobStore:
    """Owner-isolated journals; exclusive creation happens before the one POST."""
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else ROOT / ".vision-jobs"

    def _path(self, owner, call_id):
        if not owner or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(call_id)):
            raise ValueError("缺少有效的用户或调用标识")
        owner_hash = hashlib.sha256(str(owner).encode()).hexdigest()
        return self.root / owner_hash / (str(call_id) + ".json")

    def load(self, owner, call_id):
        data = json.loads(self._path(owner, call_id).read_text(encoding="utf-8"))
        if data.get("owner_hash") != hashlib.sha256(str(owner).encode()).hexdigest() or data.get("call_id") != str(call_id):
            raise ValueError("任务归属不一致")
        return data

    def save(self, owner, job):
        path = self._path(owner, job["call_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        with temp.open("w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)

    def waiting(self, owner):
        if not owner:
            return []
        folder = self._path(owner, "index").parent
        jobs = [self.load(owner, p.stem) for p in folder.glob("*.json")]
        return sorted([j for j in jobs if not j.get("acknowledged") or not j.get("settled")],
                      key=lambda j: j["created_at"], reverse=True)

    def submit(self, owner, call_id, cfg, prompt, images, max_tokens, fingerprint):
        from modules.ai_report_model import freeze_images
        from modules.ai_narrative import _VISION_SYSTEM_PROMPT
        from modules.chart_reader import image_to_data_url
        cap = min(int(max_tokens), OUTPUT_CAP)
        if cap <= 0 or not 1 <= len(images) <= 5:
            raise ValueError("本次输出预算或图片数量无效")
        path = self._path(owner, call_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        job = {"call_id": str(call_id), "owner_hash": path.parent.name, "profile": cfg["profile"],
               "model": cfg["model"], "reasoning_effort": cfg["reasoning_effort"], "base_url": cfg["base_url"],
               "output_cap": cap, "created_at": time.time(), "updated_at": time.time(), "status": "submitting",
               "response_id": None, "usage": {}, "settled": False, "usage_recorded": False,
               "fingerprint": fingerprint, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
               "sources": [{k: v for k, v in i.items() if k != "data_bytes"} for i in freeze_images(images)]}
        # Existing or interrupted jobs cannot be silently submitted a second time.
        with path.open("x", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        payload = {"model": cfg["model"], "background": True, "store": True,
                   "max_output_tokens": cap, "reasoning": {"effort": cfg["reasoning_effort"]},
                   "text": {"format": {"type": "json_schema", "name": "weather_chart_report", "strict": True,
                                        "schema": report_schema(len(images))}},
                   "input": [{"role": "system", "content": _VISION_SYSTEM_PROMPT},
                     {"role": "user", "content": [{"type": "input_text", "text": prompt}] +
                      [{"type": "input_image", "image_url": image_to_data_url(i["data_bytes"], i["mime"])} for i in images]}]}
        try:
            response = requests.post(cfg["base_url"] + "/responses",
                headers={"Authorization": "Bearer " + cfg["api_key"]}, json=payload,
                timeout=(10, WAIT_SECONDS), allow_redirects=False)
            job["request_id"] = response.headers.get("x-request-id", "")[:160]
            data = _read_response(response)
            # Persist the response ID before interpretation of usage or visible output.
            job["response_id"] = data["id"]
            job["status"] = data["status"]
            self.save(owner, job)
            _apply_response(job, data)
        except Exception as exc:
            job["status"] = "unknown" if not job.get("response_id") else job["status"]
            job["last_error"] = type(exc).__name__  # No provider body, credentials or exception text.
        self.save(owner, job)
        return job

    def poll(self, owner, call_id, cfg):
        job = self.load(owner, call_id)
        if job["status"] not in ACTIVE_STATES or not job.get("response_id"):
            return job
        if not RESPONSE_ID.fullmatch(job["response_id"]) or cfg["model"] != job["model"] or cfg["base_url"] != job["base_url"]:
            raise ValueError("任务配置或编号不一致")
        try:
            response = requests.get(job["base_url"] + "/responses/" + job["response_id"],
                headers={"Authorization": "Bearer " + cfg["api_key"]}, timeout=(10, 20), allow_redirects=False)
            _apply_response(job, _read_response(response))
        except Exception as exc:
            job["last_error"] = type(exc).__name__
        self.save(owner, job)
        return job
