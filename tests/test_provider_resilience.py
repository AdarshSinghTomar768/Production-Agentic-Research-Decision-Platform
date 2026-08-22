"""Rate-limit-aware provider behavior: fallback rotation + Retry-After backoff."""

import asyncio
from types import SimpleNamespace

import litellm
import pytest
from pydantic import BaseModel

from app.llm.provider import LiteLLMProvider, StructuredOutputError, _is_transient


class Out(BaseModel):
    ok: bool


class RateLimitError(Exception):
    status_code = 429


def _resp(ok: bool = True):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=f'{{"ok": {str(ok).lower()}}}'))],
        usage=None,
    )


@pytest.fixture()
def sleep_log(monkeypatch):
    calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return calls


@pytest.fixture()
def no_cost(monkeypatch):
    monkeypatch.setattr(LiteLLMProvider, "_safe_cost", staticmethod(lambda resp: 0.0))


def test_transient_classification():
    assert _is_transient(RateLimitError("slow down"))
    boom = Exception("x")
    boom.status_code = 503
    assert _is_transient(boom)
    bad = Exception("nope")
    bad.status_code = 400
    assert not _is_transient(bad)
    assert not _is_transient(ValueError("plain"))


async def test_falls_back_to_next_model_on_rate_limit(no_cost, monkeypatch):
    calls: list[str] = []

    async def fake_acompletion(*, model, **_):
        calls.append(model)
        if model == "primary/x":
            raise RateLimitError("429 quota exceeded")
        return _resp()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    provider = LiteLLMProvider(
        default_model="primary/x", temperature=0.2, max_tokens=64,
        timeout_s=5, max_repair_retries=2,
        fallback_models=["backup/y"], backoff_base_s=0.01,
    )

    result = await provider.structured(Out, "sys", "user", node="test")

    assert result.value.ok is True
    assert result.attempts == 2
    assert calls == ["primary/x", "backup/y"]
    assert result.usage[0].model == "backup/y"


async def test_backoff_honors_provider_retry_hint(no_cost, monkeypatch):
    """A 'retry in 45s' hint must dominate the tiny exponential base."""
    seen_delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        seen_delays.append(seconds)

    async def fake_acompletion(**_):
        raise RateLimitError('quota exceeded; Please retry in 45.2s')

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    provider = LiteLLMProvider(
        default_model="only/x", temperature=0.2, max_tokens=64,
        timeout_s=5, max_repair_retries=1, backoff_base_s=0.5,
    )

    with pytest.raises(StructuredOutputError):
        await provider.structured(Out, "sys", "user", node="test")

    assert len(seen_delays) == 1
    # 45.2s hint, capped at 60s, jittered ±20% -> must be far above the 0.5s base
    assert seen_delays[0] > 30


async def test_single_model_keeps_retrying_primary(no_cost, monkeypatch):
    calls: list[str] = []

    async def fake_acompletion(*, model, **_):
        calls.append(model)
        if len(calls) < 3:
            raise RateLimitError("429")
        return _resp()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    provider = LiteLLMProvider(
        default_model="only/x", temperature=0.2, max_tokens=64,
        timeout_s=5, max_repair_retries=2, backoff_base_s=0.001,
    )

    result = await provider.structured(Out, "sys", "user", node="test")
    assert result.attempts == 3
    assert set(calls) == {"only/x"}
