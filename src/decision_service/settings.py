import json
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False, pattern=r"\S")]


class Caller(BaseModel):
    model_config = ConfigDict(extra="forbid")
    caller_scope: Name
    project_ids: list[Name]
    bank_ids: list[Name]


class GitHubOAuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_base_url: AnyHttpUrl
    principals: dict[Name, Name] = Field(min_length=1)
    allowed_client_redirect_uris: list[Name] = Field(min_length=1)
    client_id: SecretStr
    client_secret: SecretStr
    signing_key: SecretStr

    @field_validator("public_base_url")
    @classmethod
    def public_https(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if (url.scheme != "https" or url.username or url.password or url.query is not None
                or url.fragment is not None or "//" in (url.path or "")):
            raise ValueError("OAuth requires a public HTTPS base URL")
        return url


def load_credentials(data, prefix, fields):
    for field in fields:
        env_key = prefix + field.upper()
        if env_key in os.environ:
            data[field] = os.environ[env_key]
        elif credential_file := os.environ.get(env_key + "_FILE"):
            data[field] = Path(credential_file).read_text(encoding="utf-8").rstrip("\r\n")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    db_path: Path = Path("decision-service.sqlite3")
    callers: dict[Name, Caller] = Field(default_factory=dict, repr=False)
    service_bank_ids: list[Name] = Field(default_factory=list)
    default_banks: dict[Name, list[Name]] = Field(default_factory=dict)
    mcp_allowed_hosts: list[Name] = Field(default_factory=list)
    mcp_allowed_origins: list[Name] = Field(default_factory=list)
    github_oauth: GitHubOAuthSettings | None = None
    openai_base_url: str = "https://api.openai.com"
    openai_api_key: SecretStr | None = None
    openai_model: Name = "gpt-6-luna"
    hindsight_base_url: str | None = None
    hindsight_api_key: SecretStr | None = None
    hindsight_api_mode: Literal["native", "gateway"] = "native"
    timeout_seconds: float = Field(default=15, gt=0)
    evidence_max_chars: int = Field(default=6000, gt=0)
    max_parallel_banks: int = Field(default=4, gt=0)

    @classmethod
    def from_env(cls):
        path = os.environ.get("DECISION_SERVICE_CONFIG")
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
            if not isinstance(data, dict):
                raise ValueError
            load_credentials(data, "DECISION_SERVICE_", ("openai_api_key", "hindsight_api_key"))
            if isinstance(oauth := data.get("github_oauth"), dict):
                load_credentials(oauth, "DECISION_SERVICE_OAUTH_", ("client_id", "client_secret", "signing_key"))
            return cls.model_validate(data)
        except (OSError, ValueError):
            raise ValueError("Invalid Decision Service configuration") from None

    def provider_settings(self):
        names = {
            "openai_base_url", "openai_api_key", "openai_model",
            "hindsight_base_url", "hindsight_api_key", "hindsight_api_mode", "timeout_seconds",
            "evidence_max_chars", "max_parallel_banks",
        }
        values = self.model_dump(include=names)
        for key in ("openai_api_key", "hindsight_api_key"):
            if values[key] is not None:
                values[key] = values[key].get_secret_value()
        return values
