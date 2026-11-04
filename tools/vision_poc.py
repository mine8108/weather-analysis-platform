"""Offline-first, resumable evaluation of the workbench's vision contract.

Only ``run --live`` can send a request. No credentials are read on other paths.
Production configuration, UI and Supabase quotas are never modified here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CONFIG = Path(__file__).with_name("vision_poc_config.json")
DEFAULT_REQUEST_POLICY = {"read_timeout_seconds": 180, "body_min_chars": 800, "body_max_chars": 2000}
DIMENSIONS = ("metadata", "legend_units", "values_location", "systems_evolution", "evidence")
REVIEW_FIELDS = ("blind_id", *(f"{d}_0_20" for d in DIMENSIONS),
                 "critical_error_yes_no", "acceptable_yes_no", "reviewer", "review_method", "notes")


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def money(value):
    return round(value, 8)


def validate_model(alias, model, live=False):
    allowed = {"provider", "model", "base_url", "key_env", "reasoning_effort", "output_parameter",
               "output_cap", "input_reservation_tokens", "input_usd_per_million",
               "output_usd_per_million", "input_reservation_multiplier", "temperature", "stream", "api_format"}
    if set(model) - allowed:
        raise ValueError(f"{alias}: unsupported configuration fields; store credentials only in environment variables")
    if "stream" in model and type(model["stream"]) is not bool:
        raise ValueError(f"{alias}: stream must be boolean")
    if model.get("api_format", "chat_completions") not in {"chat_completions", "responses_background"}:
        raise ValueError(f"{alias}: unsupported api_format")
    if model.get("api_format") == "responses_background" and model.get("provider") != "openai":
        raise ValueError(f"{alias}: background Responses adapter is OpenAI-only")
    if model.get("output_parameter") not in {"max_tokens", "max_completion_tokens"}:
        raise ValueError(f"{alias}: unsupported output parameter")
    for key, lower, upper in (("output_cap", 256, 32768), ("input_reservation_tokens", 4096, 131072)):
        value = model.get(key)
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"{alias}: invalid {key}")
    for key in ("input_usd_per_million", "output_usd_per_million", "input_reservation_multiplier"):
        value = model.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{alias}: set a finite nonnegative {key}; baseline prices must be filled in USD")
    if model["input_reservation_multiplier"] < 1:
        raise ValueError(f"{alias}: input reservation multiplier must be at least 1")
    if not model.get("model") or not model.get("key_env"):
        raise ValueError(f"{alias}: fill model and key_env")
    if not re.fullmatch(r"[A-Z_][A-Z_0-9]*", model["key_env"]):
        raise ValueError(f"{alias}: key_env must name an environment variable, not contain a credential")
    url = urlsplit(model.get("base_url", ""))
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError(f"{alias}: use an HTTPS base URL without credentials, query or fragment")
    if model.get("provider") == "openai" and (url.hostname != "api.openai.com" or url.port not in (None, 443)):
        raise ValueError(f"{alias}: OpenAI requests must use api.openai.com")
    if model.get("provider") == "openai" and model.get("reasoning_effort", "none") != "none" and "temperature" in model:
        raise ValueError(f"{alias}: remove temperature when reasoning is enabled")
    if live and not os.environ.get(model["key_env"], "").strip():
        raise ValueError(f"{alias}: required credential environment variable is absent")


def reservation_usd(model):
    return money((model["input_reservation_tokens"] * model["input_usd_per_million"]
                  * model["input_reservation_multiplier"]
                  + model["output_cap"] * model["output_usd_per_million"]) / 1_000_000)


def request_policy(config):
    policy = {**DEFAULT_REQUEST_POLICY, **config.get("request_policy", {})}
    if set(policy) != set(DEFAULT_REQUEST_POLICY):
        raise ValueError("unsupported request policy fields")
    for key, lower, upper in (("read_timeout_seconds", 10, 600),
                               ("body_min_chars", 1, 10000), ("body_max_chars", 1, 10000)):
        value = policy[key]
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"invalid request policy: {key}")
    if policy["body_min_chars"] > policy["body_max_chars"]:
        raise ValueError("body_min_chars must not exceed body_max_chars")
    return policy


def usage_budget_usd(usage, model):
    """Hold a cost cushion without treating it as the provider's actual charge."""
    conservative = (usage["input"] * model["input_usd_per_million"] * model["input_reservation_multiplier"]
                    + usage["output_including_reasoning"] * model["output_usd_per_million"]) / 1_000_000
    return money(max(conservative, estimated_usage_usd(usage, model) * 1.25))


def normalize_usage(raw):
    if not isinstance(raw, dict):
        return None
    values = [raw.get("prompt_tokens"), raw.get("completion_tokens")]
    if any(type(v) is not int or v < 0 for v in values):
        return None
    details = raw.get("completion_tokens_details") or {}
    cached = raw.get("prompt_tokens_details") or {}
    reasoning = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
    cache_read = cached.get("cached_tokens", 0) if isinstance(cached, dict) else 0
    if type(reasoning) is not int or not 0 <= reasoning <= values[1]:
        return None
    if type(cache_read) is not int or not 0 <= cache_read <= values[0]:
        return None
    return {"input": values[0], "output_including_reasoning": values[1],
            "reasoning_subset": reasoning, "cached_input_subset": cache_read,
            "total": sum(values)}


