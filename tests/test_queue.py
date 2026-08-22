"""Mission job queue: enqueue/claim/complete lifecycle + lease requeue."""

import asyncio
from datetime import datetime  # noqa: F401 (used by lease math in app.queue)

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import get_engine, init_db
from app.queue import (
    claim_next,
    complete_job,
    enqueue_job,
    has_active_job,
    requeue_expired,
)


@pytest.fixture()
async def engine(tmp_path):
    eng = get_engine(f"sqlite+aiosqlite:///{tmp_path}/queue.db")
    await init_db(eng)
    yield eng


async def test_enqueue_claim_complete_roundtrip(engine: AsyncEngine):
    assert await has_active_job(engine, "m-1") is False

    await enqueue_job(engine, "m-1", "start", {"question": "hello world"})
    assert await has_active_job(engine, "m-1") is True

    job = await claim_next(engine, "worker-a", lease_seconds=300)
    assert job is not None and job.mission_id == "m-1" and job.kind == "start"
    assert job.status == "running"
    assert job.claimed_by == "worker-a"
    assert job.payload["question"] == "hello world"

    # claimed jobs are invisible to other claims while leased...
    assert await claim_next(engine, "worker-b", lease_seconds=300) is None

    await complete_job(engine, job.id)
    assert await has_active_job(engine, "m-1") is False


async def test_fifo_claim_order(engine: AsyncEngine):
    await enqueue_job(engine, "m-old", "start", {})
    await asyncio.sleep(0.01)
    await enqueue_job(engine, "m-new", "start", {})

    first = await claim_next(engine, "w", 60)
    second = await claim_next(engine, "w", 60)
    assert (first.mission_id, second.mission_id) == ("m-old", "m-new")


async def test_expired_lease_is_requeued(engine: AsyncEngine):
    await enqueue_job(engine, "m-crashed", "start", {})
    job = await claim_next(engine, "dead-worker", lease_seconds=-1)  # already lapsed
    assert job.status == "running"

    # nothing claimable until the sweep runs
    assert await claim_next(engine, "w2", 60) is None

    requeued = await requeue_expired(engine)
    assert requeued == 1

    again = await claim_next(engine, "w2", 60)
    assert again is not None
    assert again.mission_id == "m-crashed"
    assert again.claimed_by == "w2"


async def test_requeue_ignores_active_leases(engine: AsyncEngine):
    await enqueue_job(engine, "m-live", "start", {})
    await claim_next(engine, "healthy-worker", lease_seconds=900)

    assert await requeue_expired(engine) == 0
