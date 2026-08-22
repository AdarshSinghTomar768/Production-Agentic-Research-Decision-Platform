"""Evidence is the currency of the platform: every claim traces to an EvidenceChunk."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class EvidenceSource(StrEnum):
    WEB = "web"
    RAG = "rag"
    DATA = "data"


_EVIDENCE_ID_PATTERN = r"^ev-(web|rag|data)-\d{3}$"


def make_evidence_id(source: EvidenceSource, seq: int) -> str:
    return f"ev-{source.value}-{seq:03d}"


class EvidenceChunk(BaseModel):
    evidence_id: str = Field(pattern=_EVIDENCE_ID_PATTERN)
    source: EvidenceSource
    title: str
    content: str
    url: str | None = None
    score: float | None = None  # provider relevance score (0..1-ish)
    query: str | None = None  # subtask query that surfaced it
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("content")
    @classmethod
    def _content_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("evidence content must not be empty")
        return v[:4000]


class Citation(BaseModel):
    """A resolved citation rendered into the final report."""

    evidence_id: str = Field(pattern=_EVIDENCE_ID_PATTERN)
    title: str
    url: str | None = None
    source: EvidenceSource
