import asyncio
import json

import httpx
import pytest

from decision_service import providers


@pytest.fixture
def settings():
    return {
        "openai_base_url": "https://decisions.example",
        "openai_api_key": "fixture-openai",
        "openai_model": "gpt-6-luna",
        "hindsight_base_url": "https://memory.example",
        "hindsight_api_key": "fixture-hindsight",
        "timeout_seconds": 2,
        "evidence_max_chars": 6,
        "max_parallel_banks": 2,
    }


@pytest.fixture
def mock_http(monkeypatch):
    client_class = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            providers.httpx,
            "AsyncClient",
            lambda **options: client_class(transport=httpx.MockTransport(handler), **options),
        )

    return install


PREDICATE = {"kind": "predicate", "question": "Is the evidence sufficient?", "context": {}}
CHOICE = {
    "kind": "choice",
    "question": "Which candidate best fits the current state?",
    "context": {"state": "ready"},
    "choices": [
        {"candidate_id": "continue", "description": "Continue", "parameters": {"step": "verify"}},
        {
            "candidate_id": "replan",
            "description": "Replan",
            "parameters": {},
            "metadata": {"executable": False, "disposition": "needs_replan"},
        },
    ],
}
SCORE = {
    "kind": "score",
    "question": "How severe is the issue?",
    "context": {},
    "levels": [
        {"label": "low", "description": "Cosmetic"},
        {"label": "high", "description": "Blocked"},
    ],
}


