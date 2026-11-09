import asyncio

import httpx
import pytest

from decision_service.app import create_app
from decision_service.settings import Settings

NOW = "2026-11-09T10:00:00+08:00"
LATER = "2026-11-09T10:01:00+08:00"
AUTH = {"Authorization": "Bearer test-token"}


def config(tmp_path):
    return Settings(
        db_path=tmp_path / "service.sqlite3",
        callers={
            "test-token": {"caller_scope": "source", "project_ids": ["p"], "bank_ids": ["a", "b", "c"]},
            "other-token": {"caller_scope": "other", "project_ids": ["p"], "bank_ids": []},
            "restricted-token": {"caller_scope": "source", "project_ids": ["q"], "bank_ids": []},
        },
        service_bank_ids=["a", "b", "d"],
        default_banks={"p": ["a", "b"]},
    )


def request(app, method, path, headers=AUTH, **kwargs):
    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, headers=headers, **kwargs)
    return asyncio.run(send())


def workflow(**overrides):
    return {
        "schema_version": 1, "request_id": "req-1", "preset": "workflow_next_action",
        "kind": "choice", "question": "Choose the next action", "context": {},
        "project_id": "p", "subject_ref": {
            "task_id": "task-1", "unit_id": "unit-1", "unit_id_source": "adapter",
            "step": "review", "source_sha256": "source", "input_sha256": "input",
        },
        "snapshot": {"state_digest": "state", "candidate_digest": "snapshot-candidates"},
        "expects_application": True, "recall": "skip",
        "choices": [
            {"candidate_id": "continue", "description": "Continue", "parameters": {"step": "next"}},
            {"candidate_id": "replan", "description": "Needs a plan", "parameters": {},
             "metadata": {"executable": False, "disposition": "needs_replan"}},
        ],
        **overrides,
    }


def provider_choice(body, evidence, settings):
    return {
        "status": "ok", "answer": {"type": "choice", "choice": "continue", "probabilities": []},
        "model": {
            "provider": "openai", "model_type": "decision", "requested_model": "gpt-6-luna",
            "model": None, "reasoning_effort": None, "configuration_status": "unconfirmed",
            "effort_status": "not_applicable",
        },
    }


def program_event(decision, kind):
    unit = {key: decision["subject_ref"][key] for key in ("task_id", "unit_id", "unit_id_source")}
    ended = kind == "result"
    return {
        "schema_version": 1, "project_id": "p", "event_id": f"unit-1.{kind}", "revision": 1,
        "kind": kind, "decision_ids": [decision["decision_id"]], "subject_ref": unit,
        "observed_at": LATER if ended else NOW, "execution_state": "ended" if ended else "running",
        "coverage_observation": {
            "scope_ref": "task-1", "observed_at": LATER if ended else NOW, "scope_complete": False,
            "units": [{"unit_id": "unit-1", "state": "ended" if ended else "pending", "expects_result": True}],
        },
        "payload": (
            {"execution_status": "completed", "quality_status": "pending",
             "result_refs": ["artifact://result"], "evidence_refs": []}
            if ended else
            {"application_status": "applied", "recommended_candidate_id": "continue",
             "effective_candidate_id": "continue", "reason_codes": [], "evidence_refs": []}
        ),
    }


def evaluate(app, body, status=200, headers=AUTH):
    reply = request(app, "POST", "/v1/decisions/evaluate", headers, json=body)
    assert reply.status_code == status, reply.text
    return reply.json()


def get(app, decision):
    reply = request(app, "GET", "/v1/decisions/" + decision["decision_id"])
    assert reply.status_code == 200, reply.text
    return reply.json()


def feedback(app, body, status=200):
    reply = request(app, "POST", "/v1/decision-feedback", json=body)
    assert reply.status_code == status, reply.text
    return reply.json()


def test_evaluate_recovery_and_feedback_survive_restart(tmp_path):
    cfg = config(tmp_path)
    app = create_app(cfg, decide=provider_choice)
    decision = evaluate(app, workflow())
    assert decision["candidate_id"] == "continue"
    assert decision["parameters"] == {"step": "next"}
    assert decision["decision_model"]["model"] is None
    assert "usage" not in decision or decision["usage"] is None
    assert decision["evidence_refs"] == [f'decision://{decision["decision_id"]}']
    assert request(app, "GET", "/v1/decisions?request_id=req-1").json()["input_digest"] == decision["input_digest"]
    application = program_event(decision, "application")
    receipt = feedback(app, application)
    assert receipt["received"] and not receipt["duplicate"]
    assert get(app, decision)["coverage"]["pending"] == 1
    feedback(app, program_event(decision, "result"))
    restarted = create_app(cfg, decide=lambda *_: pytest.fail("replay called the model"))
    assert evaluate(restarted, workflow()) == decision
    duplicate = feedback(restarted, application)
    assert duplicate["duplicate"] and duplicate["receipt_id"] == receipt["receipt_id"]
    row = get(restarted, decision)
    assert {event["kind"] for event in row["feedback"]} == {"application", "result"}
    assert row["coverage"] == {
        "application": {"expected": 1, "received": 1, "rate": 1.0},
        "result": {"expected_ended": 1, "received": 1, "rate": 1.0},
        "pending": 0, "missing": 0, "unknown": 0, "quality_pending": 1,
        "scope_complete": False, "observed_at": LATER,
    }


