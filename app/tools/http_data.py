"""Tool/API agent's data access: allowlisted HTTPS JSON endpoints.

Ships with a keyless Wikipedia REST summary tool as the concrete example.
Add hosts to ALLOWED_HOSTS (or inject your own client) for internal APIs.
"""

import logging

import httpx

from app.tools.base import RawHit

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"en.wikipedia.org"})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class HttpDataTool:
    name = "data"

    def __init__(self, *, timeout_s: float = 15.0) -> None:
        self.timeout_s = timeout_s

    async def fetch_json(self, url: str) -> dict | list:
        """GET a JSON document from an allowlisted HTTPS host, size-capped."""
        if not url.lower().startswith("https://"):
            raise ValueError("only https URLs are allowed")
        host = httpx.URL(url).host
        if not host or host not in ALLOWED_HOSTS:
            raise ValueError(f"host '{host}' is not in the tool allowlist")
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True,
                                     headers={"User-Agent": "agentic-research-platform/0.1"}) as c:
            async with c.stream("GET", url) as resp:
                resp.raise_for_status()
                buf = bytearray()
                async for chunk in resp.aiter_bytes(64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > MAX_RESPONSE_BYTES:
                        raise ValueError("response exceeded size cap")
                return resp.json()

    async def wikipedia_summary(self, company: str) -> RawHit | None:
        slug = company.strip().replace(" ", "_")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
        try:
            data = await self.fetch_json(url)
        except Exception as exc:
            logger.warning("wikipedia summary failed for %r: %s", company, exc)
            return None
        extract = (data.get("extract") or "").strip()
        if not extract:
            return None
        return RawHit(
            title=data.get("title") or company,
            content=extract[:3000],
            url=data.get("content_urls", {}).get("desktop", {}).get("page"),
            score=1.0,
            metadata={"tool": "wikipedia", "type": data.get("type")},
        )


class OfflineDataTool:
    name = "data"

    async def wikipedia_summary(self, company: str) -> RawHit | None:
        return RawHit(
            title=f"[offline-data] {company}",
            content=(
                f"Synthetic profile: {company} is a mid-market organization with active "
                f"digital transformation initiatives and growing interest in applied AI."
            ),
            url="https://example.com/offline-profile",
            score=1.0,
            metadata={"tool": "offline"},
        )
