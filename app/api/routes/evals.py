"""Evaluation suite endpoint: runs the golden set through the live pipeline."""

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from app.api.deps import require_api_key
from app.db.session import session_scope
from app.evals.harness import EvalHarness, load_golden_set
from app.graph import MissionOrchestrator
from app.graph.builder import make_services
from app.observability.tracking import persist_eval_run
from app.schemas.mission import EvalRunSummary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/evals", tags=["evals"], dependencies=[Depends(require_api_key)])


class EvalRunRequest(BaseModel):
    fake_llm: bool | None = None  # override settings; None -> use current config


@router.post("/run", response_model=EvalRunSummary)
async def run_evals(body: EvalRunRequest, request: Request):
    settings = request.app.state.settings
    fake = settings.fake_llm if body.fake_llm is None else body.fake_llm

    orchestrator = request.app.state.orchestrator
    if fake and not settings.fake_llm:
        # The live orchestrator owns real tools; fake mode needs a throwaway
        # offline stack (FakeProvider + ephemeral checkpointer), same as the CLI.
        offline_settings = settings.model_copy(update={"fake_llm": True})
        orchestrator = MissionOrchestrator(make_services(offline_settings), MemorySaver())

    harness = EvalHarness(
        orchestrator,
        orchestrator.services.provider,
        judge_model=settings.judge_model,
        pass_threshold=settings.judge_pass_threshold,
    )
    summary, details, _printable = await harness.run_suite(load_golden_set(), fake_llm=fake)
    run_id = str(uuid.uuid4())
    try:
        async with session_scope(request.app.state.engine) as ses:
            await persist_eval_run(
                ses, run_id=run_id, mean_overall=summary.mean_overall,
                pass_rate=summary.mean_pass_rate, case_count=len(summary.cases),
                fake_llm=fake, results=[c.model_dump(mode="json") for c in summary.cases],
            )
        summary.run_id = run_id
    except Exception as exc:
        logger.warning("could not persist eval run: %s", exc)
    return summary
