"""LLM provider abstraction.

- LiteLLMProvider: real calls via litellm (Gemini/Groq/OpenAI/Anthropic/Ollama —
  the provider is encoded in the model string, e.g. "gemini/gemini-2.5-flash").
  Structured outputs are enforced by a parse -> validate -> repair-retry loop,
  which works across every provider regardless of native JSON-mode support.
- FakeProvider: deterministic offline provider used by tests and CI
  (FAKE_LLM=true). Control tokens in the prompt steer behavior:
      <<FORCE_FAIL>>   -> the judge returns a failing verdict
"""

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

import litellm
from pydantic import BaseModel, ValidationError

from app.llm.usage import CallUsage
from app.schemas.judge import DIMENSIONS, DimensionScore, JudgeVerdict
from app.schemas.plan import ResearchPlan, SubTask
from app.schemas.synthesis import CITATION_TOKEN, DraftReport, ReportSection

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when the model cannot produce schema-valid JSON after all retries."""


@dataclass
class StructuredResult(Generic[T]):
    value: T
    attempts: int
    usage: list[CallUsage] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(u.prompt_tokens + u.completion_tokens for u in self.usage)


def extract_json(text: str) -> str:
    """Pull the outermost JSON object out of an arbitrary model response."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unbalanced JSON object in model output")


class LLMProvider(Protocol):
    async def structured(
        self, schema: type[T], system: str, user: str, *, node: str, model: str | None = None
    ) -> StructuredResult[T]: ...


class LiteLLMProvider:
    """Provider-agnostic completion with schema-enforced outputs.

    Rate-limit aware: on transient provider errors (429/5xx/connection) calls
    back off exponentially — honoring a provider-supplied retry delay when
    present — and rotate through the configured fallback-model chain.
    """

    def __init__(self, *, default_model: str, temperature: float, max_tokens: int,
                 timeout_s: float, max_repair_retries: int,
                 fallback_models: list[str] | None = None,
                 backoff_base_s: float = 2.0) -> None:
        self.default_model = default_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.max_repair_retries = max_repair_retries
        self.fallback_models = fallback_models or []
        self.backoff_base_s = backoff_base_s

    def _model_chain(self, primary: str) -> list[str]:
        """Primary first, then configured fallbacks (deduped)."""
        chain = [primary]
        for m in self.fallback_models:
            if m and m not in chain:
                chain.append(m)
        return chain

    @staticmethod
    def _schema_hint(schema: type[BaseModel]) -> str:
        return json.dumps(schema.model_json_schema(), indent=2)

    async def structured(
        self, schema: type[T], system: str, user: str, *, node: str, model: str | None = None
    ) -> StructuredResult[T]:
        primary = model or self.default_model
        chain = self._model_chain(primary)
        sys_prompt = (
            f"{system}\n\n"
            "OUTPUT CONTRACT: Respond with a single JSON object and nothing else. "
            "No markdown fences, no commentary. It must validate against this JSON Schema:\n"
            f"{self._schema_hint(schema)}"
        )
        messages: list[dict] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ]
        usage_records: list[CallUsage] = []
        last_errors: list[str] = []

        total_attempts = self.max_repair_retries + 1
        for attempt in range(1, total_attempts + 1):
            chosen_model = chain[(attempt - 1) % len(chain)]
            t0 = time.monotonic()
            try:
                resp = await litellm.acompletion(
                    model=chosen_model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout_s,
                )
            except Exception as exc:  # transport/provider errors are retried too
                last_errors.append(
                    f"api_error attempt {attempt} [{chosen_model}]: {exc}")
                logger.warning("[%s] llm call failed (attempt %s/%s, model=%s): %s",
                               node, attempt, total_attempts, chosen_model, exc)
                if attempt < total_attempts:
                    next_model = chain[attempt % len(chain)]
                    await asyncio.sleep(self._backoff_seconds(
                        exc, attempt, same_model=next_model == chosen_model))
                continue
            latency_ms = int((time.monotonic() - t0) * 1000)

            usage_obj = getattr(resp, "usage", None)
            cu = CallUsage(
                node=node,
                model=chosen_model,
                prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
                cost_usd=self._safe_cost(resp),
                latency_ms=latency_ms,
            )
            usage_records.append(cu)

            raw = resp.choices[0].message.content or ""
            try:
                value = schema.model_validate_json(extract_json(raw))
                return StructuredResult(value=value, attempts=attempt, usage=usage_records)
            except (ValueError, ValidationError) as exc:
                err_summary = _summarize_validation_error(exc)
                last_errors.append(f"attempt {attempt}: {err_summary}")
                logger.warning("[%s] invalid structured output (attempt %s/%s): %s",
                               node, attempt, total_attempts, err_summary)
                messages.append({"role": "assistant", "content": raw[:8000]})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous output failed validation. Fix it and return ONLY the "
                        f"corrected JSON object. Validation errors:\n{err_summary}"
                    ),
                })

        raise StructuredOutputError(
            f"node={node} could not produce valid {schema.__name__} "
            f"after {total_attempts} attempts; errors={last_errors}"
        )

    def _backoff_seconds(self, exc: Exception, attempt: int, *,
                         same_model: bool) -> float:
        """Exponential backoff with jitter; honors provider retry hints.

        Same-model retries respect a 'Please retry in 52s' hint (capped) — the
        key is saturated and hammering it extends cooldowns. Switching to a
        fallback model skips the wait entirely: another provider's quota is
        unaffected.
        """
        if not same_model:
            return random.uniform(0.5, 1.5)
        exponential = min(self.backoff_base_s * (2 ** (attempt - 1)), 30.0)
        hint = re.search(
            r"retry\s*(?:in|after)\s*:?\s*([0-9]+(?:\.[0-9]+)?)\s*s",
            str(exc), re.IGNORECASE,
        )
        delay = max(exponential, float(hint.group(1)) if hint else 0.0)
        return min(delay, 60.0) * random.uniform(0.8, 1.2)

    @staticmethod
    def _safe_cost(resp) -> float:
        try:
            return float(litellm.completion_cost(completion_response=resp))
        except Exception:
            return 0.0  # unknown pricing (local ollama, brand-new models)


