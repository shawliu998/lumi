from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, lower: float = 1e-6, upper: float = 1 - 1e-6) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class CausePrior:
    cause_id: str
    probability: float
    cohort_id: str
    sample_size: int
    source_version: str

    def __post_init__(self) -> None:
        if not 0 <= self.probability <= 1:
            raise ValueError("cause prior probability must be in [0, 1]")
        if self.sample_size < 0:
            raise ValueError("sample_size cannot be negative")


@dataclass(frozen=True)
class LearnerCauseHistory:
    counts: Mapping[str, float] = field(default_factory=dict)
    exposure_count: int = 0
    source_version: str = "learner-history-v1"


@dataclass(frozen=True)
class AttemptEvidence:
    attempt_id: str
    learner_id: str
    item_id: str
    item_type: str
    correct: bool
    response_time_seconds: float
    confidence: float | None = None
    selected_option: str | None = None
    hints_used: int = 0
    independently_answered: bool = True
    observed_at: str = field(default_factory=utc_now)
    # P(feature evidence | cause). Values need not sum to one.
    cause_likelihoods: Mapping[str, float] = field(default_factory=dict)
    evidence_features: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.response_time_seconds < 0:
            raise ValueError("response_time_seconds cannot be negative")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if self.hints_used < 0:
            raise ValueError("hints_used cannot be negative")
        if any(value < 0 for value in self.cause_likelihoods.values()):
            raise ValueError("cause likelihoods cannot be negative")

    def provenance(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "item_id": self.item_id,
            "item_type": self.item_type,
            "observed_at": self.observed_at,
            "selected_option": self.selected_option,
            "response_time_seconds": self.response_time_seconds,
            "confidence": self.confidence,
            "hints_used": self.hints_used,
            "independently_answered": self.independently_answered,
            "features": dict(self.evidence_features),
        }


@dataclass(frozen=True)
class CauseHypothesis:
    cause_id: str
    probability: float
    cohort_component: float
    learner_component: float
    evidence_likelihood: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosisResult:
    attempt_id: str
    hypotheses: tuple[CauseHypothesis, ...]
    uncertainty: float
    provenance: Mapping[str, Any]
    model_version: str = "hierarchical-cause-baseline-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillParameters:
    skill_id: str
    bkt_learn: float = 0.12
    bkt_guess: float = 0.20
    bkt_slip: float = 0.10
    pfa_intercept: float = -0.7
    pfa_success_weight: float = 0.35
    pfa_failure_weight: float = -0.25
    ensemble_weights: tuple[float, float, float] = (0.50, 0.30, 0.20)

    def __post_init__(self) -> None:
        for name in ("bkt_learn", "bkt_guess", "bkt_slip"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if len(self.ensemble_weights) != 3 or any(x < 0 for x in self.ensemble_weights):
            raise ValueError("ensemble_weights must contain three non-negative values")
        if sum(self.ensemble_weights) <= 0:
            raise ValueError("ensemble_weights must have positive total weight")


@dataclass(frozen=True)
class SkillState:
    learner_id: str
    skill_id: str
    bkt_mastery: float = 0.30
    successes: float = 0.0
    failures: float = 0.0
    irt_theta: float = 0.0
    evidence_count: int = 0
    mastery: float = 0.30
    uncertainty: float = 1.0
    last_updated_at: str | None = None
    provenance: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.bkt_mastery <= 1 or not 0 <= self.mastery <= 1:
            raise ValueError("mastery values must be in [0, 1]")
        if self.successes < 0 or self.failures < 0 or self.evidence_count < 0:
            raise ValueError("practice counts cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    intervention_id: str
    pre_mastery: float
    post_mastery: float
    mastery_gain: float
    independently_verified: bool
    effective: bool | None
    reason: str
    provenance: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
