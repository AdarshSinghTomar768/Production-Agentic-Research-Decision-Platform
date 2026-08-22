"""Entry point for `python -m app.worker`."""

import asyncio

from app.worker.main import run_worker

asyncio.run(run_worker())
