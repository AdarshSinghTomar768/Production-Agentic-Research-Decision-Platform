"""Web research agent: runs plan subtasks through the Tavily search tool."""

import logging

from app.llm.usage import AgentUsage
from app.schemas.evidence import EvidenceChunk, EvidenceSource, make_evidence_id
from app.schemas.plan import ResearchPlan
from app.tools.base import ResearchTool

logger = logging.getLogger(__name__)


class WebResearchAgent:
    name = "web_research"

    def __init__(self, tool: ResearchTool, *, max_evidence: int = 6) -> None:
        self.tool = tool
        self.max_evidence = max_evidence

    async def run(self, plan: ResearchPlan) -> tuple[list[EvidenceChunk], AgentUsage]:
        usage = AgentUsage(self.name)
        queries = [s.search_query for s in plan.subtasks if s.needs_web]
        hits, seen_urls = [], set()
        for query in queries:
            try:
                raw_hits = await self.tool.search(query)
            except Exception as exc:  # a flaky provider must not kill the mission
                logger.warning("[%s] search failed for %r: %s", self.name, query, exc)
                continue
            for h in raw_hits:
                key = h.url or f"{h.title}::{h.content[:80]}"
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                hits.append((query, h))

        evidence = [
            EvidenceChunk(
                evidence_id=make_evidence_id(EvidenceSource.WEB, i + 1),
                source=EvidenceSource.WEB,
                title=h.title,
                content=h.content,
                url=h.url,
                score=h.score,
                query=query,
            )
            for i, (query, h) in enumerate(hits[: self.max_evidence])
        ]
        logger.info("[%s] collected %d evidence chunks", self.name, len(evidence))
        return evidence, usage


class RagAgent:
    """Internal knowledge-base agent over the Qdrant retriever."""

    name = "rag_research"

    def __init__(self, retriever: ResearchTool, *, max_evidence: int = 6) -> None:
        self.retriever = retriever
        self.max_evidence = max_evidence

    async def run(self, plan: ResearchPlan) -> tuple[list[EvidenceChunk], AgentUsage]:
        usage = AgentUsage(self.name)
        queries = [s.search_query for s in plan.subtasks if s.needs_rag]
        if not queries:  # fall back to the objective so RAG still gets a say
            queries = [plan.objective]

        hits, seen = [], set()
        for query in queries:
            try:
                raw_hits = await self.retriever.search(query)
            except Exception as exc:
                logger.warning("[%s] retrieval failed for %r: %s", self.name, query, exc)
                continue
            for h in raw_hits:
                key = f"{h.title}::{h.content[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                hits.append((query, h))

        evidence = [
            EvidenceChunk(
                evidence_id=make_evidence_id(EvidenceSource.RAG, i + 1),
                source=EvidenceSource.RAG,
                title=h.title,
                content=h.content,
                url=h.url,
                score=h.score,
                query=query,
            )
            for i, (query, h) in enumerate(hits[: self.max_evidence])
        ]
        logger.info("[%s] collected %d evidence chunks", self.name, len(evidence))
        return evidence, usage
