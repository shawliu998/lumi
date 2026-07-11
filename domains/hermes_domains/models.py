from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ScoreObservation:
    """A reproducible scoring fact, never an inferred mental state."""

    observation_id: str
    kind: str
    value: Any
    evidence: str


@dataclass(frozen=True)
class CauseCandidate:
    """An explicitly unconfirmed explanation requiring a later probe."""

    cause_id: str
    label: str
    probability: float
    prior: float
    evidence_ids: tuple[str, ...]
    status: str = "unconfirmed_hypothesis"
    is_ground_truth: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.probability <= 1 or not 0 <= self.prior <= 1:
            raise ValueError("candidate probabilities must be in [0, 1]")
        if self.status != "unconfirmed_hypothesis" or self.is_ground_truth:
            raise ValueError("low-cost diagnosis cannot assert a true cause")


@dataclass(frozen=True)
class ScoreResult:
    fixture_id: str
    domain: str
    score: float
    max_score: float
    passed: bool
    observations: tuple[ScoreObservation, ...]
    cause_candidates: tuple[CauseCandidate, ...]
    adapter_version: str = "deterministic-domain-adapters-v1"

    def to_dict(self) -> Mapping[str, Any]:
        return asdict(self)
