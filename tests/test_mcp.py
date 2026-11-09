import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from fastmcp.server.auth.oauth_proxy.upstream import AsyncOAuth2Client
from fastmcp.server.auth.providers.github import GitHubProvider

from decision_service import oauth
from decision_service.app import create_app
from decision_service.settings import GitHubOAuthSettings

from test_service import AUTH, config, program_event, provider_choice, workflow


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}


def rpc(client, method, params=None, *, auth=AUTH, request_id=1):
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return client.post("/mcp", headers={**MCP_HEADERS, **auth}, json=message)


def call(client, tool, args, *, auth=AUTH):
    reply = rpc(client, "tools/call", {"name": tool, "arguments": args}, auth=auth)
    assert reply.status_code == 200, reply.text
    result = reply.json()["result"]
    return result["structuredContent"], result.get("isError", False)


def test_mcp_and_http_share_decisions_feedback_and_scope(tmp_path):
    runs = []

    def decide(*args):
        runs.append(True)
        return provider_choice(*args)

    settings = config(tmp_path).model_copy(update={"mcp_allowed_hosts": ["service.test"]})
    with TestClient(create_app(settings, decide=decide), base_url="https://service.test") as client:
        initialize = {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "decision-test", "version": "1"},
        }
        assert rpc(client, "initialize", initialize, auth={}).status_code == 401
        init = rpc(client, "initialize", initialize)
        assert init.status_code == 200
        assert init.json()["result"]["protocolVersion"] == "2025-11-25"
        assert rpc(client, "notifications/initialized", request_id=None).status_code == 202
        tools = {tool["name"]: tool for tool in rpc(client, "tools/list").json()["result"]["tools"]}
        assert tools.keys() == {"evaluate_decision", "get_decision", "record_decision_feedback"}
        assert "schema_version" in tools["evaluate_decision"]["inputSchema"]["required"]
        assert tools["get_decision"]["annotations"]["readOnlyHint"] is True

        evaluation, failed = call(client, "evaluate_decision", workflow())
        assert not failed and evaluation["disposition"] == "suggested"
        assert client.post("/v1/decisions/evaluate", headers=AUTH, json=workflow()).json() == evaluation
        assert len(runs) == 1

        event = program_event(evaluation, "result")
        receipt, failed = call(client, "record_decision_feedback", event)
        assert not failed and receipt["received"] and not receipt["duplicate"]
        repeat = client.post("/v1/decision-feedback", headers=AUTH, json=event).json()
        assert repeat["duplicate"] and repeat["receipt_id"] == receipt["receipt_id"]

        lookup, failed = call(client, "get_decision", {"request_id": "req-1"})
        assert not failed and lookup["coverage"]["result"]["received"] == 1
        assert client.get(f"/v1/decisions/{evaluation['decision_id']}", headers=AUTH).json() == lookup

        other = {"Authorization": "Bearer other-token"}
        hidden, failed = call(client, "get_decision", {"decision_id": evaluation["decision_id"]}, auth=other)
        assert failed and hidden["error"]["code"] == "not_found"
        rejected, failed = call(client, "record_decision_feedback", event, auth=other)
        assert failed and rejected["error"]["code"] == "not_found"
        malformed, failed = call(client, "evaluate_decision", workflow(schema_version=True))
        assert failed and malformed["error"]["code"] == "invalid_request"
        out_of_scope, failed = call(client, "evaluate_decision", workflow(bank_ids=["d"]))
        assert failed and out_of_scope["error"]["code"] == "forbidden_scope"
        assert len(runs) == 1


def test_mcp_rejects_untrusted_origin_and_host(tmp_path):
    app = create_app(config(tmp_path), decide=provider_choice)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert rpc(client, "tools/list", auth={**AUTH, "Origin": "https://untrusted.invalid"}).status_code == 403
        assert rpc(client, "tools/list", auth={**AUTH, "Host": "untrusted.invalid"}).status_code == 421
        bad_lookup, failed = call(client, "get_decision", {"request_id": "req", "decision_id": "decision"})
        assert failed and bad_lookup["error"]["code"] == "invalid_request"


def oauth_settings(tmp_path):
    public = "https://gateway.test/decision-service"
    settings = config(tmp_path)
    return settings.model_copy(update={
        "callers": {key: caller for key, caller in settings.callers.items() if key != "restricted-token"},
        "mcp_allowed_hosts": ["gateway.test"],
        "github_oauth": GitHubOAuthSettings(
            public_base_url=public,
            principals={"github:fixture": "source"},
            allowed_client_redirect_uris=["http://127.0.0.1:*/callback"],
            client_id="test-github-client-id", client_secret="test-github-client-secret", signing_key="a" * 48,
        ),
    })


