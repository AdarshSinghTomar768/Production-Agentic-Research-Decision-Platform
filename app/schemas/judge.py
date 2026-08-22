"""Structured output of the Critic / LLM-as-a-Judge agent."""

from pydantic import BaseModel, Field, field_validator

DIMENSIONS = ("coverage", "grounding", "actionability", "risk_awareness", "clarity")


class DimensionScore(BaseModel):
    dimension: str
    score: float = Field(ge=0.0, le=10.0)
    rationale: str

    @field_validator("dimension")
    @classmethod
    def _known_dimension(cls, v: str) -> str:
        if v not in DIMENSIONS:
            raise ValueError(f"unknown dimension '{v}', expected one of {DIMENSIONS}")
        return v


class JudgeVerdict(BaseModel):
    passed: bool
    overall_score: float = Field(ge=0.0, le=10.0)
    dimensions: list[DimensionScore] = Field(min_length=len(DIMENSIONS), max_length=len(DIMENSIONS))
    feedback: list[str] = Field(default_factory=list)  # concrete fixes when failed
    citation_issues: list[str] = Field(default_factory=list)
