"""Standalone mission worker.

Claims queued jobs from the database and drives the LangGraph pipeline
out-of-process, so the API stays responsive and workers scale horizontally:

    docker compose up -d --scale worker=4      # N containers, SKIP LOCKED claims
    uv run python -m app.worker                # local dev against compose postgres

Crash safety: every claim holds a time-boxed lease; a worker that dies leaves a
lapsed lease which the requeue sweep returns to 'queued' for another worker.
"""

import asyncio
import logging
import os
import socket
import uuid

from app.config import get_settings
from app.db.checkpointer import make_checkpointer
from app.db.session import get_engine_for_settings, init_db, session_scope
from app.graph.builder import make_services
from app.graph.runner import MissionOrchestrator
from app.observability.tracking import persist_outcome, set_status
from app.queue import claim_next, complete_job, requeue_expired
from app.schemas.mission import ApprovalDecision, MissionStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0


async def _execute(engine, orchestrator: MissionOrchestrator, job) -> None:  # noqa: ANN001
    mission_id = job.mission_id
    try:
        async with session_scope(engine) as ses:
            await set_status(ses, mission_id, MissionStatus.RUNNING.value)

        if job.kind == "start":
            outcome = await orchestrator.start_mission(
                job.payload["question"], mission_id=mission_id)
        elif job.kind == "resume":
            decision = ApprovalDecision(**job.payload)
            outcome = await orchestrator.resume_mission(
                mission_id, approved=decision.approved, feedback=decision.feedback)
        else:
            raise ValueError(f"unknown job kind '{job.kind}'")

        async with session_scope(engine) as ses:
            await persist_outcome(ses, outcome)
        logger.info("[worker] mission %s -> %s", mission_id[:8], outcome.status.value)
        await complete_job(engine, job.id)
    except Exception as exc:
        logger.exception("[worker] job %s (%s) crashed", job.id[:8], job.kind)
        try:
            async with session_scope(engine) as ses:
                await set_status(ses, mission_id, MissionStatus.FAILED.value,
                                 error=f"worker crash: {type(exc).__name__}: {exc}")
        except Exception:
            logger.exception("[worker] could not record failure state")
        await complete_job(engine, job.id, error=f"{type(exc).__name__}: {exc}")


async def _loop(engine, orchestrator: MissionOrchestrator,
                worker_id: str, lease_seconds: int) -> None:
    """One claim-at-a-time loop; N of these run concurrently = worker_concurrency."""
    while True:
        # Crash recovery first: lapsed leases from dead workers go back to 'queued'.
        await requeue_expired(engine)
        job = await claim_next(engine, worker_id, lease_seconds)
        if job is None:
            await asyncio.sleep(POLL_INTERVAL_S)
            continue
        await _execute(engine, orchestrator, job)


async def run_worker() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    engine = get_engine_for_settings(settings)
    await init_db(engine)
    checkpointer, pool = await make_checkpointer(settings)
    orchestrator = MissionOrchestrator(make_services(settings), checkpointer)

    worker_id = f"{socket.gethostname()}/{os.getpid()}/{uuid.uuid4().hex[:6]}"
    logger.info("mission worker %s started (mode=%s concurrency=%d lease=%ds "
                "fake_llm=%s model=%s fallbacks=%s)",
                worker_id, settings.execution_mode, settings.worker_concurrency,
                settings.job_lease_seconds, settings.fake_llm, settings.model,
                settings.llm_fallback_models or "-")

    try:
        await asyncio.gather(*[
            _loop(engine, orchestrator, worker_id, settings.job_lease_seconds)
            for _ in range(max(1, settings.worker_concurrency))
        ])
    finally:
        if pool is not None:
            await pool.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_worker())
