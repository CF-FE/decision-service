import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from .settings import Name

JSONObject = dict[str, JsonValue]
Revision = Annotated[int, Field(gt=0, le=2**63 - 1)]
Version = Annotated[int, Field(ge=1, le=1)]


CASH_USAGE_TERMS = {"cash", "cost", "costs", "price", "pricing", "currency",
                    "usd", "eur", "cny", "fee", "fees", "dollar", "dollars"}


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


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class Candidate(StrictModel):
    candidate_id: Name
    description: str
    parameters: JSONObject
    metadata: JSONObject | None = None


class Level(StrictModel):
    label: Name
    description: str


class Evaluate(StrictModel):
    schema_version: Version
    request_id: Name | None = None
    preset: Literal["workflow_next_action", "role_model_selection"] | None = None
    kind: Literal["choice", "predicate", "score"]
    question: Name
    context: JSONObject
    choices: Annotated[list[Candidate], Field(max_length=255)] | None = None
    levels: Annotated[list[Level], Field(min_length=2, max_length=10)] | None = None
    project_id: Name | None = None
    subject_ref: JSONObject | None = None
    snapshot: JSONObject | None = None
    bank_ids: list[Name] | None = None
    recall: Literal["auto", "skip"] = "auto"
    expects_application: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        if self.kind == "choice":
            if self.choices is None or self.levels is not None:
                raise ValueError("choice requires choices")
            if not self.choices and self.preset != "role_model_selection":
                raise ValueError("no choices")
            ids = [candidate.candidate_id for candidate in self.choices]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate candidate")
        elif self.kind == "score":
            if self.choices is not None or self.levels is None:
                raise ValueError("score requires levels")
        elif self.choices is not None or self.levels is not None:
            raise ValueError("predicate cannot have choices or levels")
        if self.preset:
            if self.kind != "choice" or not self.project_id or not self.request_id:
                raise ValueError("preset requires a project, stable request ID and choice")
            keys = ["task_id", "unit_id"]
            if self.preset == "workflow_next_action":
                keys += ["step", "source_sha256", "input_sha256"]
            if self.subject_ref is None or any(
                not isinstance(self.subject_ref.get(key), str) or not self.subject_ref[key].strip()
                for key in keys
            ) or self.subject_ref.get("unit_id_source") not in ("native", "adapter"):
                raise ValueError("invalid subject reference")
            if self.snapshot is None or any(
                not isinstance(self.snapshot.get(key), str) or not self.snapshot[key].strip()
                for key in ("state_digest", "candidate_digest")
            ):
                raise ValueError("invalid snapshot")
        if self.bank_ids is not None and len(set(self.bank_ids)) != len(self.bank_ids):
            raise ValueError("duplicate bank")
        return self


class ExecutionRef(StrictModel):
    source: Name
    ids: Annotated[dict[Name, Name], Field(min_length=1)]


class Unit(StrictModel):
    unit_id: Name
    state: Literal["pending", "ended", "unknown"]
    expects_result: bool
    execution_ref: ExecutionRef | None = None


class Observation(StrictModel):
    scope_ref: Name
    observed_at: Name
    scope_complete: bool
    units: list[Unit]

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: str) -> str:
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("timestamp requires timezone")
        return value


class ModelConfig(StrictModel):
    provider: Name | None
    model_type: Name | None
    model: Name | None
    reasoning_effort: Name | None


class ActualModel(ModelConfig):
    configuration_status: Literal["confirmed", "unconfirmed"]
    effort_status: Literal["set", "not_applicable", "unconfirmed"]

    @model_validator(mode="after")
    def valid_configuration(self) -> Self:
        if self.configuration_status == "confirmed" and not all(
            (self.provider, self.model_type, self.model)
        ):
            raise ValueError("confirmed model configuration needs an identity")
        if (self.reasoning_effort is not None) != (self.effort_status == "set"):
            raise ValueError("effort must match its status")
        return self


class Application(StrictModel):
    application_status: Literal["applied", "not_applied", "stale", "failed", "unknown"]
    recommended_candidate_id: Name | None
    effective_candidate_id: Name | None
    reason_codes: list[Name]
    evidence_refs: list[Name]
    recommended_model: ModelConfig | None = None
    launch_model: ActualModel | ModelConfig | None = None
    effective_model: ActualModel | None = None


class Result(StrictModel):
    execution_status: Literal["completed", "failed", "cancelled", "unknown"]
    quality_status: Literal["passed", "failed", "pending", "unknown"]
    result_refs: list[Name]
    evidence_refs: list[Name]
    effective_model: ActualModel | None = None
    usage: JSONObject | None = None


class Correction(StrictModel):
    target_ref: Name
    text: Name
    reason_codes: list[Name]
    evidence_refs: list[Name]


class Feedback(StrictModel):
    schema_version: Version
    project_id: Name | None
    event_id: Name
    revision: Revision
    supersedes_revision: Revision | None = None
    kind: Literal["application", "result", "correction"]
    decision_ids: Annotated[list[Name], Field(min_length=1)]
    subject_ref: JSONObject
    observed_at: Name
    execution_ref: ExecutionRef | None = None
    execution_state: Literal["not_started", "running", "ended", "unknown"] | None = None
    coverage_observation: Observation | None = None
    payload: JSONObject

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        Observation.timezone_required(self.observed_at)
        if self.revision == 1:
            if self.supersedes_revision is not None:
                raise ValueError("first revision cannot supersede")
        elif self.supersedes_revision is None or self.supersedes_revision >= self.revision:
            raise ValueError("invalid supersedes_revision")
        if len(set(self.decision_ids)) != len(self.decision_ids):
            raise ValueError("duplicate decision ID")
        if self.kind == "correction":
            Correction.model_validate(self.payload)
        else:
            if self.project_id is None:
                raise ValueError("program feedback requires a source project")
            if self.execution_state is None or self.coverage_observation is None:
                raise ValueError("program feedback requires an execution state and an observation")
            if self.kind == "application":
                if len(self.decision_ids) != 1:
                    raise ValueError("application must reference one decision")
                Application.model_validate(self.payload)
            else:
                result = Result.model_validate(self.payload)
                if result.execution_status != "unknown" and self.execution_state != "ended":
                    raise ValueError("a final result requires observed execution end")
        return self
