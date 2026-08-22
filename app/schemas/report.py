"""Final deliverable produced after human approval."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.schemas.evidence import Citation
from app.schemas.synthesis import ReportSection


class FinalReport(BaseModel):
    mission_id: str
    question: str
    title: str
    executive_summary: str
    sections: list[ReportSection]
    recommendation: str
    confidence: str  # low | medium | high
    open_questions: list[str] = Field(default_factory=list)
    sources: list[Citation]
    review_history: list[dict] = Field(default_factory=list)  # compact judge verdicts
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
