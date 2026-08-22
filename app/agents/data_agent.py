"""Data agent: structured facts about named entities via allowlisted HTTP APIs."""

import logging

from app.llm.usage import AgentUsage
from app.schemas.evidence import EvidenceChunk, EvidenceSource, make_evidence_id
from app.schemas.plan import ResearchPlan
from app.tools.http_data import HttpDataTool

logger = logging.getLogger(__name__)


class DataAgent:
    name = "data_research"

    def __init__(self, tool: HttpDataTool, *, max_lookups: int = 2) -> None:
        self.tool = tool
        self.max_lookups = max_lookups

    async def run(self, plan: ResearchPlan) -> tuple[list[EvidenceChunk], AgentUsage]:
        usage = AgentUsage(self.name)
        entities: list[str] = []
        for s in plan.subtasks:
            if s.needs_data and s.search_query not in entities:
                entities.append(s.search_query)
            if len(entities) >= self.max_lookups:
                break

        evidence: list[EvidenceChunk] = []
        seq = 0
        for entity in entities:
            hit = await self.tool.wikipedia_summary(entity)
            if hit is None:
                continue
            seq += 1
            evidence.append(
                EvidenceChunk(
                    evidence_id=make_evidence_id(EvidenceSource.DATA, seq),
                    source=EvidenceSource.DATA,
                    title=hit.title,
                    content=hit.content,
                    url=hit.url,
                    score=hit.score,
                    query=entity,
                )
            )
        logger.info("[%s] collected %d entity profiles", self.name, len(evidence))
        return evidence, usage