def _summarize_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        lines = [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return "; ".join(lines)[:2000]
    return str(exc)[:2000]


_TRANSIENT_ERROR_NAMES = {
    "RateLimitError", "APIConnectionError", "APIConnectionTimedOutError",
    "Timeout", "InternalServerError", "ServiceUnavailableError",
    "UnavailableError", "DeadlockError",
}


def _is_transient(exc: Exception) -> bool:
    """True for errors worth rotating models / backing off over (429, 5xx, network)."""
    if type(exc).__name__ in _TRANSIENT_ERROR_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


# ---------------------------------------------------------------------------
# Deterministic offline provider (tests / CI / keyless demo runs)
# ---------------------------------------------------------------------------


class FakeProvider:
    """Schema-aware canned responses. No network, fully deterministic.

    Behavior control for tests: include "<<FORCE_FAIL>>" anywhere in the user
    prompt to make judge calls return a failing verdict.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (node, user-prompt) history

    async def structured(
        self, schema: type[T], system: str, user: str, *, node: str, model: str | None = None
    ) -> StructuredResult[T]:
        self.calls.append((node, user))
        fake_usage = [CallUsage(node=node, model="fake", prompt_tokens=len(user) // 4,
                                completion_tokens=128, latency_ms=5)]
        value = self._build(schema, user)
        return StructuredResult(value=value, attempts=1, usage=fake_usage)

    def _build(self, schema: type[T], user: str):  # noqa: ANN202 - typed by caller generic
        name = schema.__name__
        question = _after_marker(user, "USER QUESTION:") or "the provided business question"
        evidence_ids = sorted(set(CITATION_TOKEN.findall(user))) or ["ev-web-001"]

        if name == "ResearchPlan":
            return ResearchPlan(
                objective=f"Determine: {question}",
                success_criteria=["Evidence-backed findings", "Actionable recommendation"],
                subtasks=[
                    SubTask(task_id="t1", description="External market signals",
                            search_query=_first_query(user) or question,
                            needs_web=True, needs_rag=False, needs_data=True),
                    SubTask(task_id="t2", description="Internal knowledge review",
                            search_query="internal analysis notes",
                            needs_web=False, needs_rag=True, needs_data=False),
                ],
            )

        if name == "DraftReport":
            cite = evidence_ids[:3]
            body = f"Analysis of '{question}' draws on " + ", ".join(f"[{c}]" for c in cite) + "."
            sections = [ReportSection(heading="Findings", body=body, citations=list(cite))]
            revision_note = None
            if "REVISION FEEDBACK:" in user:
                revision_note = "Addressed prior critique."
            return DraftReport(
                title=f"Assessment: {_truncate(question, 60)}",
                executive_summary=f"Deterministic draft answering: {question}",
                sections=sections,
                recommendation="Proceed with a scoped pilot.",
                confidence="medium",
                open_questions=["Confirm data recency."],
                revision_note=revision_note,
            )

        if name == "JudgeVerdict":
            force_fail = "<<FORCE_FAIL>>" in user
            dims = [
                DimensionScore(dimension=d, score=(4.0 if force_fail else 8.0), rationale="fake")
                for d in DIMENSIONS
            ]
            feedback = [] if not force_fail else [
                "Add more grounded evidence per claim.",
                "Sharpen the final recommendation.",
            ]
            overall = round(sum(d.score for d in dims) / len(dims), 2)
            return JudgeVerdict(passed=not force_fail, overall_score=overall,
                                dimensions=dims, feedback=feedback)

        raise NotImplementedError(f"FakeProvider has no builder for schema {name}")


def _after_marker(text: str, marker: str) -> str | None:
    idx = text.find(marker)
    if idx == -1:
        return None
    line = text[idx + len(marker):].strip().splitlines()
    return line[0].strip() if line else None


def _first_query(user: str) -> str | None:
    m = re.search(r'"search_query"\s*:\s*"([^"]+)"', user)
    return m.group(1) if m else None


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."
