"""Verify authenticated MCP and REST readback with synthetic records."""
import argparse
import json
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="HTTPS service base, without /mcp")
    parser.add_argument("token_file", type=Path, help="Owner-only file containing the Decision Service caller token")
    parser.add_argument("--request-id", required=True, help="Stable prefix for the synthetic records")
    parser.add_argument("--live-decisions", action="store_true", help="Request one real OpenAI predicate decision")
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})
            or not url.hostname or url.username or url.password or url.query or url.fragment):
        parser.error("Use the HTTPS base URL or an HTTP loopback base URL.")
    with os.fdopen(os.open(args.token_file, os.O_RDONLY | os.O_NOFOLLOW), encoding="ascii") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            parser.error("Use an owner-only regular token file.")
        token = handle.read().strip()
    if not token:
        parser.error("The token file is empty.")

    auth = {"Authorization": "Bearer " + token}
    protocol = "2025-11-25"
    mcp_headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": protocol}
    with httpx.Client(base_url=args.base_url.rstrip("/") + "/", timeout=25, trust_env=False) as client:
        def rpc(method, params, *, authorized=True, notification=False):
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            if not notification:
                message["id"] = 1
            headers = {**mcp_headers, **auth} if authorized else mcp_headers
            return client.post("mcp", headers=headers, json=message)

        def call_tool(name, arguments):
            reply = rpc("tools/call", {"name": name, "arguments": arguments})
            result = reply.raise_for_status().json()["result"]
            if result.get("isError"):
                raise SystemExit(f"{name} failed: {result['structuredContent']['error']['code']}")
            return result["structuredContent"]

        assert client.get("health").raise_for_status().json() == {"status": "ok"}
        initialize = {
            "protocolVersion": protocol, "capabilities": {},
            "clientInfo": {"name": "decision-service-deployment-check", "version": "1"},
        }
        assert rpc("initialize", initialize, authorized=False).status_code == 401
        assert rpc("initialize", initialize).raise_for_status().json()["result"]["protocolVersion"] == protocol
        assert rpc("notifications/initialized", {}, notification=True).status_code == 202
        names = {tool["name"] for tool in rpc("tools/list", {}).raise_for_status().json()["result"]["tools"]}
        assert names == {"evaluate_decision", "get_decision", "record_decision_feedback"}

        body = {
            "schema_version": 1, "request_id": args.request_id + "-transport", "kind": "choice",
            "question": "Select the single synthetic connectivity marker.", "context": {}, "recall": "skip",
            "choices": [{"candidate_id": "ready", "description": "Ready", "parameters": {}}],
        }
        decision = call_tool("evaluate_decision", body)
        assert decision["disposition"] == "suggested" and decision["candidate_id"] == "ready"
        assert decision["decision_model"]["status"] == "not_invoked"
        assert client.post("v1/decisions/evaluate", headers=auth, json=body).raise_for_status().json() == decision
        result = {
            "unauthenticated": 401, "tools": sorted(names), "mcp_and_rest_share_decision": True,
            "decision_id": decision["decision_id"],
        }

        # Keep the timestamp stable across repeat invocations with the same request ID.
        feedback = {
            "schema_version": 1, "project_id": None, "event_id": args.request_id + "-transport-note",
            "revision": 1, "kind": "correction", "decision_ids": [decision["decision_id"]],
            "subject_ref": {}, "observed_at": decision["attempts"][0]["started_at"],
            "payload": {
                "target_ref": decision["evidence_refs"][0], "text": "Synthetic connectivity check.",
                "reason_codes": [], "evidence_refs": [],
            },
        }
        receipt = call_tool("record_decision_feedback", feedback)
        replay = client.post("v1/decision-feedback", headers=auth, json=feedback).raise_for_status().json()
        assert replay["received"] and replay["duplicate"] and replay["receipt_id"] == receipt["receipt_id"]
        record = call_tool("get_decision", {"request_id": body["request_id"]})
        assert any(event["receipt_id"] == receipt["receipt_id"] for event in record["feedback"])
        result["mcp_and_rest_share_feedback_receipt"] = True

        if args.live_decisions:
            live = call_tool("evaluate_decision", {
                "schema_version": 1, "request_id": args.request_id + "-openai", "kind": "predicate",
                "question": "Is the number two greater than one?", "context": {}, "recall": "skip",
            })
            result["decisions"] = {
                "decision_id": live["decision_id"], "status": live["status"], "disposition": live["disposition"],
                "model": live["decision_model"], "reason_codes": live["reason_codes"],
            }
            if live["disposition"] != "suggested" or (live.get("answer") or {}).get("type") != "predicate":
                print(json.dumps(result))
                raise SystemExit("The OpenAI predicate did not return a usable answer.")
            assert len(live["attempts"]) == 1
            stored = call_tool("get_decision", {"decision_id": live["decision_id"]})
            assert stored["answer"] == live["answer"]
            result["decisions"]["answer_type"] = stored["answer"]["type"]
        print(json.dumps(result))


if __name__ == "__main__":
    main()
