"""Document ingestion: chunk -> embed -> upsert into Qdrant.

Chunking is paragraph-aware with a sliding window; payloads keep provenance so
RAG evidence can cite the source document.
"""

import logging
import uuid
from dataclasses import dataclass

from app.embeddings.embedder import BaseEmbedder
from app.schemas.mission import DocumentIn, SearchHit, SearchResponse
from app.tools.retriever import QdrantRetriever

logger = logging.getLogger(__name__)


def chunk_text(text: str, *, size: int = 900, overlap: int = 120) -> list[str]:
    """Paragraph-aware sliding-window chunker."""
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if len(para) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            step = max(size - overlap, 1)
            for i in range(0, len(para), step):
                pieces = para[i : i + size].strip()
                if len(pieces) < 40 and i + size >= len(para):
                    break
                chunks.append(pieces)
            continue
        if len(buf) + len(para) + 2 <= size:
            buf = f"{buf}\n\n{para}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    # merge tiny trailing chunk
    if len(chunks) >= 2 and len(chunks[-1]) < 80:
        chunks[-2] = f"{chunks[-2]}\n\n{chunks.pop()}"
    return chunks


@dataclass
class IngestionReport:
    documents_ingested: int
    chunks_indexed: int


class IngestionPipeline:
    def __init__(self, retriever: QdrantRetriever, embedder: BaseEmbedder, *,
                 chunk_size: int = 900, chunk_overlap: int = 120,
                 batch_size: int = 64) -> None:
        self.retriever = retriever
        self.embedder = embedder
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.batch_size = batch_size
        self._vector_size: int | None = None

    async def ensure_collection(self) -> int:
        """Create collection on first use; returns vector dimension."""
        if self._vector_size is None:
            probe = await self.embedder.embed(["dimension probe"])
            self._vector_size = len(probe[0])
        await self.retriever.ensure_collection(self._vector_size)
        return self._vector_size

    async def ingest_documents(self, docs: list[DocumentIn]) -> IngestionReport:
        await self.ensure_collection()
        total = 0
        for doc in docs:
            chunks = chunk_text(doc.text, size=self.chunk_size, overlap=self.chunk_overlap)
            if not chunks:
                logger.warning("document %r produced no chunks", doc.title)
                continue
            ids: list[str] = []
            payloads: list[dict] = []
            for i, chunk in enumerate(chunks):
                ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc.title}::{i}::{chunk[:64]}")))
                payloads.append({
                    "content": chunk,
                    "doc_title": doc.title,
                    "title": doc.title if i == 0 else f"{doc.title} (part {i + 1})",
                    "source_url": doc.metadata.get("source_url"),
                    "chunk_index": i,
                    "metadata": doc.metadata,
                })
            for start in range(0, len(chunks), self.batch_size):
                batch_ids = ids[start : start + self.batch_size]
                batch_payloads = payloads[start : start + self.batch_size]
                vectors = await self.embedder.embed(
                    [p["content"] for p in batch_payloads]
                )
                await self.retriever.upsert(batch_ids, vectors, batch_payloads)
            total += len(chunks)
            logger.info("ingested %r as %d chunks", doc.title, len(chunks))
        return IngestionReport(documents_ingested=len(docs), chunks_indexed=total)

    async def search(self, query: str, *, top_k: int = 5) -> SearchResponse:
        await self.ensure_collection()
        hits: list[SearchHit] = []
        try:
            from app.tools.retriever import qdrant_client

            async with qdrant_client(self.retriever.url) as client:
                vector = (await self.embedder.embed([query]))[0]
                result = await client.query_points(
                    collection_name=self.retriever.collection,
                    query=vector, limit=top_k, with_payload=True,
                )
            for scored in result.points:
                payload = scored.payload or {}
                hits.append(SearchHit(
                    score=round(float(scored.score or 0.0), 4),
                    title=payload.get("title") or "",
                    content=(payload.get("content") or "")[:600],
                    metadata={"doc_title": payload.get("doc_title"),
                              **(payload.get("metadata") or {})},
                ))
        except Exception as exc:
            logger.error("knowledge search failed: %s", exc)
            raise
        return SearchResponse(query=query, hits=hits)
