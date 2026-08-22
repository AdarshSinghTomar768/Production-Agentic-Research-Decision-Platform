"""Run the golden-set evaluation suite.

    uv run python scripts/run_evals.py            # uses .env config (real or fake)
    uv run python scripts/run_evals.py --fake     # force deterministic offline mode
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import MemorySaver

from app.config import get_settings
from app.db import get_engine, init_db, session_scope
from app.evals import EvalHarness, load_golden_set
from app.graph import MissionOrchestrator
from app.graph.builder import make_services
from app.observability.tracking import persist_eval_run

logging.basicConfig(level=logging.WARNING)
logging.getLogger("app.evals").setLevel(logging.INFO)


async def main(force_fake: bool) -> None:
    settings = get_settings()
    if force_fake:
        settings.fake_llm = True

    orchestrator = MissionOrchestrator(make_services(settings), MemorySaver())
    harness = EvalHarness(
        orchestrator,
        orchestrator.services.provider,
        judge_model=settings.judge_model,
        pass_threshold=settings.judge_pass_threshold,
    )

    t0 = time.monotonic()
    summary, details, printable = await harness.run_suite(
        load_golden_set(), fake_llm=settings.fake_llm
    )
    elapsed = int((time.monotonic() - t0) * 1000)

    print(printable)
    print(f"suite wall time: {elapsed} ms")

    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    path = artifact_dir / f"{summary.run_id}.json"
    path.write_text(json.dumps(
        {"summary": summary.model_dump(mode="json"), "details": details},
        indent=2), encoding="utf-8")
    print(f"artifact written: {path}")

    if not settings.fake_llm:
        try:
            engine = get_engine(settings.database_url, settings.db_echo)
            await init_db(engine)
            async with session_scope(engine) as ses:
                await persist_eval_run(
                    ses, run_id=summary.run_id,
                    mean_overall=summary.mean_overall,
                    pass_rate=summary.mean_pass_rate,
                    case_count=len(summary.cases),
                    fake_llm=settings.fake_llm,
                    results=[c.model_dump(mode="json") for c in summary.cases],
                )
            print("eval run persisted to database")
        except Exception as exc:  # evals must work without a DB too
            print(f"(skipped DB persistence: {exc})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true",
                        help="force deterministic offline mode")
    asyncio.run(main(parser.parse_args().fake))
