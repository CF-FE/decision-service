"""Verify workflow recovery with Herdr and loopback provider stand-ins."""
import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

def load_workflow_fixture(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--herdr-root", type=Path, default=Path(__file__).resolve().parents[3] / "herdr-4-codexcloud",
        help="Herdr checkout containing the Decision Service integration (default: adjacent checkout)",
    )
    root = parser.parse_args().herdr_root.expanduser().resolve()
    path = root / "tests" / "test_project_workflow_decision.py"
    if not path.is_file():
        parser.error(f"Herdr workflow fixture not found: {path}")
    os.environ["no_proxy"] = "127.0.0.1"
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("workflow_fixture", path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    return fixture


class Provider(BaseHTTPRequestHandler):
    calls = []
    started = threading.Event()
    release = threading.Event()

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Provider.calls.append(self.path)
        if self.path == "/v1/default/banks/demo-a/memories/recall":
            assert self.headers["Authorization"] == "Bearer local-hindsight-only"
            status, payload = 200, {"results": [{"id": "mem-a", "document_id": "doc-a", "text": "Proceed to inspect."}]}
        elif self.path == "/v1/default/banks/demo-b/memories/recall":
            status, payload = 503, {}
        elif self.path == "/v1/decisions":
            assert self.headers["Authorization"] == "Bearer local-openai-only"
            question = body["questions"][0]
            if question["type"] == "predicate":
                Provider.started.set()
                assert Provider.release.wait(10)
                status, payload = 200, {"answers": [{"type": "predicate", "probability": 1.0}]}
            else:
                assert any(c["value"] == "inspect" for c in question["choices"])
                assert "Proceed to inspect" in body["input"][1]["content"]
                status, payload = 200, {"model": "gpt-6-luna", "answers": [
                    {"type": "choice", "choice": "inspect", "probabilities": [{"value": "inspect", "probability": 1.0}]}
                ]}
        else:
            status, payload = 404, {}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass  # The interrupt probe intentionally kills the upstream client.


@contextmanager
def service(config, port):
    env = dict(os.environ, DECISION_SERVICE_CONFIG=str(config),
               DECISION_SERVICE_OPENAI_API_KEY="local-openai-only",
               DECISION_SERVICE_HINDSIGHT_API_KEY="local-hindsight-only")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "decision_service.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--workers", "1", "--no-access-log",
         "--log-level", "warning"],
        env=env,
    )
    root = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            assert process.poll() is None
            try:
                with urlopen(root + "/health", timeout=0.25) as response:
                    assert json.load(response) == {"status": "ok"}
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("service did not become ready")
        yield process, root
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def main():
    fixture = load_workflow_fixture(__doc__)
    from decision_service_client import DecisionService, DecisionServiceError
    from project_workflow_decision import Checkpoint, choose, reconcile, record_result, update_quality

    class LoseFirstResponses(DecisionService):
        def __init__(self, root, token):
            super().__init__(root, token)
            self.evaluations = self.feedbacks = 0

        def evaluate(self, request):
            super().evaluate(request)
            self.evaluations += 1
            raise DecisionServiceError("transport_error")

        def feedback(self, event):
            super().feedback(event)
            self.feedbacks += 1
            raise DecisionServiceError("transport_error")

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=fake.serve_forever, daemon=True)
    thread.start()
    provider_url = f"http://127.0.0.1:{fake.server_port}"
    case = unittest.TestCase()
    try:
        with tempfile.TemporaryDirectory(prefix="decision-cross-") as scratch:
            cfg = Path(scratch) / "config.json"
            cfg.write_text(json.dumps({
                "db_path": str(Path(scratch) / "service.sqlite3"),
                "callers": {"local-herdr-only": {"caller_scope": "isolated", "project_ids": ["example"],
                                                  "bank_ids": ["demo-a", "demo-b"]}},
                "service_bank_ids": ["demo-a", "demo-b"],
                "default_banks": {"example": ["demo-a", "demo-b"]},
                "openai_base_url": provider_url, "hindsight_base_url": provider_url,
            }))
            with socket.socket() as addr:
                addr.bind(("127.0.0.1", 0))
                port = addr.getsockname()[1]
            checkpoint = fixture.example_checkpoint(case)
            with service(cfg, port) as (process, root):
                lossy = LoseFirstResponses(root, "local-herdr-only")
                outcome = choose(checkpoint, lossy)
                assert outcome["application_status"] == "applied", outcome
                assert (lossy.evaluations, lossy.feedbacks) == (1, 1)
                first = lossy.get(request_id=outcome["request_id"])
                assert first["retrieval"]["status"] == "partial"
                assert first["retrieval"]["evidence"][0]["document_id"] == "doc-a"
                assert first["decision_model"]["model"] == "gpt-6-luna"
                assert first["coverage"]["pending"] == 1
                assert first["feedback"][0]["payload"]["application_status"] == "applied"
                action = checkpoint.native("status")["action"]["id"]
                checkpoint.native("receive", "--action", action, "--status", "COLLECTED",
                                  "--evidence", "artifact:original")
                assert checkpoint.native("status")["action"] is None
                record_result(checkpoint, outcome["unit_id"], "completed", ["artifact:original"], ["check:terminal"])
                original_receipt = first["feedback"][0]["receipt_id"]

                client = DecisionService(root, "local-herdr-only")
                interrupted = {"schema_version": 1, "request_id": "interrupt-probe", "kind": "predicate",
                               "question": "Is this interrupted?", "context": {}, "recall": "skip"}
                def start_interrupted():
                    try:
                        client.evaluate(interrupted)
                    except DecisionServiceError as error:
                        assert error.code == "transport_error"
                pending = threading.Thread(target=start_interrupted)
                pending.start()
                assert Provider.started.wait(5)
                assert client.get(request_id="interrupt-probe")["status"] == "processing"
                process.kill()
                process.wait(timeout=5)
                pending.join(5)
                assert not pending.is_alive()
                Provider.release.set()
            with service(cfg, port) as (_, root):
                client = DecisionService(root, "local-herdr-only")
                unknown = client.get(request_id="interrupt-probe")
                assert unknown["status"] == "unknown" and unknown["parameters"] is None
                assert client.evaluate(interrupted)["attempts"] == unknown["attempts"]
                recovered = Checkpoint(checkpoint.workflow, checkpoint.state)
                with patch.object(recovered, "native", side_effect=AssertionError("feedback recovery replayed business")):
                    receipt = reconcile(recovered, client)
                    assert receipt == {"received": 3, "pending": []}, receipt
                    update_quality(recovered, outcome["unit_id"], "passed", ["check:isolated"])
                    assert reconcile(recovered, client) == {"received": 1, "pending": []}
                finished = client.get(decision_id=outcome["decision_id"])
                assert next(f for f in finished["feedback"]
                            if f["kind"] == "application" and f["revision"] == 1)["receipt_id"] == original_receipt
                assert finished["coverage"] == {
                    "application": {"expected": 1, "received": 1, "rate": 1.0},
                    "result": {"expected_ended": 1, "received": 1, "rate": 1.0},
                    "pending": 0, "missing": 0, "unknown": 0, "quality_pending": 0,
                    "scope_complete": False, "observed_at": finished["coverage"]["observed_at"],
                }, finished["coverage"]
                results = [f for f in finished["feedback"] if f["kind"] == "result"]
                assert [(f["revision"], f["is_current"], f["payload"]["quality_status"]) for f in results] == [
                    (1, False, "pending"), (2, True, "passed"),
                ]
                assert all(f["execution_ref"]["ids"] == {"action_id": action} for f in results)
                assert sorted(Provider.calls) == sorted(["/v1/default/banks/demo-a/memories/recall",
                                                          "/v1/default/banks/demo-b/memories/recall",
                                                          "/v1/decisions", "/v1/decisions"])
                print(json.dumps({
                    "workflow": "applied by generated original template",
                    "provider_calls": Provider.calls, "recall": first["retrieval"]["status"],
                    "decision_ack_lost_and_recovered": True, "feedback_ack_lost_and_recovered": True,
                    "interrupted": unknown["status"], "result_revisions": [f["revision"] for f in results],
                    "coverage": finished["coverage"], "no_business_replay": True,
                }, ensure_ascii=False))
    finally:
        Provider.release.set()
        case.doCleanups()
        fake.shutdown()
        fake.server_close()


if __name__ == "__main__":
    main()
