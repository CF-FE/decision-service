import hmac
import json
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import monotonic
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.routing import Route

from .coverage import coverage_for, merge_execution_refs
from .errors import APIError, ERRORS, error_payload
from .mcp_entry import DecisionMCPEndpoint
from .models import Evaluate, Feedback
from .oauth import DecisionOAuth
from .oauth_storage import OAuthStorageFull
from .settings import Caller, Settings
from .storage import Store, canonical, digest

logger = logging.getLogger(__name__)

PRESETS = {
    "workflow_next_action": {
        "version": 1,
        "kind": "choice",
        "non_executable_disposition": "needs_replan",
    },
    "role_model_selection": {"version": 1, "kind": "choice", "empty_disposition": "unavailable"},
}

CASH_USAGE_TERMS = {"cash", "cost", "costs", "price", "pricing", "currency",
                    "usd", "eur", "cny", "fee", "fees", "dollar", "dollars"}


def error_response(code, **refs):
    status, _ = ERRORS[code]
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(error_payload(code, **refs), status, headers=headers)


def usage_without_cash(value):
    # Preserve usage from the source while excluding monetary fields.
    if isinstance(value, dict):
        return {
            key: usage_without_cash(item)
            for key, item in value.items()
            if CASH_USAGE_TERMS.isdisjoint(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
                                          .lower().replace("-", "_").split("_"))
        }
    if isinstance(value, list):
        return [usage_without_cash(item) for item in value]
    return value


