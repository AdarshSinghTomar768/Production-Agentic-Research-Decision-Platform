"""Critic / LLM-as-a-Judge: rubric scoring with code-enforced pass policy."""

import json

from app.llm.provider import LLMProvider
from app.llm.usage import AgentUsage
from app.schemas.judge import DIMENSIONS, JudgeVerdict
from app.schemas.synthesis import DraftReport

SYSTEM = """\
You are a ruthless but fair quality judge for research reports.

Score the draft on five dimensions, each 0-10:
- coverage: does it address every success criterion of the plan?
- grounding: are substantive claims supported by inline [ev-*] citations
  that exist in the evidence id list? Uncited claims count against you.
- actionability: is the recommendation specific enough to execute?
- risk_awareness: are risks, unknowns and open questions acknowledged?
- clarity: concise, structured, executive-ready prose?

Then set feedback: concrete, prioritized fixes (empty only if flawless).
Set passed=true ONLY if the draft is genuinely shippable; the platform
enforces its own threshold on top of your scores.
"""


class CriticAgent:
    name = "critic"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        pass_threshold: float = 7.0,
        dimension_floor: float = 5.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.pass_threshold = pass_threshold
        self.dimension_floor = dimension_floor

    async def run(
        self,
        question: str,
        draft: DraftReport,
        valid_evidence_ids: set[str],
        *,
        force_fail_token: str | None = None,
    ) -> tuple[JudgeVerdict, AgentUsage]:
        usage = AgentUsage(self.name)
        user_parts = [
            f"USER QUESTION:\n{question}",
            f"\nVALID EVIDENCE IDS:\n{json.dumps(sorted(valid_evidence_ids))}",
            f"\nDRAFT TO JUDGE:\n{draft.model_dump_json(indent=2)}",
        ]
        if force_fail_token:
            user_parts.append(f"\n{force_fail_token}")
        result = await self.provider.structured(
            JudgeVerdict, SYSTEM, "\n".join(user_parts), node=self.name, model=self.model
        )
        verdict = result.value
        for u in result.usage:
            usage.add(u)
        return self._enforce_policy(verdict, draft, valid_evidence_ids), usage

    def _enforce_policy(
        self, verdict: JudgeVerdict, draft: DraftReport, valid_ids: set[str]
    ) -> JudgeVerdict:
        """Code-side policy: the model advises, deterministic rules decide."""
        issues: list[str] = []
        cited = draft.all_citations()
        phantom = cited - valid_ids
        if phantom:
            issues.append(f"draft cites non-existent evidence ids: {sorted(phantom)}")
        if not cited & valid_ids:
            issues.append("draft contains no citations to real evidence")

        avg = sum(d.score for d in verdict.dimensions) / len(DIMENSIONS)
        below_floor = [d.dimension for d in verdict.dimensions if d.score < self.dimension_floor]

        passed = (
            avg >= self.pass_threshold
            and not below_floor
            and not issues
        )

        feedback = list(verdict.feedback)
        for issue in issues:
            feedback.insert(0, issue)
        for dim in below_floor:
            feedback.append(
                f"Dimension '{dim}' scored below floor "
                f"({self.dimension_floor}); strengthen it."
            )
        if not passed and not feedback:
            feedback.append(
                f"Overall {avg:.1f} is under the pass threshold ({self.pass_threshold}); revise."
            )

        return verdict.model_copy(
            update={
                "passed": passed,
                "overall_score": round(avg, 2),
                "citation_issues": issues + list(verdict.citation_issues),
                "feedback": feedback[:8],
            }
        )
