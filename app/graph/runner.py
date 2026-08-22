"""Mission execution: durable start/resume around the compiled graph."""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from app.graph.builder import Services, build_graph
from app.graph.state import snapshot_telemetry
from app.llm.guardrails import GuardrailViolation
from app.schemas.mission import MissionStatus
from app.schemas.report import FinalReport

logger = logging.getLogger(__name__)


@dataclass
class MissionOutcome:
    mission_id: str
    status: MissionStatus
    final_report: FinalReport | None = None
    error: str | None = None
    interrupt_payload: Any | None = None
    plan: Any | None = None
    revision_count: int = 0
    telemetry: dict[str, Any] = field(default_factory=dict)
    usage_events: list[dict] = field(default_factory=list)   # CallUsage dicts
    agent_runs: list[dict] = field(default_factory=list)

    @classmethod
    def from_snapshot(cls, mission_id: str, snap: dict[str, Any]) -> "MissionOutcome":
        interrupts = snap.get("__interrupt__")
        if interrupts:
            payload = getattr(interrupts[0], "value", None)
            return cls(
                mission_id=mission_id,
                status=MissionStatus.PENDING_APPROVAL,
                interrupt_payload=payload,
                plan=snap.get("plan"),
                revision_count=snap.get("revision_count", 0),
                telemetry=snapshot_telemetry(snap),
                usage_events=list(snap.get("usage", [])),
                agent_runs=list(snap.get("agent_runs", [])),
            )
        report = snap.get("final_report")
        return cls(
            mission_id=mission_id,
            status=MissionStatus.COMPLETED if report else MissionStatus.FAILED,
            final_report=report,
            error=None if report else "graph finished without a final report",
            plan=snap.get("plan"),
            revision_count=snap.get("revision_count", 0),
            telemetry=snapshot_telemetry(snap),
            usage_events=list(snap.get("usage", [])),
            agent_runs=list(snap.get("agent_runs", [])),
        )


class MissionOrchestrator:
    """Owns one compiled graph. Checkpointer makes interrupts durable."""

    def __init__(self, services: Services, checkpointer: Any) -> None:
        from app.graph.serde import platform_serde

        self.services = services
        checkpointer.serde = platform_serde()
        self._graph = build_graph(services, checkpointer)

    def _config(self, mission_id: str) -> dict:
        return {"configurable": {"thread_id": f"mission-{mission_id}"}}

    async def start_mission(self, question: str, *, mission_id: str | None = None) -> MissionOutcome:
        mission_id = mission_id or str(uuid.uuid4())
        init: dict[str, Any] = {
            "mission_id": mission_id,
            "question": question,
            "web_evidence": [],
            "rag_evidence": [],
            "data_evidence": [],
            "verdict_history": [],
            "usage": [],
            "agent_runs": [],
            "revision_count": 0,
            "guardrail_blocked": False,
        }
        try:
            snap = await self._graph.ainvoke(init, self._config(mission_id))
        except GuardrailViolation as exc:
            logger.warning("[orchestrator] mission %s blocked: %s", mission_id, exc.reason)
            return MissionOutcome(
                mission_id=mission_id,
                status=MissionStatus.GUARDRAIL_BLOCKED,
                error=exc.reason,
            )
        except Exception as exc:
            logger.exception("[orchestrator] mission %s failed", mission_id)
            return MissionOutcome(mission_id=mission_id, status=MissionStatus.FAILED,
                                  error=f"{type(exc).__name__}: {exc}")
        outcome = MissionOutcome.from_snapshot(mission_id, snap)
        self._log_summary(outcome)
        return outcome

    async def resume_mission(self, mission_id: str, *, approved: bool,
                             feedback: str | None = None) -> MissionOutcome:
        cmd = Command(resume={"approved": approved, "feedback": feedback})
        try:
            snap = await self._graph.ainvoke(cmd, self._config(mission_id))
        except GuardrailViolation as exc:
            return MissionOutcome(mission_id=mission_id,
                                  status=MissionStatus.GUARDRAIL_BLOCKED, error=exc.reason)
        except Exception as exc:
            logger.exception("[orchestrator] mission %s failed on resume", mission_id)
            return MissionOutcome(mission_id=mission_id, status=MissionStatus.FAILED,
                                  error=f"{type(exc).__name__}: {exc}")
        outcome = MissionOutcome.from_snapshot(mission_id, snap)
        self._log_summary(outcome, resumed=True)
        return outcome

    @staticmethod
    def _log_summary(outcome: MissionOutcome, *, resumed: bool = False) -> None:
        t = outcome.telemetry
        logger.info(
            "[mission %s] %s%s | revisions=%s evidence=%s llm_calls=%s "
            "tokens(p/c)=%s/%s cost=$%.6f node_latency_ms=%s",
            outcome.mission_id[:8], outcome.status.value,
            " (resumed)" if resumed else "",
            t.get("revision_count"), t.get("evidence_chunks"), t.get("llm_calls"),
            t.get("prompt_tokens"), t.get("completion_tokens"),
            t.get("cost_usd", 0.0), t.get("node_latency_ms"),
        )