def test_recall_to_decisions_uses_budgeted_evidence(mock_http, settings):
    async def upstream(request):
        payload = json.loads(request.content)
        assert request.method == "POST"
        if request.url.host == "memory.example":
            assert request.headers["authorization"] == "Bearer fixture-hindsight"
            assert payload == {"query": CHOICE["question"], "max_tokens": 6}
            path = request.url.raw_path
            if path == b"/v1/default/banks/first/memories/recall":
                return httpx.Response(200, json={"results": [
                    {
                        "id": "m1", "document_id": "d1", "text": "相关", "scores": {"final": 1},
                        "occurred_start": "2026-11-05T09:30:00+08:00",
                        "occurred_end": "2026-11-05T10:00:00+08:00",
                        "mentioned_at": "2026-11-06T01:00:00Z",
                    },
                    {"id": "m2", "text": "later"},
                ]})
            if path == b"/v1/default/banks/shared%3Ateam/memories/recall":
                return httpx.Response(200, json={"results": [
                    {"id": "m3", "text": "另一条记录", "occurred_start": None},
                ]})
            if path == b"/v1/default/banks/empty/memories/recall":
                return httpx.Response(200, json={"results": []})
            assert path == b"/v1/default/banks/failed/memories/recall"
            return httpx.Response(403, json={"message": "fixture private content"})

        assert request.url == "https://decisions.example/v1/decisions"
        assert request.headers["authorization"] == "Bearer fixture-openai"
        assert payload["model"] == "gpt-6-luna"
        assert payload["questions"] == [{
            "type": "choice",
            "instructions": CHOICE["question"],
            "choices": [
                {"value": "continue", "description": "Continue"},
                {"value": "replan", "description": "Replan"},
            ],
        }]
        assert payload["input"][0]["role"] == "developer"
        assert payload["input"][1]["role"] == "user"
        assert json.loads(payload["input"][1]["content"]) == {
            "context": CHOICE["context"],
            "evidence": expected_evidence,
            "candidates": [
                {"candidate_id": "continue", "parameters": {"step": "verify"}},
                {"candidate_id": "replan", "parameters": {}, "metadata": CHOICE["choices"][1]["metadata"]},
            ],
        }
        return httpx.Response(200, json={
            "model": "fixture-model-readback",
            "answers": [{
                "type": "choice",
                "name": None,
                "choice": "continue",
                "confidence": 0.9,
                "probabilities": [{"value": "continue", "probability": 0.8}],
                "parameters": {"step": "injected"},
            }],
            "usage": {
                "input_tokens": 90, "total_tokens": 91, "output_tokens": 1, "cost": 5,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 25},
                "output_tokens_details": {"reasoning_tokens": 0, "cash": 8},
            },
        })

    mock_http(upstream)
    expected_evidence = [
        {
            "bank_id": "first", "document_id": "d1", "memory_id": "m1", "text": "相关",
            "occurred_start": "2026-11-05T09:30:00+08:00",
            "occurred_end": "2026-11-05T10:00:00+08:00",
            "mentioned_at": "2026-11-06T01:00:00Z",
        },
        {"bank_id": "shared:team", "document_id": None, "memory_id": "m3", "text": "另一条记"},
    ]
    retrieved = providers.retrieve_evidence(
        {**CHOICE, "bank_ids": ["unresolved"]}, ["first", "shared:team", "empty", "failed"], settings
    )
    assert retrieved == {
        "evidence": expected_evidence,
        "banks": [
            {"bank_id": "first", "status": "ok", "reason_code": None},
            {"bank_id": "shared:team", "status": "ok", "reason_code": None},
            {"bank_id": "empty", "status": "empty", "reason_code": None},
            {"bank_id": "failed", "status": "failed", "reason_code": "hindsight_http_403"},
        ],
    }
    assert providers.call_decisions(CHOICE, retrieved["evidence"], settings) == {
        "status": "ok",
        "answer": {
            "type": "choice",
            "choice": "continue",
            "probabilities": [{"value": "continue", "probability": 0.8}],
        },
        "model": {
            "provider": "openai",
            "model_type": "decision",
            "model": "fixture-model-readback",
            "requested_model": "gpt-6-luna",
            "configuration_status": "confirmed",
            "reasoning_effort": None,
            "effort_status": "not_applicable",
        },
        "usage": {
            "input_tokens": 90, "total_tokens": 91, "output_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 25},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "reason_codes": [],
    }


def test_recall_parallel_limit_and_deadline_preserve_other_banks(mock_http, settings):
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    active = peak = 0

    async def upstream(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        bank = request.url.path.split("/")[4]
        try:
            if bank == "slow":
                first_started.set()
                await asyncio.Future()
            if bank == "good":
                second_started.set()
                await first_started.wait()
                return httpx.Response(200, json={"results": [{"text": "hit"}]})
            await second_started.wait()
            return httpx.Response(200, json={"results": [{"id": [], "text": "malformed"}]})
        finally:
            active -= 1

    mock_http(upstream)
    settings["timeout_seconds"] = 0.2
    result = providers.retrieve_evidence(PREDICATE, ["slow", "good", "malformed"], settings)
    assert peak == 2
    assert active == 0
    assert result["banks"] == [
        {"bank_id": "slow", "status": "failed", "reason_code": "hindsight_timeout"},
        {"bank_id": "good", "status": "ok", "reason_code": None},
        {"bank_id": "malformed", "status": "failed", "reason_code": "hindsight_invalid_response"},
    ]
    assert result["evidence"] == [
        {"bank_id": "good", "document_id": None, "memory_id": None, "text": "hit"}
    ]


def test_recall_without_authorized_banks_or_with_skip_never_connects(mock_http, settings):
    def unexpected_request(_request):
        pytest.fail("Recall contacted the upstream")

    mock_http(unexpected_request)
    assert providers.retrieve_evidence(
        {**PREDICATE, "bank_ids": ["unresolved"]}, [], settings
    ) == {"banks": [], "evidence": []}
    assert providers.retrieve_evidence(
        {**PREDICATE, "recall": "skip"}, ["first"], settings
    ) == {
        "banks": [{"bank_id": "first", "status": "skipped", "reason_code": "recall_disabled"}],
        "evidence": [],
    }
    with pytest.raises(ValueError, match="single path segments"):
        providers.retrieve_evidence(PREDICATE, ["../other"], settings)


@pytest.fixture
def gateway_settings(settings):
    return {
        **settings,
        "hindsight_api_mode": "gateway",
        "hindsight_base_url": "https://memory.example/hindsight",
    }


def gateway_receipt(bank_id, results):
    return {
        "state": "RESPONSE", "action": "recall", "bank_id": bank_id,
        "http_status": 200, "body": {"results": results},
    }


@pytest.mark.parametrize("wrapper", ["structured", "result_text", "content"])
def test_gateway_recall_uses_original_route_and_native_provenance(mock_http, gateway_settings, wrapper):
    gateway_settings["timeout_seconds"] = 240
    receipt = gateway_receipt("allowed", [{
        "id": "memory-1", "document_id": "source-1", "text": "abcdefg",
        "mentioned_at": "2026-11-05T09:00:00Z",
    }])

    def upstream(request):
        assert request.method == "POST"
        assert request.url == "https://memory.example/hindsight/api"
        assert request.headers["authorization"] == "Bearer fixture-hindsight"
        assert json.loads(request.content) == {
            "tool": "recall",
            "arguments": {"bank_id": "allowed", "query": PREDICATE["question"], "max_tokens": 6},
            "timeout_seconds": 180,
        }
        response = {"isError": False}
        if wrapper == "structured":
            response["structuredContent"] = receipt
        elif wrapper == "result_text":
            response["structuredContent"] = {"result": json.dumps(receipt)}
        else:
            response["content"] = [
                {"type": "text", "text": "Recall receipt"},
                {"type": "text", "text": json.dumps(receipt)},
            ]
        return httpx.Response(200, json=response)

    mock_http(upstream)
    result = providers.retrieve_evidence(
        {**PREDICATE, "bank_ids": ["unresolved"]}, ["allowed"], gateway_settings
    )
    assert result == {
        "banks": [{"bank_id": "allowed", "status": "ok", "reason_code": None}],
        "evidence": [{
            "bank_id": "allowed", "document_id": "source-1", "memory_id": "memory-1",
            "text": "abcdef", "mentioned_at": "2026-11-05T09:00:00Z",
        }],
    }


def test_gateway_reports_tool_and_upstream_failures_without_retry(mock_http, gateway_settings):
    called = []

    def upstream(request):
        bank = json.loads(request.content)["arguments"]["bank_id"]
        called.append(bank)
        receipt = gateway_receipt(bank, [])
        if bank == "tool-error":
            return httpx.Response(200, json={
                "isError": True, "structuredContent": receipt,
                "content": [{"type": "text", "text": "fixture private upstream detail"}],
            })
        if bank == "unknown":
            receipt["state"] = "UNKNOWN"
        if bank == "upstream-error":
            receipt["http_status"] = 503
        if bank == "mismatch":
            receipt["bank_id"] = "unrequested"
        return httpx.Response(200, json={"isError": False, "structuredContent": receipt})

    mock_http(upstream)
    banks = ["empty", "tool-error", "unknown", "upstream-error", "mismatch"]
    result = providers.retrieve_evidence(PREDICATE, banks, gateway_settings)
    assert sorted(called) == sorted(banks)
    assert result == {
        "evidence": [],
        "banks": [
            {"bank_id": "empty", "status": "empty", "reason_code": None},
            {"bank_id": "tool-error", "status": "failed", "reason_code": "hindsight_gateway_error"},
            {"bank_id": "unknown", "status": "failed", "reason_code": "hindsight_gateway_error"},
            {"bank_id": "upstream-error", "status": "failed", "reason_code": "hindsight_upstream_http_503"},
            {"bank_id": "mismatch", "status": "failed", "reason_code": "hindsight_invalid_response"},
        ],
    }


def test_gateway_forwards_remaining_budget_after_parallel_queue(mock_http, gateway_settings):
    gateway_settings.update(max_parallel_banks=1, timeout_seconds=0.5)
    budgets = []

    async def upstream(request):
        payload = json.loads(request.content)
        budgets.append(payload["timeout_seconds"])
        if len(budgets) == 1:
            await asyncio.sleep(0.05)
        return httpx.Response(200, json={
            "isError": False,
            "structuredContent": gateway_receipt(payload["arguments"]["bank_id"], []),
        })

    mock_http(upstream)
    result = providers.retrieve_evidence(PREDICATE, ["first", "second"], gateway_settings)
    assert [entry["status"] for entry in result["banks"]] == ["empty", "empty"]
    assert 0 < budgets[1] < budgets[0] - 0.04 < 0.5


@pytest.mark.parametrize("question,native,answer,status", [
    (
        PREDICATE,
        {"type": "predicate", "name": None, "probability": 0.8},
        {"type": "predicate", "probability": 0.8},
        "ok",
    ),
    (
        SCORE,
        {"type": "score", "score": 0.8, "confidence": 0.9, "probabilities": [
            {"value": 0, "label": "low", "probability": 0.2},
            {"value": 1, "label": "high", "probability": 0.8},
        ]},
        {"type": "score", "score": 0.8, "probabilities": [
            {"value": 0, "probability": 0.2}, {"value": 1, "probability": 0.8},
        ]},
        "ok",
    ),
    (CHOICE, {"type": "refusal", "name": None}, {"type": "refusal", "reason": "provider_refusal"}, "refused"),
])
def test_typed_answers_with_no_model_or_usage_readback(mock_http, settings, question, native, answer, status):
    def upstream(request):
        sent = json.loads(request.content)["questions"]
        assert len(sent) == 1
        assert sent[0]["type"] == question["kind"]
        if question["kind"] == "score":
            assert sent[0]["levels"] == question["levels"]
        return httpx.Response(200, json={"answers": [native]})

    mock_http(upstream)
    result = providers.call_decisions(question, [], settings)
    assert result["status"] == status
    assert result["answer"] == answer
    assert result["reason_codes"] == (["provider_refusal"] if status == "refused" else [])
    assert result["model"]["model"] is None
    assert result["model"]["configuration_status"] == "unconfirmed"
    assert result["model"]["requested_model"] == "gpt-6-luna"
    assert result["usage"] is None


@pytest.mark.parametrize("question,native", [
    (CHOICE, {"type": "choice", "choice": "arbitrary-command", "probabilities": []}),
    (CHOICE, {"type": "choice", "choice": "continue", "probabilities": [{"value": True, "probability": 1}]}),
    (PREDICATE, {"type": "choice", "choice": "continue", "probabilities": []}),
    (PREDICATE, {"type": "predicate", "probability": True}),
    (SCORE, {"type": "score", "score": 0.8, "probabilities": [{"value": 2, "probability": 0.8}]}),
])
def test_invalid_answers_remain_unavailable_with_observed_usage(mock_http, settings, question, native):
    mock_http(lambda _: httpx.Response(
        200, json={"answers": [native], "model": "observed", "usage": {"input_tokens": 3}}
    ))
    result = providers.call_decisions(question, [], settings)
    assert result["status"] == "unavailable"
    assert result["answer"] is None
    assert result["reason_codes"] == ["openai_invalid_response"]
    assert result["model"]["model"] == "observed"
    assert result["usage"] == {"input_tokens": 3}


@pytest.mark.parametrize("response,reason", [
    (httpx.Response(429, text="fixture-private-upstream-body"), "openai_http_429"),
    (httpx.Response(200, text="fixture-private-upstream-body"), "openai_invalid_response"),
    (httpx.Response(302, headers={"Location": "https://unexpected.example"}), "openai_http_302"),
])
def test_http_and_json_failures_return_sanitized_results(mock_http, settings, response, reason):
    def upstream(request):
        assert request.url.host == "decisions.example"
        return response

    mock_http(upstream)
    result = providers.call_decisions(PREDICATE, [], settings)
    assert result["status"] == "unavailable"
    assert result["reason_codes"] == [reason]
    assert result["answer"] is None
    assert "fixture-private-upstream-body" not in repr(result)


def test_timeout_and_programming_exception_are_distinct(mock_http, settings):
    async def slow(_request):
        await asyncio.Future()

    mock_http(slow)
    settings["timeout_seconds"] = 0.05
    assert providers.call_decisions(PREDICATE, [], settings)["reason_codes"] == ["openai_timeout"]

    def broken(_request):
        raise RuntimeError("adapter defect")

    mock_http(broken)
    with pytest.raises(RuntimeError, match="adapter defect"):
        providers.call_decisions(PREDICATE, [], settings)
