"""Durable mission job queue backed by the platform database.

No broker needed: Postgres is already the system of record, so jobs live in a
table. Workers claim rows atomically (FOR UPDATE SKIP LOCKED) making N worker
processes safe; each claim takes a time-boxed lease, and expired leases are
requeued — so a crashed worker never strands a mission.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import MissionJob
from app.db.session import session_scope

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue_job(engine: AsyncEngine, mission_id: str, kind: str,
                      payload: dict[str, Any] | None = None) -> str:
    job_id = str(uuid.uuid4())
    async with session_scope(engine) as ses:
        ses.add(MissionJob(id=job_id, mission_id=mission_id, kind=kind,
                           payload=payload or {}, status="queued"))
    return job_id


async def has_active_job(engine: AsyncEngine, mission_id: str) -> bool:
    """True if the mission already has a queued/running job (double-enqueue guard)."""
    async with session_scope(engine) as ses:
        row = (await ses.execute(
            select(MissionJob.id)
            .where(MissionJob.mission_id == mission_id,
                   MissionJob.status.in_(("queued", "running")))
            .limit(1)
        )).scalar_one_or_none()
    return row is not None


async def claim_next(engine: AsyncEngine, worker_id: str,
                     lease_seconds: int) -> MissionJob | None:
    """Atomically claim the oldest queued job; returns None when idle."""
    lease_until = _now() + timedelta(seconds=lease_seconds)
    if engine.url.get_backend_name().startswith("postgresql"):
        subq = (
            select(MissionJob.id)
            .where(MissionJob.status == "queued")
            .order_by(MissionJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        claim = (
            update(MissionJob)
            .where(MissionJob.id.in_(subq))
            .values(status="running", claimed_by=worker_id, lease_expires_at=lease_until,
                    updated_at=_now())
            .returning(MissionJob)
        )
        async with session_scope(engine) as ses:
            row = (await ses.execute(claim)).scalar_one_or_none()
        return row

    # sqlite / dev path: no SKIP LOCKED — safe because a single process claims.
    async with session_scope(engine) as ses:
        job = (await ses.execute(
            select(MissionJob)
            .where(MissionJob.status == "queued")
            .order_by(MissionJob.created_at)
            .limit(1)
        )).scalar_one_or_none()
        if job is not None:
            job.status = "running"
            job.claimed_by = worker_id
            job.lease_expires_at = lease_until
            job.updated_at = _now()
        return job


async def complete_job(engine: AsyncEngine, job_id: str,
                       error: str | None = None) -> None:
    async with session_scope(engine) as ses:
        job = await ses.get(MissionJob, job_id)
        if job is not None:
            job.status = "error" if error else "done"
            job.error = error[:2000] if error else None
            job.updated_at = _now()


async def requeue_expired(engine: AsyncEngine) -> int:
    """Requeue jobs whose claiming worker died mid-flight (lease lapsed)."""
    async with session_scope(engine) as ses:
        result = await ses.execute(
            update(MissionJob)
            .where(MissionJob.status == "running",
                   MissionJob.lease_expires_at.is_not(None),
                   MissionJob.lease_expires_at < _now())
            .values(status="queued", claimed_by=None, lease_expires_at=None,
                    updated_at=_now())
        )
        count = result.rowcount or 0
    if count:
        logger.warning("requeued %d stale job(s) from dead/expired worker leases", count)
    return count