def test_scope_controls_defaults_and_keeps_reads_private(tmp_path):
    calls = []

    def recall(body, bank_ids, settings):
        calls.append(bank_ids)
        return {
            "evidence": [{"bank_id": "a", "document_id": "d", "memory_id": None, "text": "project evidence"}],
            "banks": [
                {"bank_id": "a", "status": "ok", "reason_code": None},
                {"bank_id": "b", "status": "failed", "reason_code": "hindsight_http_503"},
            ],
        }

    app = create_app(config(tmp_path), retrieve=recall, decide=provider_choice)
    assert request(app, "GET", "/health", {}).json() == {"status": "ok"}
    assert evaluate(app, workflow(), 401, {})["error"]["code"] == "unauthenticated"
    assert evaluate(app, workflow(project_id="q"), 403)["error"]["code"] == "forbidden_scope"
    for bank in ("c", "d"):
        assert evaluate(app, workflow(bank_ids=[bank]), 403)["error"]["code"] == "forbidden_scope"
    decision = evaluate(app, workflow(recall="auto"))
    assert calls == [["a", "b"]]
    assert decision["retrieval"]["status"] == "partial"
    assert decision["retrieval"]["evidence"][0]["document_id"] == "d"
    for token in ("other-token", "restricted-token"):
        for path in (f'/v1/decisions/{decision["decision_id"]}', "/v1/decisions?request_id=req-1"):
            assert request(app, "GET", path, {"Authorization": f"Bearer {token}"}).status_code == 404

    general = evaluate(app, {"schema_version": 1, "kind": "choice", "question": "Which?",
                             "context": {}, "choices": [workflow()["choices"][0]]})
    assert general["retrieval"]["reason_code"] == "no_default_banks"
    assert general["decision_model"]["status"] == "not_invoked"
    assert calls == [["a", "b"]]


