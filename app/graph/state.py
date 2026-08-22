"""Graph state contract.

Parallel branches (web/rag/data) write disjoint keys; the two telemetry keys
accumulate across nodes via an add-reducer, so every LLM call and every node
run is captured exactly once — those feed the usage/cost endpoints.
"""

import operator
from typing import Annotated, Any, TypedDict

from app.schemas.evidence import EvidenceChunk
from app.schemas.judge import JudgeVerdict
from app.schemas.plan import ResearchPlan
from app.schemas.report import FinalReport
from app.schemas.synthesis import DraftReport


class MissionState(TypedDict, total=False):
    # identity / input
    mission_id: str
    question: str

    # planner output
    plan: ResearchPlan | None

    # parallel research outputs (disjoint writers)
    web_evidence: list[EvidenceChunk]
    rag_evidence: list[EvidenceChunk]
    data_evidence: list[EvidenceChunk]

    # synthesis <-> critic loop
    draft: DraftReport | None
    critique: JudgeVerdict | None
    revision_count: int
    verdict_history: list[dict]  # [{revision, overall_score, passed, stage}]

    # human-in-the-loop
    approved: bool | None  # set by human_review node after interrupt resumes
    human_feedback: str | None

    # outputs / control
    final_report: FinalReport | None
    error: str | None
    guardrail_blocked: bool

    # telemetry (append-only across all nodes, incl. parallel branches)
    usage: Annotated[list[dict], operator.add]      # CallUsage dicts
    agent_runs: Annotated[list[dict], operator.add] # {node,status,latency_ms,revision,error}


def evidence_pool(state: MissionState) -> list[EvidenceChunk]:
    return state.get("web_evidence", []) + state.get("rag_evidence", []) + \
        state.get("data_evidence", [])


def valid_evidence_ids(state: MissionState) -> set[str]:
    return {e.evidence_id for e in evidence_pool(state)}


def snapshot_telemetry(state: MissionState) -> dict[str, Any]:
    """Aggregate numbers for logging/persistence."""
    usage = state.get("usage", [])
    runs = state.get("agent_runs", [])
    return {
        "llm_calls": len(usage),
        "prompt_tokens": sum(u["prompt_tokens"] for u in usage),
        "completion_tokens": sum(u["completion_tokens"] for u in usage),
        "cost_usd": round(sum(u["cost_usd"] for u in usage), 6),
        "node_latency_ms": {
            n: sum(r.get("latency_ms") or 0 for r in runs if r.get("node") == n)
            for n in sorted({r["node"] for r in runs})
        },
        "revision_count": state.get("revision_count", 0),
        "evidence_chunks": len(evidence_pool(state)),
    }
