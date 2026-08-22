"""Checkpoint serializer locked to our schema types.

LangGraph's default is permissive (any python type deserializes, with a warning).
We pin an explicit allowlist of platform types so checkpoints stay safe and the
logs stay clean.
"""

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.schemas.evidence import Citation, EvidenceChunk, EvidenceSource
from app.schemas.judge import DimensionScore, JudgeVerdict
from app.schemas.plan import ResearchPlan, SubTask
from app.schemas.report import FinalReport
from app.schemas.synthesis import DraftReport, ReportSection

PLATFORM_TYPES: list[type] = [
    Citation,
    DimensionScore,
    DraftReport,
    EvidenceChunk,
    EvidenceSource,
    FinalReport,
    JudgeVerdict,
    ReportSection,
    ResearchPlan,
    SubTask,
]


def platform_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=list(PLATFORM_TYPES))
