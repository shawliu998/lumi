from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable


FIXED_SESSION_SIZE = 8
NEAR_TRANSFER_MIN_GAP = 2
NEAR_TRANSFER_MAX_GAP = 4
DELAYED_VALIDATION_HOURS = 24


class PracticePolicyError(RuntimeError):
    """Base error raised by the deterministic practice policy."""


class InvalidTransition(PracticePolicyError):
    """Raised when a state machine transition is not allowed."""


class InvalidSubmission(PracticePolicyError):
    """Raised when an answer or its trusted scoring metadata is invalid."""


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class SessionStatus(_StringEnum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    ENDED_EARLY = "ended_early"


class QuestionRole(_StringEnum):
    PRACTICE = "practice"
    NEAR_TRANSFER = "near_transfer"
    DELAYED_VALIDATION = "delayed_validation"
    PROBE = "probe"


class RecommendationAction(_StringEnum):
    SERVE_QUESTION = "serve_question"
    CONTINUE = "continue"
    LIGHT_FEEDBACK = "light_feedback"
    SHOW_MICRO_TUTORIAL = "show_micro_tutorial"
    SHOW_PROBE = "show_probe"
    VALIDATION_SCHEDULED = "validation_scheduled"
    END_SESSION = "end_session"
    NO_ELIGIBLE_QUESTION = "no_eligible_question"


class HypothesisStatus(_StringEnum):
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    REPEATED_ERROR_OBSERVED = "repeated_error_observed"
    AWAITING_DISAMBIGUATION = "awaiting_disambiguation"
    SUPPORTED = "supported_hypothesis"
    AWAITING_TRANSFER = "awaiting_transfer_validation"
    WEAKENED_BY_TRANSFER = "weakened_by_transfer"
    PERSISTENT_OR_RECURRENT = "persistent_or_recurrent"
    RESOLVED_AFTER_VALIDATION = "resolved_after_validation"
    WITHDRAWN = "hypothesis_withdrawn"
    VOIDED = "voided"


class ValidationKind(_StringEnum):
    NEAR_TRANSFER = "near_transfer"
    DELAYED = "delayed"


class ValidationStatus(_StringEnum):
    SCHEDULED = "scheduled"
    ELIGIBLE = "eligible"
    PRESENTED = "presented"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    VOIDED = "voided"


class PerformanceStatus(_StringEnum):
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    ONE_INDEPENDENT_SUCCESS = "one_independent_success"
    REPEATED_INDEPENDENT_SUCCESS = "repeated_independent_success"
    RECENTLY_STABLE = "recently_stable"
    UNSTABLE = "unstable"


@dataclass(frozen=True)
class StateTransition:
    from_status: str
    to_status: str
    reason: str
    at: datetime


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class QuestionCandidate:
    question_id: str
    diagnostic_unit_id: str
    evidence_family_id: str
    material_group_id: str
    eligible_roles: frozenset[QuestionRole] = frozenset({QuestionRole.PRACTICE})

    def __post_init__(self) -> None:
        _require_identifier("question_id", self.question_id)
        _require_identifier("diagnostic_unit_id", self.diagnostic_unit_id)
        _require_identifier("evidence_family_id", self.evidence_family_id)
        _require_identifier("material_group_id", self.material_group_id)
        if not self.eligible_roles:
            raise ValueError("eligible_roles cannot be empty")
        if any(not isinstance(role, QuestionRole) for role in self.eligible_roles):
            raise ValueError("eligible_roles must contain QuestionRole values")


_SESSION_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.CREATED: frozenset({SessionStatus.ACTIVE}),
    SessionStatus.ACTIVE: frozenset(
        {SessionStatus.COMPLETED, SessionStatus.ENDED_EARLY}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.ENDED_EARLY: frozenset(),
}


@dataclass
class PracticeSession:
    session_id: str
    started_at: datetime
    allowed_unit_ids: frozenset[str] = frozenset()
    target_count: int = FIXED_SESSION_SIZE
    item_count: int = 0
    graded_count: int = 0
    status: SessionStatus = SessionStatus.CREATED
    ended_at: datetime | None = None
    end_reason: str | None = None
    transitions: list[StateTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_identifier("session_id", self.session_id)
        _require_aware("started_at", self.started_at)
        if self.target_count != FIXED_SESSION_SIZE:
            raise ValueError(f"practice sessions must contain exactly {FIXED_SESSION_SIZE} items")
        for unit_id in self.allowed_unit_ids:
            _require_identifier("allowed_unit_ids item", unit_id)

    @property
    def remaining_count(self) -> int:
        return self.target_count - self.item_count

    def transition(self, to_status: SessionStatus, *, reason: str, at: datetime) -> None:
        _require_aware("at", at)
        previous_at = self.transitions[-1].at if self.transitions else self.started_at
        if at < previous_at:
            raise InvalidTransition("session transitions must be chronological")
        if to_status not in _SESSION_TRANSITIONS[self.status]:
            raise InvalidTransition(
                f"session cannot transition from {self.status.value} to {to_status.value}"
            )
        previous = self.status
        self.status = to_status
        self.transitions.append(
            StateTransition(previous.value, to_status.value, reason, at)
        )
        if to_status in {SessionStatus.COMPLETED, SessionStatus.ENDED_EARLY}:
            self.ended_at = at
            self.end_reason = reason

    def consume_item(self, *, graded: bool, at: datetime) -> None:
        _require_aware("at", at)
        if self.status is not SessionStatus.ACTIVE:
            raise InvalidTransition("only an active session can consume an item")
        previous_at = self.transitions[-1].at if self.transitions else self.started_at
        if at < previous_at:
            raise InvalidTransition("session items cannot precede the active session")
        if self.item_count >= self.target_count:
            raise InvalidSubmission("the fixed eight-item session is already full")
        self.item_count += 1
        if graded:
            self.graded_count += 1
        if self.item_count == self.target_count:
            self.transition(
                SessionStatus.COMPLETED,
                reason="fixed_session_size_reached",
                at=at,
            )


@dataclass(frozen=True)
class RecommendationDecision:
    decision_id: str
    action: RecommendationAction
    reason_codes: tuple[str, ...]
    created_at: datetime
    session_id: str | None = None
    slot: int | None = None
    question_id: str | None = None
    diagnostic_unit_id: str | None = None
    evidence_family_id: str | None = None
    material_group_id: str | None = None
    role: QuestionRole | None = None
    validation_event_id: str | None = None
    hypothesis_id: str | None = None
    target_cause_id: str | None = None
    was_previously_exposed: bool | None = None

    def __post_init__(self) -> None:
        _require_identifier("decision_id", self.decision_id)
        _require_aware("created_at", self.created_at)
        if not self.reason_codes:
            raise ValueError("recommendation decisions require at least one reason code")


@dataclass(frozen=True)
class ScoredAttempt:
    attempt_id: str
    session_id: str
    source_decision_id: str
    question_id: str
    diagnostic_unit_id: str
    evidence_family_id: str
    material_group_id: str
    role: QuestionRole
    answer: str
    correct: bool
    hints_used: int
    was_previously_exposed: bool
    independent_evidence: bool
    independent_ineligibility_reasons: tuple[str, ...]
    error_signature_id: str | None
    cause_candidates: tuple[str, ...]
    answered_at: datetime
    global_graded_ordinal: int
    session_item_ordinal: int
    validation_event_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "session_id",
            "source_decision_id",
            "question_id",
            "diagnostic_unit_id",
            "evidence_family_id",
            "material_group_id",
        ):
            _require_identifier(name, getattr(self, name))
        if not isinstance(self.answer, str) or not self.answer.strip():
            raise InvalidSubmission("answer is the only required learner input and cannot be blank")
        if self.hints_used < 0:
            raise InvalidSubmission("hints_used cannot be negative")
        _require_aware("answered_at", self.answered_at)


_HYPOTHESIS_TRANSITIONS: dict[HypothesisStatus, frozenset[HypothesisStatus]] = {
    HypothesisStatus.EVIDENCE_INSUFFICIENT: frozenset(
        {
            HypothesisStatus.REPEATED_ERROR_OBSERVED,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.REPEATED_ERROR_OBSERVED: frozenset(
        {
            HypothesisStatus.AWAITING_DISAMBIGUATION,
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.AWAITING_DISAMBIGUATION: frozenset(
        {
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.SUPPORTED: frozenset(
        {
            HypothesisStatus.AWAITING_TRANSFER,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.AWAITING_TRANSFER: frozenset(
        {
            HypothesisStatus.WEAKENED_BY_TRANSFER,
            HypothesisStatus.PERSISTENT_OR_RECURRENT,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.WEAKENED_BY_TRANSFER: frozenset(
        {
            HypothesisStatus.RESOLVED_AFTER_VALIDATION,
            HypothesisStatus.PERSISTENT_OR_RECURRENT,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.PERSISTENT_OR_RECURRENT: frozenset(
        {
            HypothesisStatus.AWAITING_TRANSFER,
            HypothesisStatus.WITHDRAWN,
            HypothesisStatus.VOIDED,
        }
    ),
    HypothesisStatus.RESOLVED_AFTER_VALIDATION: frozenset(),
    HypothesisStatus.WITHDRAWN: frozenset(),
    HypothesisStatus.VOIDED: frozenset(),
}


@dataclass
class ErrorHypothesis:
    hypothesis_id: str
    diagnostic_unit_id: str
    error_signature_id: str
    episode: int
    created_at: datetime
    status: HypothesisStatus = HypothesisStatus.EVIDENCE_INSUFFICIENT
    cause_candidates: tuple[str, ...] = ()
    supporting_family_ids: set[str] = field(default_factory=set)
    supporting_material_group_ids: set[str] = field(default_factory=set)
    supporting_attempt_ids: list[str] = field(default_factory=list)
    candidate_sets_by_family: dict[str, tuple[str, ...]] = field(default_factory=dict)
    intervention_ids: list[str] = field(default_factory=list)
    validation_event_ids: list[str] = field(default_factory=list)
    transitions: list[StateTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_identifier("hypothesis_id", self.hypothesis_id)
        _require_identifier("diagnostic_unit_id", self.diagnostic_unit_id)
        _require_identifier("error_signature_id", self.error_signature_id)
        _require_aware("created_at", self.created_at)
        if self.episode < 1:
            raise ValueError("episode must be positive")

    @property
    def is_terminal(self) -> bool:
        return not _HYPOTHESIS_TRANSITIONS[self.status]

    def transition(self, to_status: HypothesisStatus, *, reason: str, at: datetime) -> None:
        _require_aware("at", at)
        previous_at = self.transitions[-1].at if self.transitions else self.created_at
        if at < previous_at:
            raise InvalidTransition("hypothesis transitions must be chronological")
        if to_status not in _HYPOTHESIS_TRANSITIONS[self.status]:
            raise InvalidTransition(
                "hypothesis cannot transition "
                f"from {self.status.value} to {to_status.value}"
            )
        previous = self.status
        self.status = to_status
        self.transitions.append(
            StateTransition(previous.value, to_status.value, reason, at)
        )


_VALIDATION_TRANSITIONS: dict[ValidationStatus, frozenset[ValidationStatus]] = {
    ValidationStatus.SCHEDULED: frozenset(
        {
            ValidationStatus.ELIGIBLE,
            ValidationStatus.INCONCLUSIVE,
            ValidationStatus.VOIDED,
        }
    ),
    ValidationStatus.ELIGIBLE: frozenset(
        {
            ValidationStatus.PRESENTED,
            ValidationStatus.INCONCLUSIVE,
            ValidationStatus.VOIDED,
        }
    ),
    ValidationStatus.PRESENTED: frozenset(
        {
            ValidationStatus.PASSED,
            ValidationStatus.FAILED,
            ValidationStatus.INCONCLUSIVE,
            ValidationStatus.VOIDED,
        }
    ),
    ValidationStatus.PASSED: frozenset(),
    ValidationStatus.FAILED: frozenset(),
    ValidationStatus.INCONCLUSIVE: frozenset(),
    ValidationStatus.VOIDED: frozenset(),
}


@dataclass
class ValidationEvent:
    validation_event_id: str
    kind: ValidationKind
    hypothesis_id: str
    diagnostic_unit_id: str
    created_at: datetime
    scheduled_after_graded_count: int
    excluded_family_ids: frozenset[str]
    excluded_material_group_ids: frozenset[str]
    status: ValidationStatus = ValidationStatus.SCHEDULED
    earliest_gap: int | None = None
    latest_gap: int | None = None
    due_at: datetime | None = None
    presented_question_id: str | None = None
    presented_family_id: str | None = None
    outcome_attempt_id: str | None = None
    replacement_of_event_id: str | None = None
    transitions: list[StateTransition] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_identifier("validation_event_id", self.validation_event_id)
        _require_identifier("hypothesis_id", self.hypothesis_id)
        _require_identifier("diagnostic_unit_id", self.diagnostic_unit_id)
        _require_aware("created_at", self.created_at)
        if self.scheduled_after_graded_count < 0:
            raise ValueError("scheduled_after_graded_count cannot be negative")
        if self.kind is ValidationKind.NEAR_TRANSFER:
            if self.earliest_gap != NEAR_TRANSFER_MIN_GAP:
                raise ValueError("near transfer earliest_gap must be 2")
            if self.latest_gap != NEAR_TRANSFER_MAX_GAP:
                raise ValueError("near transfer latest_gap must be 4")
            if self.due_at is not None:
                raise ValueError("near transfer uses graded-question gaps, not due_at")
        else:
            if self.due_at is None:
                raise ValueError("delayed validation requires due_at")
            _require_aware("due_at", self.due_at)

    @property
    def is_terminal(self) -> bool:
        return not _VALIDATION_TRANSITIONS[self.status]

    def transition(self, to_status: ValidationStatus, *, reason: str, at: datetime) -> None:
        _require_aware("at", at)
        previous_at = self.transitions[-1].at if self.transitions else self.created_at
        if at < previous_at:
            raise InvalidTransition("validation transitions must be chronological")
        if to_status not in _VALIDATION_TRANSITIONS[self.status]:
            raise InvalidTransition(
                "validation cannot transition "
                f"from {self.status.value} to {to_status.value}"
            )
        previous = self.status
        self.status = to_status
        self.transitions.append(
            StateTransition(previous.value, to_status.value, reason, at)
        )


@dataclass(frozen=True)
class DiagnosticUnitPerformance:
    diagnostic_unit_id: str
    status: PerformanceStatus
    reason_codes: tuple[str, ...]
    independent_success_attempt_ids: tuple[str, ...]
    independent_failure_attempt_ids: tuple[str, ...]
    independent_family_ids: tuple[str, ...]
    updated_at: datetime | None


@dataclass(frozen=True)
class SubmissionResult:
    attempt: ScoredAttempt
    feedback_decision: RecommendationDecision
    performance: DiagnosticUnitPerformance
    hypothesis_id: str | None
    validation_event_id: str | None
    session_status: SessionStatus


@dataclass(frozen=True)
class ProbeSubmissionResult:
    hypothesis_id: str
    answer: str | None
    supported_cause_id: str | None
    skipped: bool
    decision: RecommendationDecision
    session_status: SessionStatus
    global_graded_ordinal: int | None


def normalized_candidates(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {value.strip() for value in values if isinstance(value, str) and value.strip()}
    return tuple(sorted(normalized))
