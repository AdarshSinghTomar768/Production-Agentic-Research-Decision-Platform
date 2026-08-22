"""Evaluation harness: runs the full mission pipeline per golden case, then
scores the final report with an independent judge pass and aggregates metrics."""

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.graph import MissionOrchestrator
from app.llm.provider import LLMProvider
from app.schemas.judge import DIMENSIONS, JudgeVerdict
from app.schemas.mission import EvalCaseResult, EvalRunSummary

logger = logging.getLogger(__name__)

GOLDEN_SET = Path(__file__).parent / "golden_set.jsonl"

SCORING_SYSTEM = """\
You are an independent evaluator grading decision reports produced by a research
system. Score ONLY what is written, on five dimensions (0-10 each):
coverage, grounding, actionability, risk_awareness, clarity.
Grounding means claims are tied to explicit [ev-*] citations. Be strict;
average professional work is a 6. Additional rubric emphasis for this case
is provided and must weight your coverage/actionability scores.
"""


def load_golden_set(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or GOLDEN_SET
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cases.append(json.loads(line))
    return cases


class EvalHarness:
    def __init__(self, orchestrator: MissionOrchestrator, provider: LLMProvider, *,
                 judge_model: str, pass_threshold: float = 7.0) -> None:
        self.orchestrator = orchestrator
        self.provider = provider
        self.judge_model = judge_model
        self.pass_threshold = pass_threshold

    async def _drive_to_completion(self, question: str):
        outcome = await self.orchestrator.start_mission(question)
        resumes = 0
        while outcome.status.value == "pending_approval" and resumes < 5:
            outcome = await self.orchestrator.resume_mission(
                outcome.mission_id, approved=True)
            resumes += 1
        return outcome

    async def _score(self, case: dict[str, Any], report) -> JudgeVerdict:
        focus = "\n".join(f"- {f}" for f in case.get("rubric_focus", []))
        user = (
            f"CASE QUESTION:\n{case['question']}\n\n"
            f"RUBRIC EMPHASIS:\n{focus or '(none)'}\n\n"
            f"REPORT TO GRADE:\n{report.model_dump_json(indent=2)}"
        )
        result = await self.provider.structured(
            JudgeVerdict, SCORING_SYSTEM, user,
            node="eval_scorer", model=self.judge_model,
        )
        verdict = result.value
        avg = sum(d.score for d in verdict.dimensions) / len(DIMENSIONS)
        return verdict.model_copy(update={"overall_score": round(avg, 2),
                                          "passed": avg >= self.pass_threshold})

    async def run_case(self, case: dict[str, Any]) -> tuple[EvalCaseResult, dict[str, Any]]:
        t0 = time.monotonic()
        outcome = await self._drive_to_completion(case["question"])
        notes: list[str] = []

        report = outcome.final_report
        if report is None:
            notes.append(f"pipeline ended in status={outcome.status.value}: {outcome.error}")
            return (
                EvalCaseResult(case_id=case["id"], question=case["question"],
                               overall_score=0.0, passed_judge=False,
                               dimensions={}, notes=notes),
                {"wall_time_ms": int((time.monotonic() - t0) * 1000), "telemetry": {}},
            )

        cited = set()
        for s in report.sections:
            cited.update(s.citations)
        source_ids = {s.evidence_id for s in report.sources}
        phantom = cited - source_ids
        if phantom:
            notes.append(f"citations not backed by sources: {sorted(phantom)}")

        missing = [kw for kw in case.get("must_address_keywords", [])
                   if kw.lower() not in report.model_dump_json().lower()]
        if missing:
            notes.append(f"keywords never addressed: {missing}")

        verdict = await self._score(case, report)
        dims = {d.dimension: d.score for d in verdict.dimensions}
        telemetry = {
            "revisions": outcome.revision_count,
            "evidence_chunks": outcome.telemetry.get("evidence_chunks"),
            "llm_calls": outcome.telemetry.get("llm_calls"),
            "prompt_tokens": outcome.telemetry.get("prompt_tokens"),
            "completion_tokens": outcome.telemetry.get("completion_tokens"),
            "cost_usd": outcome.telemetry.get("cost_usd"),
        }
        return (
            EvalCaseResult(
                case_id=case["id"], question=case["question"],
                overall_score=verdict.overall_score, passed_judge=verdict.passed,
                dimensions=dims, notes=notes + verdict.feedback[:3],
            ),
            {"wall_time_ms": int((time.monotonic() - t0) * 1000), "telemetry": telemetry},
        )

    async def run_suite(self, cases: list[dict[str, Any]], *, fake_llm: bool) -> tuple[
            EvalRunSummary, dict[str, Any], str]:
        """Returns (summary, raw_details, printable_report)."""
        results: list[EvalCaseResult] = []
        details: list[dict[str, Any]] = []
        for case in cases:
            logger.info("[eval] running case %s", case["id"])
            res, extra = await self.run_case(case)
            results.append(res)
            details.append({"case_id": res.case_id, **extra,
                            "notes": res.notes, "dimensions": res.dimensions})

        dims_matrix = [r.dimensions for r in results]
        mean_overall = round(sum(r.overall_score for r in results) / max(len(results), 1), 2)
        pass_rate = round(sum(1 for r in results if r.passed_judge) / max(len(results), 1), 2)

        summary = EvalRunSummary(
            run_id=f"eval-{int(time.time())}",
            cases=results,
            mean_overall=mean_overall,
            mean_pass_rate=pass_rate,
            fake_llm=fake_llm,
        )
        printable = render_summary(summary, dims_matrix, details)
        return summary, details, printable


def render_summary(summary: EvalRunSummary, dims_matrix: list[dict],
                   details: list[dict]) -> str:
    lines: list[str] = []
    lines.append("=" * 74)
    lines.append("EVALUATION RUN SUMMARY".center(74))
    lines.append("=" * 74)
    header = f"{'case':<18}{'overall':>8}{'pass':>6}{'rev':>5}{'evd':>5}{'llmcalls':>9}{'cost$':>10}"
    lines.append(header)
    lines.append("-" * 74)
    for r, d in zip(summary.cases, details, strict=True):
        tel = d.get("telemetry") or {}
        cost = tel.get("cost_usd") or 0.0
        lines.append(
            f"{r.case_id:<18}{r.overall_score:>8.2f}"
            f"{'PASS' if r.passed_judge else 'FAIL':>6}"
            f"{tel.get('revisions', 0):>5}{tel.get('evidence_chunks') or 0:>5}"
            f"{tel.get('llm_calls') or 0:>9}{cost:>10.4f}"
        )
    lines.append("-" * 74)
    if dims_matrix:
        dim_names = sorted({k for m in dims_matrix for k in m})
        for name in dim_names:
            vals = [m[name] for m in dims_matrix if name in m]
            if vals:
                lines.append(f"  {name:<16} mean {sum(vals) / len(vals):.2f}")
    lines.append("-" * 74)
    total_cost = sum((d.get("telemetry") or {}).get("cost_usd") or 0.0 for d in details)
    tokens_in = sum((d.get("telemetry") or {}).get("prompt_tokens") or 0 for d in details)
    tokens_out = sum((d.get("telemetry") or {}).get("completion_tokens") or 0 for d in details)
    wall = sum(d.get("wall_time_ms", 0) for d in details)
    lines.append(f"mean_overall={summary.mean_overall}  pass_rate={summary.mean_pass_rate}")
    lines.append(f"tokens(in/out)={tokens_in}/{tokens_out}  llm_cost=${total_cost:.4f}  "
                 f"total_wall_ms={wall}  fake_llm={summary.fake_llm}")
    lines.append("=" * 74)
    notes_all = [(c.case_id, n) for c in summary.cases for n in c.notes]
    if notes_all:
        lines.append("notes:")
        lines.extend(f"  [{cid}] {n}" for cid, n in notes_all[:12])
    return "\n".join(lines)
