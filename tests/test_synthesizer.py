"""Synthesizer prompt budgeting: evidence caps + slim revision passes."""

from types import SimpleNamespace

from app.agents.synthesizer import SynthesizerAgent
from app.schemas.evidence import EvidenceChunk, EvidenceSource
from app.schemas.plan import ResearchPlan, SubTask
from app.schemas.synthesis import DraftReport, ReportSection


def _chunk(eid: str) -> EvidenceChunk:
    return EvidenceChunk(
        evidence_id=eid,
        source=EvidenceSource.WEB,
        title=f"Title {eid}",
        url="https://example.com/x",
        content="X" * 5000,
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        objective="obj",
        success_criteria=["c1"],
        subtasks=[SubTask(task_id="t1", description="d", search_query="q",
                          needs_web=True, needs_rag=False, needs_data=False)],
    )


def _draft(eid: str = "ev-web-001") -> DraftReport:
    return DraftReport(
        title="T", executive_summary="S",
        sections=[ReportSection(heading="H", body=f"Claim [{eid}].",
                                citations=[eid])],
        recommendation="R", confidence="medium",
    )


class _CapturingProvider:
    """Records the user prompt; returns a fixed draft regardless of input."""

    def __init__(self, draft: DraftReport):
        self.draft = draft
        self.users: list[str] = []

    async def structured(self, schema, system, user, *, node, model=None):
        self.users.append(user)
        return SimpleNamespace(value=self.draft, usage=[], attempts=1)


async def test_first_draft_includes_capped_evidence_bodies():
    provider = _CapturingProvider(_draft())
    agent = SynthesizerAgent(provider, max_evidence_chars=120)

    await agent.run("q?", _plan(), [_chunk("ev-web-001"), _chunk("ev-web-002")])

    user = provider.users[0]
    assert "EVIDENCE POOL (2 chunks)" in user
    assert "X" * 120 in user            # body present up to the cap...
    assert "X" * 121 not in user        # ...and never beyond it


async def test_revision_pass_sends_index_not_bodies():
    provider = _CapturingProvider(_draft())
    agent = SynthesizerAgent(provider, max_evidence_chars=120)
    prior = _draft()

    await agent.run("q?", _plan(), [_chunk("ev-web-001"), _chunk("ev-web-002")],
                    critique=_verdict(), prior_draft=prior)

    user = provider.users[0]
    assert "EVIDENCE INDEX" in user
    assert "ev-web-002 | web | Title ev-web-002" in user  # ids stay visible
    assert "XXXXX" not in user                            # no bodies at all
    assert "REVISION FEEDBACK" in user and "PRIOR DRAFT" in user


def _verdict():
    from app.schemas.judge import DimensionScore, JudgeVerdict

    return JudgeVerdict(
        dimensions=[DimensionScore(dimension=d, score=6, rationale="meh")
                    for d in ("coverage", "grounding", "actionability",
                              "risk_awareness", "clarity")],
        overall_score=6.0,
        passed=False,
        feedback=["tighten section 2"],
        citation_issues=[],
    )
