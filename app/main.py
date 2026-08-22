"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import evals, health, knowledge, missions
from app.config import Settings, get_settings
from app.db.checkpointer import make_checkpointer
from app.db.session import get_engine_for_settings, init_db
from app.embeddings.embedder import get_embedder
from app.graph.builder import make_services
from app.graph.runner import MissionOrchestrator
from app.ingestion.pipeline import IngestionPipeline
from app.llm.guardrails import GuardrailViolation
from app.tools.retriever import QdrantRetriever

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    if settings.execution_mode not in ("inline", "workers"):
        raise ValueError(f"EXECUTION_MODE must be 'inline' or 'workers', "
                         f"got '{settings.execution_mode}'")
    engine = get_engine_for_settings(settings)
    await init_db(engine)

    checkpointer, pool = await make_checkpointer(settings)
    orchestrator = MissionOrchestrator(make_services(settings), checkpointer)

    embedder = get_embedder(settings.embedding_model, fake=settings.fake_llm,
                            dim=settings.vector_size if settings.fake_llm else 768)
    retriever = QdrantRetriever(
        url=settings.qdrant_url, collection=settings.qdrant_collection,
        embedder=embedder, top_k=settings.rag_top_k,
        score_threshold=settings.rag_score_threshold,
    )
    pipeline = IngestionPipeline(retriever, embedder)

    app.state.settings = settings
    app.state.engine = engine
    app.state.orchestrator = orchestrator
    app.state.pipeline = pipeline
    app.state.mission_tasks = {}

    logger.info("%s started (env=%s fake_llm=%s model=%s execution=%s)",
                settings.app_name, settings.environment, settings.fake_llm,
                settings.model, settings.execution_mode)
    yield

    for task in list(app.state.mission_tasks.values()):
        task.cancel()
    if pool is not None:
        await pool.close()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agentic Research & Decision Platform",
        version="0.1.0",
        description="Multi-agent research pipeline with RAG, LLM-as-a-judge "
                    "quality gating, human-in-the-loop approval and full cost/latency telemetry.",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(missions.router)
    app.include_router(knowledge.router)
    app.include_router(evals.router)

    @app.exception_handler(GuardrailViolation)
    async def guardrail_handler(_: Request, exc: GuardrailViolation):
        return JSONResponse(status_code=422,
                            content={"detail": f"blocked by input guardrail: {exc.reason}"})

    return app


app = create_app()
