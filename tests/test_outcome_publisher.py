import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import httpx
import pytest

from decision_service.outcome_publisher import OutcomePublisher, PublicationError, PublisherConfig
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


def test_lost_submission_response_reuses_frozen_identity_and_waits_for_real_receipt(tmp_path):
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


def test_confirmed_unsent_retry_and_completed_operation_compensation_use_same_ids(tmp_path):
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
