"""Offline tests of selected profiles, single-submission jobs and the workbench UI."""
import io
import json
from pathlib import Path
from unittest.mock import Mock

from PIL import Image
import pytest
import requests

from modules import vision_service as svc
from modules import chart_reader, ai_narrative
from modules.ai_report_model import SECTION_TITLES


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("BASELINE_VISION_API_KEY", "offline-qwen-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(requests.Session, "request", Mock(side_effect=AssertionError("Real HTTP blocked in offline test")))


@pytest.fixture
def images():
    b = io.BytesIO()
    Image.new("RGB", (500, 320), "white").save(b, format="PNG")
    return [chart_reader.process_image(b.getvalue(), "weather.png")]


def visible_text(chars=900, invalid_ref=False):
    return json.dumps({"schema_version": 1,
        "findings": [{"id": "F1", "text": "可见标注", "kind": "visible", "evidence_ids": ["bad" if invalid_ref else "E1"], "limitation_ids": []}],
        "evidence": [{"id": "E1", "image_id": "img_1", "location": "左上", "feature": "标题"}],
        "limitations": [{"id": "L1", "missing": "时效", "impact": "不能预测", "next_input": "时次"}],
        "sections": [{"title": t, "body": "测" * (chars // 6 + (i < chars % 6))} for i, t in enumerate(SECTION_TITLES)]}, ensure_ascii=False)


class Response:
    status_code = 200
    headers = {"x-request-id": "offline-request"}
    def __init__(self, status="queued", text=None, response_id="resp_offline", usage=None):
        self.data = {"id": response_id, "status": status,
            "output": [{"type": "reasoning", "content": [{"text": "INTERNAL_REASONING_NEVER_STORE"}]},
                       {"type": "message", "content": [{"type": "output_text", "text": text or ""}]}],
            "usage": usage}
        self.content = json.dumps(self.data).encode()
    def json(self): return self.data


def completed(chars=900, invalid_ref=False, status="completed"):
    return Response(status, visible_text(chars, invalid_ref), usage={"input_tokens": 100, "output_tokens": 200,
        "total_tokens": 300, "output_tokens_details": {"reasoning_tokens": 120}})


@pytest.mark.parametrize("profile,model,effort", [("terra", "gpt-6.1-terra", "xhigh"), ("sol", "gpt-6.1-sol", "high")])
def test_profile_maps_to_exact_model_and_effort(profile, model, effort):
    cfg = ai_narrative.resolve_vision_config(profile=profile)
    assert (cfg["model"], cfg["reasoning_effort"], cfg["output_cap"]) == (model, effort, 32768)
    assert cfg["base_url"] == "https://api.openai.com/v1" and cfg["read_timeout_seconds"] == 180


def test_openai_credentials_never_fall_back_to_qwen(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    fake = {"LLM_VISION_MODEL": "qwen3.8-flash", "LLM_VISION_API_KEY": "qwen-only", "LLM_VISION_BASE_URL": "https://dashscope.aliyuncs.com"}
    assert svc.resolve_config("terra", secret_getter=fake.get, env_path=tmp_path / "absent") is None
    path = tmp_path / ".env.local"
    path.write_text("OPENAI_API_KEY=local-test-key\nBASELINE_VISION_API_KEY=qwen-only\n")
    cfg = svc.resolve_config("terra", env_path=path)
    assert cfg["api_key"] == "local-test-key" and cfg["model"] == "gpt-6.1-terra"
    assert svc.resolve_config("terra", secret_getter={"OPENAI_API_KEY": "secret-test-key"}.get, env_path=path)["api_key"] == "secret-test-key"


@pytest.mark.parametrize("profile", ["terra", "sol"])
def test_submission_is_reserved_durably_and_never_repeated(tmp_path, monkeypatch, images, profile):
    store, calls = svc.JobStore(tmp_path), []
    cfg = svc.resolve_config(profile)
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        job = store.load("u1", "call1")
        assert job["status"] == "submitting"
        assert "api_key" not in job and "data_bytes" not in json.dumps(job)
        assert kwargs["timeout"] == (10, 180) and kwargs["allow_redirects"] is False
        assert url == "https://api.openai.com/v1/responses"
        return Response()
    monkeypatch.setattr(requests, "post", post)
    store.submit("u1", "call1", cfg, svc.build_prompt(images), images, 60000, "fp")
    with pytest.raises(FileExistsError):
        store.submit("u1", "call1", cfg, svc.build_prompt(images), images, 60000, "fp")
    assert len(calls) == 1
    payload = calls[0]
    assert payload["model"] == cfg["model"] and payload["reasoning"] == {"effort": cfg["reasoning_effort"]}
    assert payload["max_output_tokens"] == 32768 and "temperature" not in payload and "max_tokens" not in payload
    assert payload["text"]["format"]["strict"] and payload["text"]["format"]["type"] == "json_schema"
    assert payload["input"][1]["content"][1]["type"] == "input_image"
    assert "offline-test-key" not in next(tmp_path.rglob("*.json")).read_text(encoding="utf-8")
    assert "INTERNAL_REASONING_NEVER_STORE" not in next(tmp_path.rglob("*.json")).read_text(encoding="utf-8")


def test_restart_retrieves_same_response_after_temporary_get_error(tmp_path, monkeypatch, images):
    post = Mock(return_value=Response())
    monkeypatch.setattr(requests, "post", post)
    store = svc.JobStore(tmp_path)
    cfg = svc.resolve_config("terra")
    store.submit("u1", "call1", cfg, svc.build_prompt(images), images, 2000, "fp")
    restored = svc.JobStore(tmp_path)
    assert restored.waiting("u1")[0]["response_id"] == "resp_offline"
    get = Mock(side_effect=[requests.exceptions.SSLError("offline-test-key must not leak"), completed()])
    monkeypatch.setattr(requests, "get", get)
    assert restored.poll("u1", "call1", cfg)["status"] == "queued"
    job = restored.poll("u1", "call1", cfg)
    assert job["status"] == "completed" and job["output_contract"] == "ok"
    assert job["usage"] == {"prompt": 100, "completion": 200, "reasoning": 120, "total": 300}
    restored.poll("u1", "call1", cfg)
    assert post.call_count == 1 and get.call_count == 2
    assert "INTERNAL_REASONING_NEVER_STORE" not in next(tmp_path.rglob("*.json")).read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError): restored.load("other-user", "call1")
    with pytest.raises(ValueError): restored.load("u1", "../call1")


def test_unknown_submission_retains_job_without_resubmitting(tmp_path, monkeypatch, images):
    monkeypatch.setattr(requests, "post", Mock(side_effect=requests.Timeout("offline-test-key")))
    store = svc.JobStore(tmp_path)
    job = store.submit("u1", "call1", svc.resolve_config("terra"), svc.build_prompt(images), images, 2000, "fp")
    assert job["status"] == "unknown" and job["usage"] == {} and not job["settled"]
    assert store.waiting("u1") and "offline-test-key" not in next(tmp_path.rglob("*.json")).read_text(encoding="utf-8")
    assert store.poll("u1", "call1", svc.resolve_config("terra"))["response_id"] is None


@pytest.mark.parametrize("chars,invalid_ref,status,contract", [
    (799,False,"completed","body_length_failed"), (800,False,"completed","ok"),
    (2000,False,"completed","ok"), (2001,False,"completed","body_length_failed"),
    (900,True,"completed","invalid_structure"), (900,False,"incomplete","truncated"),
    (900,False,"failed","response_failed")])
def test_output_validation_preserves_known_usage_without_paid_repair(tmp_path, monkeypatch, images, chars, invalid_ref, status, contract):
    post = Mock(return_value=completed(chars, invalid_ref, status))
    monkeypatch.setattr(requests, "post", post)
    job = svc.JobStore(tmp_path).submit("u1", "call1", svc.resolve_config("terra"), svc.build_prompt(images), images, 3000, "fp")
    assert job["output_contract"] == contract and job["usage"]["total"] == 300
    assert post.call_count == 1


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": 100}, {"input_tokens": True, "output_tokens": 2},
    {"input_tokens": 1, "output_tokens": 2, "total_tokens": 5},
    {"input_tokens": 1, "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 3}}])
def test_missing_or_inconsistent_usage_stays_unknown(usage):
    assert svc.normalize_usage(usage) == {}


@pytest.mark.parametrize("profile", ["terra", "sol"])
def test_ui_selection_generation_retrieval_and_render_do_not_duplicate_calls(tmp_path, monkeypatch, images, profile):
    import db
    from streamlit.testing.v1 import AppTest
    original_store = svc.JobStore
    monkeypatch.setattr(svc, "JobStore", lambda: original_store(tmp_path))
    monkeypatch.setattr(db, "get_vision_quota", lambda: {"tokens_limit": 80000, "tokens_used": 0, "calls_limit": 10, "calls_used": 0, "calls_remaining": 10, "tokens_remaining": 80000})
    begin = Mock(return_value={"allowed": True, "call_id": "ui-call", "reserved_tokens": 80000})
    settle = Mock(return_value={"ok": True})
    monkeypatch.setattr(db, "begin_vision_call", begin)
    monkeypatch.setattr(db, "record_vision_usage", settle)
    post = Mock(return_value=Response())
    get = Mock(return_value=Response())
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    at = AppTest.from_string("from modules.chart_reader import render_chart_reader_tab\nrender_chart_reader_tab()", default_timeout=30)
    at.session_state["auth_user"] = {"id": "u1"}
    at.session_state["chart_reader_images"] = images
    at.run()
    assert not at.exception
    assert at.selectbox(key="chart_reader_model_profile").value == "qwen"
    assert any("Qwen" in v for v in at.selectbox(key="chart_reader_model_profile").options)
    at.selectbox(key="chart_reader_model_profile").select("sol").run()
    assert post.call_count == 0 and begin.call_count == 0
    at.selectbox(key="chart_reader_model_profile").select(profile).run()
    at.button(key="chart_reader_generate").click().run()
    assert not at.exception and post.call_count == 1 and begin.call_count == 1
    assert post.call_args.kwargs["json"]["model"] == svc.PROFILES[profile]["model"]
    assert at.button(key="chart_reader_generate").disabled
    at.selectbox(key="chart_reader_model_profile").select("terra" if profile == "sol" else "sol").run()
    get.return_value = completed()
    at.button(key="chart_reader_poll_job").click().run()
    assert not at.exception
    assert svc.PROFILES[profile]["model"] in at.session_state["chart_reader_meta"]["scope"]
    assert at.session_state["chart_reader_result"]["structured"]
    assert at.session_state["chart_reader_usage_total"]["total"] == 300
    assert at.session_state["chart_reader_report_images"][0]["data_bytes"] == images[0]["data_bytes"]
    gets = get.call_count
    at.run()
    assert post.call_count == 1 and get.call_count == gets and settle.call_count == 1
    assert not at.exception


def test_denied_quota_prevents_any_generation(tmp_path, monkeypatch, images):
    import db
    import streamlit as st
    original_store = svc.JobStore
    monkeypatch.setattr(svc, "JobStore", lambda: original_store(tmp_path))
    monkeypatch.setattr(st, "session_state", {"auth_user": {"id": "u1"}})
    monkeypatch.setattr(st, "error", Mock())
    monkeypatch.setattr(db, "begin_vision_call", lambda: None)
    post = Mock(side_effect=AssertionError("No paid request without a reservation"))
    monkeypatch.setattr(requests, "post", post)
    chart_reader._generate(svc.resolve_config("terra"), images, "")
    assert post.call_count == 0


def test_qwen_is_default_and_uses_independent_credentials():
    cfg = svc.resolve_config()
    assert svc.DEFAULT_PROFILE == "qwen"
    assert cfg["model"] == "qwen3.8-flash" and cfg["api_key"] == "offline-qwen-key"
    assert cfg["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg["api_format"] == "chat_completions" and cfg["stream"]
    assert svc.resolve_config("terra")["api_key"] == "offline-test-key"


class QwenResponse:
    status_code = 200
    text = ""
    def __init__(self, finish="stop", end=True): self.finish, self.end = finish, end
    def raise_for_status(self): pass
    def close(self): pass
    def iter_lines(self, **kwargs):
        yield b'data: {"choices":[{"delta":{"reasoning_content":"INTERNAL_REASONING_NEVER_STORE"}}]}'
        yield ("data: " + json.dumps({"choices": [{"delta": {"content": visible_text()}, "finish_reason": self.finish}]})).encode()
        yield b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":200,"total_tokens":300,"completion_tokens_details":{"reasoning_tokens":120}}}'
        if self.end: yield b'data: [DONE]'


@pytest.mark.parametrize("finish,end,ok", [("stop",True,True), ("length",True,False), ("stop",False,False)])
def test_qwen_stream_preserves_usage_and_never_resubmits(monkeypatch, finish, end, ok):
    post = Mock(return_value=QwenResponse(finish, end))
    monkeypatch.setattr(requests, "post", post)
    usage = {}
    def call():
        return ai_narrative.call_vision_llm("JSON", ["data:image/png;base64,AAAA"], "offline-qwen-key",
            "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.8-flash", 32768, usage, stream=True, read_timeout=180)
    if ok:
        assert "INTERNAL_REASONING_NEVER_STORE" not in call()
    else:
        with pytest.raises(ValueError): call()
    assert usage["total"] == 300 and usage["reasoning"] == 120
    assert post.call_count == 1 and post.call_args.kwargs["json"]["max_tokens"] == 32768
    assert post.call_args.kwargs["json"]["stream_options"] == {"include_usage": True}


def test_qwen_default_generation_uses_qwen_without_openai_call(tmp_path, monkeypatch, images):
    import db
    from streamlit.testing.v1 import AppTest
    original_store = svc.JobStore
    monkeypatch.setattr(svc, "JobStore", lambda: original_store(tmp_path))
    monkeypatch.setattr(db, "get_vision_quota", lambda: {"calls_remaining": 10, "tokens_remaining": 80000})
    monkeypatch.setattr(db, "begin_vision_call", lambda: {"allowed": True, "call_id": "qwen-ui", "reserved_tokens": 80000})
    settle = Mock(return_value={"ok": True})
    monkeypatch.setattr(db, "record_vision_usage", settle)
    post = Mock(return_value=QwenResponse())
    monkeypatch.setattr(requests, "post", post)
    at = AppTest.from_string("from modules.chart_reader import render_chart_reader_tab\nrender_chart_reader_tab()", default_timeout=30)
    at.session_state["auth_user"] = {"id": "u1"}
    at.session_state["chart_reader_images"] = images
    at.run()
    at.button(key="chart_reader_generate").click().run()
    assert not at.exception
    assert at.session_state["chart_reader_result_profile"] == "qwen"
    assert "qwen3.8-flash" in at.session_state["chart_reader_meta"]["scope"]
    assert post.call_count == 1 and post.call_args.args[0].startswith("https://dashscope.aliyuncs.com/")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer offline-qwen-key"
    assert at.session_state["chart_reader_usage_total"]["total"] == 300
    at.run()
    assert post.call_count == 1 and settle.call_count == 1