def estimated_usage_usd(usage, model):
    # An uncached-list-price estimate, not an invoice. Cache writes/discounts,
    # provider-specific adjustments and FX are reconciled separately.
    return money((usage["input"] * model["input_usd_per_million"]
                  + usage["output_including_reasoning"] * model["output_usd_per_million"]) / 1_000_000)


def prepare_case(case, manifest_dir, policy):
    from modules.chart_reader import MAX_IMAGES, build_chart_prompt, check_total_size, process_image
    images = case.get("images")
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError(f"{case['id']}: provide 1 to {MAX_IMAGES} images")
    prepared, sources = [], []
    for index, relative in enumerate(images, 1):
        path = (manifest_dir / relative).resolve()
        if not path.is_relative_to(manifest_dir.resolve()):
            raise ValueError(f"{case['id']}: images must be inside the manifest directory")
        raw = path.read_bytes()
        item = process_image(raw, f"image_{index:02d}{path.suffix.lower()}")
        if not item["ok"]:
            raise ValueError(f"{case['id']}: image {index} rejected by production preprocessing")
        prepared.append(item)
        sources.append({"path": relative, "original_sha256": digest(raw),
                        "submitted_sha256": digest(item["data_bytes"]),
                        "width": item["width"], "height": item["height"], "bytes": len(item["data_bytes"])})
    if check_total_size(prepared):
        raise ValueError(f"{case['id']}: total image size exceeds production limit")
    note = case.get("note", "")
    if not isinstance(note, str) or len(note) > 500:
        raise ValueError(f"{case['id']}: note must be at most 500 characters")
    prompt = build_chart_prompt(prepared, note)
    prompt += ("\n\n本次正文长度要求：sections 六段 body 合计 %d—%d 字。"
               "按去除空白后的 Unicode 字符数计数，标点、数字和英文字母均计入；"
               "标题、JSON 键名及 findings/evidence/limitations 字段不计入。"
               "保持六段结构和 JSON 格式，依据条目简洁，不为凑字数重复内容或编造信息。"
               "图像不可判读时据实说明，可少于要求字数，由验证程序标记长度未通过。"
               % (policy["body_min_chars"], policy["body_max_chars"]))
    return prepared, prompt, sources


def build_jobs(manifest_path, config, aliases, case_ids=None, repeat=1, split=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    policy = request_policy(config)
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema")
    if not 1 <= repeat <= 3:
        raise ValueError("repeat must be 1 to 3")
    aliases = list(dict.fromkeys(aliases))
    if not aliases:
        raise ValueError("select at least one model")
    for alias in aliases:
        if alias not in config["models"]:
            raise ValueError(f"unknown model alias: {alias}")
        validate_model(alias, config["models"][alias])
    cases = manifest.get("cases", [])
    ids = [c["id"] for c in cases]
    if not cases or len(set(ids)) != len(ids):
        raise ValueError("manifest needs nonempty, unique case IDs")
    if case_ids and set(case_ids) - set(ids):
        raise ValueError("requested case ID is absent from manifest")
    jobs = []
    from modules.ai_narrative import _VISION_SYSTEM_PROMPT
    for case in cases:
        if case_ids and case["id"] not in case_ids or split and case.get("split") != split:
            continue
        if case.get("status") != "ready" or case.get("reference_reviewed") is not True:
            raise ValueError(f"{case['id']}: finalize images and review the reference before running")
        if case.get("kind") not in {"synthetic", "public", "operational"}:
            raise ValueError(f"{case['id']}: invalid kind")
        if not case.get("reference"):
            raise ValueError(f"{case['id']}: reference is required")
        if case["kind"] == "public" and not case.get("source_url"):
            raise ValueError(f"{case['id']}: public cases need source_url")
        prepared, prompt, sources = prepare_case(case, manifest_path.parent, policy)
        for trial in range(1, repeat + 1):
            for alias in aliases:
                model = config["models"][alias]
                identity = {"submitted_images": [i["submitted_sha256"] for i in sources],
                            "prompt": prompt, "system": _VISION_SYSTEM_PROMPT,
                            "alias": alias, "model_config": model, "trial": trial,
                            "case_id": case["id"], "request_policy": policy}
                job_id = digest(identity)
                jobs.append({"job_id": job_id, "blind_id": "R" + job_id[:12],
                             "case": case, "alias": alias, "model_config": model, "trial": trial,
                             "images": prepared, "prompt": prompt, "sources": sources,
                             "request_policy": dict(policy),
                             "system": _VISION_SYSTEM_PROMPT, "reservation_usd": reservation_usd(model)})
    if not jobs:
        raise ValueError("selection contains no cases")
    return jobs


def public_job(job):
    return {"job_id": job["job_id"], "case_id": job["case"]["id"],
            "kind": job["case"]["kind"], "group": job["case"]["group"],
            "split": job["case"].get("split"), "alias": job["alias"], "trial": job["trial"],
            "model": job["model_config"]["model"], "sources": job["sources"],
            "reasoning_effort": job["model_config"].get("reasoning_effort"),
            "output_cap": job["model_config"]["output_cap"], "request_policy": job["request_policy"],
            "prompt_sha256": digest(job["prompt"].encode()), "reservation_usd": job["reservation_usd"]}


def write_plan(jobs, output):
    plan = {"mode": "offline_no_api_calls", "created_at": utc_now(),
            "jobs": [public_job(j) for j in jobs],
            "sum_reservations_usd": money(sum(j["reservation_usd"] for j in jobs)),
            "notes": ["Reservations are conservative planning envelopes, not verified input-token bounds.",
                      "List-price cost estimates are reconciled against provider invoices.",
                      "References and scores are never included in model requests."]}
    write_json(Path(output) / "plan.json", plan)
    return plan


def load_states(path):
    states = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)  # Corruption stops the run; never discard a reservation.
                states[event["job_id"]] = event
    return states


