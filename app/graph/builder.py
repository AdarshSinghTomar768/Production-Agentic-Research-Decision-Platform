"""LangGraph assembly: fan-out research, critic revise-loop, human interrupt."""

import logging
import time
from dataclasses import dataclass, field

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents import (
    CriticAgent,
    DataAgent,
    PlannerAgent,
    RagAgent,
    SynthesizerAgent,
    WebResearchAgent,
)
from app.config import Settings
from app.graph.state import MissionState, valid_evidence_ids
from app.llm.guardrails import GuardrailViolation, check_user_question
from app.llm.provider import FakeProvider, LiteLLMProvider, LLMProvider
from app.schemas.judge import DIMENSIONS, DimensionScore, JudgeVerdict
from app.tools.base import ResearchTool
from app.tools.http_data import HttpDataTool, OfflineDataTool
from app.tools.retriever import OfflineRetriever, QdrantRetriever
from app.tools.web_search import OfflineWebSearchTool, WebSearchTool

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """Dependency bundle captured by the graph nodes."""

    provider: LLMProvider
    judge_model: str
    web_tool: ResearchTool
    retriever: ResearchTool
    data_tool: HttpDataTool | OfflineDataTool
    max_evidence_per_agent: int = 6
    max_revisions: int = 2
    judge_pass_threshold: float = 7.0
    judge_dimension_floor: float = 5.0


def make_services(settings: Settings) -> Services:
    if settings.fake_llm:
        provider: LLMProvider = FakeProvider()
        web: ResearchTool = OfflineWebSearchTool()
        retriever: ResearchTool = OfflineRetriever()
        data = OfflineDataTool()
    else:
        provider = LiteLLMProvider(
            default_model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_completion_tokens,
            timeout_s=settings.llm_timeout_seconds,
            max_repair_retries=settings.max_repair_retries,
            fallback_models=settings.fallback_model_list,
            backoff_base_s=settings.llm_retry_backoff_seconds,
        )
        web = WebSearchTool(settings.tavily_api_key,
                            max_results=settings.web_results_per_query)
        retriever = _lazy_retriever(settings)
        data = HttpDataTool(timeout_s=settings.http_tool_timeout_seconds)
    return Services(
        provider=provider,
        judge_model=settings.judge_model,
        web_tool=web,
        retriever=retriever,
        data_tool=data,
        max_evidence_per_agent=settings.max_evidence_per_agent,
        max_revisions=settings.max_revisions,
        judge_pass_threshold=settings.judge_pass_threshold,
        judge_dimension_floor=settings.judge_dimension_floor,
    )


def _lazy_retriever(settings: Settings):
    from app.embeddings.embedder import get_embedder

    return QdrantRetriever(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        embedder=get_embedder(settings.embedding_model, fake=settings.fake_llm),
        top_k=settings.rag_top_k,
        score_threshold=settings.rag_score_threshold,
    )


