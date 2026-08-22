"""Mission lifecycle endpoints, including the human-approval resume flow."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_api_key
from app.db.models import Mission
from app.db.session import session_scope
from app.graph.runner import MissionOutcome
from app.llm.guardrails import check_user_question
from app.observability.tracking import create_mission as _create_mission_row
from app.observability.tracking import (
    get_mission_usage,
    persist_outcome,
    platform_stats,
    set_status,
)
from app.queue import enqueue_job, has_active_job
from app.schemas.mission import (
    ApprovalDecision,
    MissionCreate,
    MissionCreated,
    MissionDetail,
    MissionStatus,
    MissionUsage,
)
from app.schemas.plan import ResearchPlan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/missions", tags=["missions"], dependencies=[Depends(require_api_key)])


# --- background execution -----------------------------------------------------


async def _run_flow(app, mission_id: str, *, question: str | None = None,
                    decision: ApprovalDecision | None = None) -> None:
    """Inline mode: shared start/resume execution as a background task."""
    orchestrator = app.state.orchestrator
    engine = app.state.engine
    try:
        async with session_scope(engine) as ses:
            await set_status(ses, mission_id, MissionStatus.RUNNING.value)

        outcome: MissionOutcome = (
            await orchestrator.start_mission(question, mission_id=mission_id)
            if decision is None
            else await orchestrator.resume_mission(
                mission_id, approved=decision.approved, feedback=decision.feedback
            )
        )
        async with session_scope(engine) as ses:
            await persist_outcome(ses, outcome)
        logger.info("[api] mission %s -> %s", mission_id[:8], outcome.status.value)
    except Exception:
        logger.exception("[api] background run failed for %s", mission_id[:8])
        try:
            async with session_scope(engine) as ses:
                await set_status(ses, mission_id, MissionStatus.FAILED.value,
                                 error="background runner crashed; see server logs")
        except Exception:
            logger.exception("[api] could not record failure state")


def _schedule(app, mission_id: str, coro) -> None:
    tasks: dict[str, asyncio.Task] = app.state.mission_tasks
    old = tasks.get(mission_id)
    if old and not old.done():
        raise HTTPException(status_code=409, detail="mission already has a running task")
    tasks[mission_id] = asyncio.create_task(coro)


async def _dispatch(app, mission_id: str, *, question: str | None = None,
                    decision: ApprovalDecision | None = None) -> str:
    """Hand the work to an executor.

    inline  — background task in this process (dev/tests).
    workers — durable row in mission_jobs; a worker process picks it up.
              Returns the status the client should see next.
    """
    if app.state.settings.execution_mode != "workers":
        _schedule(app, mission_id, _run_flow(app, mission_id,
                                             question=question, decision=decision))
        return MissionStatus.RUNNING.value

    kind = "resume" if decision is not None else "start"
    if await has_active_job(app.state.engine, mission_id):
        raise HTTPException(status_code=409,
                            detail="mission already has a queued or running job")
    payload = (
        {"approved": decision.approved, "feedback": decision.feedback}
        if decision is not None else {"question": question}
    )
    await enqueue_job(app.state.engine, mission_id, kind, payload)
    return MissionStatus.QUEUED.value


# --- helpers ------------------------------------------------------------------


async def _load(session: AsyncSession, mission_id: str) -> Mission:
    m = await session.get(Mission, mission_id)
    if m is None:
        raise HTTPException(status_code=404, detail="mission not found")
    return m


# --- routes -------------------------------------------------------------------


@router.post("", status_code=202, response_model=MissionCreated)
async def create_mission(body: MissionCreate, request: Request):
    question = check_user_question(body.question)  # raises GuardrailViolation -> handler
    mission_id = str(uuid.uuid4())
    engine = request.app.state.engine
    async with session_scope(engine) as ses:
        m = await _create_mission_row(ses, mission_id=mission_id, question=question)
        status = m.status
    await _dispatch(request.app, mission_id, question=question)
    return MissionCreated(mission_id=m.id, status=MissionStatus(status))


@router.get("", response_model=list[MissionDetail])
async def list_missions(request: Request, limit: int = 20):
    engine = request.app.state.engine
    async with session_scope(engine) as ses:
        rows = (await ses.execute(
            select(Mission).order_by(Mission.created_at.desc()).limit(min(limit, 100))
        )).scalars().all()
    return [_to_detail(m) for m in rows]


@router.get("/stats")
async def stats(request: Request):
    async with session_scope(request.app.state.engine) as ses:
        return await platform_stats(ses)


@router.get("/{mission_id}", response_model=MissionDetail)
async def get_mission(mission_id: str, request: Request):
    async with session_scope(request.app.state.engine) as ses:
        m = await _load(ses, mission_id)
    return _to_detail(m)


@router.get("/{mission_id}/review")
async def get_review_payload(mission_id: str, request: Request):
    """Everything a human reviewer needs to approve/reject."""
    async with session_scope(request.app.state.engine) as ses:
        m = await _load(ses, mission_id)
    if m.status != MissionStatus.PENDING_APPROVAL.value or not m.interrupt_payload_json:
        raise HTTPException(status_code=409,
                            detail=f"mission is '{m.status}', nothing awaiting review")
    return {"mission_id": m.id, "status": m.status, "review": m.interrupt_payload_json}


@router.post("/{mission_id}/decision", status_code=202, response_model=MissionCreated)
async def decide(mission_id: str, body: ApprovalDecision, request: Request):
    if not body.approved and not (body.feedback and body.feedback.strip()):
        raise HTTPException(status_code=422,
                            detail="rejecting requires 'feedback' to guide the revision")
    async with session_scope(request.app.state.engine) as ses:
        m = await _load(ses, mission_id)
        if m.status != MissionStatus.PENDING_APPROVAL.value:
            raise HTTPException(
                status_code=409,
                detail=f"mission is '{m.status}'; decisions apply only to pending_approval",
            )
    next_status = await _dispatch(request.app, mission_id, decision=body)
    return MissionCreated(mission_id=mission_id,
                          status=MissionStatus(next_status))


@router.get("/{mission_id}/report")
async def get_report(mission_id: str, request: Request):
    async with session_scope(request.app.state.engine) as ses:
        m = await _load(ses, mission_id)
    if not m.report_json:
        raise HTTPException(status_code=409,
                            detail=f"no report yet; mission status='{m.status}'")
    return {"mission_id": m.id, "question": m.question, "report": m.report_json}


@router.get("/{mission_id}/usage", response_model=MissionUsage)
async def usage(mission_id: str, request: Request):
    async with session_scope(request.app.state.engine) as ses:
        await _load(ses, mission_id)
        data = await get_mission_usage(ses, mission_id)
    return MissionUsage(**data)


def _to_detail(m: Mission) -> MissionDetail:
    plan = None
    if m.plan_json:
        try:
            plan = ResearchPlan.model_validate(m.plan_json)
        except Exception:
            plan = None
    return MissionDetail(
        mission_id=m.id, question=m.question, status=MissionStatus(m.status),
        plan=plan, revision_count=m.revision_count, error=m.error,
        created_at=m.created_at, updated_at=m.updated_at,
    )