def append_event(path, event):
    with Path(path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def held_usd(states):
    return money(sum(e.get("budget_charge_usd", e["reservation_usd"]) for e in states.values()))


def check_live_window(config, now=None):
    cutoff = datetime.fromisoformat(config["live_before"])
    if cutoff.tzinfo is None:
        raise ValueError("live_before must include a timezone")
    if (now or datetime.now(timezone.utc)) >= cutoff:
        raise ValueError("live window closed; review the credit expiry and config before continuing")


def request_once(job):
    """One HTTP request, no retries, redirects or response-body logging on errors."""
    import requests
    from modules.chart_reader import image_to_data_url
    model = job["model_config"]
    if model.get("api_format") == "responses_background":
        return request_background(job)
    content = [{"type": "text", "text": job["prompt"]}]
    for item in job["images"]:
        content.append({"type": "image_url", "image_url": {
            "url": image_to_data_url(item["data_bytes"], item["mime"])}})
    payload = {"model": model["model"], "messages": [
        {"role": "system", "content": job["system"]}, {"role": "user", "content": content}],
        model["output_parameter"]: model["output_cap"]}
    for key in ("reasoning_effort", "temperature"):
        if key in model:
            payload[key] = model[key]
    if model.get("stream"):
        payload.update(stream=True, stream_options={"include_usage": True})
    # Request policy is intentionally separate from production's fixed parameters.
    response = requests.post(model["base_url"].rstrip("/") + "/chat/completions",
                             headers={"Authorization": "Bearer " + os.environ[model["key_env"]].strip()},
                             json=payload, timeout=(10, job["request_policy"]["read_timeout_seconds"]),
                             allow_redirects=False, stream=model.get("stream", False))
    request_id = response.headers.get("x-request-id", "")[:160]
    if not 200 <= response.status_code < 300:
        receipt = {"http_status": response.status_code, "request_id": request_id, "status": "http_error"}
        try:
            data = response.json()
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                for key in ("code", "type", "param"):
                    value = error.get(key)
                    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
                        receipt["provider_error_" + key] = value
        except ValueError:
            pass
        return receipt
    if model.get("stream"):
        return consume_stream(response, request_id)
    if len(response.content) > 2 * 1024 * 1024:
        return {"http_status": response.status_code, "request_id": request_id, "status": "response_too_large"}
    try:
        data = response.json()
    except ValueError:
        return {"http_status": response.status_code, "request_id": request_id, "status": "invalid_json"}
    if not isinstance(data, dict):
        return {"http_status": response.status_code, "request_id": request_id, "status": "invalid_response"}
    return {"http_status": response.status_code, "request_id": request_id, "data": data}


def request_background(job):
    """Create once, checkpoint its ID, then poll the same response without regeneration."""
    import requests
    from modules.chart_reader import image_to_data_url
    model = job["model_config"]
    headers = {"Authorization": "Bearer " + os.environ[model["key_env"]].strip()}
    content = [{"type": "input_text", "text": job["prompt"]}]
    content += [{"type": "input_image", "image_url": image_to_data_url(i["data_bytes"], i["mime"])} for i in job["images"]]
    payload = {"model": model["model"], "background": True, "store": True,
               "max_output_tokens": model["output_cap"],
               "reasoning": {"effort": model["reasoning_effort"]},
               "input": [{"role": "system", "content": job["system"]}, {"role": "user", "content": content}]}
    timeout = (10, job["request_policy"]["read_timeout_seconds"])
    response = requests.post(model["base_url"].rstrip("/") + "/responses", headers=headers,
                             json=payload, timeout=timeout, allow_redirects=False)
    receipt = {"http_status": response.status_code, "request_id": response.headers.get("x-request-id", "")[:160],
               "api_format": "responses_background"}
    try:
        data = response.json()
    except ValueError:
        return {**receipt, "status": "invalid_json"}
    if not 200 <= response.status_code < 300:
        receipt["status"] = "http_error"
        error = data.get("error", {}) if isinstance(data, dict) else {}
        for key in ("code", "type", "param"):
            value = error.get(key) if isinstance(error, dict) else None
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
                receipt["provider_error_" + key] = value
        return receipt
    response_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(response_id, str) or not re.fullmatch(r"resp_[A-Za-z0-9_-]+", response_id):
        return {**receipt, "status": "invalid_response"}
    receipt["response_id"] = response_id
    if job.get("checkpoint_path"):
        write_json(job["checkpoint_path"], {"job_id": job["job_id"], "response_id": response_id,
                                          "request_id": receipt["request_id"], "at": utc_now()})
    deadline = time.monotonic() + job["request_policy"]["read_timeout_seconds"]
    polls = 0
    consecutive_poll_errors = 0
    while data.get("status") in {"queued", "in_progress"}:
        if time.monotonic() >= deadline:
            receipt["status"] = "background_pending"
            break
        time.sleep(2)
        try:
            polled = requests.get(model["base_url"].rstrip("/") + "/responses/" + response_id,
                                  headers=headers, timeout=timeout, allow_redirects=False)
            if polled.status_code != 200:
                if polled.status_code == 429 or polled.status_code >= 500:
                    consecutive_poll_errors += 1
                    receipt.setdefault("transient_poll_errors", []).append({"http_status": polled.status_code})
                    if consecutive_poll_errors < 3:
                        continue  # GET reads the same response; never creates another generation.
                receipt.update(status="background_poll_error", poll_http_status=polled.status_code)
                break
            data = polled.json()
            polls += 1
            consecutive_poll_errors = 0
        except (requests.RequestException, ValueError) as exc:
            consecutive_poll_errors += 1
            receipt.setdefault("transient_poll_errors", []).append({"error_type": type(exc).__name__})
            if consecutive_poll_errors < 3:
                continue
            receipt.update(status="background_poll_error", error_type=type(exc).__name__)
            break
    receipt.update(response_status=data.get("status"), poll_count=polls)
    if data.get("status") not in {"completed", "incomplete", "queued", "in_progress"}:
        receipt.setdefault("status", "response_failed")
    text = "\n".join(part.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
                     for part in item.get("content", []) if part.get("type") == "output_text")
    native = data.get("usage")
    usage = None
    if isinstance(native, dict):
        usage = {"prompt_tokens": native.get("input_tokens"), "completion_tokens": native.get("output_tokens"),
                 "completion_tokens_details": native.get("output_tokens_details"),
                 "prompt_tokens_details": native.get("input_tokens_details")}
    finish = "stop" if data.get("status") == "completed" else "length" if data.get("status") == "incomplete" else None
    receipt["data"] = {"usage": usage, "choices": [{"message": {"content": text}, "finish_reason": finish}]}
    return receipt


def consume_stream(response, request_id):
    """Keep only visible text and final usage; never retain reasoning deltas."""
    import requests
    receipt = {"http_status": response.status_code, "request_id": request_id}
    pieces, usage, finish, done = [], None, None, False
    received_bytes = 0
    try:
        for raw in response.iter_lines(chunk_size=1):
            if not raw:
                continue
            received_bytes += len(raw)
            if received_bytes > 2 * 1024 * 1024:
                receipt["status"] = "response_too_large"
                break
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            value = line[5:].strip()
            if value == "[DONE]":
                done = True
                break
            try:
                chunk = json.loads(value)
            except ValueError:
                receipt["status"] = "invalid_json"
                break
            if not isinstance(chunk, dict) or chunk.get("error"):
                receipt["status"] = "stream_error"
                break
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                if choice.get("index", 0) != 0:
                    continue
                delta = choice.get("delta") or {}
                if isinstance(delta.get("content"), str):
                    pieces.append(delta["content"])
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
    except requests.RequestException as exc:
        receipt.update(status="stream_interrupted", error_type=type(exc).__name__)
    finally:
        getattr(response, "close", lambda: None)()
    if not done:
        receipt.setdefault("status", "stream_interrupted")
    receipt["stream_completed"] = done
    receipt["data"] = {"usage": usage, "choices": [{"message": {"content": "".join(pieces)}, "finish_reason": finish}]}
    return receipt


def interpret_response(receipt, job):
    from modules.ai_narrative import _extract_message_text
    from modules.ai_report_model import decode_report, freeze_images
    transport_status = receipt.get("status")
    data = receipt.pop("data", {})
    usage = normalize_usage(data.get("usage"))
    receipt["usage"] = usage
    if usage is not None:
        receipt["estimated_usd"] = estimated_usage_usd(usage, job["model_config"])
    try:
        choice = data["choices"][0]
        finish = choice.get("finish_reason")
        text = _extract_message_text(choice["message"])
    except (KeyError, IndexError, TypeError, AttributeError):
        receipt.setdefault("status", "invalid_response")
        receipt["structured"] = False
        return receipt
    parsed = decode_report(text, freeze_images(job["images"]))
    body_chars = len(re.sub(r"\s+", "", "".join(s["body"] for s in parsed["sections"]))) if parsed["structured"] else None
    policy = job["request_policy"]
    length_ok = body_chars is not None and policy["body_min_chars"] <= body_chars <= policy["body_max_chars"]
    receipt.update({"finish_reason": finish, "response_text": text,
                    "structured": parsed["structured"], "report": parsed,
                    "body_chars": body_chars, "body_length_ok": length_ok})
    receipt["status"] = ("truncated" if finish == "length" else "empty" if not text else
                         "invalid_structure" if not parsed["structured"] or finish != "stop" else
                         "ok" if length_ok else "body_length_failed")
    if transport_status:
        receipt["status"] = transport_status
    return receipt


def run_live(jobs, config, output, budget_usd, limit=None, request_fn=None, workers=1):
    if not math.isfinite(budget_usd) or not 0 < budget_usd <= 30:
        raise ValueError("study budget must be greater than 0 and at most USD 30")
    if type(workers) is not int or not 1 <= workers <= 2:
        raise ValueError("workers must be 1 or 2")
    check_live_window(config)
    for job in jobs:
        validate_model(job["alias"], job["model_config"], live=True)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lock_path = output / "run.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("run.lock exists; check for an active or interrupted run before removing it") from None
    ledger = output / "ledger.jsonl"
    count = 0
    consecutive_contract_failures = 0
    try:
        os.write(lock_fd, str(os.getpid()).encode())
        states = load_states(ledger)
        def perform(job):
            started = time.monotonic()
            try:
                receipt = interpret_response((request_fn or request_once)(job), job)
            except Exception as exc:
                # Never serialize exception text: it can contain request data or credentials.
                receipt = {"status": "request_or_parse_error", "error_type": type(exc).__name__, "usage": None}
            return {**receipt, "latency_seconds": round(time.monotonic() - started, 3)}

        pending, index, dispatched, stopping = {}, 0, 0, False
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while True:
                # Only this thread reads/writes the ledger. Network workers receive
                # a job only after its reservation is durable and included in held spend.
                while not stopping and len(pending) < workers and index < len(jobs):
                    job = jobs[index]
                    if job["job_id"] in states:
                        index += 1
                        continue
                    if limit is not None and dispatched >= limit:
                        stopping = True
                        break
                    try:
                        check_live_window(config)
                    except ValueError:
                        if not pending:
                            raise
                        stopping = True
                        break
                    if held_usd(states) + job["reservation_usd"] > budget_usd + 1e-9:
                        if not pending:
                            print("Stopped before the next request: local budget reservation would exceed the study cap.")
                            stopping = True
                        break  # An in-flight request may settle below its reservation.
                    event = {**public_job(job), "blind_id": job["blind_id"], "state": "started", "at": utc_now(),
                             "provider": job["model_config"]["provider"], "model_config": job["model_config"],
                             "case": job["case"], "manifest_dir": str(Path(job["manifest_dir"]).resolve()),
                             "pricing_checked_on": config["pricing_checked_on"], "pricing_reference": config.get("pricing_reference", {})}
                    append_event(ledger, event)
                    states[job["job_id"]] = event
                    job["checkpoint_path"] = str(output / "response-checkpoints" / (job["job_id"] + ".json"))
                    pending[pool.submit(perform, job)] = (job, event)
                    index += 1
                    dispatched += 1
                if not pending:
                    break
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    job, event = pending.pop(future)
                    event = {**event, **future.result(), "state": "finished", "at": utc_now()}
                    estimate = event.get("estimated_usd")
                    event["budget_charge_usd"] = usage_budget_usd(event["usage"], job["model_config"]) if estimate is not None else job["reservation_usd"]
                    append_event(ledger, event)
                    states[job["job_id"]] = event
                    count += 1
                    print(f"{job['case']['id']} / {job['alias']} / {event['status']}", flush=True)
                    bound_broken = (event.get("usage") or {}).get("input", 0) > job["model_config"]["input_reservation_tokens"]
                    if event["status"] in {"http_error", "request_or_parse_error", "invalid_json", "response_too_large", "invalid_response", "stream_interrupted", "stream_error", "background_pending", "background_poll_error", "response_failed"}:
                        print("Stopped new requests after an uncertain or rejected response; settling any in-flight requests.")
                        stopping = True
                    consecutive_contract_failures = consecutive_contract_failures + 1 if event["status"] != "ok" else 0
                    if consecutive_contract_failures >= 2:
                        print("Stopped new requests after two consecutive output-contract failures.")
                        stopping = True
                    if bound_broken or event["budget_charge_usd"] > job["reservation_usd"] or held_usd(states) >= budget_usd:
                        stopping = True
        return count
    finally:
        os.close(lock_fd)
        lock_path.unlink()


def review_score(row):
    if any(not row.get(f"{d}_0_20", "").strip() for d in DIMENSIONS):
        return None
    scores = [float(row[f"{d}_0_20"]) for d in DIMENSIONS]
    if any(not math.isfinite(v) or not 0 <= v <= 20 for v in scores):
        raise ValueError("review scores must be finite numbers between 0 and 20")
    critical = row.get("critical_error_yes_no", "").strip().lower()
    acceptable = row.get("acceptable_yes_no", "").strip().lower()
    if critical not in {"yes", "no"} or acceptable not in {"yes", "no"}:
        return None
    return {"score": sum(scores), "critical": critical == "yes",
            "human_accepted": acceptable == "yes" and critical == "no" and sum(scores) >= 80}


def configuration_fingerprint(event):
    return digest({"model_config": event["model_config"], "request_policy": event.get("request_policy")})


def paired_comparisons(events, reviews):
    """Use trial 1 only; reject ambiguous reruns or mismatched inputs."""
    by_case = {}
    for event in events:
        if event["trial"] == 1:
            key = (event["case_id"], event["kind"], event.get("split"), event["group"])
            by_case.setdefault(key, {}).setdefault(event["alias"], []).append(event)
    pairs, excluded = [], []
    for key, models in sorted(by_case.items()):
        if "baseline" not in models:
            continue
        for alias, candidates in sorted(models.items()):
            if alias == "baseline":
                continue
            if len(models["baseline"]) != 1 or len(candidates) != 1:
                excluded.append({"case_id": key[0], "alias": alias, "reason": "multiple_configurations_for_same_case"})
                continue
            baseline, candidate = models["baseline"][0], candidates[0]
            signature = lambda e: (e["prompt_sha256"], [i["submitted_sha256"] for i in e["sources"]])
            if signature(baseline) != signature(candidate):
                excluded.append({"case_id": key[0], "alias": alias, "reason": "different_inputs_or_prompt"})
                continue
            a = review_score(reviews[baseline["blind_id"]]) if baseline["blind_id"] in reviews else None
            b = review_score(reviews[candidate["blind_id"]]) if candidate["blind_id"] in reviews else None
            if a is None or b is None:
                continue
            pairs.append({"case_id": key[0], "kind": key[1], "split": key[2], "group": key[3],
                          "alias": alias, "baseline_configuration": configuration_fingerprint(baseline),
                          "candidate_configuration": configuration_fingerprint(candidate),
                          "baseline_accepted": a["human_accepted"] and baseline.get("status") == "ok",
                          "candidate_accepted": b["human_accepted"] and candidate.get("status") == "ok",
                          "baseline_score": a["score"], "candidate_score": b["score"],
                          "score_outcome": "win" if b["score"] > a["score"] else "loss" if b["score"] < a["score"] else "tie"})
    return pairs, excluded


def make_report(output):
    output = Path(output)
    states = load_states(output / "ledger.jsonl")
    rows = list(states.values())
    reviews_path = output / "reviews.csv"
    reviews = {}
    if reviews_path.exists():
        with reviews_path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["blind_id"] in reviews:
                    raise ValueError("duplicate blind ID in reviews.csv")
                reviews[row["blind_id"]] = row
    packets = []
    for event in rows:
        packets.append({"blind_id": event["blind_id"], "case_id": event["case_id"],
                        "kind": event["kind"], "group": event["group"], "split": event.get("split"),
                        "manifest_dir": event["manifest_dir"], "images": event["case"]["images"],
                        "note": event["case"].get("note", ""), "reference": event["case"]["reference"],
                        "response_text": event.get("response_text", "")})
        errata_path = Path(event["manifest_dir"]) / "reference_errata.json"
        if errata_path.exists():
            correction = read_json(errata_path).get("cases", {}).get(event["case_id"])
            if correction:
                packets[-1]["reference_errata"] = correction
    random.Random(20261104).shuffle(packets)
    write_json(output / "blind_review.json", packets)
    write_json(output / "private_mapping.json", [{"blind_id": e["blind_id"], "alias": e["alias"],
                                                  "model": e["model"], "trial": e["trial"]} for e in rows])
    with reviews_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for packet in packets:
            writer.writerow({k: reviews.get(packet["blind_id"], {}).get(k, packet["blind_id"] if k == "blind_id" else "") for k in REVIEW_FIELDS})
    groups = {}
    for e in rows:
        # Keep synthetic/real and dev/holdout results separate.
        key = (e["alias"], configuration_fingerprint(e), e["kind"], e.get("split", "unspecified"), e["group"])
        groups.setdefault(key, []).append(e)
    aggregates = []
    for key, events in sorted(groups.items()):
        scored = [(e, review_score(reviews[e["blind_id"]])) for e in events if e["blind_id"] in reviews]
        scored = [(e, s) for e, s in scored if s is not None]
        accepted = sum(s["human_accepted"] and e.get("status") == "ok" for e, s in scored)
        known_cost = sum(e.get("estimated_usd", 0) for e in events)
        unknown = sum(e.get("usage") is None for e in events)
        latencies = sorted(e["latency_seconds"] for e in events if "latency_seconds" in e)
        complete_review = len(scored) == len(events)
        aggregates.append({"alias": key[0], "configuration_sha256": key[1], "kind": key[2], "split": key[3], "group": key[4],
                           "attempts": len(events),
                           "ok_structure_and_finish": sum(bool(e.get("structured")) and e.get("finish_reason") == "stop" for e in events),
                           "ok_output_contract": sum(e.get("status") == "ok" for e in events),
                           "body_length_checked": sum(e.get("body_chars") is not None for e in events),
                           "body_length_passed": sum(e.get("body_length_ok") is True for e in events),
                           "same_response_read_recoveries": sum(e.get("recovered_via_same_response_id") is True for e in events),
                           "reviewed": len(scored), "accepted": accepted,
                           "mean_review_score": statistics.mean(s["score"] for _, s in scored) if scored else None,
                           "critical_errors": sum(s["critical"] for _, s in scored),
                           "known_usage_estimated_usd": money(known_cost), "unknown_usage_attempts": unknown,
                           "estimated_usd_per_accepted": money(known_cost / accepted) if complete_review and accepted and not unknown else None,
                           "median_latency_s": statistics.median(latencies) if latencies else None,
                           "p95_latency_s_nearest_rank": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None})
    pairs, excluded = paired_comparisons(rows, reviews)
    provider_costs = {}
    for event in rows:
        provider = provider_costs.setdefault(event["provider"], {"known_usage_estimated_usd": 0, "unknown_usage_attempts": 0})
        provider["known_usage_estimated_usd"] = money(provider["known_usage_estimated_usd"] + event.get("estimated_usd", 0))
        provider["unknown_usage_attempts"] += event.get("usage") is None
    summary = {"created_at": utc_now(), "attempts": len(rows), "held_budget_usd": held_usd(states),
               "groups": aggregates, "paired_cases_trial_1": pairs, "excluded_pairs": excluded,
               "provider_costs": provider_costs,
               "review_methods": sorted({row.get("review_method", "unspecified") or "unspecified" for row in reviews.values()}),
               "scientific_quality_is_human_reviewed": bool(rows) and all(
                   reviews.get(e["blind_id"], {}).get("review_method") == "human" and
                   review_score(reviews[e["blind_id"]]) is not None for e in rows),
               "independent_expert_review_required": True,
               "costs_are_list_price_estimates_not_invoices": True,
               "baseline_costs_are_not_paid_from_openai_credits": True}
    write_json(output / "summary.json", summary)
    return summary


def create_demo(target):
    from PIL import Image, ImageDraw, ImageFont
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise ValueError("demo directory is not empty; choose a new directory")
    target.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    def canvas(title):
        image = Image.new("RGB", (1000, 650), "white")
        draw = ImageDraw.Draw(image)
        draw.text((35, 18), "SYNTHETIC TEST FIXTURE / NOT OBSERVATIONS", font=font, fill="black")
        draw.text((35, 58), title, font=font, fill="black")
        return image, draw
    image, draw = canvas("Temperature / deg C / 2026-10-23 / UTC+8")
    draw.line([(100, 130), (100, 550), (920, 550)], fill="black", width=3)
    for value in (20, 25, 30, 35, 40, 45):
        y = 550 - (value - 20) * 15
        draw.text((40, y - 12), str(value), font=font, fill="black")
        draw.line([(100, y), (920, y)], fill="#dddddd")
    points = [(140, 475), (380, 475), (620, 235), (860, 475)]
    draw.line(points, fill="#c00000", width=5)
    for (x, y), hour in zip(points, (0, 6, 12, 18)):
        draw.ellipse((x-5, y-5, x+5, y+5), fill="#c00000")
        draw.text((x-20, 565), f"{hour:02d}:00", font=font, fill="black")
    draw.text((630, 195), "41 deg C", font=font, fill="black")
    image.save(target / "curve.png")
    image, draw = canvas("Schematic pressure / hPa / 2026-10-23 08:00 UTC")
    for center, value, color in ((280, "L 1000", "#1454bd"), (750, "H 1020", "#c3382d")):
        for radius in (70, 120, 170):
            draw.ellipse((center-radius, 350-radius, center+radius, 350+radius), outline=color, width=3)
        draw.text((center-45, 335), value, font=font, fill=color)
    draw.text((35, 595), "North is up. No wind or temperature field is provided.", font=font, fill="black")
    image.save(target / "pressure.png")
    for name, hour, maximum, center, legend in (("frame_a", "08:00", 30, 300, True),
                                              ("frame_b", "09:00", 50, 650, True),
                                              ("no_legend", "08:00", 30, 300, False)):
        image, draw = canvas(f"Schematic radar / 2026-10-23 {hour} UTC / North up")
        draw.rectangle((80, 140, 900, 540), outline="black", width=3)
        draw.ellipse((center-90, 240, center+90, 420), fill="#e43a20")
        draw.text((100, 495), "WEST", font=font, fill="black")
        draw.text((780, 495), "EAST", font=font, fill="black")
        if legend:
            draw.rectangle((100, 580, 145, 610), fill="#e43a20")
            draw.text((160, 578), f"Patch reflectivity: {maximum} dBZ", font=font, fill="black")
        image.save(target / f"{name}.png")
    definitions = [
        ("demo_curve", "curve", ["curve.png"], ["Maximum is explicitly labeled 41 deg C at 12:00 UTC+8.", "Other three values are 25 deg C."], ["A real heat warning or a climate trend."]),
        ("demo_pressure", "synoptic", ["pressure.png"], ["Left low center 1000 hPa; right high center 1020 hPa.", "Wind and temperature are not supplied."], ["Observed precipitation, fronts or a weather forecast."]),
        ("demo_sequence", "multi", ["frame_a.png", "frame_b.png"], ["08:00 to 09:00 UTC: patch shifts west to east and changes 30 to 50 dBZ."], ["An exact rainfall amount from reflectivity alone."]),
        ("demo_missing_legend", "radar", ["no_legend.png"], ["No legend or reflectivity unit/value is visible.", "Single time cannot establish motion."], ["A numerical dBZ value inferred just from the red color."]),
        ("demo_reverse_order", "multi", ["frame_b.png", "frame_a.png"], ["Chronological order follows visible timestamps, not input order.", "08:00 to 09:00 UTC: west to east; 30 to 50 dBZ."], ["East to west motion caused by upload order."]),
        ("demo_mixed_timezones", "multi", ["curve.png", "pressure.png"], ["Temperature uses UTC+8; pressure uses UTC.", "The two variables do not demonstrate a causal connection."], ["Treating labels as one common timezone or claiming pressure caused the temperature peak."])
    ]
    cases = [{"id": identity, "kind": "synthetic", "group": group, "split": "dev", "status": "ready",
              "reference_reviewed": True, "images": images, "note": "请按图中时间标注比较，保留单位与时区。",
              "reference": {"required_facts": facts, "forbidden_inferences": forbidden}}
             for identity, group, images, facts, forbidden in definitions]
    manifest = target / "manifest.json"
    write_json(manifest, {"schema_version": 1, "purpose": "Synthetic pipeline fixtures, not professional capability evidence", "cases": cases})
    return manifest


def create_template(target):
    cases = []
    for group, count, dev in (("curve", 4, 1), ("synoptic", 6, 2), ("radar", 4, 1),
                              ("satellite", 4, 1), ("multi", 6, 1)):
        for index in range(1, count + 1):
            identity = f"{group}_{index:02d}"
            cases.append({"id": identity, "kind": "public", "group": group,
                          "split": "dev" if index <= dev else "holdout", "status": "pending",
                          "reference_reviewed": False, "images": [f"images/{identity}.png"],
                          "source_url": "", "source_accessed_at": "", "note": "",
                          "reference": {"required_facts": [], "forbidden_inferences": [],
                                        "numeric_tolerances": [], "reviewer": ""}})
    path = Path(target)
    if path.exists():
        raise ValueError("template target already exists")
    write_json(path, {"schema_version": 1, "purpose": "24-case real-image comparison; populate and review before use", "cases": cases})
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "template"):
        p = sub.add_parser(name)
        p.add_argument("--out", required=True)
    p = sub.add_parser("run")
    p.add_argument("--manifest", required=True)
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--models", nargs="+", help="Model aliases; default comes from config (Sol high)")
    p.add_argument("--cases", nargs="+")
    p.add_argument("--split", choices=["dev", "holdout"])
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--out", default=str(ROOT / ".vision-poc" / "study"))
    p.add_argument("--budget-usd", type=float, default=10)
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, choices=[1, 2], default=1, help="At most two network requests; reservations stay serialized")
    p.add_argument("--live", action="store_true", help="Actually send paid API requests; absent means offline only")
    p = sub.add_parser("report")
    p.add_argument("--out", default=str(ROOT / ".vision-poc" / "study"))
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            print(create_demo(args.out))
        elif args.command == "template":
            print(create_template(args.out))
        elif args.command == "report":
            summary = make_report(args.out)
            print(f"Report: {summary['attempts']} attempts; human review required for quality conclusions.")
        else:
            if args.limit is not None and args.limit <= 0:
                raise ValueError("limit must be positive")
            config = read_json(args.config)
            aliases = args.models if args.models is not None else config.get("default_models", ["sol"])
            if not isinstance(aliases, list) or not aliases or any(not isinstance(alias, str) for alias in aliases):
                raise ValueError("default_models must be a nonempty list of model aliases")
            jobs = build_jobs(args.manifest, config, aliases, args.cases, args.repeat, args.split)
            for job in jobs:
                job["manifest_dir"] = str(Path(args.manifest).resolve().parent)
            plan = write_plan(jobs, args.out)
            print(f"Offline plan: {len(jobs)} jobs; summed conservative reservations USD {plan['sum_reservations_usd']:.4f}.")
            if args.live:
                count = run_live(jobs, config, args.out, args.budget_usd, args.limit, workers=args.workers)
                make_report(args.out)
                print(f"New API attempts: {count}.")
            else:
                print("DRY RUN: no API request sent; credentials were not read.")
        return 0
    except (ValueError, KeyError, OSError) as exc:
        # Exceptions generated by this tool contain paths/field names only.
        # Network exceptions are handled without their message in run_live.
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
