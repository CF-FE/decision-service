"""Build a local Codex marketplace or add the skill to a native private App."""

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile


SOURCE = Path(__file__).resolve().parent
SKILL_PATH = "skills/decision-service/SKILL.md"


def package_local(output, mcp_url, auth, skill):
    endpoint_error = "provide an HTTPS MCP endpoint without credentials, query, or fragment"
    try:
        url = urlsplit(mcp_url)
        port = url.port
    except ValueError:
        raise ValueError(endpoint_error) from None
    local_http = url.scheme == "http" and url.hostname in {"127.0.0.1", "::1", "localhost"}
    if (
        not (url.scheme == "https" or local_http) or not url.hostname or not url.path
        or url.username is not None or url.query or url.fragment or port == 0
        or any(character.isspace() for character in mcp_url)
    ):
        raise ValueError(endpoint_error)

    manifest = json.loads(
        (SOURCE / "decision-service" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    name = manifest["name"]
    marketplace = {
        "name": "cf-fe-decision-local",
        "interface": {"displayName": "CF-FE Decision Service"},
        "plugins": [{
            "name": name,
            "source": {"source": "local", "path": f"./{name}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
            "category": manifest["interface"]["category"],
        }],
    }
    server = {"url": mcp_url}
    if auth == "bearer":
        server["bearer_token_env_var"] = "DECISION_SERVICE_MCP_TOKEN"
    mcp = {"mcpServers": {name: server}}
    output.mkdir()
    for relative, data in {
        ".agents/plugins/marketplace.json": marketplace,
        f"{name}/.codex-plugin/plugin.json": manifest,
        f"{name}/.mcp.json": mcp,
    }.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = output / name / SKILL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(skill)


def package_cloud_skill(output, native_manifest, native_app, skill):
    manifest = json.loads(native_manifest.read_text(encoding="utf-8"))
    app_binding = json.loads(native_app.read_text(encoding="utf-8"))
    metadata_fields = {"name", "version", "description", "author", "homepage", "repository", "license", "keywords"}
    if (
        not isinstance(manifest, dict)
        or set(manifest) - metadata_fields - {"interface", "apps", "skills"}
        or manifest.get("apps") != "./.app.json"
        or manifest.get("skills", "./skills/") not in ("./skills", "./skills/")
        or not isinstance(manifest.get("name"), str)
        or not isinstance(manifest.get("interface"), dict)
    ):
        raise ValueError("expected the native App-backed compatibility manifest")
    apps = app_binding.get("apps") if isinstance(app_binding, dict) else None
    if not isinstance(apps, dict) or len(apps) != 1:
        raise ValueError("expected exactly one verified native App binding")
    app = next(iter(apps.values()))
    app_id = app.get("id") if isinstance(app, dict) else None
    if not isinstance(app_id, str) or not re.fullmatch(
        r"(?:asdk_app_|connector_|templated_apps_)[A-Za-z0-9][A-Za-z0-9_-]*", app_id
    ):
        raise ValueError("expected a verified native App ID")

    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version):
        raise ValueError("expected a stable semantic version in the native manifest")
    major, minor, patch = version.split(".")
    manifest["version"] = f"{major}.{minor}.{int(patch) + 1}"
    manifest.setdefault("skills", "./skills/")
    portable = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        **{key: manifest[key] for key in manifest if key in metadata_fields},
        "extensions": {"com.openai": {"interface": manifest["interface"], "apps": manifest["apps"]}},
    }

    # The update archive overlays the native release and leaves its .app.json in place.
    with ZipFile(output, "x", ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", json.dumps(portable, ensure_ascii=False, indent=2))
        archive.writestr(".codex-plugin/plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr(SKILL_PATH, skill)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_subparsers(dest="target", required=True)
    local = targets.add_parser("local", help="Build a local Codex marketplace")
    local.add_argument("--mcp-url", required=True, help="Verified Streamable HTTP MCP endpoint")
    local.add_argument("--auth", choices=("oauth", "bearer"), default="oauth")
    local.add_argument("--output", required=True, type=Path, help="New marketplace directory")
    cloud = targets.add_parser("cloud-skill", help="Build a skill update for an existing native App-backed plugin")
    cloud.add_argument("--native-manifest", required=True, type=Path, help="Read back .codex-plugin/plugin.json")
    cloud.add_argument("--native-app", required=True, type=Path, help="Read back .app.json from the same release")
    cloud.add_argument("--output", required=True, type=Path, help="New update ZIP file")
    args = parser.parse_args()

    skill = (SOURCE.parent / "skill" / "decision-service" / "SKILL.md").read_bytes()
    try:
        if args.target == "local":
            package_local(args.output, args.mcp_url, args.auth, skill)
        else:
            package_cloud_skill(args.output, args.native_manifest, args.native_app, skill)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
