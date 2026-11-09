import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import httpx
import pytest

from decision_service.outcome_publisher import OutcomePublisher, PublicationError, PublisherConfig, main
from decision_service.storage import canonical
from test_service import program_event


def publisher(tmp_path, transport):
    config = PublisherConfig(project_id="p", bank_id="p-bank", caller_scope="source",
                             producer_secret="secret-for-the-fake-publisher-only",
                             gateway_url="https://hindsight.test/hindsight", gateway_token="gateway-test",
                             decision_service_url="https://decision.test/decision-service",
                             decision_service_token="decision-test", state=tmp_path / "publications.db")
    return OutcomePublisher(config, httpx.Client(transport=httpx.MockTransport(transport)))


def event():
    return program_event({"decision_id": "d", "subject_ref": {"task_id": "t", "unit_id": "u",
                          "unit_id_source": "adapter"}}, "result")


def gateway(action, args, state, status, body, **extra):
    return httpx.Response(200, json={"structuredContent": {"action": action, "bank_id": args["bank_id"],
        "operation_id": args["operation_id"], "document_id": args.get("document_id"), "state": state,
        "http_status": status, "body": body, **extra}})


@pytest.mark.parametrize("failure", ["transport", "contradictory-busy"])
def test_lost_submission_response_reuses_frozen_identity_and_waits_for_real_receipt(tmp_path, failure):
    source = event()
    sends = []
    operation_visible = False
    recorded = False

    def upstream(req):
        if req.url.host == "decision.test":
            assert req.headers["authorization"] == "Bearer decision-test" and req.method == "GET"
            rows = [{"source": "webhook", "state": "recorded", "receipt_id": "actual-receipt"}] if recorded else []
            return httpx.Response(200, json={"document_id": req.url.path.rsplit("/", 1)[1], "deliveries": rows})
        assert req.headers["authorization"] == "Bearer gateway-test"
        request = json.loads(req.content)
        action, args = request["tool"], request["arguments"]
        if action == "get_operation":
            if operation_visible:
                assert args["operation_id"] == sends[0]["operation_id"]
                return gateway(action, args, "RESPONSE", 200, {"status": "completed", "operation_id": args["operation_id"]})
            return gateway(action, args, "RESPONSE", 404, {})
        assert action == "retain"
        sends.append(args)
        assert json.loads(args["content"])["outcome"]["feedback"] == source
        assert args["document_id"].endswith(sha256(args["content"].encode()).hexdigest())
        if failure == "contradictory-busy":
            return httpx.Response(200, json={"isError": True, "content": [
                {"type": "text", "text": "BUSY: no upstream action started"}],
                "_meta": {"hindsight_gateway": {"attempts": [{"request_may_have_started": True}]}}})
        raise httpx.ReadTimeout("response lost")

    first = publisher(tmp_path, upstream).publish(source)
    assert first["state"] == "unknown" and "receipt_id" not in first
    assert publisher(tmp_path, upstream).publish(source)["reason"] == "original_operation_not_visible"
    operation_visible = True
    assert publisher(tmp_path, upstream).publish(source)["state"] == "awaiting_webhook"
    recorded = True
    assert publisher(tmp_path, upstream).publish(source)["receipt_id"] == "actual-receipt"
    assert len(sends) == 1
    with pytest.raises(PublicationError, match="publication_revision_conflict"):
        publisher(tmp_path, upstream).publish(source | {"observed_at": "2026-11-09T11:30:00+08:00"})


