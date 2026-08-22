"""Tavily web search tool (https://tavily.com). Free tier: ~1000 searches/mo."""

import logging

import httpx

from app.tools.base import RawHit

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.tavily.com/search"


class WebSearchTool:
    name = "web"

    def __init__(self, api_key: str | None, *, max_results: int = 5, timeout_s: float = 20.0) -> None:
        self.api_key = api_key
        self.max_results = max_results
        self.timeout_s = timeout_s

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[RawHit]:
        if not self.available:
            logger.warning("web search skipped: TAVILY_API_KEY not configured")
            return []
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": self.max_results,
            "search_depth": "basic",
            "include_answer": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(_ENDPOINT, json=payload)
            resp.raise_for_status()
            data = resp.json()
        hits = []
        for r in data.get("results", []):
            content = (r.get("content") or "").strip()
            if not content:
                continue
            hits.append(
                RawHit(
                    title=(r.get("title") or query)[:300],
                    content=content,
                    url=r.get("url"),
                    score=float(r.get("score")) if r.get("score") is not None else None,
                    metadata={"tool": "tavily"},
                )
            )
        logger.info("web search %r -> %d hits", query, len(hits))
        return hits


class OfflineWebSearchTool:
    """Deterministic stand-in used when FAKE_LLM=true and no key is set."""

    name = "web"

    def __init__(self, results_per_query: int = 3) -> None:
        self.results_per_query = results_per_query

    @property
    def available(self) -> bool:
        return True

    async def search(self, query: str) -> list[RawHit]:
        return [
            RawHit(
                title=f"[offline-web] result {i + 1} for {query!r}",
                content=(
                    f"Offline synthetic finding #{i + 1} about '{query}': market indicators "
                    f"suggest moderate opportunity with execution risk concentrated in "
                    f"data-readiness and change management."
                ),
                url="https://example.com/offline-source",
                score=round(0.9 - 0.1 * i, 2),
                metadata={"tool": "offline"},
            )
            for i in range(self.results_per_query)
        ]
