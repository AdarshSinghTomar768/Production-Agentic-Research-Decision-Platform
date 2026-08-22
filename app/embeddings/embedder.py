"""Embedding abstraction. Real path goes through LiteLLM (provider encoded in the
model string); tests use a deterministic hashing embedder."""

import hashlib
import logging

import litellm

logger = logging.getLogger(__name__)


class BaseEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError


class LiteLLMEmbedder(BaseEmbedder):
    def __init__(self, model: str) -> None:
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await litellm.aembedding(model=self.model, input=texts)
        vectors = [item["embedding"] for item in resp.data]
        logger.debug("embedded %d texts via %s", len(vectors), self.model)
        return vectors


class FakeEmbedder(BaseEmbedder):
    """Deterministic feature-hashing embedder — no network, stable across runs.

    Same-text similarity is exact-match; near-duplicates land close enough for
    smoke tests. Not semantically meaningful; only for CI.
    """

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            tokens = "".join(ch.lower() if ch.isalnum() else " " for ch in t).split()
            for tok in tokens:
                h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:4], "big")
                idx = h % self.dim
                sign = 1.0 if (h >> 31) & 1 else -1.0
                vec[idx] += sign
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


def get_embedder(model: str, *, fake: bool = False, dim: int = 768) -> BaseEmbedder:
    return FakeEmbedder(dim=dim) if fake else LiteLLMEmbedder(model)
