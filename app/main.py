"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import evals, health, knowledge, missions
from app.config import Settings, get_settings
from app.db.session import get_engine, init_db
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


async def _make_checkpointer(settings: Settings):
    """Postgres-backed checkpointer when available; in-memory otherwise."""
    if settings.database_url.startswith("postgresql"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        conninfo = settings.database_url.replace("+asyncpg", "")
        # autocommit is required: checkpointer.setup() issues CREATE INDEX CONCURRENTLY
        pool = AsyncConnectionPool(conninfo=conninfo, open=False, max_size=10,
                                   kwargs={"autocommit": True})
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        logger.info("langgraph checkpointer: postgres")
        return saver, pool
    from langgraph.checkpoint.memory import MemorySaver

    logger.warning("langgraph checkpointer: in-memory (interrupts lost on restart)")
    return MemorySaver(), None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    engine = get_engine(settings.database_url, settings.db_echo)
    await init_db(engine)

    checkpointer, pool = await _make_checkpointer(settings)
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

    logger.info("%s started (env=%s fake_llm=%s model=%s)",
                settings.app_name, settings.environment, settings.fake_llm, settings.model)
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
