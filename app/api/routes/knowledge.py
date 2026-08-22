"""Knowledge base management: ingestion and direct semantic search."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import require_api_key
from app.schemas.mission import IngestRequest, IngestResponse, SearchRequest, SearchResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"],
                   dependencies=[Depends(require_api_key)])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(body: IngestRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        report = await pipeline.ingest_documents(
            [d for d in body.documents]
        )
    except Exception as exc:
        logger.error("ingestion failed: %s", exc)
        raise HTTPException(status_code=503, detail=(
            f"ingestion failed (is Qdrant up and the embedding model reachable?): {exc}"
        )) from exc
    return IngestResponse(documents_ingested=report.documents_ingested,
                          chunks_indexed=report.chunks_indexed,
                          collection=request.app.state.settings.qdrant_collection)


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, request: Request):
    pipeline = request.app.state.pipeline
    try:
        return await pipeline.search(body.query, top_k=body.top_k)
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail=f"search failed (is Qdrant up?): {exc}") from exc
