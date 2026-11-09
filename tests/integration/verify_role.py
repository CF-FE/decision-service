"""Cross-repository model application with loopback providers and a simulated Herdr host."""
import json
import socket
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from verify_cross import Provider, load_workflow_fixture, service


def main():
    fixture = load_workflow_fixture(__doc__)
    from decision_service_client import DecisionService
    from herdr_model_selection import LOCATION, apply, reconcile_model
    from project_workflow_decision import choose, reconcile, record_result

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    provider_url = f"http://127.0.0.1:{fake.server_port}"
    case = unittest.TestCase()
    try:
        with tempfile.TemporaryDirectory(prefix="decision-role-cross-") as scratch:
            scratch = Path(scratch)
            cfg = scratch / "config.json"
            cfg.write_text(json.dumps({
                "db_path": str(scratch / "service.sqlite3"),
                "callers": {"local-herdr-only": {"caller_scope": "isolated", "project_ids": ["example"],
                                                  "bank_ids": ["demo-a", "demo-b"]}},
                "service_bank_ids": ["demo-a", "demo-b"], "default_banks": {"example": ["demo-a", "demo-b"]},
                "openai_base_url": provider_url, "hindsight_base_url": provider_url,
            }))
            with socket.socket() as addr:
                addr.bind(("127.0.0.1", 0))
                port = addr.getsockname()[1]
            checkpoint = fixture.example_checkpoint(case)
            with service(cfg, port) as (_, root):
                client = DecisionService(root, "local-herdr-only")
                workflow = choose(checkpoint, client)
                assert workflow["application_status"] == "applied"
                action = checkpoint.native("status")["action"]["id"]
                cwd = str(scratch)
                location = {key: f"isolated-{key}" for key in LOCATION}
                binding = {
                    **location, "mode": "new-unit", "session": "isolated-session", "agent": "isolated-role",
                    "cwd": cwd, "authorization_ref": "fixture:isolated", "provider": "openai",
                    "project_id": "example", "task_id": "issue-7", "unit_id": workflow["unit_id"],
                    "action_id": action, "codex_args": ["--no-daemon"],
                }
                selection = {
                    "requirements": {}, "recall": "auto", "capabilities": [{
                        "worker_id": "mac-codex", "backend_id": "current-default", "provider": "openai",
                        "model_type": "coding", "model": "fixture-model", "supported_efforts": ["high"],
                        "context_window": 4096, "tools": [], "modalities": ["text"], "evidence_ref": "fixture:capability",
                    }],
                }
                starts = []
                foreground_reads = []

                def host(session, *command):
                    assert session == "isolated-session"
                    if command[:2] == ("agent", "list"):
                        return {"agents": []}
                    if command[:2] == ("pane", "list"):
                        return {"panes": [{**location, "cwd": cwd, "foreground_cwd": cwd, "launch_pending": False}]}
                    if command[:2] == ("pane", "process-info"):
                        if starts:
                            launch = starts[0]
                            argv = ["codex", *launch[launch.index("--") + 1:]]
                            pid = 456
                        else:
                            argv = ["zsh"]
                            pid = 123
                        foreground_reads.append(argv[0])
                        return {"process_info": {
                            "pane_id": location["pane_id"], "shell_pid": 123, "foreground_process_group_id": pid,
                            "foreground_processes": [{"pid": pid, "cwd": cwd, "argv": argv}],
                        }}
                    if command[:2] == ("agent", "start"):
                        starts.append(command)
                        assert command[-5:] == ("--no-daemon", "-m", "fixture-model", "-c", 'model_reasoning_effort="high"')
                        return {}
                    if command[:2] == ("agent", "get"):
                        assert len(starts) == 1
                        return {"agent": {
                            **location, "name": "isolated-role", "agent": "codex", "cwd": cwd, "foreground_cwd": cwd,
                            "agent_session": {"agent": "codex", "kind": "id", "value": "isolated-thread"},
                        }}
                    raise AssertionError(command)

                proposed = apply(checkpoint, client, workflow["unit_id"], binding, selection, host=host)
                assert not proposed["feedback"]["pending"], proposed
                assert proposed["thread_id"] == "isolated-thread" and foreground_reads == ["zsh", "codex"]
                assert proposed["application_status"] == "unknown" and proposed["effective_model"]["model"] is None
                assert apply(checkpoint, client, workflow["unit_id"], binding, selection, host=host)["application_status"] == "unknown"
                assert len(starts) == 1
                rollout = scratch / "isolated-rollout.jsonl"
                rollout.write_text(json.dumps({"type": "session_meta", "payload": {
                    "id": "isolated-thread", "cwd": cwd, "model_provider": "openai",
                }}) + "\n" + json.dumps({"type": "turn_context", "payload": {
                    "turn_id": "isolated-turn", "cwd": cwd, "model": "fixture-model", "effort": "high",
                }}) + "\n")
                rollout.chmod(0o600)
                applied = reconcile_model(checkpoint, client, proposed["request_id"],
                                          rollout=rollout, turn_id="isolated-turn", host=host)
                assert applied["application_status"] == "applied", applied
                assert not applied["feedback"]["pending"], applied
                assert applied["effective_model"]["configuration_status"] == "confirmed"
                checkpoint.native("receive", "--action", action, "--status", "COLLECTED", "--evidence", "fixture:output")
                record_result(checkpoint, workflow["unit_id"], "completed", ["fixture:output"], ["fixture:terminal"])
                assert not reconcile(checkpoint, client)["pending"]
                ids = [workflow["decision_id"], proposed["decision_id"]]
                records = [client.get(decision_id=decision_id) for decision_id in ids]
                result = [next(f for f in row["feedback"] if f["kind"] == "result") for row in records]
                assert result[0] == result[1]
                assert sorted(result[0]["decision_ids"]) == sorted(ids)
                assert result[0]["execution_ref"]["ids"]["turn_id"] == "isolated-turn"
                assert result[0]["execution_ref"]["ids"]["action_id"] == action
                assert result[0]["payload"]["effective_model"]["model"] == "fixture-model"
                assert all(row["coverage"]["result"]["received"] == 1 for row in records)
                assert records[1]["retrieval"]["reason_code"] == "single_candidate"
                assert len(starts) == 1 and len(Provider.calls) == 3 and Provider.calls.count("/v1/decisions") == 1
                print(json.dumps({
                    "role_start_calls": len(starts), "host": "isolated stand-in",
                    "foreground_reads": foreground_reads, "launch_argv_readback_verified": True,
                    "recommendation_and_launch": proposed["launch_model"], "initial_application": "unknown",
                    "effective_readback": applied["effective_model"], "result_event_shared": True,
                    "result_coverage_per_record": [row["coverage"]["result"] for row in records],
                    "provider_calls": Provider.calls,
                }, ensure_ascii=False))
    finally:
        case.doCleanups()
        fake.shutdown()
        fake.server_close()


if __name__ == "__main__":
    main()
