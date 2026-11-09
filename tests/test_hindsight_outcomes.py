import hashlib
import hmac
import json
import sqlite3
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from decision_service import hindsight_outcomes
from decision_service.app import create_app
from decision_service.settings import Settings
from decision_service.storage import canonical
from test_service import AUTH, config, evaluate, feedback, get, program_event, provider_choice, request, workflow


HOOK = b"webhook-signing-key-for-local-tests"
PRODUCER = b"producer-signing-key-for-local-tests"
WEBHOOK = "/v1/hindsight-webhooks/a"


def settings(tmp_path):
    return config(tmp_path).model_dump() | {
        "hindsight_base_url": "http://hindsight.test",
        "hindsight_api_key": "test-reader-key",
        "hindsight_outcomes": {"a": {"project_id": "p", "caller_scope": "source",
                                     "webhook_secret": HOOK.decode(), "producer_secret": PRODUCER.decode()}},
    }


def outcome(event, key=PRODUCER):
    signed = {"record_type": "decision_outcome", "bank_id": "a", "caller_scope": "source", "feedback": event}
    mac = hmac.digest(key, canonical(signed).encode(), "sha256").hex()
    original = canonical({"outcome": signed, "signature": mac})
    return "decision-outcome-v1-" + hashlib.sha256(original.encode()).hexdigest(), original


def delivery(app, document_id, event_id="native-1", *, timestamp=None, key=HOOK):
    raw = json.dumps({"event_id": event_id, "event": "retain.completed", "bank_id": "a",
                      "operation_id": "retain-1", "status": "completed",
                      "data": {"document_id": document_id}}).encode()
    timestamp = timestamp if timestamp is not None else int(time.time())
    signature = hmac.digest(key, str(timestamp).encode() + b"." + raw, "sha256").hex()
    return request(app, "POST", WEBHOOK, {"X-Hindsight-Signature-V2": f"t={timestamp},v1={signature}"}, content=raw)


def settled(client, doc_id):
    for _ in range(150):
        response = client.get(f"/v1/hindsight-outcomes/a/{doc_id}", headers=AUTH)
        assert response.status_code == 200, response.text
        rows = response.json()["deliveries"]
        if rows and all(row["state"] != "pending" for row in rows):
            return rows
        time.sleep(.02)
    raise AssertionError(f"Outcome did not settle: {rows}")


def exact_reader(monkeypatch, serve):
    client_factory = httpx.AsyncClient
    monkeypatch.setattr(hindsight_outcomes, "http_client", lambda **kw: client_factory(
        transport=httpx.MockTransport(serve), **kw))


def gateway_document(doc_id, original, status=200):
    return httpx.Response(200, json={"isError": status >= 400, "structuredContent": {
        "state": "RESPONSE", "action": "get_document", "bank_id": "a", "document_id": doc_id,
        "http_status": status, "body": {"id": doc_id, "bank_id": "a", "original_text": original},
    }})


def test_webhook_survives_restart_and_shares_receipt_with_direct_path(tmp_path, monkeypatch):
    configuration = Settings.model_validate(settings(tmp_path))
    app = create_app(configuration, decide=provider_choice)
    decision = evaluate(app, workflow())
    event = program_event(decision, "result")
    direct = feedback(app, event)
    doc_id, original = outcome(event)
    assert delivery(app, doc_id, timestamp=1).status_code == 401
    assert delivery(app, doc_id, key=PRODUCER).status_code == 401
    assert delivery(app, doc_id).status_code == 202
    assert delivery(app, doc_id).json()["duplicate"] is True
    assert delivery(app, outcome(event | {"event_id": "other"})[0]).status_code == 409

    def serve(req):
        assert req.method == "GET"
        assert req.url.path == f"/v1/default/banks/a/documents/{doc_id}"
        return httpx.Response(200, json={"id": doc_id, "bank_id": "a", "original_text": original})

    exact_reader(monkeypatch, serve)
    restarted = create_app(configuration)
    with TestClient(restarted) as client:
        row, = settled(client, doc_id)
        assert row["state"] == "recorded"
        assert row["receipt_id"] == direct["receipt_id"]
    assert len(get(restarted, decision)["feedback"]) == 1