def test_oauth_metadata_and_registration_are_scoped_and_survive_restart(tmp_path, monkeypatch, caplog):
    settings = oauth_settings(tmp_path)
    monkeypatch.setattr(oauth, "OAUTH_STORAGE_BYTES", 320 * 1024)
    public = str(settings.github_oauth.public_base_url)
    protected_path = "/.well-known/oauth-protected-resource/decision-service/mcp"
    with TestClient(create_app(settings), base_url="https://gateway.test") as client:
        missing = rpc(client, "tools/list", auth={})
        assert missing.status_code == 401
        assert f'resource_metadata="https://gateway.test{protected_path}"' in missing.headers["WWW-Authenticate"]
        protected = client.get(protected_path).raise_for_status().json()
        assert protected["resource"] == public + "/mcp"
        assert protected["authorization_servers"] == [public]
        discovery = client.get("/.well-known/oauth-authorization-server/decision-service").raise_for_status().json()
        assert discovery["issuer"] == public
        assert discovery["registration_endpoint"] == public + "/register"
        assert discovery["token_endpoint"] == public + "/token"
        assert "S256" in discovery["code_challenge_methods_supported"]

        redirect = "http://127.0.0.1:51301/callback"
        registration = {
            "redirect_uris": [redirect], "application_type": "native", "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "client_name": "isolated integration client", "scope": "read:user",
        }
        denied = client.post("/register", json={**registration, "redirect_uris": ["https://wrong.invalid/callback"]})
        assert denied.status_code == 400
        registration["client_name"] = "isolated integration client " + "x" * (65 * 1024)
        registered = client.post("/register", json=registration)
        assert registered.status_code == 201, registered.text
        client_id = registered.json()["client_id"]
        exhausted = client.post("/register", json=registration)
        assert exhausted.status_code == 503

    with TestClient(create_app(settings), base_url="https://gateway.test", follow_redirects=False) as client:
        consent = client.get("/authorize", params={
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": "read:user",
            "code_challenge": "s" * 43, "code_challenge_method": "S256", "resource": public + "/mcp",
            "state": "synthetic-state",
        })
        assert consent.is_redirect
        assert consent.headers["location"].startswith(public + "/consent?")

        marker = "synthetic-sensitive-token-error"

        async def fail_token_exchange(client, **params):
            raise RuntimeError(marker)

        monkeypatch.setattr(AsyncOAuth2Client, "fetch_token", fail_token_exchange)
        txn_id = parse_qs(urlsplit(consent.headers["location"]).query)["txn_id"][0]
        form = client.get("/consent", params={"txn_id": txn_id}).raise_for_status().text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', form).group(1)
        approval = client.post("/consent", data={"txn_id": txn_id, "csrf_token": csrf, "action": "approve"})
        assert approval.is_redirect
        upstream = urlsplit(approval.headers["location"])
        assert upstream.hostname == "github.com"
        state = parse_qs(upstream.query)["state"][0]
        callback = client.get("/auth/callback", params={"state": state, "code": "synthetic-code"})
        assert callback.status_code == 500
        assert marker not in callback.text
        assert marker not in caplog.text
        assert "RuntimeError" in caplog.text


def test_verified_oauth_principal_reads_same_scope_as_bearer(tmp_path, monkeypatch):
    async def verify_token(provider, token):
        if token == "oauth-fixture":
            return SimpleNamespace(claims={"login": "FIXTURE"}, scopes=["read:user"])
        if token == "oauth-other":
            return SimpleNamespace(claims={"login": "another-user"}, scopes=["read:user"])
        return None

    monkeypatch.setattr(GitHubProvider, "verify_token", verify_token)
    settings = oauth_settings(tmp_path)
    with TestClient(create_app(settings, decide=provider_choice), base_url="https://gateway.test") as client:
        decision = client.post("/v1/decisions/evaluate", headers=AUTH, json=workflow()).raise_for_status().json()
        oauth = {"Authorization": "Bearer oauth-fixture"}
        record, failed = call(client, "get_decision", {"request_id": "req-1"}, auth=oauth)
        assert not failed and record["decision_id"] == decision["decision_id"]
        blocked, failed = call(client, "evaluate_decision", workflow(bank_ids=["d"]), auth=oauth)
        assert failed and blocked["error"]["code"] == "forbidden_scope"
        assert rpc(client, "tools/list", auth={"Authorization": "Bearer oauth-other"}).status_code == 403
        assert rpc(client, "tools/list", auth={"Authorization": "Bearer oauth-unknown"}).status_code == 401
        assert client.get("/v1/decisions", params={"request_id": "req-1"}, headers=oauth).status_code == 401
