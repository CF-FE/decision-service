import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "plugin" / "package_plugin.py"
SKILL = ROOT / "skill" / "decision-service" / "SKILL.md"
ENDPOINT = "https://decision.example.invalid/mcp"


@pytest.mark.parametrize("extra_args,credentials", [
    ([], {}),
    (["--auth", "bearer"], {"bearer_token_env_var": "DECISION_SERVICE_MCP_TOKEN"}),
])
def test_local_marketplace_contains_the_skill_and_native_auth(tmp_path, extra_args, credentials):
    marketplace = tmp_path / "marketplace"
    subprocess.run([
        sys.executable, BUILDER, "local", "--mcp-url", ENDPOINT, "--output", marketplace, *extra_args,
    ], check=True)
    catalog = json.loads((marketplace / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert catalog["name"] == "cf-fe-decision-local"
    local = marketplace / catalog["plugins"][0]["source"]["path"]
    manifest = json.loads((local / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((local / manifest["mcpServers"]).read_text(encoding="utf-8"))
    assert manifest["name"] == "decision-service"
    assert (local / manifest["skills"] / "decision-service/SKILL.md").read_bytes() == SKILL.read_bytes()
    assert mcp["mcpServers"]["decision-service"] == {"url": ENDPOINT, **credentials}


def test_cloud_update_preserves_native_app_binding_and_presentation(tmp_path):
    native_manifest = tmp_path / "native-plugin.json"
    native_app = tmp_path / "native-app.json"
    archive = tmp_path / "decision-service-skill.zip"
    source = {
        "name": "app-fixture",
        "version": "1.0.0",
        "description": "Native private MCP App",
        "apps": "./.app.json",
        "interface": {"displayName": "Decision Service", "defaultPrompt": ["First", "Second"]},
    }
    native_manifest.write_text(json.dumps(source), encoding="utf-8")
    native_app.write_text(json.dumps({"apps": {"fixture": {"id": "asdk_app_fixture"}}}), encoding="utf-8")
    subprocess.run([
        sys.executable, BUILDER, "cloud-skill", "--native-manifest", native_manifest,
        "--native-app", native_app, "--output", archive,
    ], check=True)

    with ZipFile(archive) as package:
        # Updating the release leaves the native binding itself in place.
        assert set(package.namelist()) == {
            "plugin.json", ".codex-plugin/plugin.json", "skills/decision-service/SKILL.md",
        }
        manifest = json.loads(package.read("plugin.json"))
        legacy = json.loads(package.read(".codex-plugin/plugin.json"))
        assert package.read("skills/decision-service/SKILL.md") == SKILL.read_bytes()
    assert manifest["name"] == source["name"]
    assert manifest["version"] == "1.0.1"
    assert manifest["extensions"]["com.openai"] == {"apps": source["apps"], "interface": source["interface"]}
    assert legacy == {**source, "version": "1.0.1", "skills": "./skills/"}


@pytest.mark.parametrize("url", [
    "https://user:fixture-secret@example.invalid/mcp",
    "https://example.invalid/mcp?token=fixture-secret",
    "http://example.invalid/mcp",
    "https://example.invalid:fixture-secret/mcp",
])
def test_packaging_rejects_secret_urls_and_insecure_remote_transport(tmp_path, url):
    output = tmp_path / "artifact"
    result = subprocess.run([
        sys.executable, BUILDER, "local", "--mcp-url", url, "--output", output,
    ], capture_output=True, text=True)
    assert result.returncode == 2
    assert "fixture-secret" not in result.stderr
    assert not output.exists()
