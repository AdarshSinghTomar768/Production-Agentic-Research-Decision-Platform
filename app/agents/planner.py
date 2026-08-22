"""Planner: decomposes a business question into a structured research plan."""

from app.llm.provider import LLMProvider
from app.llm.usage import AgentUsage
from app.schemas.plan import ResearchPlan

SYSTEM = """\
You are the lead research planner of a business intelligence team.

Given a business question you produce a research plan:
- Restate the question as a sharp, falsifiable objective.
- Define 1-6 concrete success criteria for the final report.
- Decompose into 1-8 subtasks (t1, t2, ...). Each subtask gets:
  * description: what this line of investigation establishes
  * search_query: ONE concrete retrieval query (keywords, not sentences)
  * needs_web: external/public information required
  * needs_rag: internal knowledge base likely to hold relevant material
  * needs_data: structured facts about a named entity (company, product)

Rules:
- Prefer 3-5 focused subtasks over one vague mega-task.
- Every subtask must be answerable independently.
- Do not invent entities; use exactly the names given in the question.
"""


class PlannerAgent:
    name = "planner"

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def run(self, question: str) -> tuple[ResearchPlan, AgentUsage]:
        usage = AgentUsage(self.name)
        result = await self.provider.structured(
            ResearchPlan,
            SYSTEM,
            f"USER QUESTION:\n{question}",
            node=self.name,
        )
        for u in result.usage:
            usage.add(u)
        return result.value, usage
