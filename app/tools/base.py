"""Shared tool contracts. Tools return raw hits; agents assign evidence ids."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class RawHit:
    title: str
    content: str
    url: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ResearchTool(Protocol):
    name: str

    async def search(self, query: str) -> list[RawHit]: ...
