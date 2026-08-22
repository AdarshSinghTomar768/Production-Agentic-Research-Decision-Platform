"""Qdrant-backed retrieval tool for the internal knowledge base."""

import logging
from contextlib import asynccontextmanager

from qdrant_client import AsyncQdrantClient, models

from app.embeddings.embedder import BaseEmbedder
from app.tools.base import RawHit

logger = logging.getLogger(__name__)


@asynccontextmanager
async def qdrant_client(url: str):
    """AsyncQdrantClient lifecycle helper (no native async-with support)."""
    client = AsyncQdrantClient(url=url)
    try:
        yield client
    finally:
        await client.close()


class QdrantRetriever:
    name = "rag"

    def __init__(
        self,
        url: str,
        collection: str,
        embedder: BaseEmbedder,
        *,
        top_k: int = 5,
        score_threshold: float = 0.3,
    ) -> None:
        self.url = url
        self.collection = collection
        self.embedder = embedder
        self.top_k = top_k
        self.score_threshold = score_threshold

    async def ensure_collection(self, vector_size: int) -> None:
        async with qdrant_client(self.url) as client:
            exists = await client.collection_exists(self.collection)
            if not exists:
                await client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=vector_size, distance=models.Distance.COSINE
                    ),
                )
                logger.info("created qdrant collection %s (dim=%d)", self.collection, vector_size)

    async def upsert(self, ids: list[str], vectors: list[list[float]],
                     payloads: list[dict]) -> int:
        if not ids:
            return 0
        points = [
            models.PointStruct(id=pid, vector=vec, payload=payload)
            for pid, vec, payload in zip(ids, vectors, payloads, strict=True)
        ]
        async with qdrant_client(self.url) as client:
            await client.upsert(collection_name=self.collection, points=points)
        return len(points)

    async def search(self, query: str) -> list[RawHit]:
        vector = (await self.embedder.embed([query]))[0]
        try:
            async with qdrant_client(self.url) as client:
                result = await client.query_points(
                    collection_name=self.collection,
                    query=vector,
                    limit=self.top_k,
                    with_payload=True,
                )
        except Exception as exc:
            logger.error("qdrant query failed: %s", exc)
            return []
        hits: list[RawHit] = []
        for scored in result.points:
            score = float(scored.score or 0.0)
            payload = scored.payload or {}
            content = (payload.get("content") or "").strip()
            if score < self.score_threshold or not content:
                continue
            hits.append(
                RawHit(
                    title=(payload.get("title") or "untitled chunk")[:300],
                    content=content,
                    url=payload.get("source_url"),
                    score=score,
                    metadata={
                        "tool": "qdrant",
                        "doc_title": payload.get("doc_title"),
                        "chunk_index": payload.get("chunk_index"),
                        **(payload.get("metadata") or {}),
                    },
                )
            )
        logger.info("rag search %r -> %d hits", query[:80], len(hits))
        return hits


class OfflineRetriever:
    """Deterministic stand-in when FAKE_LLM=true / no Qdrant running."""

    name = "rag"

    @property
    def available(self) -> bool:
        return True

    async def search(self, query: str) -> list[RawHit]:
        return [
            RawHit(
                title="[offline-rag] internal brief",
                content=(
                    f"Internal knowledge base excerpt relevant to '{query}': prior engagements "
                    f"show AI services deals close faster when scoped to one workflow with "
                    f"measurable ROI within two quarters."
                ),
                url=None,
                score=0.82,
                metadata={"tool": "offline"},
            ),
            RawHit(
                title="[offline-rag] capability matrix",
                content=(
                    "Our delivery data indicates mid-market firms respond best to fixed-scope "
                    "AI assessments followed by implementation retainers."
                ),
                url=None,
                score=0.74,
                metadata={"tool": "offline"},
            ),
        ]
