"""Persistence of mission lifecycle + telemetry, and the aggregate queries
that produce the platform's headline numbers (cost/latency/score stats)."""

import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, EvalRun, Mission, UsageEvent
from app.graph.runner import MissionOutcome

logger = logging.getLogger(__name__)


# --- writes -----------------------------------------------------------------


async def create_mission(session: AsyncSession, *, mission_id: str, question: str,
                         status: str = "queued") -> Mission:
    m = Mission(id=mission_id, question=question, status=status)
    session.add(m)
    await session.flush()
    return m


async def set_status(session: AsyncSession, mission_id: str, status: str, *,
                     error: str | None = None) -> None:
    m = await session.get(Mission, mission_id)
    if m is None:
        logger.error("set_status on unknown mission %s", mission_id)
        return
    m.status = status
    if error is not None:
        m.error = error[:2000]


async def persist_outcome(session: AsyncSession, outcome: MissionOutcome) -> None:
    """Write telemetry rows and the terminal/paused state for one graph run.

    Snapshots are cumulative across resume legs (add-reducers keep full
    history), so persistence replaces prior rows for the mission — making
    this call idempotent no matter how many times it runs.
    """
    await session.execute(delete(AgentRun).where(AgentRun.mission_id == outcome.mission_id))
    await session.execute(delete(UsageEvent).where(UsageEvent.mission_id == outcome.mission_id))
    for run in outcome.agent_runs:
        session.add(AgentRun(
            mission_id=outcome.mission_id,
            node=run.get("node", "unknown"),
            status=run.get("status", "ok"),
            latency_ms=run.get("latency_ms"),
            revision=run.get("revision", 0),
            error=run.get("error"),
        ))
    for u in outcome.usage_events:
        session.add(UsageEvent(
            mission_id=outcome.mission_id,
            node=u.get("node", "unknown"),
            model=u.get("model", "unknown"),
            prompt_tokens=int(u.get("prompt_tokens", 0)),
            completion_tokens=int(u.get("completion_tokens", 0)),
            cost_usd=float(u.get("cost_usd", 0.0)),
            latency_ms=int(u.get("latency_ms", 0)),
        ))

    m = await session.get(Mission, outcome.mission_id)
    if m is None:
        logger.error("persist_outcome on unknown mission %s", outcome.mission_id)
        return
    m.status = outcome.status.value
    m.revision_count = outcome.revision_count
    m.error = outcome.error[:2000] if outcome.error else None
    if outcome.plan is not None:
        m.plan_json = _dump(outcome.plan)
    if outcome.final_report is not None:
        m.report_json = _dump(outcome.final_report)
        m.verdict_history_json = list(outcome.final_report.review_history)
    elif outcome.interrupt_payload is not None:
        m.interrupt_payload_json = _dump(outcome.interrupt_payload)


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else model


async def persist_eval_run(session: AsyncSession, *, run_id: str, mean_overall: float,
                           pass_rate: float, case_count: int, fake_llm: bool,
                           results: list[dict]) -> None:
    session.add(EvalRun(
        id=run_id, mean_overall=mean_overall, pass_rate=pass_rate,
        case_count=case_count, fake_llm=fake_llm, results=results,
    ))


# --- reads / aggregates -------------------------------------------------------


async def get_mission_usage(session: AsyncSession, mission_id: str) -> dict[str, Any]:
    """Per-(node, model) rollup plus totals for one mission."""
    rows = (await session.execute(
        select(
            UsageEvent.node,
            UsageEvent.model,
            func.count().label("calls"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
            func.coalesce(func.sum(UsageEvent.latency_ms), 0),
        )
        .where(UsageEvent.mission_id == mission_id)
        .group_by(UsageEvent.node, UsageEvent.model)
        .order_by(UsageEvent.node)
    )).all()

    per_node_latency = dict((await session.execute(
        select(AgentRun.node, func.coalesce(func.sum(AgentRun.latency_ms), 0))
        .where(AgentRun.mission_id == mission_id)
        .group_by(AgentRun.node)
    )).all())

    usage_rows = [
        {
            "node": r.node, "model": r.model, "calls": r.calls,
            "prompt_tokens": int(r[3]), "completion_tokens": int(r[4]),
            "cost_usd": round(float(r[5]), 6), "total_latency_ms": int(r[6]),
        }
        for r in rows
    ]
    totals = {
        "calls": sum(r["calls"] for r in usage_rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in usage_rows),
        "completion_tokens": sum(r["completion_tokens"] for r in usage_rows),
        "cost_usd": round(sum(r["cost_usd"] for r in usage_rows), 6),
        "llm_latency_ms": sum(r["total_latency_ms"] for r in usage_rows),
        "node_wall_time_ms": {k: int(v) for k, v in sorted(per_node_latency.items())},
    }
    return {"mission_id": mission_id, "rows": usage_rows, "totals": totals}


async def platform_stats(session: AsyncSession) -> dict[str, Any]:
    """The global scoreboard: volume, cost, latency, quality."""
    missions_total = (await session.execute(select(func.count(Mission.id)))).scalar_one()
    by_status_rows = (await session.execute(
        select(Mission.status, func.count()).group_by(Mission.status)
    )).all()
    by_status = {status: n for status, n in by_status_rows}

    completed = by_status.get("completed", 0)

    llm = (await session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
        )
    )).one()

    avg_node_latency = dict((await session.execute(
        select(AgentRun.node, func.coalesce(func.avg(AgentRun.latency_ms), 0.0))
        .group_by(AgentRun.node)
    )).all())

    # quality signal: critic scores recorded in verdict histories
    judge_scores: list[float] = []
    revisions: list[int] = []
    for m in (await session.execute(
        select(Mission.verdict_history_json, Mission.revision_count)
        .where(Mission.verdict_history_json.is_not(None))
    )).all():
        history, rev = m[0] or [], m[1]
        revisions.append(rev or 0)
        judge_scores += [h["overall_score"] for h in history if h.get("stage") == "critic"]

    return {
        "missions": {
            "total": missions_total,
            "by_status": by_status,
            "completion_rate": round(completed / missions_total, 3) if missions_total else 0.0,
            "avg_revisions": round(sum(revisions) / len(revisions), 2) if revisions else 0.0,
        },
        "llm": {
            "calls": int(llm[0]),
            "prompt_tokens": int(llm[1]),
            "completion_tokens": int(llm[2]),
            "cost_usd": round(float(llm[3]), 4),
        },
        "quality": {
            "avg_judge_score": (
                round(sum(judge_scores) / len(judge_scores), 2) if judge_scores else None
            ),
            "judged_reports": len(judge_scores),
        },
        "avg_node_latency_ms": {k: round(float(v), 1) for k, v in sorted(avg_node_latency.items())},
    }
