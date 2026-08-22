import pytest
from pydantic import ValidationError

from app.schemas.evidence import EvidenceChunk, make_evidence_id
from app.schemas.judge import JudgeVerdict
from app.schemas.plan import ResearchPlan, SubTask
from app.schemas.synthesis import DraftReport, ReportSection


def _subtask(i: int = 1) -> SubTask:
    return SubTask(task_id=f"t{i}", description="d", search_query="q")


class TestPlan:
    def test_valid_plan(self):
        plan = ResearchPlan(objective="o", success_criteria=["c"],
                            subtasks=[_subtask(1), _subtask(2)])
        assert len(plan.subtasks) == 2

    def test_duplicate_task_ids_rejected(self):
        with pytest.raises(ValidationError):
            ResearchPlan(objective="o", success_criteria=["c"],
                         subtasks=[_subtask(), _subtask()])

    def test_bad_task_id_format(self):
        with pytest.raises(ValidationError):
            SubTask(task_id="task-9", description="d", search_query="q")

    def test_too_many_subtasks(self):
        with pytest.raises(ValidationError):
            ResearchPlan(objective="o", success_criteria=["c"],
                         subtasks=[_subtask(i) for i in range(1, 10)])


class TestEvidence:
    def test_id_pattern_enforced(self):
        with pytest.raises(ValidationError):
            EvidenceChunk(evidence_id="web-1", source="web", title="t", content="c")
        assert make_evidence_id.__doc__ is None  # import sanity

    def test_empty_content_rejected(self):
        with pytest.raises(ValidationError):
            EvidenceChunk(evidence_id="ev-web-001", source="web", title="t", content="   ")


class TestDraft:
    def test_citations_derived_from_body(self):
        s = ReportSection(heading="h", body="X [ev-web-001].",
                          citations=[])  # forgot to declare
        assert s.citations == ["ev-web-001"]

    def test_all_citations_union(self):
        d = DraftReport(
            title="t", executive_summary="s",
            sections=[
                ReportSection(heading="a", body="[ev-web-001]", citations=["ev-web-001"]),
                ReportSection(heading="b", body="[ev-rag-002]", citations=["ev-rag-002"]),
            ],
            recommendation="r", confidence="high",
        )
        assert d.all_citations() == {"ev-web-001", "ev-rag-002"}


class TestVerdict:
    @staticmethod
    def _dims(scores) -> list[dict]:
        names = ["coverage", "grounding", "actionability", "risk_awareness", "clarity"]
        return [{"dimension": n, "score": s, "rationale": "r"}
                for n, s in zip(names, scores, strict=False)]

    def test_unknown_dimension_rejected(self):
        dims = self._dims([8] * 5)
        dims[0]["dimension"] = "vibes"
        with pytest.raises(ValidationError):
            JudgeVerdict(passed=True, overall_score=8.0, dimensions=dims)

    def test_wrong_dimension_count_rejected(self):
        with pytest.raises(ValidationError):
            JudgeVerdict(passed=True, overall_score=8.0, dimensions=self._dims([8] * 4))

    def test_score_bounds(self):
        dims = self._dims([11, 8, 8, 8, 8])
        with pytest.raises(ValidationError):
            JudgeVerdict(passed=True, overall_score=8.0, dimensions=dims)