def create_app(settings: Settings | None = None, *, retrieve=None, decide=None):
    settings = settings if settings is not None else Settings.from_env()
    store = Store(settings.db_path)
    provider_settings = settings.provider_settings()
    service_banks = set(settings.service_bank_ids)

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.manager.run():
            yield

    app = FastAPI(title="Decision Service", version="1.0", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)

    @app.exception_handler(APIError)
    async def application_error(_, exc):
        return error_response(exc.code, **exc.refs)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, exc):
        # FastAPI validation errors can include original body values.
        return error_response("invalid_request")

    @app.exception_handler(HTTPException)
    async def http_error(_, exc):
        if exc.status_code in (400, 404):
            return error_response("invalid_request" if exc.status_code == 400 else "not_found")
        return JSONResponse({"error": {"code": "invalid_request", "message": "Unsupported HTTP request."}},
                            exc.status_code, headers=exc.headers)

    @app.exception_handler(sqlite3.Error)
    async def database_error(_, exc):
        logger.error("SQLite operation failed (%s)", type(exc).__name__)
        return error_response("unavailable")

    @app.exception_handler(OAuthStorageFull)
    async def oauth_capacity_error(_, exc):
        return JSONResponse({"error": "server_error", "error_description": "OAuth storage capacity reached."}, 503)

    def caller_for_bearer(authorization) -> Caller | None:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() == "bearer" and token:
            token_bytes = token.encode("utf-8")
            for known, caller in settings.callers.items():
                if hmac.compare_digest(known.encode("utf-8"), token_bytes):
                    return caller
        return None

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> Caller:
        caller = caller_for_bearer(authorization)
        if caller is None:
            raise APIError("unauthenticated")
        return caller

    def can_read(row, caller):
        return (
            row["project_id"] is None or row["project_id"] in caller.project_ids
        ) and set(json.loads(row["frozen"])["bank_ids"]) <= service_banks.intersection(caller.bank_ids)

    @app.get("/health")
    def health():
        with store.transaction() as conn:
            conn.execute("SELECT id FROM decisions LIMIT 1").fetchone()
        return {"status": "ok"}

    @app.post("/v1/decisions/evaluate")
    def evaluate(body: Evaluate, caller: Annotated[Caller, Depends(authenticate)]):
        if body.project_id is not None and body.project_id not in caller.project_ids:
            raise APIError("forbidden_scope")
        bank_ids = body.bank_ids
        if bank_ids is None:
            bank_ids = settings.default_banks.get(body.project_id, []) if body.recall == "auto" else []
        if not set(bank_ids) <= service_banks.intersection(caller.bank_ids):
            raise APIError("forbidden_scope")

        request = body.model_dump(exclude_unset=True)
        request["recall"] = body.recall
        request["expects_application"] = body.expects_application
        request["request_id"] = body.request_id or str(uuid4())
        request["bank_ids"] = list(bank_ids)
        frozen = {"request": request, "preset": PRESETS.get(body.preset), "bank_ids": list(bank_ids)}
        if body.bank_ids is not None:
            # Preserve whether the caller explicitly selected the banks.
            frozen["explicit_bank_ids"] = body.bank_ids
        try:
            frozen_json = canonical(frozen)
            input_digest = digest(frozen)
            candidate_digest = digest(request["choices"]) if body.choices is not None else None
        except (ValueError, UnicodeError):
            raise APIError("invalid_request") from None
        refs = {"request_id": request["request_id"], "decision_id": str(uuid4())}
        decision_id = refs["decision_id"]
        attempt = {
            "attempt_id": str(uuid4()),
            "status": "processing",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        no_model = {
            "status": "not_invoked", "provider": None, "model_type": None, "model": None,
            "reasoning_effort": None, "configuration_status": "unconfirmed", "effort_status": "unconfirmed",
        }
        record = {
            "schema_version": 1, **refs, "status": "processing", "disposition": None,
            "answer": None, "candidate_id": None, "parameters": None,
            "project_id": body.project_id, "subject_ref": body.subject_ref, "snapshot": body.snapshot,
            "input_digest": input_digest, "candidate_digest": candidate_digest,
            "evidence_refs": [f"decision://{decision_id}"],
            "retrieval": {"evidence": [], "banks": [], "status": "pending", "reason_code": None},
            "decision_model": {**no_model, "status": "unconfirmed"},
            "attempts": [attempt], "reason_codes": [],
        }
        with store.transaction(write=True) as conn:
            prior = conn.execute("SELECT * FROM decisions WHERE scope = ? AND request_id = ?",
                                 (caller.caller_scope, request["request_id"])).fetchone()
            if prior is not None:
                if not can_read(prior, caller):
                    raise APIError("not_found")
                prior_refs = {**refs, "decision_id": prior["id"]}
                if prior["input_digest"] != input_digest:
                    raise APIError("input_conflict", **prior_refs)
                if prior["status"] == "processing":
                    raise APIError("request_in_progress", **prior_refs)
                return json.loads(prior["record"])
            conn.execute("""
                INSERT INTO decisions (id, scope, request_id, project_id, input_digest, frozen, status, record)
                VALUES (?, ?, ?, ?, ?, ?, 'processing', ?)
            """, (decision_id, caller.caller_scope, request["request_id"], body.project_id,
                  input_digest, frozen_json, canonical(record)))

        candidates = {entry["candidate_id"]: entry for entry in request.get("choices") or []}
        empty_role = body.preset == "role_model_selection" and not candidates
        single_candidate = len(candidates) == 1
        deadline = monotonic() + provider_settings["timeout_seconds"]
        try:
            reason = None
            if body.recall == "skip":
                reason = "recall_skipped"
            elif not bank_ids:
                reason = "no_banks_selected" if body.bank_ids is not None else "no_default_banks"
            elif empty_role:
                reason = "no_eligible_candidates"
            elif single_candidate:
                reason = "single_candidate"
            if reason is not None:
                record["retrieval"] = {
                    "status": "skipped", "reason_code": reason, "evidence": [],
                    "banks": [{"bank_id": bank, "status": "skipped", "reason_code": reason} for bank in bank_ids],
                }
            else:
                if retrieve is None:
                    from .providers import retrieve_evidence as run_retrieval
                else:
                    run_retrieval = retrieve
                retrieval = run_retrieval(request, bank_ids, provider_settings)
                states = {bank["status"] for bank in retrieval["banks"]}
                status = next(iter(states)) if len(states) == 1 else "partial"
                record["retrieval"] = {**retrieval, "status": status, "reason_code": None}

            if empty_role:
                reply = {"status": "unavailable", "answer": None, "model": no_model,
                         "reason_codes": ["no_eligible_candidates"]}
            elif single_candidate:
                sole = next(iter(candidates))
                reply = {"status": "ok", "answer": {"type": "choice", "choice": sole, "probabilities": []},
                         "model": no_model, "reason_codes": ["single_candidate"]}
            elif (remaining := deadline - monotonic()) > 0:
                if decide is None:
                    from .providers import call_decisions as run_decision
                else:
                    run_decision = decide
                reply = run_decision(request, record["retrieval"]["evidence"],
                                     {**provider_settings, "timeout_seconds": remaining})
            else:
                reply = {"status": "unavailable", "answer": None, "model": no_model,
                         "reason_codes": ["decision_budget_exhausted"]}

            answer = reply["answer"]
            status = reply["status"]
            reasons = list(reply["reason_codes"]) if "reason_codes" in reply else []
            selected = None
            disposition = "unavailable"
            if status == "refused" and answer and answer.get("type") == "refusal":
                disposition = "abstain"
            elif status == "ok" and answer and answer.get("type") == body.kind:
                if body.kind == "choice":
                    selected = candidates.get(answer.get("choice"))
                    if selected is None:
                        answer = None
                        reasons.append("invalid_candidate")
                    else:
                        meta = selected.get("metadata") or {}
                        if meta.get("executable") is False:
                            disposition = ("needs_replan" if body.preset == "workflow_next_action"
                                           and meta.get("disposition") == "needs_replan" else "needs_review")
                        else:
                            disposition = "suggested"
                else:
                    disposition = "suggested"
            else:
                answer = None
                if status in ("ok", "refused"):
                    reasons.append("invalid_answer_type")

            record.update(
                disposition=disposition, answer=answer, decision_model=reply["model"],
                candidate_id=selected["candidate_id"] if selected else None,
                parameters=selected["parameters"] if disposition == "suggested" and selected else None,
                reason_codes=reasons,
            )
            if "usage" in reply:
                record["usage"] = usage_without_cash(reply["usage"])
            if status == "unavailable" and "openai_timeout" in reasons:
                record.update(status="unknown", disposition=None)
            else:
                record["status"] = "complete"
            attempt["status"] = record["status"]
            # Fail closed if an adapter violates the JSON return boundary.
            canonical(record).encode("utf-8")
        except Exception as exc:
            # Upstream and parsing exceptions can carry secrets in their text.
            frame = exc.__traceback__
            while frame.tb_next:
                frame = frame.tb_next
            logger.error("Provider processing failed (%s in %s:%d)", type(exc).__name__,
                         frame.tb_frame.f_code.co_name, frame.tb_lineno)
            record.update(
                status="unknown", disposition=None, answer=None, candidate_id=None, parameters=None,
                decision_model={**no_model, "status": "unconfirmed"},
                reason_codes=["provider_internal_error"],
                retrieval={"status": "unknown", "reason_code": "provider_internal_error", "evidence": [], "banks": []},
            )
            record.pop("usage", None)
            attempt["status"] = "unknown"
        attempt["finished_at"] = datetime.now(timezone.utc).isoformat()
        with store.transaction(write=True) as conn:
            store.finish(conn, decision_id, record)
        return record

    def read_decision(caller, decision_id=None, request_id=None):
        with store.transaction() as conn:
            if decision_id is None:
                row = conn.execute("SELECT * FROM decisions WHERE scope = ? AND request_id = ?",
                                   (caller.caller_scope, request_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM decisions WHERE scope = ? AND id = ?",
                                   (caller.caller_scope, decision_id)).fetchone()
            if row is None or not can_read(row, caller):
                raise APIError("not_found")
            events = store.related_feedback(conn, row["id"])
        record = json.loads(row["record"])
        expects = json.loads(row["frozen"])["request"]["expects_application"]
        return {**record, "feedback": events, "coverage": coverage_for(expects, events)}

    @app.get("/v1/decisions")
    def by_request(caller: Annotated[Caller, Depends(authenticate)],
                   request_id: Annotated[str, Query(min_length=1)]):
        return read_decision(caller, request_id=request_id)

    @app.get("/v1/decisions/{decision_id}")
    def by_id(decision_id: str, caller: Annotated[Caller, Depends(authenticate)]):
        return read_decision(caller, decision_id=decision_id)

    @app.post("/v1/decision-feedback")
    def record_feedback(event: Feedback, caller: Annotated[Caller, Depends(authenticate)]):
        if event.project_id is not None and event.project_id not in caller.project_ids:
            raise APIError("forbidden_scope")
        data = event.model_dump(exclude_unset=True)
        if "usage" in data["payload"]:
            data["payload"]["usage"] = usage_without_cash(data["payload"]["usage"])
        try:
            body_json = canonical(data)
            body_json.encode("utf-8")
        except (ValueError, UnicodeError):
            raise APIError("invalid_request") from None
        # The empty key is reserved for a projectless correction. Real project
        # names are nonempty, and the SQLite primary key stays non-null.
        identity = (caller.caller_scope, event.project_id or "", event.event_id)
        receipt_id = str(uuid4())
        duplicate = False
        with store.transaction(write=True) as conn:
            existing = conn.execute("""
                SELECT revision, receipt_id, body FROM feedback WHERE scope = ? AND project_id = ? AND event_id = ?
            """, identity).fetchall()
            for prior in existing:
                if prior["revision"] == event.revision:
                    if prior["body"] != body_json:
                        raise APIError("revision_conflict")
                    receipt_id, duplicate = prior["receipt_id"], True
                    break
            for decision_id in event.decision_ids:
                row = conn.execute("""
                    SELECT * FROM decisions WHERE id = ? AND scope = ? AND project_id IS ?
                """, (decision_id, caller.caller_scope, event.project_id)).fetchone()
                if row is None or not can_read(row, caller):
                    raise APIError("not_found")
                if event.kind == "correction":
                    continue
                frozen = json.loads(row["frozen"])["request"]
                decision = json.loads(row["record"])
                subject = frozen.get("subject_ref") or {}
                if any(
                    event.subject_ref.get(key) != subject[key]
                    for key in ("task_id", "unit_id", "unit_id_source") if key in subject
                ) or any(
                    event.subject_ref[key] != subject[key]
                    for key in ("step", "source_sha256", "input_sha256") if key in subject and key in event.subject_ref
                ):
                    raise APIError("invalid_request")
                if event.kind == "application":
                    if event.payload["recommended_candidate_id"] != decision["candidate_id"]:
                        raise APIError("invalid_request")
                    if event.payload["application_status"] == "applied" and (
                        decision["status"] != "complete" or decision["disposition"] != "suggested"
                        or event.payload["effective_candidate_id"] != decision["candidate_id"]
                    ):
                        raise APIError("invalid_request")
                    if frozen.get("preset") == "role_model_selection":
                        if not {"recommended_model", "launch_model", "effective_model"} <= event.payload.keys():
                            raise APIError("invalid_request")
                        if event.payload["application_status"] == "applied" and (
                            (event.payload.get("effective_model") or {}).get("configuration_status") != "confirmed"
                        ):
                            raise APIError("invalid_request")
                elif frozen.get("preset") == "role_model_selection" and "effective_model" not in event.payload:
                    raise APIError("invalid_request")

            if not duplicate:
                for prior in existing:
                    old = json.loads(prior["body"])
                    if (
                        old["kind"] != event.kind
                        or any(old["subject_ref"].get(key) != event.subject_ref.get(key)
                               for key in ("task_id", "unit_id", "unit_id_source"))
                        or (event.kind != "result" and set(old["decision_ids"]) != set(event.decision_ids))
                        or not merge_execution_refs((old.get("execution_ref"), data.get("execution_ref")))[1]
                        or ((old.get("coverage_observation") or {}).get("scope_ref")
                            != (data.get("coverage_observation") or {}).get("scope_ref"))
                    ):
                        raise APIError("revision_conflict")
                conn.execute("""
                    INSERT INTO feedback (scope, project_id, event_id, revision, receipt_id, body)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (*identity, event.revision, receipt_id, body_json))
                conn.executemany("""
                    INSERT INTO feedback_decisions (decision_id, receipt_id) VALUES (?, ?)
                """, ((decision_id, receipt_id) for decision_id in event.decision_ids))
        return {"receipt_id": receipt_id, "event_id": event.event_id, "revision": event.revision,
                "received": True, "duplicate": duplicate}

    oauth = (DecisionOAuth(settings.github_oauth, settings.callers, settings.db_path.parent / "oauth")
             if settings.github_oauth else None)
    mcp = DecisionMCPEndpoint(settings, caller_for_bearer, evaluate, read_decision, record_feedback, oauth)
    app.router.routes.append(Route("/mcp", endpoint=mcp, methods=["GET", "POST", "DELETE"]))
    if oauth is not None:
        app.router.routes.extend(oauth.routes)
    return app
