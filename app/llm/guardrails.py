"""Guardrails: input screening (injection heuristics) and output verification
(citation grounding). Both are deterministic code, not model judgment."""

import logging
import re

from app.schemas.synthesis import CITATION_TOKEN, DraftReport

logger = logging.getLogger(__name__)


class GuardrailViolation(Exception):
    """Raised when user input fails safety screening."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# Heuristic patterns for the most common direct-injection attempts. This is a
# speed bump, not a fortress — the real defense is that every agent's outputs
# are schema-constrained and every claim must cite retrieved evidence.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|prompts|rules)",
        r"disregard\s+(all\s+|any\s+)?(previous|prior|your)\s+(instructions|prompts|rules)",
        r"reveal\s+(your\s+)?(system\s+prompt|instructions|rules)",
        r"print\s+(your\s+)?(system\s+prompt|instructions)",
        r"you\s+are\s+now\s+(a|an|the)\s+",
        r"enter\s+(developer|god|admin|sudo)\s+mode",
        r"jailbreak",
        r"repeat\s+(everything|the text)\s+(above|before)",
    )
]

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_question(question: str) -> str:
    return _CONTROL_CHARS.sub(" ", question).strip()


def check_user_question(question: str) -> str:
    """Validate + sanitize a user-submitted question.

    Returns the sanitized question; raises GuardrailViolation when blocked.
    """
    q = sanitize_question(question)
    if len(q) < 10:
        raise GuardrailViolation("Question too short (min 10 characters after sanitization).")
    if len(q) > 4000:
        raise GuardrailViolation("Question too long (max 4000 characters).")
    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(q)
        if m:
            raise GuardrailViolation(
                f"Potential prompt injection detected near {m.group(0)!r}; request blocked."
            )
    return q


# ---------------------------------------------------------------------------
# Citation verification (output guardrail)
# ---------------------------------------------------------------------------

_BRACKET_GROUP = re.compile(r"\[([^\[\]]*)\]")


def _clean_body(body: str, valid_ids: set[str], removed: set[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        ids = CITATION_TOKEN.findall(inner)
        if not ids:
            return m.group(0)  # ordinary bracketed text, leave alone
        kept = [i for i in ids if i in valid_ids]
        bad = [i for i in ids if i not in valid_ids]
        removed.update(bad)
        if not kept:
            return ""
        if bad:
            return "[" + ", ".join(kept) + "]"
        return m.group(0)

    out = _BRACKET_GROUP.sub(repl, body)
    # collapse whitespace artifacts left by removed citations
    out = re.sub(r"[ \t]{2,}", " ", out).replace(" .", ".").strip()
    return out


def verify_citations(draft: DraftReport, valid_ids: set[str]) -> tuple[DraftReport, list[str]]:
    """Strip any citation markers that don't reference real evidence.

    Returns (cleaned_draft, removed_ids). The platform never ships a report
    citing evidence it does not hold.
    """
    removed: set[str] = set()
    changed = False
    new_sections = []
    for section in draft.sections:
        body = _clean_body(section.body, valid_ids, removed)
        clean_cites = [c for c in section.citations if c in valid_ids]
        if body != section.body or clean_cites != section.citations:
            changed = True
        new_sections.append(
            section.model_copy(update={"body": body, "citations": sorted(set(clean_cites))})
        )

    cleaned = draft.model_copy(update={"sections": new_sections})
    if removed:
        logger.warning("citation guardrail stripped ungrounded references: %s", sorted(removed))
        note = f"Citation guardrail removed ungrounded references: {sorted(removed)}."
        cleaned.revision_note = (
            f"{draft.revision_note} {note}".strip() if draft.revision_note else note
        )
    elif changed:
        logger.info("citation guardrail normalized citation markers")
    return cleaned, sorted(removed)
