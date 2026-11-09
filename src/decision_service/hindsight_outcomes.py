"""Recover project-published Feedback through exact Hindsight document reads."""

import asyncio
import hmac
import json
import logging
import re
import sqlite3
from contextlib import asynccontextmanager, suppress
from hashlib import sha256
from time import time
from typing import Annotated, Literal

from fastapi import Depends, Request, Response
from httpx import AsyncClient as http_client, HTTPError
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from starlette.concurrency import run_in_threadpool

from .errors import APIError
from .models import Feedback
from .providers import _gateway_body
from .settings import Caller
from .storage import canonical

LOG = logging.getLogger(__name__)
DOC_PREFIX = "decision-outcome-v1-"
DOC_ID = re.compile(DOC_PREFIX + r"[0-9a-f]{64}")
SIGNATURE = re.compile(r"t=([0-9]{1,12}),v1=([0-9a-f]{64})")
DELIVERY_LIMIT = 32 * 1024
DOCUMENT_LIMIT = 256 * 1024
READ_LIMIT = 2 * 1024 * 1024
RETRY_DELAYS = (5, 30, 120)
Ref = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]


class RetainData(BaseModel):
    model_config = ConfigDict(strict=True)
    document_id: str | None


class RetainDelivery(BaseModel):
    model_config = ConfigDict(strict=True)
    event: Literal["retain.completed"]
    event_id: Ref
    bank_id: str
    operation_id: Ref
    status: Literal["completed"]
    data: RetainData


