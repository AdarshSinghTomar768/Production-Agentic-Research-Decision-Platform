"""Checkpoint serde: compression round-trip + backwards compatibility."""

from app.graph.serde import platform_serde
from app.schemas.plan import ResearchPlan, SubTask


def _sample_plan() -> ResearchPlan:
    return ResearchPlan(
        objective="Assess the migration risk",
        success_criteria=["Evidence-backed", "Actionable"],
        subtasks=[
            SubTask(task_id="t1", description="web", search_query="q1",
                    needs_web=True, needs_rag=False, needs_data=False),
            SubTask(task_id="t2", description="rag", search_query="internal notes",
                    needs_web=False, needs_rag=True, needs_data=False),
        ],
    )


def test_roundtrip_compresses_and_restores():
    serde = platform_serde()
    type_tag, blob = serde.dumps_typed(_sample_plan())

    assert type_tag.endswith(".gz")          # self-describing compressed format
    restored = serde.loads_typed((type_tag, blob))
    assert restored == _sample_plan()


def test_compression_actually_shrinks_text_heavy_state():
    """The whole point: evidence-heavy state should get meaningfully smaller."""
    plan = _sample_plan()
    filler = "distribution center operational details " * 500  # ~23KB of text
    plan.subtasks[0].description = filler

    serde = platform_serde()
    _, blob = serde.dumps_typed(plan)
    _, raw = __import__("langgraph.checkpoint.serde.jsonplus",
                        fromlist=["JsonPlusSerializer"]).JsonPlusSerializer().dumps_typed(plan)

    assert len(blob) < len(raw) / 3


def test_loads_uncompressed_legacy_blobs():
    """Checkpoints written before compression must still load."""
    legacy = platform_serde().__class__.__mro__[1]()  # plain JsonPlusSerializer
    type_tag, blob = legacy.dumps_typed(_sample_plan())
    assert not type_tag.endswith(".gz")

    serde = platform_serde()
    assert serde.loads_typed((type_tag, blob)) == _sample_plan()
