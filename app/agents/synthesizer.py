"""Synthesizer: turns the evidence pool into a cited draft report."""

import json

from app.llm.provider import LLMProvider
from app.llm.usage import AgentUsage
from app.schemas.evidence import EvidenceChunk
from app.schemas.judge import JudgeVerdict
from app.schemas.plan import ResearchPlan
from app.schemas.synthesis import DraftReport

SYSTEM = """\
You are a senior consultant writing an evidence-grounded decision memo.

You receive: the business question, the research plan, and a numbered evidence pool.
Write a draft report with:
- title, executive_summary (<=150 words)
- 3-5 sections covering findings, analysis, and risks/opportunities
- recommendation: a concrete next action
- confidence: "low" | "medium" | "high"
- open_questions where evidence was thin

CITATION CONTRACT (critical):
- Support every substantive claim with inline markers like [ev-web-001] or [ev-rag-002].
- Use ONLY evidence ids from the provided evidence pool. Never invent ids.
- A claim with no supporting evidence must be framed as an open question instead.
- List each section's used ids in its citations field.
"""


class SynthesizerAgent:
    name = "synthesizer"

    def __init__(self, provider: LLMProvider, *, model: str | None = None) -> None:
        self.provider = provider
        self.model = model

    async def run(
        self,
        question: str,
        plan: ResearchPlan,
        evidence: list[EvidenceChunk],
        critique: JudgeVerdict | None = None,
        prior_draft: DraftReport | None = None,
    ) -> tuple[DraftReport, AgentUsage]:
        usage = AgentUsage(self.name)
        lines = [
            f"{e.evidence_id} | {e.source.value} | {e.title} | "
            f"{'<no url>' if not e.url else e.url}\n{e.content}"
            for e in evidence
        ]
        parts = [
            f"USER QUESTION:\n{question}",
            f"\nRESEARCH PLAN:\n{plan.model_dump_json(indent=2)}",
            f"\nEVIDENCE POOL ({len(lines)} chunks):\n" + "\n\n".join(lines or ["(none found)"]),
        ]
        if critique is not None and prior_draft is not None:
            parts.append(
                "\nREVISION FEEDBACK (fix every point):\n"
                + json.dumps(critique.model_dump(), indent=2)
                + "\n\nPRIOR DRAFT TO REVISE:\n"
                + prior_draft.model_dump_json(indent=2)
            )
        user = "\n".join(parts)

        result = await self.provider.structured(DraftReport, SYSTEM, user,
                                                node=self.name, model=self.model)
        for u in result.usage:
            usage.add(u)
        return result.value, usage