def test_concurrent_replay_does_not_start_a_second_provider_attempt(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()

    def decide(*args):
        entered.set()
        assert release.wait(5)
        return provider_choice(*args)

    app = create_app(config(tmp_path), decide=decide)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(evaluate, app, workflow())
        try:
            assert entered.wait(5)
            processing = request(app, "GET", "/v1/decisions?request_id=req-1").json()
            assert processing["status"] == "processing" and processing["parameters"] is None
            assert evaluate(app, workflow(), 409)["error"]["code"] == "request_in_progress"
            changed = workflow()
            changed["choices"][0]["parameters"]["step"] = "changed"
            assert evaluate(app, changed, 409)["error"]["code"] == "input_conflict"
        finally:
            release.set()
        complete = future.result(5)
    assert evaluate(app, workflow()) == complete
    assert complete["parameters"] == {"step": "next"} and len(complete["attempts"]) == 1


def test_single_candidate_skips_both_upstreams_even_with_default_banks(tmp_path):
    def unexpected(*args):
        pytest.fail("deterministic selection contacted an upstream")

    app = create_app(config(tmp_path), retrieve=unexpected, decide=unexpected)
    decision = evaluate(app, workflow(recall="auto", choices=[workflow()["choices"][0]]))
    assert decision["disposition"] == "suggested"
    assert decision["candidate_id"] == "continue"
    assert decision["decision_model"]["status"] == "not_invoked"
    assert decision["retrieval"]["reason_code"] == "single_candidate"
    assert [bank["status"] for bank in decision["retrieval"]["banks"]] == ["skipped", "skipped"]


def test_out_of_order_quality_revision_and_scope_observation(tmp_path):
    app = create_app(config(tmp_path), decide=provider_choice)
    decision = evaluate(app, workflow())
    assert get(app, decision)["coverage"]["result"]["expected_ended"] is None
    initial = program_event(decision, "result")
    revised = program_event(decision, "result")
    revised.update(revision=2, supersedes_revision=1)
    revised["payload"].update(quality_status="passed", evidence_refs=["check://passed"])
    revised["execution_ref"] = {"source": "herdr", "ids": {"action_id": "native-a", "turn_id": "native-t"}}
    revised["coverage_observation"]["units"][0]["execution_ref"] = revised["execution_ref"]
    revised["coverage_observation"]["units"] += [
        {"unit_id": "unit-2", "state": "ended", "expects_result": True},
        {"unit_id": "unit-3", "state": "pending", "expects_result": True},
        {"unit_id": "unit-4", "state": "unknown", "expects_result": True},
    ]
    feedback(app, revised)
    first = get(app, decision)
    assert first["coverage"]["result"] == {"expected_ended": 2, "received": 1, "rate": 0.5}
    assert {key: first["coverage"][key] for key in ("missing", "pending", "unknown", "quality_pending")} == {
        "missing": 1, "pending": 1, "unknown": 1, "quality_pending": 0,
    }
    assert first["feedback"][0]["supersedes_revision"] == 1  # Its predecessor has not arrived.
    feedback(app, initial)
    feedback(app, program_event(decision, "application"))  # Older pending observation.
    record = get(app, decision)
    assert record["coverage"]["result"] == first["coverage"]["result"]
    assert [e["is_current"] for e in record["feedback"] if e["kind"] == "result"] == [False, True]
    changed = {**revised, "observed_at": NOW}
    assert feedback(app, changed, 409)["error"]["code"] == "revision_conflict"
    changed = {**revised, "revision": 3, "supersedes_revision": 2,
               "execution_ref": {"source": "herdr", "ids": {"action_id": "different"}}}
    assert feedback(app, changed, 409)["error"]["code"] == "revision_conflict"


def test_tied_observations_keep_conflict_unknown_and_never_use_results_as_denominator(tmp_path):
    app = create_app(config(tmp_path), decide=provider_choice)
    decision = evaluate(app, workflow())
    application = program_event(decision, "application")
    result = program_event(decision, "result")
    application["coverage_observation"]["observed_at"] = "2026-11-09T02:01:00Z"
    feedback(app, application)
    feedback(app, result)
    coverage = get(app, decision)["coverage"]
    assert coverage["unknown"] == 1 and not coverage["scope_complete"]
    assert coverage["result"] == {"expected_ended": 0, "received": 0, "rate": None}


@pytest.mark.parametrize(("scope_complete", "known_count"), [(False, None), (True, 0)])
def test_empty_observation_only_proves_zero_when_scope_is_complete(tmp_path, scope_complete, known_count):
    app = create_app(config(tmp_path), decide=provider_choice)
    decision = evaluate(app, workflow())
    event = program_event(decision, "application")
    event["execution_state"] = "not_started"
    event["payload"].update(application_status="not_applied", effective_candidate_id=None)
    event["coverage_observation"].update(scope_complete=scope_complete, units=[])
    feedback(app, event)
    assert get(app, decision)["coverage"] == {
        "application": {"expected": 1, "received": 1, "rate": 1.0},
        "result": {"expected_ended": known_count, "received": known_count, "rate": None},
        "pending": known_count, "missing": known_count, "unknown": known_count, "quality_pending": known_count,
        "scope_complete": scope_complete, "observed_at": NOW,
    }


def test_model_application_distinguishes_recommended_launched_and_effective(tmp_path):
    app = create_app(config(tmp_path), decide=provider_choice)
    recommended = {"provider": "codex", "model_type": "coding", "model": "recommended",
                   "reasoning_effort": "high"}
    role = evaluate(app, workflow(request_id="role-1", preset="role_model_selection", choices=[
        {"candidate_id": "continue", "description": "Known host option", "parameters": recommended},
    ]))
    wf = evaluate(app, workflow())
    event = program_event(role, "application")
    event["payload"].update(
        recommended_model=recommended, launch_model={**recommended, "model": "launched"},
        effective_model={
            "provider": None, "model_type": None, "model": None, "reasoning_effort": None,
            "configuration_status": "unconfirmed", "effort_status": "unconfirmed",
        },
    )
    assert feedback(app, event, 400)["error"]["code"] == "invalid_request"
    event["payload"].update(application_status="unknown", effective_candidate_id=None)
    feedback(app, event)
    result = program_event(role, "result")
    result["decision_ids"].append(wf["decision_id"])
    result["payload"]["effective_model"] = event["payload"]["effective_model"]
    result["execution_ref"] = {"source": "herdr", "ids": {"action_id": "a", "turn_id": "t"}}
    result["coverage_observation"]["units"][0]["execution_ref"] = result["execution_ref"]
    feedback(app, result)
    event.update(revision=2, supersedes_revision=1, observed_at=LATER, execution_state="ended",
                 coverage_observation=program_event(role, "result")["coverage_observation"],
                 execution_ref={"source": "herdr", "ids": {"action_id": "a"}})
    event["coverage_observation"]["units"][0]["execution_ref"] = event["execution_ref"]
    feedback(app, event)
    record = get(app, role)
    assert record["feedback"][1]["payload"]["effective_model"]["model"] is None
    assert record["feedback"][1]["payload"]["recommended_model"]["model"] == "recommended"
    assert record["coverage"]["result"]["received"] == get(app, wf)["coverage"]["result"]["received"] == 1


@pytest.mark.parametrize(("kind", "answer", "status", "expected"), [
    ("predicate", {"type": "predicate", "probability": 0.8}, "ok", "suggested"),
    ("score", {"type": "score", "score": 0.8, "probabilities": []}, "ok", "suggested"),
    ("choice", {"type": "refusal", "reason": "provider_refusal"}, "refused", "abstain"),
    ("choice", {"type": "choice", "choice": "unfrozen", "probabilities": []}, "ok", "unavailable"),
    ("choice", {"type": "choice", "choice": "replan", "probabilities": []}, "ok", "needs_replan"),
    ("choice", {"type": "predicate", "probability": 1.0}, "ok", "unavailable"),
    ("choice", None, "unavailable", "unavailable"),
])
def test_typed_answers_never_execute_unfrozen_or_refused_choices(tmp_path, kind, answer, status, expected):
    def decide(*args):
        return {**provider_choice(*args), "status": status, "answer": answer}

    app = create_app(config(tmp_path), decide=decide)
    body = workflow() if kind == "choice" else {"schema_version": 1, "kind": kind,
                                               "question": "Assess this", "context": {}}
    if kind == "score":
        body["levels"] = [{"label": v, "description": v} for v in ("low", "high")]
    response = evaluate(app, body)
    assert response["disposition"] == expected
    assert response["parameters"] is None
    assert response["answer"] == (None if expected == "unavailable" else answer)


def test_bad_json_types_and_foreign_links_do_not_enter_ledger(tmp_path):
    app = create_app(config(tmp_path), decide=provider_choice)
    assert request(app, "POST", "/v1/decisions/evaluate", content=b'{"question":').status_code == 400
    malformed = request(app, "POST", "/v1/decisions/evaluate",
                        headers={**AUTH, "Content-Type": "application/json"}, content=b'{"question":"\xff"}')
    assert malformed.status_code == 400 and malformed.json()["error"]["code"] == "invalid_request"
    assert evaluate(app, workflow(schema_version=True), 400)["error"]["code"] == "invalid_request"
    raw = b'{"schema_version":1,"kind":"predicate","question":"Q","context":{"num":NaN}}'
    assert request(app, "POST", "/v1/decisions/evaluate", content=raw).status_code == 400
    decision = evaluate(app, workflow())
    other = evaluate(app, workflow(), headers={"Authorization": "Bearer other-token"})
    event = program_event(decision, "result")
    event["decision_ids"].append(other["decision_id"])
    assert feedback(app, event, 404)["error"]["code"] == "not_found"
    assert get(app, decision)["feedback"] == []


def test_feedback_keeps_result_and_measured_usage_without_cash_estimates(tmp_path):
    app = create_app(config(tmp_path), decide=provider_choice)
    decision = evaluate(app, workflow(context={"quoted_price_usd": 12.50}))
    event = program_event(decision, "result")
    event["payload"].update(
        quality_status="passed",
        evidence_refs=["check://passed"],
        usage={
            "input_tokens": 6, "estimated_cost_usd": 0.2,
            "details": [{"cached_tokens": 2, "currency": "USD", "estimatedFee": 0.1}],
        },
    )
    receipt = feedback(app, event)
    assert receipt["received"] and not receipt["duplicate"]
    event["payload"]["usage"]["estimated_cost_usd"] = 0.3
    retry = feedback(app, event)
    assert retry["duplicate"] and retry["receipt_id"] == receipt["receipt_id"]
    event["payload"]["usage"]["input_tokens"] = 7
    assert feedback(app, event, 409)["error"]["code"] == "revision_conflict"
    record = get(app, decision)
    assert record["feedback"][0]["payload"]["usage"] == {
        "input_tokens": 6, "details": [{"cached_tokens": 2}],
    }
    assert record["feedback"][0]["payload"]["quality_status"] == "passed"
    assert record["coverage"]["result"]["received"] == 1


def test_projectless_correction_respects_scope_and_survives_restart(tmp_path):
    cfg = config(tmp_path)
    app = create_app(cfg, decide=provider_choice)
    general = evaluate(app, {
        "schema_version": 1, "request_id": "general", "kind": "choice", "question": "Where to route?",
        "context": {}, "choices": [{"candidate_id": "continue", "description": "Continue", "parameters": {}}],
    })
    project = evaluate(app, workflow())
    event = {
        "schema_version": 1, "project_id": None, "kind": "correction", "event_id": "routing-note",
        "revision": 1, "decision_ids": [general["decision_id"]], "subject_ref": {}, "observed_at": NOW,
        "payload": {
            "target_ref": general["evidence_refs"][0], "text": "Use the revised routing evidence.",
            "reason_codes": [], "evidence_refs": ["source://routing-update"],
        },
        "coverage_observation": {
            "scope_ref": "reviewer-note", "observed_at": NOW, "scope_complete": True,
            "units": [{"unit_id": "claimed-unit", "state": "ended", "expects_result": True}],
        },
    }
    assert general["project_id"] is None
    assert feedback(app, {**event, "project_id": "p"}, 404)["error"]["code"] == "not_found"
    assert feedback(app, {**event, "decision_ids": [project["decision_id"]]}, 404)["error"]["code"] == "not_found"
    foreign = request(app, "POST", "/v1/decision-feedback", {"Authorization": "Bearer other-token"}, json=event)
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "not_found"
    receipt = feedback(app, event)
    assert receipt["received"] and not receipt["duplicate"]

    app = create_app(cfg, decide=lambda *_: pytest.fail("feedback contacted provider"))
    replay = feedback(app, event)
    assert replay["duplicate"] and replay["receipt_id"] == receipt["receipt_id"]
    changed = {**event, "payload": {**event["payload"], "text": "Revised correction."}}
    assert feedback(app, changed, 409)["error"]["code"] == "revision_conflict"
    newer = feedback(app, {**changed, "revision": 2, "supersedes_revision": 1})
    assert newer["receipt_id"] != receipt["receipt_id"]

    record = get(app, general)
    assert [(item["project_id"], item["revision"], item["is_current"]) for item in record["feedback"]] == [
        (None, 1, False), (None, 2, True),
    ]
    assert record["coverage"]["application"]["received"] == 0
    assert record["coverage"]["result"] == {"expected_ended": None, "received": None, "rate": None}
    assert record["coverage"]["observed_at"] is None
    assert get(app, project)["feedback"] == []


@pytest.mark.parametrize("kind", ["application", "result"])
def test_program_feedback_still_requires_a_source_project(tmp_path, kind):
    app = create_app(config(tmp_path), decide=provider_choice)
    decision = evaluate(app, workflow())
    event = {**program_event(decision, kind), "project_id": None}
    assert feedback(app, event, 400)["error"]["code"] == "invalid_request"
    assert get(app, decision)["feedback"] == []


def test_empty_role_and_timeout_cannot_be_applied(tmp_path):
    def decide(*args):
        return {**provider_choice(*args), "status": "unavailable", "answer": None,
                "reason_codes": ["openai_timeout"]}

    app = create_app(config(tmp_path), decide=decide)
    empty = evaluate(app, workflow(request_id="empty-role", preset="role_model_selection", choices=[]))
    assert empty["disposition"] == "unavailable"
    assert empty["decision_model"]["status"] == "not_invoked"
    uncertain = evaluate(app, workflow())
    assert uncertain["status"] == "unknown" and uncertain["attempts"][0]["status"] == "unknown"
    assert uncertain["parameters"] is None and evaluate(app, workflow()) == uncertain
    event = program_event(uncertain, "application")
    event["payload"].update(recommended_candidate_id=None, effective_candidate_id=None)
    assert feedback(app, event, 400)["error"]["code"] == "invalid_request"
    event["payload"]["application_status"] = "unknown"
    feedback(app, event)
    event["payload"]["application_status"] = "not_applied"
    assert feedback(app, event, 409)["error"]["code"] == "revision_conflict"


def test_provider_programming_error_is_unknown_and_never_discloses_exception(tmp_path, caplog):
    def broken(*args):
        raise ValueError("secret exception text")

    app = create_app(config(tmp_path), decide=broken)
    row = evaluate(app, workflow())
    assert row["status"] == "unknown" and row["parameters"] is None
    assert row["attempts"][0]["status"] == "unknown"
    assert "secret exception text" not in str(row) + caplog.text
    assert evaluate(app, workflow()) == row
