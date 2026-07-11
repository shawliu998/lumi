from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class Phase(StrEnum):
    OBSERVE = "observe"
    DIAGNOSE = "diagnose"
    PROBE = "probe"
    TEACH = "teach"
    VERIFY = "verify"
    UPDATE = "update"
    REFLECT = "reflect"
    COMPLETE = "complete"


class RunStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


PHASE_ORDER = (
    Phase.OBSERVE,
    Phase.DIAGNOSE,
    Phase.PROBE,
    Phase.TEACH,
    Phase.VERIFY,
    Phase.UPDATE,
    Phase.REFLECT,
)


@dataclass(slots=True)
class AgentState:
    learner_id: str
    domain: str
    goal: str
    run_id: str = field(default_factory=lambda: uuid4().hex)
    phase: Phase = Phase.OBSERVE
    status: RunStatus = RunStatus.READY
    cycle: int = 1
    max_cycles: int = 2
    step_count: int = 0
    max_steps: int = 32
    context: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_error: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")
        if self.max_steps < len(PHASE_ORDER):
            raise ValueError("max_steps must permit at least one full cycle")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase"] = self.phase.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentState":
        data = dict(value)
        data["phase"] = Phase(data["phase"])
        data["status"] = RunStatus(data["status"])
        return cls(**data)

    def append_artifact(self, phase: Phase, artifact: Mapping[str, Any]) -> None:
        self.artifacts.setdefault(phase.value, []).append(dict(artifact))