def build_graph(services: Services, checkpointer) :
    planner = PlannerAgent(services.provider)
    web_agent = WebResearchAgent(services.web_tool, max_evidence=services.max_evidence_per_agent)
    rag_agent = RagAgent(services.retriever, max_evidence=services.max_evidence_per_agent)
    data_agent = DataAgent(services.data_tool)
    synthesizer = SynthesizerAgent(services.provider)
    critic = CriticAgent(
        services.provider,
        model=services.judge_model,
        pass_threshold=services.judge_pass_threshold,
        dimension_floor=services.judge_dimension_floor,
    )

    def _telemetry(node: str, t0: float, usage_dicts: list[dict], *,
                   revision: int, status: str = "ok", error: str | None = None) -> dict:
        return {
            "usage": usage_dicts,
            "agent_runs": [{
                "node": node, "status": status, "error": error, "revision": revision,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }],
        }

    # --- nodes -------------------------------------------------------------

    async def guardrail_node(state: MissionState) -> dict:
        t0 = time.monotonic()
        try:
            check_user_question(state["question"])
        except GuardrailViolation as exc:
            logger.warning("[guardrail] blocked mission %s: %s", state["mission_id"], exc)
            raise
        return _telemetry("guardrail", t0, [], revision=0)

    async def planner_node(state: MissionState) -> dict:
        t0 = time.monotonic()
        plan, usage = await planner.run(state["question"])
        return {
            "plan": plan,
            **_telemetry("planner", t0, [u.__dict__ for u in usage.calls], revision=0),
        }

    async def web_node(state: MissionState) -> dict:
        t0 = time.monotonic()
        evidence, usage = await web_agent.run(state["plan"])  # type: ignore[arg-type]
        rev = state.get("revision_count", 0)
        return {"web_evidence": evidence,
                **_telemetry("web_research", t0, [u.__dict__ for u in usage.calls], revision=rev)}

    async def rag_node(state: MissionState) -> dict:
        t0 = time.monotonic()
        evidence, usage = await rag_agent.run(state["plan"])  # type: ignore[arg-type]
        rev = state.get("revision_count", 0)
        return {"rag_evidence": evidence,
                **_telemetry("rag_research", t0, [u.__dict__ for u in usage.calls], revision=rev)}

    async def data_node(state: MissionState) -> dict:
        t0 = time.monotonic()
        evidence, usage = await data_agent.run(state["plan"])  # type: ignore[arg-type]
        rev = state.get("revision_count", 0)
        return {"data_evidence": evidence,
                **_telemetry("data_research", t0, [u.__dict__ for u in usage.calls], revision=rev)}

    async def synthesizer_node(state: MissionState) -> dict:
        from app.graph.state import evidence_pool

        t0 = time.monotonic()
        critique = state.get("critique")
        revision = state.get("revision_count", 0) + (1 if critique else 0)
        draft, usage = await synthesizer.run(
            question=state["question"],
            plan=state["plan"],  # type: ignore[arg-type]
            evidence=evidence_pool(state),
            critique=critique,
            prior_draft=state.get("draft") if critique else None,
        )
        updates = {
            "draft": draft,
            "revision_count": revision,
            "critique": None if critique is None else critique,  # consumed for this round
            **_telemetry("synthesizer", t0, [u.__dict__ for u in usage.calls],
                         revision=revision),
        }
        return updates

    async def critic_node(state: MissionState) -> dict:
        t0 = time.monotonic()
        verdict, usage = await critic.run(
            question=state["question"],
            draft=state["draft"],  # type: ignore[arg-type]
            valid_evidence_ids=valid_evidence_ids(state),
        )
        history = list(state.get("verdict_history", [])) + [{
            "stage": "critic",
            "revision": state.get("revision_count", 0),
            "overall_score": verdict.overall_score,
            "passed": verdict.passed,
            "dimensions": {d.dimension: d.score for d in verdict.dimensions},
        }]
        return {"critique": verdict, "verdict_history": history,
                **_telemetry("critic", t0, [u.__dict__ for u in usage.calls],
                             revision=state.get("revision_count", 0))}

    async def human_review_node(state: MissionState) -> dict:
        """Durable pause. Re-executes after resume; interrupt() then yields the decision."""
        draft = state["draft"]
        last_verdict = state.get("critique")
        decision: dict = interrupt({
            "question": state["question"],
            "title": draft.title,
            "executive_summary": draft.executive_summary,
            "recommendation": draft.recommendation,
            "confidence": draft.confidence,
            "citations": sorted(draft.all_citations()),
            "evidence_chunks": len(valid_evidence_ids(state)),
            "revision_count": state.get("revision_count", 0),
            "judge": (last_verdict.model_dump(mode="json") if last_verdict else None),
        })
        approved = bool(decision.get("approved"))
        feedback = decision.get("feedback")
        if approved:
            return {"approved": True,
                    **_telemetry("human_review", time.monotonic(), [],
                                 revision=state.get("revision_count", 0))}
        synthetic = JudgeVerdict(
            passed=False,
            overall_score=last_verdict.overall_score if last_verdict else 0.0,
            dimensions=[
                DimensionScore(dimension=d,
                               score=(next((x.score for x in last_verdict.dimensions
                                            if x.dimension == d), 6.0))
                               if last_verdict else 6.0,
                               rationale="human rejection feedback")
                for d in DIMENSIONS
            ],
            feedback=[feedback or "Rejected by human reviewer; revise the report."],
        )
        history = list(state.get("verdict_history", [])) + [{
            "stage": "human_rejection",
            "revision": state.get("revision_count", 0),
            "feedback": feedback or "",
        }]
        return {
            "approved": False,
            "critique": synthetic,
            "verdict_history": history,
            **_telemetry("human_review", time.monotonic(), [],
                         revision=state.get("revision_count", 0)),
        }

    async def finalize_node(state: MissionState) -> dict:
        from app.graph.state import evidence_pool
        from app.schemas.evidence import Citation
        from app.schemas.report import FinalReport

        t0 = time.monotonic()
        draft = state["draft"]
        pool = {e.evidence_id: e for e in evidence_pool(state)}
        sources = [
            Citation(evidence_id=eid, title=pool[eid].title,
                     url=pool[eid].url, source=pool[eid].source)
            for eid in sorted(draft.all_citations()) if eid in pool
        ]
        history = list(state.get("verdict_history", [])) + [
            {"stage": "human_approval", "approved": True}
        ]
        final = FinalReport(
            mission_id=state["mission_id"],
            question=state["question"],
            title=draft.title,
            executive_summary=draft.executive_summary,
            sections=draft.sections,
            recommendation=draft.recommendation,
            confidence=draft.confidence,
            open_questions=draft.open_questions,
            sources=sources,
            review_history=history,
        )
        return {"final_report": final,
                **_telemetry("finalize", t0, [], revision=state.get("revision_count", 0))}

    # --- routing -----------------------------------------------------------

    def route_after_critic(state: MissionState) -> str:
        verdict = state.get("critique")
        if verdict is not None and verdict.passed:
            return "review"
        if state.get("revision_count", 0) >= services.max_revisions:
            logger.warning("max revisions reached; escalating to human review")
            return "review"
        return "revise"

    def route_after_human(state: MissionState) -> str:
        return "finalize" if state.get("approved") else "revise"

    # --- wiring ------------------------------------------------------------

    g = StateGraph(MissionState)
    g.add_node("guardrail", guardrail_node)
    g.add_node("planner", planner_node)
    g.add_node("web_research", web_node)
    g.add_node("rag_research", rag_node)
    g.add_node("data_research", data_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("critic", critic_node)
    g.add_node("human_review", human_review_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "guardrail")
    g.add_edge("guardrail", "planner")
    # fan-out: one planner -> three parallel researchers
    g.add_edge("planner", "web_research")
    g.add_edge("planner", "rag_research")
    g.add_edge("planner", "data_research")
    g.add_edge("web_research", "synthesizer")
    g.add_edge("rag_research", "synthesizer")
    g.add_edge("data_research", "synthesizer")
    g.add_edge("synthesizer", "critic")
    g.add_conditional_edges("critic", route_after_critic,
                            {"revise": "synthesizer", "review": "human_review"})
    g.add_conditional_edges("human_review", route_after_human,
                            {"finalize": "finalize", "revise": "synthesizer"})
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)


@dataclass
class GraphDeps:
    services: Services
    checkpointer: object = field(default=None)
