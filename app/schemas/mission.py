"""API-facing request/response models."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.plan import ResearchPlan


class MissionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PENDING_APPROVAL = "pending_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    GUARDRAIL_BLOCKED = "guardrail_blocked"


# --- Missions ---


class MissionCreate(BaseModel):
    question: str = Field(min_length=10, max_length=4000)


class ApprovalDecision(BaseModel):
    approved: bool
    feedback: str | None = None  # required-ish when rejecting; fed back to synthesizer


class MissionCreated(BaseModel):
    mission_id: str
    status: MissionStatus


class AgentRunSummary(BaseModel):
    node: str
    status: str
    latency_ms: int | None
    revision: int


class MissionDetail(BaseModel):
    mission_id: str
    question: str
    status: MissionStatus
    plan: ResearchPlan | None = None
    revision_count: int = 0
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class UsageRow(BaseModel):
    node: str
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    total_latency_ms: int


class MissionUsage(BaseModel):
    mission_id: str
    rows: list[UsageRow]
    totals: dict[str, Any]


# --- Knowledge base ---


class DocumentIn(BaseModel):
    title: str
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    documents: list[DocumentIn] = Field(min_length=1)


class IngestResponse(BaseModel):
    documents_ingested: int
    chunks_indexed: int
    collection: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    score: float
    title: str
    content: str
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


# --- Evals ---


class EvalCaseResult(BaseModel):
    case_id: str
    question: str
    overall_score: float
    passed_judge: bool
    dimensions: dict[str, float]
    notes: list[str] = Field(default_factory=list)


class EvalRunSummary(BaseModel):
    run_id: str
    cases: list[EvalCaseResult]
    mean_overall: float
    mean_pass_rate: float
    fake_llm: bool
