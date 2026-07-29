from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DecisionStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class ProjectionStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    RETRY_REQUIRED = "RETRY_REQUIRED"


class Dependency(BaseModel):
    asset_urn: str
    dependency_type: str = "dataset"
    field_path: str | None = None


class DecisionContext(BaseModel):
    source: str
    tools: list[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    facts: list[str] = Field(default_factory=list)
    snapshot: dict[str, object] = Field(default_factory=dict)


class ReorderAnalysis(BaseModel):
    source: str
    question: str
    conversation_id: str | None = None
    engine_name: str | None = None
    answer: str
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, object]] = Field(default_factory=list)
    chart: dict[str, object] | None = None
    context_quality: dict[str, object] | None = None
    tool_calls: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    status: DecisionStatus = DecisionStatus.PENDING_APPROVAL
    summary: str
    evidence: list[str]
    dependencies: list[Dependency]
    context: DecisionContext | None = None
    analysis: ReorderAnalysis | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None
    supersedes: UUID | None = None
    datahub_urn: str | None = None
    projection_status: ProjectionStatus = ProjectionStatus.NOT_CONFIGURED
    projection_error: str | None = None


class InvalidationEvent(BaseModel):
    asset_urn: str
    event_type: str = "DATASET_STALE"
    severity: str = "high"


class InvalidationRecord(InvalidationEvent):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    impacted_decision_ids: list[UUID] = Field(default_factory=list)


class FieldChange(BaseModel):
    path: str
    change_type: str
    before: object | None = None
    after: object | None = None


class RoutineImpact(BaseModel):
    routine: str
    effect: str
    triggered_by: list[str] = Field(default_factory=list)


class DecisionComparison(BaseModel):
    prior: Decision
    current: Decision
    changes: list[FieldChange] = Field(default_factory=list)
    routine_impacts: list[RoutineImpact] = Field(default_factory=list)


class AgentRegistration(BaseModel):
    agent_urn: str
    skill_urn: str
    tool_urns: list[str]
    consumed_dataset_urns: list[str]