def test_exact_compensation_checks_producer_and_preserves_current_revision(tmp_path, monkeypatch):
    app = create_app(Settings.model_validate(settings(tmp_path) | {"hindsight_api_mode": "gateway"}),
                     decide=provider_choice)
    decision = evaluate(app, workflow())
    model_decision = evaluate(app, workflow(request_id="model", preset="role_model_selection", choices=[
        {"candidate_id": "standard", "description": "Standard", "parameters": {"model": "test-model"}}
    ]))
    old = program_event(decision, "result")
    old["decision_ids"].append(model_decision["decision_id"])
    old["payload"]["effective_model"] = {
        "provider": "test", "model_type": "agent", "model": "test-model", "reasoning_effort": "high",
        "configuration_status": "confirmed", "effort_status": "set",
    }
    new = old | {"revision": 2, "supersedes_revision": 1, "payload": old["payload"] | {
        "quality_status": "unknown", "result_refs": [], "evidence_refs": ["withdrawal://original"]}}
    new_id, new_text = outcome(new)
    old_id, old_text = outcome(old)
    bad_id, bad_text = outcome(old, key=HOOK)
    documents = {new_id: new_text, old_id: old_text, bad_id: bad_text}
    attempts = []
    monkeypatch.setattr(hindsight_outcomes, "RETRY_DELAYS", (0, 0))

    def serve(req):
        body = json.loads(req.content)
        assert req.method == "POST" and req.url.path == "/api" and body["tool"] == "get_document"
        assert body["arguments"]["bank_id"] == "a"
        doc_id = body["arguments"]["document_id"]
        attempts.append(doc_id)
        if len(attempts) == 1:
            return httpx.Response(200, json={"isError": True, "content": [
                {"type": "text", "text": "BUSY: no upstream action started"},
            ]})
        if len(attempts) == 2:
            return httpx.Response(503)
        return gateway_document(doc_id, documents[doc_id])

    exact_reader(monkeypatch, serve)
    with TestClient(app) as client:
        assert client.post(f"/v1/hindsight-outcomes/a/{new_id}",
                           headers={"Authorization": "Bearer other-token"}).status_code == 403
        assert client.post(f"/v1/hindsight-outcomes/a/{new_id}", headers=AUTH).status_code == 202
        row = settled(client, new_id)[0]
        assert row["state"] == "recorded" and row["attempts"] == 3
        assert feedback(app, new)["receipt_id"] == row["receipt_id"]
        assert delivery(app, old_id, "native-old").status_code == 202
        assert delivery(app, bad_id, "native-untrusted").status_code == 202
        assert settled(client, old_id)[0]["state"] == "recorded"
        assert settled(client, bad_id)[0]["state"] == "rejected"
    for linked in (decision, model_decision):
        assert [(row["revision"], row["is_current"]) for row in get(app, linked)["feedback"]] == [(1, False), (2, True)]


def test_new_bank_binding_cannot_see_or_process_previous_projects_inbox(tmp_path, monkeypatch):
    configuration = settings(tmp_path)
    app = create_app(Settings.model_validate(configuration), decide=provider_choice)
    decision = evaluate(app, workflow())
    doc_id, _ = outcome(program_event(decision, "result"))
    assert delivery(app, doc_id).status_code == 202

    configuration["hindsight_outcomes"]["a"].update(project_id="q", caller_scope="other")
    configuration["callers"]["other-token"].update(project_ids=["q"], bank_ids=["a"])
    new_app = create_app(Settings.model_validate(configuration))
    attempted = []
    exact_reader(monkeypatch, lambda req: attempted.append(req.url.path) or httpx.Response(404))
    with TestClient(new_app) as client:
        response = client.get(f"/v1/hindsight-outcomes/a/{doc_id}",
                              headers={"Authorization": "Bearer other-token"})
        assert response.json()["deliveries"] == []
    assert attempted == []


