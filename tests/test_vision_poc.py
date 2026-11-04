"""Offline tests: real preprocessing, synthetic responses, no provider traffic."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from tools import vision_poc as poc


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch):
    import requests
    def blocked(*args, **kwargs):
        raise AssertionError("Offline test attempted a real HTTP request")
    monkeypatch.setattr(requests.Session, "request", blocked)


@pytest.fixture
def setup(tmp_path):
    manifest = poc.create_demo(tmp_path / "images")
    config = poc.read_json(poc.DEFAULT_CONFIG)
    config["live_before"] = "2099-01-01T00:00:00+00:00"
    jobs = poc.build_jobs(manifest, config, ["sol"])
    for job in jobs:
        job["manifest_dir"] = str(manifest.parent)
    return manifest, config, jobs, tmp_path / "results"


def valid_receipt(body_chars=900):
    from modules.ai_report_model import SECTION_TITLES
    text = json.dumps({"schema_version": 1,
                       "evidence": [{"id": "E1", "image_id": "img_1", "location": "title", "feature": "synthetic"}],
                       "limitations": [{"id": "L1", "missing": "real observations", "impact": "no forecast", "next_input": "observations"}],
                       "findings": [{"id": "F1", "text": "Synthetic fixture", "kind": "visible", "evidence_ids": ["E1"], "limitation_ids": []}],
                       "sections": [{"title": title, "body": "测" * (body_chars // 6 + (index < body_chars % 6))}
                                    for index, title in enumerate(SECTION_TITLES)]})
    return {"data": {"usage": {"prompt_tokens": 1000, "completion_tokens": 500,
                               "completion_tokens_details": {"reasoning_tokens": 300}},
                     "choices": [{"message": {"content": text}, "finish_reason": "stop"}]}}


def test_default_cli_never_reads_credentials_or_calls_network(setup, monkeypatch):
    manifest, _, _, output = setup
    def forbidden(*args, **kwargs):
        raise AssertionError("Network call attempted during dry run")
    monkeypatch.setattr(poc, "request_once", forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert poc.main(["run", "--manifest", str(manifest), "--out", str(output)]) == 0
    plan = poc.read_json(output / "plan.json")
    assert len(plan["jobs"]) == 6
    assert {j["alias"] for j in plan["jobs"]} == {"sol"}
    assert all(j["reasoning_effort"] == "high" and j["output_cap"] == 32768 for j in plan["jobs"])
    assert all(j["request_policy"] == {"read_timeout_seconds": 180, "body_min_chars": 800, "body_max_chars": 2000} for j in plan["jobs"])
    assert plan["sum_reservations_usd"] == pytest.approx(6 * .49152)
    assert not (output / "ledger.jsonl").exists()
    assert "base64" not in (output / "plan.json").read_text(encoding="utf-8")


def test_resume_does_not_repeat_success_or_uncertain_request(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    calls = []
    def interrupted(job):
        calls.append(job["job_id"])
        raise TimeoutError("Bearer fake-offline-key; request data must never be logged")
    assert poc.run_live(jobs, config, output, 1, request_fn=interrupted) == 1
    states = poc.load_states(output / "ledger.jsonl")
    assert poc.held_usd(states) == jobs[0]["reservation_usd"]
    assert "fake-offline-key" not in (output / "ledger.jsonl").read_text(encoding="utf-8")
    assert poc.run_live(jobs[:1], config, output, 1, request_fn=interrupted) == 0
    assert len(calls) == 1


def test_budget_is_reserved_before_provider_request(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    calls = []
    def provider(job):
        states = poc.load_states(output / "ledger.jsonl")
        assert states[job["job_id"]]["state"] == "started"
        calls.append(job["job_id"])
        return valid_receipt()
    assert poc.run_live(jobs, config, output, .01, request_fn=provider) == 0
    assert calls == []
    assert poc.run_live(jobs, config, output, 1, limit=1, request_fn=provider) == 1
    assert poc.run_live(jobs[:1], config, output, 1, request_fn=provider) == 0
    assert len(calls) == 1


def test_stale_lock_and_started_event_fail_closed(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    output.mkdir()
    (output / "run.lock").write_text("123")
    with pytest.raises(ValueError, match="run.lock"):
        poc.run_live(jobs, config, output, 1)
    (output / "run.lock").unlink()
    poc.append_event(output / "ledger.jsonl", {"job_id": jobs[0]["job_id"], "state": "started", "reservation_usd": .9})
    assert poc.run_live(jobs[:1], config, output, 1, request_fn=lambda _: pytest.fail("duplicate")) == 0
    assert poc.held_usd(poc.load_states(output / "ledger.jsonl")) == .9


def test_reasoning_is_subset_and_malformed_usage_remains_unknown():
    usage = poc.normalize_usage({"prompt_tokens": 921, "completion_tokens": 2096,
                                 "completion_tokens_details": {"reasoning_tokens": 1836}})
    assert usage["total"] == 3017
    assert poc.normalize_usage({"total_tokens": 3017}) is None
    assert poc.normalize_usage({"prompt_tokens": True, "completion_tokens": 2}) is None
    assert poc.normalize_usage({"prompt_tokens": 1, "completion_tokens": 2,
                                "completion_tokens_details": {"reasoning_tokens": 3}}) is None


def test_expiry_blocks_calls_even_with_credentials(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    config["live_before"] = "2000-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="window closed"):
        poc.run_live(jobs, config, output, 1, request_fn=lambda _: pytest.fail("expired call"))
    assert not (output / "ledger.jsonl").exists()
    config["live_before"] = "2026-11-14T00:00:00+08:00"
    with pytest.raises(ValueError, match="window closed"):
        poc.check_live_window(config, datetime(2026, 11, 13, 16, tzinfo=timezone.utc))


def test_references_do_not_reach_payload_and_gpt6_parameters_are_adapted(setup, monkeypatch):
    import requests
    _, _, jobs, _ = setup
    jobs[0]["model_config"] = {**jobs[0]["model_config"], "api_format": "chat_completions", "stream": True}
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    jobs[0]["case"]["reference"] = {"answer": "SECRET_GROUND_TRUTH"}
    captured = {}
    class Response:
        headers = {"x-request-id": "test-id"}
        status_code = 200
        content = b"{}"
        def json(self):
            return valid_receipt()["data"]
        def iter_lines(self, **kwargs):
            data = valid_receipt()["data"]
            yield ("data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": data["choices"][0]["message"]["content"]}, "finish_reason": "stop"}]})).encode()
            yield ("data: " + json.dumps({"choices": [], "usage": data["usage"]})).encode()
            yield b"data: [DONE]"
    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return Response()
    monkeypatch.setattr(requests, "post", fake_post)
    receipt = poc.request_once(jobs[0])
    assert receipt["request_id"] == "test-id"
    payload = captured["json"]
    assert "SECRET_GROUND_TRUTH" not in json.dumps(payload)
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 32768
    assert payload["reasoning_effort"] == "high"
    assert captured["timeout"] == (10, 180)
    prompt = payload["messages"][1]["content"][0]["text"]
    assert "800—2000" in prompt
    assert payload["stream"] is True and payload["stream_options"] == {"include_usage": True}
    assert captured["allow_redirects"] is False


def test_report_separates_synthetic_and_real_and_rejects_critical_error(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    poc.run_live(jobs[:1], config, output, 1, request_fn=lambda _: valid_receipt())
    summary = poc.make_report(output)
    assert summary["groups"][0]["accepted"] == 0
    assert summary["groups"][0]["estimated_usd_per_accepted"] is None
    with (output / "reviews.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0].update({f"{d}_0_20": "20" for d in poc.DIMENSIONS})
    rows[0].update(critical_error_yes_no="yes", acceptable_yes_no="yes")
    with (output / "reviews.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=poc.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = poc.make_report(output)
    group = summary["groups"][0]
    assert group["kind"] == "synthetic" and group["split"] == "dev"
    assert group["mean_review_score"] == 100
    assert group["critical_errors"] == 1 and group["accepted"] == 0
    assert "alias" not in poc.read_json(output / "blind_review.json")[0]


def test_pending_real_template_is_not_runnable_and_fixture_is_not_overwritten(tmp_path):
    path = poc.create_template(tmp_path / "real" / "manifest.json")
    cases = poc.read_json(path)["cases"]
    assert len(cases) == 24
    assert sum(c["split"] == "holdout" for c in cases) == 18
    with pytest.raises(ValueError, match="finalize"):
        poc.build_jobs(path, poc.read_json(poc.DEFAULT_CONFIG), ["terra"])
    demo = poc.create_demo(tmp_path / "demo")
    original = (demo.parent / "curve.png").read_bytes()
    with pytest.raises(ValueError, match="not empty"):
        poc.create_demo(demo.parent)
    assert (demo.parent / "curve.png").read_bytes() == original


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, 31])
def test_invalid_budget_never_calls_provider(setup, monkeypatch, invalid):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    with pytest.raises(ValueError, match="budget"):
        poc.run_live(jobs, config, output, invalid, request_fn=lambda _: pytest.fail("invalid budget"))


def test_image_path_escape_cannot_read_unlisted_local_files(setup):
    manifest, config, _, _ = setup
    value = poc.read_json(manifest)
    value["cases"][0]["images"] = ["../outside.png"]
    poc.write_json(manifest, value)
    with pytest.raises(ValueError, match="inside"):
        poc.build_jobs(manifest, config, ["terra"])


def test_paired_scores_require_identical_inputs_and_unambiguous_trial_1(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    poc.run_live(jobs[:1], config, output, 1, request_fn=lambda _: valid_receipt())
    event = next(iter(poc.load_states(output / "ledger.jsonl").values()))
    baseline = {**event, "alias": "baseline", "blind_id": "B1", "job_id": "baseline-job"}
    row = {**{f"{d}_0_20": "18" for d in poc.DIMENSIONS}, "critical_error_yes_no": "no", "acceptable_yes_no": "yes"}
    reviews = {event["blind_id"]: row, "B1": row}
    pairs, excluded = poc.paired_comparisons([baseline, event], reviews)
    assert len(pairs) == 1 and pairs[0]["score_outcome"] == "tie"
    changed = {**event, "prompt_sha256": "changed-prompt"}
    pairs, excluded = poc.paired_comparisons([baseline, changed], reviews)
    assert not pairs and excluded[0]["reason"] == "different_inputs_or_prompt"
    pairs, excluded = poc.paired_comparisons([baseline, event, changed], reviews)
    assert not pairs and excluded[0]["reason"] == "multiple_configurations_for_same_case"


def test_raw_credential_fields_cannot_be_recorded_in_config(setup):
    _, config, _, _ = setup
    model = {**config["models"]["terra"], "api_key": "must-not-be-logged"}
    with pytest.raises(ValueError, match="configuration fields"):
        poc.validate_model("terra", model)
    model.pop("api_key")
    model["key_env"] = "sk-proj-" + "offline-fixture-" * 4
    with pytest.raises(ValueError, match="environment variable"):
        poc.validate_model("terra", model)


@pytest.mark.parametrize("chars,expected", [(799, "body_length_failed"), (800, "ok"),
                                          (2000, "ok"), (2001, "body_length_failed")])
def test_body_length_boundaries_count_only_six_section_bodies(setup, chars, expected):
    _, _, jobs, _ = setup
    receipt = valid_receipt(chars)
    message = receipt["data"]["choices"][0]["message"]
    report = json.loads(message["content"])
    # Non-body fields and whitespace must not help a short body reach the minimum.
    report["evidence"][0]["feature"] = "证" * 900
    report["findings"][0]["text"] = "结" * 900
    for section in report["sections"]:
        section["body"] = "\n \t" + section["body"] + " \n"
    message["content"] = json.dumps(report)
    result = poc.interpret_response(receipt, jobs[0])
    assert result["structured"] is True
    assert result["body_chars"] == chars
    assert result["status"] == expected
    assert result["usage"]["total"] == 1500


def test_length_failure_is_charged_once_and_never_accepted_or_retried(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    calls = []
    def short_answer(job):
        calls.append(job["job_id"])
        return valid_receipt(799)
    assert poc.run_live(jobs[:1], config, output, 1, request_fn=short_answer) == 1
    assert poc.run_live(jobs[:1], config, output, 1, request_fn=short_answer) == 0
    assert len(calls) == 1
    event = next(iter(poc.load_states(output / "ledger.jsonl").values()))
    assert event["status"] == "body_length_failed" and event["estimated_usd"] > 0
    assert event["budget_charge_usd"] == poc.usage_budget_usd(event["usage"], jobs[0]["model_config"])
    poc.make_report(output)
    row = {"blind_id": event["blind_id"], **{f"{d}_0_20": "20" for d in poc.DIMENSIONS},
           "critical_error_yes_no": "no", "acceptable_yes_no": "yes"}
    with (output / "reviews.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=poc.REVIEW_FIELDS)
        writer.writeheader()
        writer.writerow(row)
    group = poc.make_report(output)["groups"][0]
    assert group["ok_structure_and_finish"] == 1
    assert group["ok_output_contract"] == 0
    assert group["body_length_checked"] == 1 and group["body_length_passed"] == 0
    assert group["accepted"] == 0


def test_sol_high_budget_blocks_old_small_reservation_and_covers_full_output(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    model = jobs[0]["model_config"]
    poc.validate_model("sol", model)
    assert jobs[0]["reservation_usd"] == pytest.approx(.49152)
    assert poc.run_live(jobs[:1], config, output, .49,
                        request_fn=lambda _: pytest.fail("insufficient reservation")) == 0
    usage = {"input": 32768, "output_including_reasoning": 32768, "reasoning_subset": 30000}
    assert poc.estimated_usage_usd(usage, model) == pytest.approx(.393216)
    assert poc.usage_budget_usd(usage, model) == pytest.approx(.49152)
    with pytest.raises(ValueError, match="output_cap"):
        poc.validate_model("sol", {**model, "output_cap": 32769})


def test_policy_change_changes_job_identity_and_report_cohort(setup):
    manifest, config, jobs, _ = setup
    changed_config = {**config, "request_policy": {**config["request_policy"], "read_timeout_seconds": 120}}
    changed_jobs = poc.build_jobs(manifest, changed_config, ["sol"])
    assert changed_jobs[0]["job_id"] != jobs[0]["job_id"]
    assert poc.configuration_fingerprint(changed_jobs[0]) != poc.configuration_fingerprint(jobs[0])


@pytest.mark.parametrize("policy", [{"body_min_chars": 2001, "body_max_chars": 2000},
                                    {"read_timeout_seconds": True}, {"read_timeout_seconds": 0},
                                    {"body_max_chars": "2000"}])
def test_invalid_request_policy_stops_before_requests(setup, policy):
    manifest, config, _, _ = setup
    config["request_policy"] = {**config["request_policy"], **policy}
    with pytest.raises(ValueError, match="body_min_chars|request policy"):
        poc.build_jobs(manifest, config, ["sol"])


def test_http_error_preserves_safe_provider_code_without_error_body(setup, monkeypatch):
    import requests
    _, _, jobs, _ = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    class Response:
        headers = {"x-request-id": "test-error-id"}
        status_code = 404
        def json(self):
            return {"error": {"code": "model_not_found", "type": "invalid_request_error",
                              "param": None, "message": "must-not-log: fake-offline-key"}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: Response())
    receipt = poc.request_once(jobs[0])
    assert receipt["provider_error_code"] == "model_not_found"
    assert receipt["request_id"] == "test-error-id"
    assert "fake-offline-key" not in json.dumps(receipt)


@pytest.mark.parametrize("completed", [True, False])
def test_stream_usage_is_preserved_and_reasoning_text_is_discarded(setup, completed):
    _, _, jobs, _ = setup
    data = valid_receipt()["data"]
    class Response:
        status_code = 200
        def iter_lines(self, **kwargs):
            yield b'data: {"choices":[{"index":0,"delta":{"reasoning_content":"DO_NOT_STORE_REASONING"}}]}'
            text = data["choices"][0]["message"]["content"]
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]})).encode()
            if completed:
                yield ("data: " + json.dumps({"choices": [], "usage": data["usage"]})).encode()
                yield b"data: [DONE]"
    receipt = poc.interpret_response(poc.consume_stream(Response(), "stream-id"), jobs[0])
    assert "DO_NOT_STORE_REASONING" not in json.dumps(receipt)
    assert receipt["status"] == ("ok" if completed else "stream_interrupted")
    assert (receipt["usage"] is not None) is completed


def test_two_workers_reserve_before_dispatch_and_settle_inflight_after_error(setup, monkeypatch):
    from threading import Barrier
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    barrier = Barrier(2)
    calls = []
    def provider(job):
        calls.append(job["job_id"])
        barrier.wait(timeout=5)
        states = poc.load_states(output / "ledger.jsonl")
        assert all(j["job_id"] in states for j in jobs[:2])
        assert poc.held_usd(states) <= 1
        if job["job_id"] == jobs[0]["job_id"]:
            raise TimeoutError("offline")
        return valid_receipt()
    assert poc.run_live(jobs, config, output, 1, limit=2, request_fn=provider, workers=2) == 2
    states = poc.load_states(output / "ledger.jsonl")
    assert len(calls) == 2 and all(e["state"] == "finished" for e in states.values())
    assert sum(e.get("status") == "request_or_parse_error" for e in states.values()) == 1


def test_concurrent_budget_waits_for_settlement_instead_of_overspending(setup, monkeypatch):
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    calls = []
    def provider(job):
        assert poc.held_usd(poc.load_states(output / "ledger.jsonl")) <= .6
        calls.append(job["job_id"])
        return valid_receipt()
    assert poc.run_live(jobs[:2], config, output, .6, request_fn=provider, workers=2) == 2
    assert len(calls) == 2


@pytest.mark.parametrize("transient_get_failure", [True, False])
def test_background_adapter_posts_once_checkpoints_then_polls_same_response(setup, monkeypatch, transient_get_failure):
    import requests
    _, _, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    job = jobs[0]
    job["model_config"] = {**job["model_config"], "api_format": "responses_background"}
    job["checkpoint_path"] = str(output / "checkpoint.json")
    visible = valid_receipt()["data"]["choices"][0]["message"]["content"]
    response_id = "resp_offline_123"
    bodies = [{"id": response_id, "status": "queued"},
              {"id": response_id, "status": "completed", "output": [{"type": "reasoning", "content": "DO_NOT_STORE"},
                 {"type": "message", "content": [{"type": "output_text", "text": visible}]}],
               "usage": {"input_tokens": 1000, "output_tokens": 500, "output_tokens_details": {"reasoning_tokens": 300}}}]
    captured = []
    gets = []
    class Response:
        status_code = 200
        headers = {"x-request-id": "offline-bg"}
        def __init__(self, data): self.data = data
        def json(self): return self.data
    def post(url, **kwargs):
        captured.append(kwargs["json"])
        return Response(bodies[0])
    def get(url, **kwargs):
        assert url.endswith(response_id)
        assert poc.read_json(job["checkpoint_path"])["response_id"] == response_id
        gets.append(url)
        if transient_get_failure and len(gets) == 1:
            raise requests.exceptions.SSLError('offline transient failure')
        return Response(bodies[1])
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(poc.time, "sleep", lambda _: None)
    receipt = poc.interpret_response(poc.request_background(job), job)
    assert len(captured) == 1 and captured[0]["max_output_tokens"] == 32768
    assert captured[0]["reasoning"] == {"effort": "high"}
    assert receipt["status"] == "ok" and receipt["usage"]["total"] == 1500
    assert len(gets) == (2 if transient_get_failure else 1)
    assert "DO_NOT_STORE" not in json.dumps(receipt)


@pytest.mark.parametrize("completed", [True, False])
def test_reconcile_reads_existing_response_without_new_generation(setup, monkeypatch, completed):
    from tools import vision_poc_recover
    _, config, jobs, output = setup
    monkeypatch.setenv("OPENAI_API_KEY", "fake-offline-key")
    job = jobs[0]
    response_id = "resp_recovery_offline"
    def interrupted(job):
        poc.write_json(job['checkpoint_path'], {'job_id': job['job_id'], 'response_id': response_id})
        return {'status': 'background_poll_error', 'response_id': response_id, 'request_id': 'initial-request'}
    poc.run_live([job], config, output, 1, request_fn=interrupted)
    visible = valid_receipt()['data']['choices'][0]['message']['content']
    class Response:
        status_code = 200
        headers = {'x-request-id': 'recovery-get'}
        def json(self):
            return {'id': response_id, 'status': 'completed' if completed else 'in_progress',
                    'output': [{'type': 'reasoning', 'content': 'NEVER_SAVE_THIS'},
                               {'type': 'message', 'content': [{'type': 'output_text', 'text': visible}]}],
                    'usage': {'input_tokens': 1000, 'output_tokens': 500,
                              'output_tokens_details': {'reasoning_tokens': 300}}}
    gets = []
    def get(url, **kwargs):
        assert url.endswith(response_id)
        gets.append(url)
        return Response()
    result = vision_poc_recover.reconcile(output, job['case']['id'], get_fn=get)
    states = poc.load_states(output / 'ledger.jsonl')
    assert len(gets) == 1 and len(states) == 1
    assert result['reconciled'] is completed
    assert states[job['job_id']]['status'] == ('ok' if completed else 'background_poll_error')
    assert poc.held_usd(states) < job['reservation_usd'] if completed else poc.held_usd(states) == job['reservation_usd']
    assert 'NEVER_SAVE_THIS' not in (output / 'ledger.jsonl').read_text(encoding='utf-8')
    if completed:
        assert result['new_generation_requests'] == 0
        assert states[job['job_id']]['recovered_via_same_response_id'] is True
        with pytest.raises(ValueError):
            vision_poc_recover.reconcile(output, job['case']['id'], get_fn=get)


def test_reference_errata_is_attached_without_rewriting_frozen_reference(setup, monkeypatch):
    manifest, config, jobs, output = setup
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-offline-key')
    original = manifest.read_bytes()
    correction = {'corrected_facts': ['Visible unit is DBZ.']}
    poc.write_json(manifest.parent / 'reference_errata.json', {'cases': {jobs[0]['case']['id']: correction}})
    poc.run_live(jobs[:1], config, output, 1, request_fn=lambda _: valid_receipt())
    poc.make_report(output)
    packet = poc.read_json(output / 'blind_review.json')[0]
    assert packet['reference_errata'] == correction
    assert packet['reference'] == jobs[0]['case']['reference']
    assert manifest.read_bytes() == original


def test_background_persistent_get_failure_stops_after_three_reads(setup, monkeypatch):
    import requests
    _, _, jobs, _ = setup
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-offline-key')
    class Response:
        status_code = 200
        headers = {}
        def json(self): return {'id': 'resp_still_running', 'status': 'in_progress'}
    posts, gets = [], []
    def post(*a, **k):
        posts.append(1)
        return Response()
    def get(*a, **k):
        gets.append(1)
        raise requests.exceptions.SSLError('offline')
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(poc.time, 'sleep', lambda _: None)
    receipt = poc.interpret_response(poc.request_background(jobs[0]), jobs[0])
    assert len(posts) == 1 and len(gets) == 3
    assert receipt['status'] == 'background_poll_error' and receipt['usage'] is None
