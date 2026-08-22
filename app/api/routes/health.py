from fastapi import APIRouter, Request
from sqlalchemy import select

from app.db.session import session_scope
from app.tools.retriever import qdrant_client

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> dict:
    checks: dict[str, str] = {}
    try:
        async with session_scope(request.app.state.engine) as ses:
            await ses.execute(select(1))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    try:
        settings = request.app.state.settings
        async with qdrant_client(settings.qdrant_url) as client:
            await client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        checks["qdrant"] = f"error: {exc}"
    ok = all(v == "ok" for v in checks.values())
    return {"ready": ok, "checks": checks}
