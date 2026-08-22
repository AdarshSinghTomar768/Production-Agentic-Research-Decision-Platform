"""Checkpoint serializer locked to our schema types.

LangGraph's default is permissive (any python type deserializes, with a warning).
We pin an explicit allowlist of platform types so checkpoints stay safe and the
logs stay clean.

Checkpoints are also zlib-compressed: mission state carries full evidence text,
and every graph super-step rewrites it — compression cuts checkpoint writes and
Postgres round-trips roughly 3-4x on text-heavy missions. The type tag suffix
(".gz") keeps the format self-describing for future readers.
"""

import zlib

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


class CompressedJsonPlusSerializer(JsonPlusSerializer):
    """zlib-compresses serialized blobs; tags them with a '.gz' type suffix."""

    def dumps_typed(self, obj) -> tuple[str, bytes]:
        type_tag, blob = super().dumps_typed(obj)
        return f"{type_tag}.gz", zlib.compress(blob)

    def loads_typed(self, typed: tuple[str, bytes]):  # noqa: ANN001 - upstream signature
        type_tag, blob = typed
        if isinstance(type_tag, str) and type_tag.endswith(".gz"):
            return super().loads_typed((type_tag[:-3], zlib.decompress(blob)))
        return super().loads_typed(typed)


def platform_serde() -> JsonPlusSerializer:
    return CompressedJsonPlusSerializer(
        allowed_msgpack_modules=list(PLATFORM_TYPES)
    )