class SignedOutcome(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    record_type: Literal["decision_outcome"]
    bank_id: str
    caller_scope: str
    feedback: dict


class OutcomeDocument(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    outcome: SignedOutcome
    signature: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ReadFailure(Exception):
    def __init__(self, code, *, retryable=False, access_blocked=False):
        self.code = code
        self.retryable = retryable
        self.access_blocked = access_blocked


class OutcomeInbox:
    def __init__(self, settings, store, persist_feedback):
        self.settings = settings
        self.sources = settings.hindsight_outcomes
        self.store = store
        self.persist_feedback = persist_feedback
        self.callers = {bank: settings.outcome_caller(bank, source) for bank, source in self.sources.items()}
        self.bindings = {bank: (bank, source.project_id, source.caller_scope) for bank, source in self.sources.items()}

    def mount(self, app, authenticate):
        if not self.sources:
            return

        @app.post("/v1/hindsight-webhooks/{bank_id}", status_code=202)
        async def webhook(bank_id: str, request: Request):
            source = self.sources.get(bank_id)
            if source is None:
                return Response(status_code=404)
            match = SIGNATURE.fullmatch(request.headers.get("X-Hindsight-Signature-V2", ""))
            if not match or abs(time() - int(match[1])) > 300:
                return Response(status_code=401)
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > DELIVERY_LIMIT:
                    return Response(status_code=413)
                raw.extend(chunk)
            expected = hmac.digest(source.webhook_secret.get_secret_value().encode(),
                                   match[1].encode() + b"." + raw, "sha256").hex()
            if not hmac.compare_digest(expected, match[2]):
                return Response(status_code=401)
            try:
                delivery = RetainDelivery.model_validate_json(raw)
            except ValidationError:
                raise APIError("invalid_request") from None
            if delivery.bank_id != bank_id:
                raise APIError("forbidden_scope")
            document_id = delivery.data.document_id
            if not document_id or not DOC_ID.fullmatch(document_id):
                return Response(status_code=204)
            # Use the immutable signed body, not the timestamp of this attempt.
            result = await run_in_threadpool(self.enqueue, bank_id, document_id, "webhook", delivery.event_id,
                                             delivery.operation_id, sha256(raw).hexdigest())
            return result

        def authorize(bank_id, document_id, caller):
            source = self.sources.get(bank_id)
            if source is None or not DOC_ID.fullmatch(document_id):
                raise APIError("not_found")
            if (caller.caller_scope != source.caller_scope or source.project_id not in caller.project_ids
                    or bank_id not in caller.bank_ids
                    or not set(self.callers[bank_id].bank_ids) <= set(caller.bank_ids)):
                raise APIError("forbidden_scope")

        @app.post("/v1/hindsight-outcomes/{bank_id}/{document_id}", status_code=202)
        def compensate(bank_id: str, document_id: str, caller: Annotated[Caller, Depends(authenticate)]):
            authorize(bank_id, document_id, caller)
            return self.enqueue(bank_id, document_id, "reconcile", document_id)

        @app.get("/v1/hindsight-outcomes/{bank_id}/{document_id}")
        def status(bank_id: str, document_id: str, caller: Annotated[Caller, Depends(authenticate)]):
            authorize(bank_id, document_id, caller)
            with self.store.transaction() as conn:
                rows = conn.execute("""
                    SELECT source, delivery_key, operation_id, state, attempts, reason, receipt_id
                    FROM hindsight_inbox WHERE (bank_id, project_id, caller_scope, document_id) = (?, ?, ?, ?)
                    ORDER BY rowid
                """, (*self.bindings[bank_id], document_id)).fetchall()
            return {"document_id": document_id, "deliveries": [dict(row) for row in rows]}

    def enqueue(self, bank_id, document_id, source, delivery_key, operation_id=None, payload_digest=None):
        key = (*self.bindings[bank_id], source, delivery_key)
        requeued = False
        state = "pending"
        with self.store.transaction(write=True) as conn:
            row = conn.execute("""SELECT document_id, payload_digest, state FROM hindsight_inbox
                WHERE (bank_id, project_id, caller_scope, source, delivery_key) = (?, ?, ?, ?, ?)""", key).fetchone()
            if row is None:
                conn.execute("""INSERT INTO hindsight_inbox
                    (bank_id, project_id, caller_scope, source, delivery_key, document_id, operation_id, payload_digest)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (*key, document_id, operation_id, payload_digest))
            elif (row["document_id"], row["payload_digest"]) != (document_id, payload_digest):
                raise APIError("revision_conflict")
            elif source == "reconcile" and row["state"] in {"retry_exhausted", "access_blocked"}:
                conn.execute("""UPDATE hindsight_inbox SET state = 'pending', next_attempt = 0, attempts = 0,
                    reason = NULL WHERE (bank_id, project_id, caller_scope, source, delivery_key) = (?, ?, ?, ?, ?)""", key)
                requeued = True
            else:
                state = row["state"]
        return {"accepted": True, "duplicate": row is not None, "requeued": requeued,
                "state": state, "document_id": document_id}

    @asynccontextmanager
    async def run(self):
        if not self.sources:
            yield
            return
        key = self.settings.hindsight_api_key
        headers = {"Authorization": "Bearer " + key.get_secret_value()} if key else {}
        async with http_client(base_url=self.settings.hindsight_base_url, headers=headers,
                               trust_env=False, timeout=None) as client:
            worker = asyncio.create_task(self.consume(client))
            try:
                yield
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    async def consume(self, client):
        while True:
            try:
                if await self.process_next(client):
                    continue
            except sqlite3.Error as error:
                LOG.error("Hindsight inbox storage unavailable (%s)", type(error).__name__)
            await asyncio.sleep(.5)

    async def process_next(self, client):
        def next_pending():
            bindings = ",".join("(?, ?, ?)" for _ in self.bindings)
            params = (part for binding in self.bindings.values() for part in binding)
            with self.store.transaction() as conn:
                return conn.execute(f"""SELECT * FROM hindsight_inbox WHERE state = 'pending'
                    AND next_attempt <= ? AND (bank_id, project_id, caller_scope) IN (VALUES {bindings})
                    ORDER BY next_attempt, rowid LIMIT 1""", (time(), *params)).fetchone()

        row = await run_in_threadpool(next_pending)
        if row is None:
            return False
        bank_id, document_id = row["bank_id"], row["document_id"]
        attempts = row["attempts"] + 1
        key = (*self.bindings[bank_id], row["source"], row["delivery_key"])

        def settle(conn, state, *, reason=None, receipt_id=None, next_attempt=0):
            conn.execute("""UPDATE hindsight_inbox SET state = ?, reason = ?, attempts = ?,
                next_attempt = ?, receipt_id = ?
                WHERE (bank_id, project_id, caller_scope, source, delivery_key) = (?, ?, ?, ?, ?)""",
                (state, reason, attempts, next_attempt, receipt_id, *key))

        def record(event):
            with self.store.transaction(write=True) as conn:
                receipt = self.persist_feedback(conn, event, self.callers[bank_id])
                settle(conn, "recorded", receipt_id=receipt["receipt_id"])

        def fail(error):
            retryable = error.retryable if isinstance(error, ReadFailure) else error.code == "not_found"
            next_attempt = 0
            if isinstance(error, ReadFailure) and error.access_blocked:
                state = "access_blocked"
            elif retryable and attempts <= len(RETRY_DELAYS):
                state, next_attempt = "pending", time() + RETRY_DELAYS[attempts - 1]
            else:
                state = "retry_exhausted" if retryable else "rejected"
            with self.store.transaction(write=True) as conn:
                settle(conn, state, reason=error.code, next_attempt=next_attempt)

        try:
            original = await self.read_document(client, bank_id, document_id)
            event = self.verify_document(original, bank_id, document_id)
            # Feedback and the inbox receipt commit together; later loss of the document cannot erase the receipt.
            await run_in_threadpool(record, event)
        except (ReadFailure, APIError) as error:
            await run_in_threadpool(fail, error)
        return True

    async def read_document(self, client, bank_id, document_id):
        mode, timeout = self.settings.hindsight_api_mode, self.settings.timeout_seconds
        try:
            async with asyncio.timeout(timeout):
                if mode == "gateway":
                    stream = client.stream("POST", "/api", json={"tool": "get_document", "arguments": {
                        "bank_id": bank_id, "document_id": document_id}, "timeout_seconds": min(timeout, 180)})
                else:
                    stream = client.stream("GET", f"/v1/default/banks/{bank_id}/documents/{document_id}")
                async with stream as response:
                    if not response.is_success:
                        status = response.status_code
                        if status in {401, 403}:
                            raise ReadFailure("document_access_denied", access_blocked=True)
                        raise ReadFailure(f"document_http_{status}",
                                          retryable=status in {404, 408, 429} or status >= 500)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > READ_LIMIT:
                            raise ReadFailure("document_response_too_large")
                        raw.extend(chunk)
        except (TimeoutError, HTTPError):
            raise ReadFailure("document_read_unavailable", retryable=True) from None
        try:
            document = json.loads(raw)
        except (ValueError, RecursionError):
            raise ReadFailure("invalid_document_response") from None
        if mode == "gateway" and isinstance(document, dict):
            document, reason = _gateway_body(document, bank_id, action="get_document", document_id=document_id)
            if reason:
                if reason in {"hindsight_upstream_http_401", "hindsight_upstream_http_403"}:
                    raise ReadFailure("document_access_denied", access_blocked=True)
                raise ReadFailure(reason, retryable=reason != "hindsight_invalid_response")
        if (not isinstance(document, dict) or document.get("id") != document_id
                or document.get("bank_id") != bank_id or not isinstance(document.get("original_text"), str)):
            raise ReadFailure("invalid_document_response")
        return document["original_text"]

    def verify_document(self, original, bank_id, document_id):
        try:
            raw = original.encode("utf-8")
            if len(raw) > DOCUMENT_LIMIT or DOC_PREFIX + sha256(raw).hexdigest() != document_id:
                raise ReadFailure("document_digest_mismatch")
            document = OutcomeDocument.model_validate_json(raw)
            source = self.sources[bank_id]
            signed = document.outcome
            mac = hmac.digest(source.producer_secret.get_secret_value().encode(),
                              canonical(signed.model_dump()).encode(), "sha256").hex()
            if (signed.bank_id != bank_id or signed.caller_scope != source.caller_scope
                    or not hmac.compare_digest(mac, document.signature)):
                raise ReadFailure("untrusted_outcome_producer")
            event = Feedback.model_validate(signed.feedback)
        except (ValueError, RecursionError):
            raise ReadFailure("invalid_outcome_document") from None
        if event.project_id != source.project_id:
            raise ReadFailure("outcome_project_mismatch")
        return event
