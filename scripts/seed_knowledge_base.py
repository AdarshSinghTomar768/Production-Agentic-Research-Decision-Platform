"""Seed the knowledge base from markdown files in knowledge/sample_docs/.

Usage:
    uv run python scripts/seed_knowledge_base.py [--reset]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import get_engine, init_db, session_scope  # noqa: F401 (validates config)
from app.embeddings.embedder import get_embedder
from app.ingestion.pipeline import IngestionPipeline
from app.schemas.mission import DocumentIn
from app.tools.retriever import QdrantRetriever

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("seed")


async def main(reset: bool) -> None:
    settings = get_settings()
    embedder = get_embedder(settings.embedding_model, fake=settings.fake_llm)
    retriever = QdrantRetriever(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        embedder=embedder,
    )
    pipeline = IngestionPipeline(retriever, embedder)

    docs_dir = Path(__file__).resolve().parents[1] / "knowledge" / "sample_docs"
    files = sorted(docs_dir.glob("*.md"))
    if not files:
        logger.error("no .md documents found in %s", docs_dir)
        return

    if reset:
        from qdrant_client import AsyncQdrantClient

        async with AsyncQdrantClient(url=settings.qdrant_url) as client:
            await client.delete_collection(settings.qdrant_collection)
        logger.info("reset collection %s", settings.qdrant_collection)

    docs = [
        DocumentIn(
            title=f.stem.replace("_", " ").title(),
            text=f.read_text(encoding="utf-8"),
            metadata={"source": "sample_seed", "file": f.name},
        )
        for f in files
    ]
    report = await pipeline.ingest_documents(docs)
    logger.info(
        "done: %d documents -> %d chunks in collection %r (%s vectors)",
        report.documents_ingested, report.chunks_indexed,
        settings.qdrant_collection, settings.embedding_model,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop the collection first")
    asyncio.run(main(parser.parse_args().reset))