@pytest.mark.parametrize("failure", ["native-unsent", "gateway-busy", "gateway-unavailable"])
def test_confirmed_unsent_retry_and_completed_operation_compensation_use_same_ids(tmp_path, failure):
    source = event()
    sends = []
    compensation = []

    def upstream(req):
        if req.url.host == "decision.test":
            doc = req.url.path.rsplit("/", 1)[1]
            if req.method == "POST":
                compensation.append(doc)
                return httpx.Response(202, json={"accepted": True, "document_id": doc})
            return httpx.Response(200, json={"document_id": doc, "deliveries": []})
        request = json.loads(req.content)
        action, args = request["tool"], request["arguments"]
        if action == "get_operation":
            if len(sends) == 2:
                return gateway(action, args, "RESPONSE", 200, {"status": "completed", "operation_id": args["operation_id"],
                    "completed_at": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()})
            return gateway(action, args, "RESPONSE", 404, {})
        sends.append(args)
        if len(sends) == 1:
            if failure == "gateway-busy":
                return httpx.Response(200, json={"isError": True, "content": [
                    {"type": "text", "text": "BUSY: no upstream action started"}]})
            if failure == "gateway-unavailable":
                return httpx.Response(200, json={"isError": True, "structuredContent": {
                    "state": "UNAVAILABLE", "operation_id": args["operation_id"], "document_id": args["document_id"],
                }, "_meta": {"hindsight_gateway": {
                    "operation_id": args["operation_id"], "document_id": args["document_id"],
                    "request_sha256": sha256(canonical(args).encode()).hexdigest(),
                    "attempts": [{"request_may_have_started": False}, {"request_may_have_started": False}],
                }}})
            return gateway(action, args, "NOT_SUBMITTED", None, None, request_started=False)
        return gateway(action, args, "SUBMITTED", 200, {"success": True, "async": True, "bank_id": args["bank_id"],
                                                       "operation_id": args["operation_id"]})

    pub = publisher(tmp_path, upstream)
    assert pub.publish(source)["state"] == "not_submitted"
    assert pub.publish(source)["state"] == "submitted"
    result = pub.publish(source)
    assert result["state"] == "compensation_queued" and "receipt_id" not in result
    assert sends[0] == sends[1]
    assert compensation == [sends[0]["document_id"]]


def test_publication_cli_rejects_a_different_original_decision_client(tmp_path, monkeypatch, capsys):
    config = publisher(tmp_path, lambda _: pytest.fail("must not send a request")).config
    values = config.model_dump(mode="json")
    for key in ("producer_secret", "gateway_token", "decision_service_token"):
        values[key] = getattr(config, key).get_secret_value()
    file = tmp_path / "publisher.json"
    file.write_text(json.dumps(values))
    monkeypatch.setattr(sys, "argv", ["outcome_publisher", "--config", str(file)])
    monkeypatch.setenv("DECISION_SERVICE_URL", config.decision_service_url)
    monkeypatch.setenv("DECISION_SERVICE_TOKEN", "different-scope")
    assert main() == 1
    assert json.loads(capsys.readouterr().out) == {"state": "unknown", "reason": "publication_decision_client_mismatch"}
    assert not config.state.exists()


def test_read_access_recovery_reuses_exact_document_and_never_requeues_rejection(tmp_path):
    state = "access_blocked"
    posts = []

    def upstream(req):
        assert req.url.host == "decision.test"
        document = req.url.path.rsplit("/", 1)[1]
        if req.method == "POST":
            posts.append(document)
            return httpx.Response(202, json={"accepted": True, "document_id": document})
        row = {"state": state, "reason": "document_access_denied"}
        return httpx.Response(200, json={"document_id": document, "deliveries": [row]})

    pub = publisher(tmp_path, upstream)
    source = event()
    first = pub.publish(source)
    assert first["state"] == "compensation_queued" and posts == [first["document_id"]]
    assert pub.publish(source)["state"] == "access_blocked" and len(posts) == 1
    with sqlite3.connect(pub.config.state) as db:
        db.execute("UPDATE publications SET compensation_after = 0")
    state = "retry_exhausted"
    assert pub.publish(source)["state"] == "compensation_queued" and posts == [first["document_id"]] * 2
    with sqlite3.connect(pub.config.state) as db:
        db.execute("UPDATE publications SET compensation_after = 0")
    state = "rejected"
    assert pub.publish(source)["state"] == "rejected" and len(posts) == 2


def test_cash_usage_never_enters_signed_original_or_publication_index(tmp_path):
    source = event()
    source["payload"]["usage"] = {"total_tokens": 11, "estimatedCostUsd": 2.0,
                                 "breakdown": [{"input_tokens": 7, "cost_in_cny": 1.0}]}
    pub = publisher(tmp_path, lambda _: pytest.fail("must not send a request"))
    _, original, _, _, _ = pub.freeze(source)
    with sqlite3.connect(pub.config.state) as db:
        stored, signed = db.execute("SELECT payload, original FROM publications").fetchone()
    assert original == signed
    for feedback in (json.loads(stored), json.loads(signed)["outcome"]["feedback"]):
        assert feedback["payload"]["usage"] == {"total_tokens": 11, "breakdown": [{"input_tokens": 7}]}