def test_malformed_gateway_documents_do_not_stop_the_inbox_worker(tmp_path, monkeypatch):
    configuration = Settings.model_validate(settings(tmp_path) | {"hindsight_api_mode": "gateway"})
    app = create_app(configuration, decide=provider_choice)
    decision = evaluate(app, workflow())
    doc_id, original = outcome(program_event(decision, "result"))
    malformed = {
        "decision-outcome-v1-" + "1" * 64: {"structuredContent": {"result": "[" * 1200 + "0" + "]" * 1200}},
        "decision-outcome-v1-" + "2" * 64: {"content": [{"type": "text", "text": "1" * 10000}]},
    }

    def serve(req):
        requested = json.loads(req.content)["arguments"]["document_id"]
        if requested in malformed:
            return httpx.Response(200, json=malformed[requested])
        return gateway_document(doc_id, original)

    exact_reader(monkeypatch, serve)
    for i, bad_id in enumerate(malformed):
        assert delivery(app, bad_id, f"bad-{i}").status_code == 202
    assert delivery(app, doc_id).status_code == 202
    with TestClient(app) as client:
        for bad_id in malformed:
            row, = settled(client, bad_id)
            assert (row["state"], row["reason"]) == ("rejected", "hindsight_invalid_response")
        assert settled(client, doc_id)[0]["state"] == "recorded"


@pytest.mark.parametrize("mode,where", [("native", "outer"), ("gateway", "outer"), ("gateway", "relay")])
def test_exact_compensation_reopens_after_read_access_is_repaired(tmp_path, monkeypatch, mode, where):
    cfg = settings(tmp_path) | {"hindsight_api_mode": mode}
    app = create_app(Settings.model_validate(cfg), decide=provider_choice)
    decision = evaluate(app, workflow())
    doc_id, original = outcome(program_event(decision, "result"))
    route = f"/v1/hindsight-outcomes/a/{doc_id}"

    def serve(req):
        if req.headers.get("Authorization") != "Bearer restored-key":
            return gateway_document(doc_id, None, status=403) if where == "relay" else httpx.Response(401)
        if mode == "gateway":
            return gateway_document(doc_id, original)
        return httpx.Response(200, json={"id": doc_id, "bank_id": "a", "original_text": original})

    exact_reader(monkeypatch, serve)
    with TestClient(app) as client:
        assert client.post(route, headers=AUTH).status_code == 202
        row, = settled(client, doc_id)
        assert (row["state"], row["reason"]) == ("access_blocked", "document_access_denied")
    with TestClient(create_app(Settings.model_validate(cfg | {"hindsight_api_key": "restored-key"}))) as client:
        reply = client.post(route, headers=AUTH)
        assert reply.status_code == 202 and reply.json()["requeued"] is True
        assert settled(client, doc_id)[0]["state"] == "recorded"


def test_feedback_and_inbox_receipt_commit_or_roll_back_together(tmp_path, monkeypatch):
    configuration = Settings.model_validate(settings(tmp_path))
    app = create_app(configuration, decide=provider_choice)
    decision = evaluate(app, workflow())
    doc_id, original = outcome(program_event(decision, "result"))
    route = f"/v1/hindsight-outcomes/a/{doc_id}"
    reads = []
    restored = False

    def serve(req):
        reads.append(req.url.path)
        if len(reads) == 1 or restored:
            return httpx.Response(200, json={"id": doc_id, "bank_id": "a", "original_text": original})
        return httpx.Response(404)

    exact_reader(monkeypatch, serve)
    monkeypatch.setattr(hindsight_outcomes, "RETRY_DELAYS", ())
    with sqlite3.connect(configuration.db_path) as conn:
        conn.execute("""CREATE TRIGGER interrupt_settle BEFORE UPDATE OF receipt_id ON hindsight_inbox
            WHEN NEW.receipt_id IS NOT NULL BEGIN SELECT RAISE(ABORT, 'interrupted settlement'); END""")
    with TestClient(app) as client:
        assert client.post(route, headers=AUTH).status_code == 202
        row, = settled(client, doc_id)
        assert (row["state"], row["receipt_id"]) == ("retry_exhausted", None)
        assert get(app, decision)["feedback"] == []
    with sqlite3.connect(configuration.db_path) as conn:
        conn.execute("DROP TRIGGER interrupt_settle")
    restored = True
    with TestClient(create_app(configuration)) as client:
        assert client.post(route, headers=AUTH).json()["requeued"] is True
        recorded, = settled(client, doc_id)
        assert recorded["state"] == "recorded"
    restored = False
    count = len(reads)
    with TestClient(create_app(configuration)) as client:
        assert settled(client, doc_id) == [recorded]
    assert len(reads) == count
