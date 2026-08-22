"""Structured output of the Synthesizer agent (pre-judgment draft)."""

import re

from pydantic import BaseModel, Field, model_validator

CITATION_TOKEN = re.compile(r"ev-(?:web|rag|data)-\d{3}")


class ReportSection(BaseModel):
    heading: str
    body: str  # markdown; inline citation markers like [ev-web-001]
    citations: list[str] = Field(default_factory=list)  # evidence ids used here

    @model_validator(mode="after")
    def _citations_consistent_with_body(self) -> "ReportSection":
        found = set(CITATION_TOKEN.findall(self.body))
        declared = {c.strip() for c in self.citations}
        # Declared citations must cover markers in the body; extra declarations are dropped.
        self.citations = sorted(found & declared | found)
        return self


class DraftReport(BaseModel):
    title: str
    executive_summary: str
    sections: list[ReportSection] = Field(min_length=1)
    recommendation: str
    confidence: str  # low | medium | high
    open_questions: list[str] = Field(default_factory=list)
    revision_note: str | None = None  # what changed after a critique round

    def all_citations(self) -> set[str]:
        out: set[str] = set()
        for s in self.sections:
            out.update(s.citations)
            out.update(CITATION_TOKEN.findall(s.body))
        return out

    @property
    def confidence_is_valid(self) -> bool:
        return self.confidence in {"low", "medium", "high"}
