"""Publish a workflow's frozen result through the Hindsight outcome contract."""

import argparse
import hmac
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from .models import Feedback
from .settings import Name
from .storage import canonical


class PublisherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: Name
    bank_id: Name
    caller_scope: Name
    producer_secret: SecretStr = Field(min_length=32)
    gateway_url: str
    gateway_token: SecretStr
    decision_service_url: str
    decision_service_token: SecretStr
    state: Path
    timeout_seconds: float = Field(default=10, ge=1, le=30)


class PublicationError(ValueError):
    pass


class OutcomePublisher:
    def __init__(self, config, http):
        self.config = config
        self.http = http
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", config.bank_id):
            raise PublicationError("invalid_bank_binding")
        for value in (config.gateway_url, config.decision_service_url):
            url = urlsplit(value)
            if ((url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "::1", "localhost"}))
                    or not url.hostname or url.username is not None or url.query or url.fragment):
                raise PublicationError("invalid_publication_url")
        if not config.state.is_absolute() or not config.state.parent.is_dir():
            raise PublicationError("private_publication_directory_required")

    def freeze(self, event):
        feedback = Feedback.model_validate(event)
        if feedback.kind != "result" or feedback.project_id != self.config.project_id:
            raise PublicationError("publication_scope_mismatch")
        payload = feedback.model_dump(exclude_unset=True)
        key = (self.config.caller_scope, feedback.project_id, feedback.event_id, feedback.revision)
        encoded = canonical(payload)
        binding = {"record_type": "decision_outcome", "bank_id": self.config.bank_id,
                   "caller_scope": self.config.caller_scope, "feedback": payload}
        signature = hmac.digest(self.config.producer_secret.get_secret_value().encode(),
                                canonical(binding).encode(), "sha256").hex()
        original = canonical({"outcome": binding, "signature": signature})
        if len(original.encode()) > 256 * 1024:
            raise PublicationError("publication_document_too_large")
        document = "decision-outcome-v1-" + sha256(original.encode()).hexdigest()
        operation = str(uuid5(NAMESPACE_URL, f"decision-service:outcome:{self.config.bank_id}:{document}"))
        with closing(sqlite3.connect(self.config.state)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS publications (
                scope TEXT NOT NULL, project TEXT NOT NULL, event TEXT NOT NULL, revision INTEGER NOT NULL,
                bank TEXT NOT NULL, payload TEXT NOT NULL, original TEXT NOT NULL, document TEXT NOT NULL,
                operation TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'ready',
                PRIMARY KEY(scope, project, event, revision))""")
            db.execute("""INSERT INTO publications(scope, project, event, revision, bank, payload, original, document, operation)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (*key, self.config.bank_id, encoded, original, document, operation))
            row = db.execute("""SELECT bank, payload, original, document, operation, phase FROM publications
                WHERE (scope, project, event, revision) = (?, ?, ?, ?)""", key).fetchone()
        bank, frozen, original, document, operation, phase = row
        if bank != self.config.bank_id or frozen != encoded:
            raise PublicationError("publication_revision_conflict")
        return key, original, document, operation, phase

    def set_phase(self, key, previous, phase):
        with closing(sqlite3.connect(self.config.state)) as db, db:
            return db.execute("""UPDATE publications SET phase = ?
                WHERE (scope, project, event, revision, phase) = (?, ?, ?, ?, ?)""",
                (phase, *key, previous)).rowcount == 1

    def request(self, method, url, token, body=None):
        try:
            response = self.http.request(method, url, headers={"Authorization": "Bearer " + token.get_secret_value()},
                                         json=body)
            value = response.json()
        except (httpx.HTTPError, ValueError, RecursionError):
            raise PublicationError("publication_transport_unknown") from None
        if not response.is_success or not isinstance(value, dict):
            raise PublicationError(f"publication_http_{response.status_code}")
        return value

    def gateway(self, action, operation, **arguments):
        bank = self.config.bank_id
        result = self.request("POST", self.config.gateway_url.rstrip("/") + "/api", self.config.gateway_token, {
            "tool": action, "arguments": {"bank_id": bank, "operation_id": operation, **arguments},
            "timeout_seconds": self.config.timeout_seconds,
        })
        receipt = result.get("structuredContent")
        if (not isinstance(receipt, dict) or receipt.get("action") != action or receipt.get("bank_id") != bank
                or receipt.get("operation_id") != operation
                or ("document_id" in arguments and receipt.get("document_id") != arguments["document_id"])):
            raise PublicationError("publication_gateway_unknown")
        return receipt

    def publish(self, event):
        key, original, document, operation, phase = self.freeze(event)
        config = self.config
        path = config.decision_service_url.rstrip("/") + f"/v1/hindsight-outcomes/{config.bank_id}/{document}"
        result = {"event_id": key[2], "revision": key[3], "document_id": document, "operation_id": operation}
        try:
            inbox = self.request("GET", path, config.decision_service_token)
            if inbox.get("document_id") != document or not isinstance(rows := inbox.get("deliveries"), list):
                raise PublicationError("publication_inbox_unknown")
            if rows:
                if any(not isinstance(row, dict) or (row.get("state") == "recorded" and (
                    not isinstance(row.get("receipt_id"), str) or not row["receipt_id"]
                )) for row in rows):
                    raise PublicationError("publication_inbox_conflict")
                receipts = {row["receipt_id"] for row in rows if row.get("state") == "recorded"}
                if len(receipts) == 1:
                    receipt = next(iter(receipts))
                    return {**result, "state": "recorded", "receipt_id": receipt, "received": True}
                if receipts:
                    raise PublicationError("publication_inbox_conflict")
                return {**result, "state": "awaiting_inbox", "inbox_states": sorted({str(row.get("state")) for row in rows})}

            status = self.gateway("get_operation", operation)
            if status.get("state") == "RESPONSE" and status.get("http_status") == 200:
                body = status.get("body")
                if not isinstance(body, dict) or body.get("operation_id") != operation:
                    raise PublicationError("publication_operation_mismatch")
                state = body.get("status")
                if state not in {"pending", "processing", "completed", "failed", "cancelled"}:
                    raise PublicationError("publication_operation_unknown")
                if state == "completed" and isinstance(body.get("completed_at"), str):
                    try:
                        completed = datetime.fromisoformat(body["completed_at"])
                    except ValueError:
                        raise PublicationError("publication_operation_unknown") from None
                    if completed.utcoffset() is not None and datetime.now(timezone.utc) - completed >= timedelta(minutes=2):
                        ack = self.request("POST", path, config.decision_service_token)
                        if ack.get("accepted") is not True or ack.get("document_id") != document:
                            raise PublicationError("publication_compensation_unknown")
                        return {**result, "state": "compensation_queued"}
                return {**result, "state": "awaiting_webhook" if state == "completed" else state}
            if status.get("state") != "RESPONSE" or status.get("http_status") != 404:
                raise PublicationError("publication_operation_unknown")
            if phase != "ready" or not self.set_phase(key, "ready", "intent"):
                return {**result, "state": "unknown", "reason": "original_operation_not_visible"}

            try:
                submitted = self.gateway("retain", operation, document_id=document, content=original)
            except PublicationError as error:
                # The gateway rejects unauthorized requests before invoking the relay.
                if str(error) in {"publication_http_401", "publication_http_403"}:
                    self.set_phase(key, "intent", "ready")
                raise
            if submitted.get("state") == "NOT_SUBMITTED" and submitted.get("request_started") is False:
                self.set_phase(key, "intent", "ready")
                return {**result, "state": "not_submitted"}
            body = submitted.get("body")
            if (submitted.get("state") != "SUBMITTED" or not isinstance(body, dict)
                    or body.get("operation_id") != operation or body.get("bank_id") != config.bank_id
                    or body.get("success") is not True or body.get("async") is not True):
                raise PublicationError("publication_retain_unknown")
            self.set_phase(key, "intent", "submitted")
            return {**result, "state": "submitted"}
        except PublicationError as error:
            return {**result, "state": "unknown", "reason": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config = PublisherConfig.model_validate_json(args.config.read_bytes())
        with httpx.Client(timeout=config.timeout_seconds, trust_env=False, follow_redirects=False) as http:
            print(canonical(OutcomePublisher(config, http).publish(json.load(sys.stdin))))
    except (OSError, sqlite3.Error, ValidationError, ValueError, RecursionError):
        # Never echo submitted bodies or values from the private configuration.
        print('{"state":"unknown","reason":"publication_input_or_state_error"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
