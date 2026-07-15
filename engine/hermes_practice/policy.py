from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from .models import (
    DELAYED_VALIDATION_HOURS,
    FIXED_SESSION_SIZE,
    NEAR_TRANSFER_MAX_GAP,
    NEAR_TRANSFER_MIN_GAP,
    DiagnosticUnitPerformance,
    ErrorHypothesis,
    HypothesisStatus,
    InvalidSubmission,
    InvalidTransition,
    PerformanceStatus,
    PracticeSession,
    ProbeSubmissionResult,
    QuestionCandidate,
    QuestionRole,
    RecommendationAction,
    RecommendationDecision,
    ScoredAttempt,
    SessionStatus,
    SubmissionResult,
    ValidationEvent,
    ValidationKind,
    ValidationStatus,
    normalized_candidates,
    _require_aware,
    _require_identifier,
)


_TERMINAL_HYPOTHESIS_STATUSES = {
    HypothesisStatus.RESOLVED_AFTER_VALIDATION,
    HypothesisStatus.WITHDRAWN,
    HypothesisStatus.VOIDED,
}


class PracticePolicyEngine:
    """Deterministic, dependency-free policy for Lumi's eight-item practice loop.

    The engine owns policy state, not content scoring. Callers supply the trusted
    correctness and distractor mapping alongside the learner's one required input:
    ``answer``. Every recommendation records machine-readable reason codes.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, PracticeSession] = {}
        self.current_session_id: str | None = None
        self.decisions: list[RecommendationDecision] = []
        self.attempts: list[ScoredAttempt] = []
        self.hypotheses: dict[str, ErrorHypothesis] = {}
        self.validation_events: dict[str, ValidationEvent] = {}
        self.exposed_question_ids: set[str] = set()
        self._pending_question_decision_id: str | None = None
        self._decision_index: dict[str, RecommendationDecision] = {}
        self._answered_decision_ids: set[str] = set()
        self._used_evidence_families: dict[str, set[str]] = defaultdict(set)
        self._used_material_groups: dict[str, set[str]] = defaultdict(set)
        self._active_hypothesis_ids: dict[tuple[str, str], str] = {}
        self._episode_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._open_probe_hypothesis_ids: set[str] = set()
        self._counters: dict[str, int] = defaultdict(int)
        self.global_graded_count = 0
        self._latest_activity_at: datetime | None = None

    @property
    def current_session(self) -> PracticeSession | None:
        if self.current_session_id is None:
            return None
        return self.sessions[self.current_session_id]

    @property
    def pending_question_decision(self) -> RecommendationDecision | None:
        """The currently exposed unanswered question, if any."""

        if self._pending_question_decision_id is None:
            return None
        return self._decision_index[self._pending_question_decision_id]

    @property
    def open_probe_hypothesis_ids(self) -> tuple[str, ...]:
        """Stable, read-only view of optional probe offers awaiting answer/skip."""

        return tuple(sorted(self._open_probe_hypothesis_ids))

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}-{self._counters[prefix]:06d}"

    def _require_chronological(self, at: datetime) -> None:
        _require_aware("at", at)
        if self._latest_activity_at is not None and at < self._latest_activity_at:
            raise InvalidTransition("practice policy activity must be chronological")

    def _touch(self, at: datetime) -> None:
        self._require_chronological(at)
        self._latest_activity_at = at

    def _record_decision(
        self,
        *,
        action: RecommendationAction,
        reason_codes: Iterable[str],
        at: datetime,
        session: PracticeSession | None = None,
        slot: int | None = None,
        candidate: QuestionCandidate | None = None,
        role: QuestionRole | None = None,
        validation_event_id: str | None = None,
        hypothesis_id: str | None = None,
        target_cause_id: str | None = None,
        was_previously_exposed: bool | None = None,
    ) -> RecommendationDecision:
        self._touch(at)
        decision = RecommendationDecision(
            decision_id=self._next_id("decision"),
            action=action,
            reason_codes=tuple(reason_codes),
            created_at=at,
            session_id=session.session_id if session else None,
            slot=slot,
            question_id=candidate.question_id if candidate else None,
            diagnostic_unit_id=candidate.diagnostic_unit_id if candidate else None,
            evidence_family_id=candidate.evidence_family_id if candidate else None,
            material_group_id=candidate.material_group_id if candidate else None,
            role=role,
            validation_event_id=validation_event_id,
            hypothesis_id=hypothesis_id,
            target_cause_id=target_cause_id,
            was_previously_exposed=was_previously_exposed,
        )
        self.decisions.append(decision)
        self._decision_index[decision.decision_id] = decision
        return decision

    def start_session(
        self,
        session_id: str,
        *,
        started_at: datetime,
        allowed_unit_ids: Iterable[str] = (),
    ) -> PracticeSession:
        _require_identifier("session_id", session_id)
        self._require_chronological(started_at)
        if self.current_session is not None and self.current_session.status is SessionStatus.ACTIVE:
            raise InvalidTransition("end the active session before starting another")
        if session_id in self.sessions:
            raise InvalidSubmission(f"session_id already exists: {session_id}")
        if isinstance(allowed_unit_ids, (str, bytes)):
            raise InvalidSubmission("allowed_unit_ids must be an iterable of identifiers")
        try:
            normalized_unit_ids = frozenset(allowed_unit_ids)
        except TypeError:
            raise InvalidSubmission("allowed_unit_ids must contain hashable identifiers") from None
        for unit_id in normalized_unit_ids:
            try:
                _require_identifier("allowed_unit_ids item", unit_id)
            except ValueError as exc:
                raise InvalidSubmission(str(exc)) from None
        session = PracticeSession(
            session_id=session_id,
            started_at=started_at,
            allowed_unit_ids=normalized_unit_ids,
            target_count=FIXED_SESSION_SIZE,
        )
        session.transition(SessionStatus.ACTIVE, reason="session_started", at=started_at)
        self.sessions[session_id] = session
        self.current_session_id = session_id
        self._pending_question_decision_id = None
        self._touch(started_at)
        return session

    def end_session_early(self, *, at: datetime, reason: str = "learner_ended_early") -> PracticeSession:
        session = self._require_active_session()
        self._require_chronological(at)
        if self._pending_question_decision_id is not None:
            pending = self._decision_index[self._pending_question_decision_id]
            if pending.validation_event_id:
                event = self.validation_events[pending.validation_event_id]
                if event.status is ValidationStatus.PRESENTED:
                    event.transition(
                        ValidationStatus.INCONCLUSIVE,
                        reason="session_ended_after_validation_exposure_without_answer",
                        at=at,
                    )
                    self._schedule_replacement_validation(
                        event,
                        at=at,
                        reason="validation_exposed_but_session_ended_before_answer",
                        additional_excluded_family_ids=(pending.evidence_family_id,),
                        additional_excluded_material_group_ids=(pending.material_group_id,),
                    )
            self._pending_question_decision_id = None
        session.transition(SessionStatus.ENDED_EARLY, reason=reason, at=at)
        self._record_decision(
            action=RecommendationAction.END_SESSION,
            reason_codes=("learner_ended_before_fixed_eight",),
            at=at,
            session=session,
        )
        return session

    def _require_active_session(self) -> PracticeSession:
        session = self.current_session
        if session is None or session.status is not SessionStatus.ACTIVE:
            raise InvalidTransition("an active practice session is required")
        return session

    def refresh_validations(self, *, at: datetime) -> tuple[ValidationEvent, ...]:
        self._touch(at)
        changed: list[ValidationEvent] = []
        for event in sorted(self.validation_events.values(), key=lambda item: item.validation_event_id):
            if event.kind is ValidationKind.NEAR_TRANSFER:
                if event.status not in {
                    ValidationStatus.SCHEDULED,
                    ValidationStatus.ELIGIBLE,
                }:
                    continue
                gap = self.global_graded_count - event.scheduled_after_graded_count
                if gap > NEAR_TRANSFER_MAX_GAP:
                    event.transition(
                        ValidationStatus.INCONCLUSIVE,
                        reason="near_transfer_window_missed_without_extending_session",
                        at=at,
                    )
                    self._schedule_replacement_validation(
                        event,
                        at=at,
                        reason="near_transfer_window_missed_replacement_scheduled",
                    )
                    changed.append(event)
                elif (
                    event.status is ValidationStatus.SCHEDULED
                    and gap >= NEAR_TRANSFER_MIN_GAP
                ):
                    event.transition(
                        ValidationStatus.ELIGIBLE,
                        reason="two_graded_items_have_intervened",
                        at=at,
                    )
                    changed.append(event)
            elif (
                event.status is ValidationStatus.SCHEDULED
                and event.due_at is not None
                and at >= event.due_at
            ):
                event.transition(
                    ValidationStatus.ELIGIBLE,
                    reason="delayed_validation_due_at_reached",
                    at=at,
                )
                changed.append(event)
        return tuple(changed)

    def recommend_next(
        self,
        candidates: Iterable[QuestionCandidate],
        *,
        at: datetime,
    ) -> RecommendationDecision:
        session = self._require_active_session()
        self._require_chronological(at)
        if self._pending_question_decision_id is not None:
            raise InvalidTransition("submit or abandon the presented question before requesting another")
        if self._open_probe_hypothesis_ids:
            hypothesis_id = min(self._open_probe_hypothesis_ids)
            return self._record_decision(
                action=RecommendationAction.SHOW_PROBE,
                reason_codes=(
                    "optional_probe_offer_is_pending",
                    "answer_or_skip_probe_before_next_question",
                    "probe_will_use_next_fixed_session_slot",
                ),
                at=at,
                session=session,
                slot=session.item_count + 1,
                role=QuestionRole.PROBE,
                hypothesis_id=hypothesis_id,
            )
        self.refresh_validations(at=at)
        candidate_list = sorted(candidates, key=lambda item: item.question_id)
        candidate_list = [item for item in candidate_list if self._in_scope(session, item)]

        eligible_events = [
            event
            for event in sorted(
                self.validation_events.values(), key=lambda item: item.validation_event_id
            )
            if event.status is ValidationStatus.ELIGIBLE
            and (
                not session.allowed_unit_ids
                or event.diagnostic_unit_id in session.allowed_unit_ids
            )
        ]
        unavailable_validation = False
        for event in eligible_events:
            role = (
                QuestionRole.NEAR_TRANSFER
                if event.kind is ValidationKind.NEAR_TRANSFER
                else QuestionRole.DELAYED_VALIDATION
            )
            selected = self._select_validation_candidate(candidate_list, event, role)
            if selected is None:
                unavailable_validation = True
                continue
            return self._present_question(
                session=session,
                candidate=selected,
                role=role,
                event=event,
                at=at,
                reasons=(
                    "validation_event_is_eligible",
                    "candidate_is_unexposed_and_cross_family",
                    "fixed_session_slot_preserved",
                ),
            )

        normal_candidates = [
            item for item in candidate_list if QuestionRole.PRACTICE in item.eligible_roles
        ]
        if not normal_candidates:
            reasons = ["no_in_scope_practice_candidate"]
            if unavailable_validation:
                reasons.append("eligible_validation_has_no_independent_candidate")
            return self._record_decision(
                action=RecommendationAction.NO_ELIGIBLE_QUESTION,
                reason_codes=reasons,
                at=at,
                session=session,
                slot=session.item_count + 1,
            )

        # Prefer a never-seen question, but allow ordinary repeated practice. A
        # repeated item is recorded as ineligible for positive independent evidence.
        selected = min(
            normal_candidates,
            key=lambda item: (item.question_id in self.exposed_question_ids, item.question_id),
        )
        reasons = ["fixed_session_next_practice_slot"]
        if unavailable_validation:
            reasons.append("eligible_validation_has_no_independent_candidate")
        if selected.question_id in self.exposed_question_ids:
            reasons.append("repeated_question_allowed_for_practice_only")
        return self._present_question(
            session=session,
            candidate=selected,
            role=QuestionRole.PRACTICE,
            event=None,
            at=at,
            reasons=tuple(reasons),
        )

    def _in_scope(self, session: PracticeSession, candidate: QuestionCandidate) -> bool:
        return not session.allowed_unit_ids or candidate.diagnostic_unit_id in session.allowed_unit_ids

    def _select_validation_candidate(
        self,
        candidates: list[QuestionCandidate],
        event: ValidationEvent,
        role: QuestionRole,
    ) -> QuestionCandidate | None:
        used_families = self._used_evidence_families[event.diagnostic_unit_id]
        used_materials = self._used_material_groups[event.diagnostic_unit_id]
        matches = [
            item
            for item in candidates
            if item.diagnostic_unit_id == event.diagnostic_unit_id
            and role in item.eligible_roles
            and item.question_id not in self.exposed_question_ids
            and item.evidence_family_id not in event.excluded_family_ids
            and item.material_group_id not in event.excluded_material_group_ids
            and item.evidence_family_id not in used_families
            and item.material_group_id not in used_materials
        ]
        return min(matches, key=lambda item: item.question_id) if matches else None

    def _present_question(
        self,
        *,
        session: PracticeSession,
        candidate: QuestionCandidate,
        role: QuestionRole,
        event: ValidationEvent | None,
        at: datetime,
        reasons: tuple[str, ...],
    ) -> RecommendationDecision:
        was_exposed = candidate.question_id in self.exposed_question_ids
        if event is not None:
            event.transition(
                ValidationStatus.PRESENTED,
                reason="recommended_candidate_presented",
                at=at,
            )
            event.presented_question_id = candidate.question_id
            event.presented_family_id = candidate.evidence_family_id
        decision = self._record_decision(
            action=RecommendationAction.SERVE_QUESTION,
            reason_codes=reasons,
            at=at,
            session=session,
            slot=session.item_count + 1,
            candidate=candidate,
            role=role,
            validation_event_id=event.validation_event_id if event else None,
            hypothesis_id=event.hypothesis_id if event else None,
            was_previously_exposed=was_exposed,
        )
        self.exposed_question_ids.add(candidate.question_id)
        self._pending_question_decision_id = decision.decision_id
        return decision

    def submit_answer(
        self,
        decision_id: str,
        *,
        answer: str,
        is_correct: bool,
        at: datetime,
        error_signature_id: str | None = None,
        cause_candidates: Iterable[str] = (),
        hints_used: int = 0,
    ) -> SubmissionResult:
        session = self._require_active_session()
        self._require_chronological(at)
        if not isinstance(answer, str) or not answer.strip():
            raise InvalidSubmission("answer is the only required learner input and cannot be blank")
        if not isinstance(is_correct, bool):
            raise InvalidSubmission("is_correct must be trusted boolean scoring metadata")
        if isinstance(hints_used, bool) or not isinstance(hints_used, int) or hints_used < 0:
            raise InvalidSubmission("hints_used must be a non-negative integer")
        decision = self._decision_index.get(decision_id)
        if decision is None or decision.action is not RecommendationAction.SERVE_QUESTION:
            raise InvalidSubmission("decision_id does not identify a presented question")
        if decision_id in self._answered_decision_ids:
            raise InvalidSubmission("the presented question was already answered")
        if self._pending_question_decision_id != decision_id:
            raise InvalidSubmission("decision_id is not the current presented question")
        if decision.session_id != session.session_id:
            raise InvalidSubmission("presented question belongs to another session")
        if at < decision.created_at:
            raise InvalidSubmission("answer time cannot precede question presentation")

        if isinstance(cause_candidates, (str, bytes)):
            raise InvalidSubmission("cause_candidates must be an iterable of identifiers")
        try:
            raw_cause_candidates = tuple(cause_candidates)
        except TypeError:
            raise InvalidSubmission("cause_candidates must be iterable") from None
        if any(not isinstance(item, str) or not item.strip() for item in raw_cause_candidates):
            raise InvalidSubmission("cause_candidates must contain non-empty strings")
        normalized_cause_candidates = normalized_candidates(raw_cause_candidates)
        if is_correct and (error_signature_id is not None or normalized_cause_candidates):
            raise InvalidSubmission("correct answers cannot carry error-cause metadata")
        if not is_correct and error_signature_id is None and normalized_cause_candidates:
            raise InvalidSubmission("cause candidates require an error_signature_id")
        if error_signature_id is not None:
            try:
                _require_identifier("error_signature_id", error_signature_id)
            except ValueError as exc:
                raise InvalidSubmission(str(exc)) from None

        if (
            decision.question_id is None
            or decision.diagnostic_unit_id is None
            or decision.evidence_family_id is None
            or decision.material_group_id is None
            or decision.role is None
        ):
            raise InvalidSubmission("presented-question decision is missing content metadata")
        family_seen = (
            decision.evidence_family_id
            in self._used_evidence_families[decision.diagnostic_unit_id]
        )
        material_seen = (
            decision.material_group_id
            in self._used_material_groups[decision.diagnostic_unit_id]
        )
        ineligibility_reasons: list[str] = []
        if hints_used:
            ineligibility_reasons.append("help_used_on_question")
        if decision.was_previously_exposed:
            ineligibility_reasons.append("question_previously_exposed")
        if family_seen:
            ineligibility_reasons.append("evidence_family_already_used")
        if material_seen:
            ineligibility_reasons.append("material_group_already_used")
        independent = not ineligibility_reasons

        self.global_graded_count += 1
        attempt = ScoredAttempt(
            attempt_id=self._next_id("attempt"),
            session_id=session.session_id,
            source_decision_id=decision.decision_id,
            question_id=decision.question_id,
            diagnostic_unit_id=decision.diagnostic_unit_id,
            evidence_family_id=decision.evidence_family_id,
            material_group_id=decision.material_group_id,
            role=decision.role,
            answer=answer,
            correct=is_correct,
            hints_used=hints_used,
            was_previously_exposed=bool(decision.was_previously_exposed),
            independent_evidence=independent,
            independent_ineligibility_reasons=tuple(ineligibility_reasons),
            error_signature_id=error_signature_id if not is_correct else None,
            cause_candidates=normalized_cause_candidates,
            answered_at=at,
            global_graded_ordinal=self.global_graded_count,
            session_item_ordinal=session.item_count + 1,
            validation_event_id=decision.validation_event_id,
        )
        self.attempts.append(attempt)
        if independent:
            self._used_evidence_families[attempt.diagnostic_unit_id].add(
                attempt.evidence_family_id
            )
            self._used_material_groups[attempt.diagnostic_unit_id].add(
                attempt.material_group_id
            )
        self._answered_decision_ids.add(decision_id)
        self._pending_question_decision_id = None

        validation_hypothesis: ErrorHypothesis | None = None
        if attempt.validation_event_id:
            validation_hypothesis = self._apply_validation_attempt(attempt)

        hypothesis: ErrorHypothesis | None = validation_hypothesis
        feedback_action = RecommendationAction.CONTINUE
        feedback_reasons: tuple[str, ...] = ("correct_answer_feedback_collapsed",)
        target_cause_id: str | None = None
        if not is_correct:
            if error_signature_id:
                if attempt.independent_evidence:
                    hypothesis, feedback_action, feedback_reasons, target_cause_id = (
                        self._record_error_signature(attempt)
                    )
                else:
                    feedback_action = RecommendationAction.LIGHT_FEEDBACK
                    feedback_reasons = (
                        "error_signature_observed_without_independent_evidence",
                        *attempt.independent_ineligibility_reasons,
                        "no_cause_claim_made",
                    )
            else:
                feedback_action = RecommendationAction.LIGHT_FEEDBACK
                feedback_reasons = (
                    "incorrect_answer_without_mapped_error_signature",
                    "no_cause_claim_made",
                )

        session.consume_item(graded=True, at=at)
        feedback = self._record_decision(
            action=feedback_action,
            reason_codes=feedback_reasons,
            at=at,
            session=session,
            slot=attempt.session_item_ordinal,
            hypothesis_id=hypothesis.hypothesis_id if hypothesis else None,
            target_cause_id=target_cause_id,
            validation_event_id=attempt.validation_event_id,
        )
        if feedback_action is RecommendationAction.SHOW_PROBE and hypothesis is not None:
            self._open_probe_hypothesis_ids.add(hypothesis.hypothesis_id)
        return SubmissionResult(
            attempt=attempt,
            feedback_decision=feedback,
            performance=self.performance_for(attempt.diagnostic_unit_id),
            hypothesis_id=hypothesis.hypothesis_id if hypothesis else None,
            validation_event_id=attempt.validation_event_id,
            session_status=session.status,
        )

    def _record_error_signature(
        self, attempt: ScoredAttempt
    ) -> tuple[
        ErrorHypothesis,
        RecommendationAction,
        tuple[str, ...],
        str | None,
    ]:
        assert attempt.error_signature_id is not None
        key = (attempt.diagnostic_unit_id, attempt.error_signature_id)
        hypothesis = self._active_hypothesis(key, at=attempt.answered_at)
        is_new_family = attempt.evidence_family_id not in hypothesis.supporting_family_ids
        is_new_material = (
            attempt.material_group_id not in hypothesis.supporting_material_group_ids
        )
        hypothesis.supporting_family_ids.add(attempt.evidence_family_id)
        hypothesis.supporting_material_group_ids.add(attempt.material_group_id)
        hypothesis.supporting_attempt_ids.append(attempt.attempt_id)
        if is_new_family:
            hypothesis.candidate_sets_by_family[attempt.evidence_family_id] = (
                attempt.cause_candidates
            )

        if (
            hypothesis.status is HypothesisStatus.EVIDENCE_INSUFFICIENT
            and len(hypothesis.supporting_family_ids) >= 2
            and len(hypothesis.supporting_material_group_ids) >= 2
        ):
            hypothesis.transition(
                HypothesisStatus.REPEATED_ERROR_OBSERVED,
                reason="same_signature_observed_across_two_families_and_material_groups",
                at=attempt.answered_at,
            )
            clear_cause, aggregate_candidates = self._resolve_candidate_clarity(hypothesis)
            hypothesis.cause_candidates = aggregate_candidates
            if clear_cause is not None:
                hypothesis.transition(
                    HypothesisStatus.SUPPORTED,
                    reason="one_common_actionable_cause_remains",
                    at=attempt.answered_at,
                )
                return (
                    hypothesis,
                    RecommendationAction.SHOW_MICRO_TUTORIAL,
                    (
                        "signature_repeated_across_independent_family_and_material_groups",
                        "single_actionable_cause_candidate",
                    ),
                    clear_cause,
                )
            hypothesis.transition(
                HypothesisStatus.AWAITING_DISAMBIGUATION,
                reason="multiple_or_unmapped_causes_require_probe",
                at=attempt.answered_at,
            )
            return (
                hypothesis,
                RecommendationAction.SHOW_PROBE,
                (
                    "signature_repeated_across_independent_family_and_material_groups",
                    "cause_candidates_are_ambiguous",
                    "probe_is_optional_and_uses_one_of_eight_slots",
                ),
                None,
            )

        if not is_new_family or not is_new_material:
            overlap_reason = (
                "same_signature_seen_in_same_family_and_material"
                if not is_new_family and not is_new_material
                else "same_signature_seen_without_family_and_material_independence"
            )
            return (
                hypothesis,
                RecommendationAction.LIGHT_FEEDBACK,
                (
                    overlap_reason,
                    "not_counted_as_repetition",
                    "no_cause_claim_made",
                ),
                None,
            )
        if hypothesis.status is HypothesisStatus.EVIDENCE_INSUFFICIENT:
            return (
                hypothesis,
                RecommendationAction.LIGHT_FEEDBACK,
                (
                    "first_independent_family_material_observation_for_error_signature",
                    "candidate_recorded_without_learner_label",
                ),
                None,
            )
        if hypothesis.status in {
            HypothesisStatus.AWAITING_TRANSFER,
            HypothesisStatus.WEAKENED_BY_TRANSFER,
        }:
            self._void_open_validations(
                hypothesis,
                reason="same_signature_recurred_before_successful_validation",
                at=attempt.answered_at,
            )
            hypothesis.transition(
                HypothesisStatus.PERSISTENT_OR_RECURRENT,
                reason="same_signature_recurred_in_new_evidence_family",
                at=attempt.answered_at,
            )
        if hypothesis.status is HypothesisStatus.PERSISTENT_OR_RECURRENT:
            target = hypothesis.cause_candidates[0] if len(hypothesis.cause_candidates) == 1 else None
            action = (
                RecommendationAction.SHOW_MICRO_TUTORIAL
                if target
                else RecommendationAction.SHOW_PROBE
            )
            return (
                hypothesis,
                action,
                ("supported_signature_recurred_in_new_evidence_family",),
                target,
            )
        if hypothesis.status is HypothesisStatus.SUPPORTED:
            target = hypothesis.cause_candidates[0] if len(hypothesis.cause_candidates) == 1 else None
            return (
                hypothesis,
                RecommendationAction.SHOW_MICRO_TUTORIAL,
                ("supported_signature_recurred_before_tutorial",),
                target,
            )
        if hypothesis.status is HypothesisStatus.AWAITING_DISAMBIGUATION:
            return (
                hypothesis,
                RecommendationAction.SHOW_PROBE,
                ("ambiguity_remains_after_additional_family",),
                None,
            )
        return (
            hypothesis,
            RecommendationAction.LIGHT_FEEDBACK,
            ("error_recorded_without_additional_policy_action",),
            None,
        )

    def _active_hypothesis(
        self, key: tuple[str, str], *, at: datetime
    ) -> ErrorHypothesis:
        existing_id = self._active_hypothesis_ids.get(key)
        if existing_id is not None:
            existing = self.hypotheses[existing_id]
            if existing.status not in _TERMINAL_HYPOTHESIS_STATUSES:
                return existing
        self._episode_counts[key] += 1
        hypothesis = ErrorHypothesis(
            hypothesis_id=self._next_id("hypothesis"),
            diagnostic_unit_id=key[0],
            error_signature_id=key[1],
            episode=self._episode_counts[key],
            created_at=at,
        )
        self.hypotheses[hypothesis.hypothesis_id] = hypothesis
        self._active_hypothesis_ids[key] = hypothesis.hypothesis_id
        return hypothesis

    @staticmethod
    def _resolve_candidate_clarity(
        hypothesis: ErrorHypothesis,
    ) -> tuple[str | None, tuple[str, ...]]:
        candidate_sets = [
            set(values)
            for values in hypothesis.candidate_sets_by_family.values()
        ]
        if not candidate_sets or any(not values for values in candidate_sets):
            aggregate = tuple(sorted(set().union(*candidate_sets))) if candidate_sets else ()
            return None, aggregate
        common = set.intersection(*candidate_sets)
        aggregate = tuple(sorted(set.union(*candidate_sets)))
        if len(common) == 1:
            return next(iter(common)), tuple(sorted(common))
        return None, aggregate

    def submit_probe_answer(
        self,
        hypothesis_id: str,
        *,
        answer: str,
        supported_cause_id: str | None,
        at: datetime,
    ) -> ProbeSubmissionResult:
        session = self._require_active_session()
        self._require_chronological(at)
        if not isinstance(answer, str) or not answer.strip():
            raise InvalidSubmission("probe answer cannot be blank; use skip_probe instead")
        hypothesis = self._require_hypothesis(hypothesis_id)
        if hypothesis.status is not HypothesisStatus.AWAITING_DISAMBIGUATION:
            raise InvalidTransition("probe answers require an awaiting-disambiguation hypothesis")
        if hypothesis_id not in self._open_probe_hypothesis_ids:
            raise InvalidTransition("no optional probe offer is open for this hypothesis")
        if supported_cause_id is not None:
            _require_identifier("supported_cause_id", supported_cause_id)
            if (
                hypothesis.cause_candidates
                and supported_cause_id not in hypothesis.cause_candidates
            ):
                raise InvalidSubmission("probe result is not one of the candidate causes")
        self.global_graded_count += 1
        session.consume_item(graded=True, at=at)
        self._open_probe_hypothesis_ids.remove(hypothesis_id)
        if supported_cause_id is None:
            decision = self._record_decision(
                action=RecommendationAction.CONTINUE,
                reason_codes=(
                    "probe_was_inconclusive",
                    "hypothesis_remains_awaiting_disambiguation",
                ),
                at=at,
                session=session,
                slot=session.item_count,
                role=QuestionRole.PROBE,
                hypothesis_id=hypothesis_id,
            )
        else:
            hypothesis.cause_candidates = (supported_cause_id,)
            hypothesis.transition(
                HypothesisStatus.SUPPORTED,
                reason="optional_probe_supported_one_actionable_cause",
                at=at,
            )
            decision = self._record_decision(
                action=RecommendationAction.SHOW_MICRO_TUTORIAL,
                reason_codes=(
                    "probe_supported_one_actionable_cause",
                    "probe_result_is_not_mastery_evidence",
                ),
                at=at,
                session=session,
                slot=session.item_count,
                role=QuestionRole.PROBE,
                hypothesis_id=hypothesis_id,
                target_cause_id=supported_cause_id,
            )
        return ProbeSubmissionResult(
            hypothesis_id=hypothesis_id,
            answer=answer,
            supported_cause_id=supported_cause_id,
            skipped=False,
            decision=decision,
            session_status=session.status,
            global_graded_ordinal=self.global_graded_count,
        )

    def skip_probe(
        self, hypothesis_id: str, *, at: datetime
    ) -> ProbeSubmissionResult:
        session = self._require_active_session()
        self._require_chronological(at)
        hypothesis = self._require_hypothesis(hypothesis_id)
        if hypothesis.status is not HypothesisStatus.AWAITING_DISAMBIGUATION:
            raise InvalidTransition("only a pending optional probe can be skipped")
        if hypothesis_id not in self._open_probe_hypothesis_ids:
            raise InvalidTransition("no optional probe offer is open for this hypothesis")
        session.consume_item(graded=False, at=at)
        self._open_probe_hypothesis_ids.remove(hypothesis_id)
        decision = self._record_decision(
            action=RecommendationAction.CONTINUE,
            reason_codes=(
                "optional_probe_skipped",
                "one_fixed_session_slot_consumed_without_diagnostic_claim",
            ),
            at=at,
            session=session,
            slot=session.item_count,
            role=QuestionRole.PROBE,
            hypothesis_id=hypothesis_id,
        )
        return ProbeSubmissionResult(
            hypothesis_id=hypothesis_id,
            answer=None,
            supported_cause_id=None,
            skipped=True,
            decision=decision,
            session_status=session.status,
            global_graded_ordinal=None,
        )

    def record_tutorial_shown(
        self,
        hypothesis_id: str,
        *,
        asset_id: str,
        at: datetime,
    ) -> ValidationEvent:
        _require_identifier("asset_id", asset_id)
        self._require_chronological(at)
        hypothesis = self._require_hypothesis(hypothesis_id)
        if hypothesis.status not in {
            HypothesisStatus.SUPPORTED,
            HypothesisStatus.PERSISTENT_OR_RECURRENT,
        }:
            raise InvalidTransition("tutorial requires a supported or recurrent hypothesis")
        intervention_id = self._next_id("intervention")
        hypothesis.intervention_ids.append(intervention_id)
        hypothesis.transition(
            HypothesisStatus.AWAITING_TRANSFER,
            reason=f"micro_tutorial_shown:{asset_id}",
            at=at,
        )
        event = ValidationEvent(
            validation_event_id=self._next_id("validation"),
            kind=ValidationKind.NEAR_TRANSFER,
            hypothesis_id=hypothesis_id,
            diagnostic_unit_id=hypothesis.diagnostic_unit_id,
            created_at=at,
            scheduled_after_graded_count=self.global_graded_count,
            excluded_family_ids=frozenset(hypothesis.supporting_family_ids),
            excluded_material_group_ids=frozenset(
                hypothesis.supporting_material_group_ids
            ),
            earliest_gap=NEAR_TRANSFER_MIN_GAP,
            latest_gap=NEAR_TRANSFER_MAX_GAP,
        )
        self.validation_events[event.validation_event_id] = event
        hypothesis.validation_event_ids.append(event.validation_event_id)
        session = self.current_session
        reason_codes = [
            "tutorial_shown_near_transfer_scheduled",
            "requires_two_to_four_intervening_graded_items",
        ]
        if session is None or session.status is not SessionStatus.ACTIVE or session.remaining_count <= 2:
            reason_codes.append("deferred_across_session_without_extending_fixed_eight")
        self._record_decision(
            action=RecommendationAction.VALIDATION_SCHEDULED,
            reason_codes=reason_codes,
            at=at,
            session=session,
            validation_event_id=event.validation_event_id,
            hypothesis_id=hypothesis_id,
            target_cause_id=(
                hypothesis.cause_candidates[0]
                if len(hypothesis.cause_candidates) == 1
                else None
            ),
        )
        return event

    def _apply_validation_attempt(self, attempt: ScoredAttempt) -> ErrorHypothesis:
        assert attempt.validation_event_id is not None
        event = self.validation_events.get(attempt.validation_event_id)
        if event is None or event.status is not ValidationStatus.PRESENTED:
            raise InvalidTransition("validation attempt requires a presented validation event")
        hypothesis = self._require_hypothesis(event.hypothesis_id)
        event.outcome_attempt_id = attempt.attempt_id
        if not attempt.independent_evidence:
            event.transition(
                ValidationStatus.INCONCLUSIVE,
                reason="help_exposure_or_reused_family_invalidated_positive_evidence",
                at=attempt.answered_at,
            )
            self._schedule_replacement_validation(
                event,
                at=attempt.answered_at,
                reason="non_independent_validation_replacement_scheduled",
                additional_excluded_family_ids=(attempt.evidence_family_id,),
                additional_excluded_material_group_ids=(attempt.material_group_id,),
            )
            return hypothesis
        if attempt.evidence_family_id in event.excluded_family_ids:
            event.transition(
                ValidationStatus.INCONCLUSIVE,
                reason="validation_used_non_independent_evidence_family",
                at=attempt.answered_at,
            )
            self._schedule_replacement_validation(
                event,
                at=attempt.answered_at,
                reason="reused_family_validation_replacement_scheduled",
                additional_excluded_family_ids=(attempt.evidence_family_id,),
                additional_excluded_material_group_ids=(attempt.material_group_id,),
            )
            return hypothesis
        if attempt.material_group_id in event.excluded_material_group_ids:
            event.transition(
                ValidationStatus.INCONCLUSIVE,
                reason="validation_used_non_independent_material_group",
                at=attempt.answered_at,
            )
            self._schedule_replacement_validation(
                event,
                at=attempt.answered_at,
                reason="reused_material_validation_replacement_scheduled",
                additional_excluded_family_ids=(attempt.evidence_family_id,),
                additional_excluded_material_group_ids=(attempt.material_group_id,),
            )
            return hypothesis
        if attempt.correct:
            event.transition(
                ValidationStatus.PASSED,
                reason="unprompted_unexposed_cross_family_answer_was_correct",
                at=attempt.answered_at,
            )
            if event.kind is ValidationKind.NEAR_TRANSFER:
                hypothesis.transition(
                    HypothesisStatus.WEAKENED_BY_TRANSFER,
                    reason="independent_near_transfer_passed",
                    at=attempt.answered_at,
                )
                self._schedule_delayed_validation(hypothesis, attempt)
            else:
                hypothesis.transition(
                    HypothesisStatus.RESOLVED_AFTER_VALIDATION,
                    reason="independent_validation_passed_after_at_least_24_hours",
                    at=attempt.answered_at,
                )
            return hypothesis
        event.transition(
            ValidationStatus.FAILED,
            reason="independent_cross_family_validation_answer_was_incorrect",
            at=attempt.answered_at,
        )
        if hypothesis.status in {
            HypothesisStatus.AWAITING_TRANSFER,
            HypothesisStatus.WEAKENED_BY_TRANSFER,
        }:
            hypothesis.transition(
                HypothesisStatus.PERSISTENT_OR_RECURRENT,
                reason="independent_validation_failed",
                at=attempt.answered_at,
            )
        return hypothesis

    def _schedule_replacement_validation(
        self,
        event: ValidationEvent,
        *,
        at: datetime,
        reason: str,
        additional_excluded_family_ids: Iterable[str | None] = (),
        additional_excluded_material_group_ids: Iterable[str | None] = (),
    ) -> ValidationEvent | None:
        hypothesis = self._require_hypothesis(event.hypothesis_id)
        if hypothesis.status in _TERMINAL_HYPOTHESIS_STATUSES:
            return None
        excluded_families = set(event.excluded_family_ids)
        excluded_families.update(
            item
            for item in additional_excluded_family_ids
            if isinstance(item, str) and item
        )
        excluded_materials = set(event.excluded_material_group_ids)
        excluded_materials.update(
            item
            for item in additional_excluded_material_group_ids
            if isinstance(item, str) and item
        )
        if event.kind is ValidationKind.NEAR_TRANSFER:
            replacement = ValidationEvent(
                validation_event_id=self._next_id("validation"),
                kind=ValidationKind.NEAR_TRANSFER,
                hypothesis_id=event.hypothesis_id,
                diagnostic_unit_id=event.diagnostic_unit_id,
                created_at=at,
                scheduled_after_graded_count=self.global_graded_count,
                excluded_family_ids=frozenset(excluded_families),
                excluded_material_group_ids=frozenset(excluded_materials),
                earliest_gap=NEAR_TRANSFER_MIN_GAP,
                latest_gap=NEAR_TRANSFER_MAX_GAP,
                replacement_of_event_id=event.validation_event_id,
            )
        else:
            replacement = ValidationEvent(
                validation_event_id=self._next_id("validation"),
                kind=ValidationKind.DELAYED,
                hypothesis_id=event.hypothesis_id,
                diagnostic_unit_id=event.diagnostic_unit_id,
                created_at=at,
                scheduled_after_graded_count=self.global_graded_count,
                excluded_family_ids=frozenset(excluded_families),
                excluded_material_group_ids=frozenset(excluded_materials),
                due_at=max(at, event.due_at or at),
                replacement_of_event_id=event.validation_event_id,
            )
        self.validation_events[replacement.validation_event_id] = replacement
        hypothesis.validation_event_ids.append(replacement.validation_event_id)
        self._record_decision(
            action=RecommendationAction.VALIDATION_SCHEDULED,
            reason_codes=(
                reason,
                "replacement_preserves_independent_transfer_requirement",
            ),
            at=at,
            session=self.current_session,
            validation_event_id=replacement.validation_event_id,
            hypothesis_id=hypothesis.hypothesis_id,
            target_cause_id=(
                hypothesis.cause_candidates[0]
                if len(hypothesis.cause_candidates) == 1
                else None
            ),
        )
        return replacement

    def _schedule_delayed_validation(
        self, hypothesis: ErrorHypothesis, near_attempt: ScoredAttempt
    ) -> ValidationEvent:
        excluded = set(hypothesis.supporting_family_ids)
        excluded.add(near_attempt.evidence_family_id)
        excluded_materials = set(hypothesis.supporting_material_group_ids)
        excluded_materials.add(near_attempt.material_group_id)
        event = ValidationEvent(
            validation_event_id=self._next_id("validation"),
            kind=ValidationKind.DELAYED,
            hypothesis_id=hypothesis.hypothesis_id,
            diagnostic_unit_id=hypothesis.diagnostic_unit_id,
            created_at=near_attempt.answered_at,
            scheduled_after_graded_count=self.global_graded_count,
            excluded_family_ids=frozenset(excluded),
            excluded_material_group_ids=frozenset(excluded_materials),
            due_at=near_attempt.answered_at + timedelta(hours=DELAYED_VALIDATION_HOURS),
        )
        self.validation_events[event.validation_event_id] = event
        hypothesis.validation_event_ids.append(event.validation_event_id)
        self._record_decision(
            action=RecommendationAction.VALIDATION_SCHEDULED,
            reason_codes=(
                "independent_near_transfer_passed",
                "delayed_cross_family_validation_due_after_24_hours",
            ),
            at=near_attempt.answered_at,
            session=self.current_session,
            validation_event_id=event.validation_event_id,
            hypothesis_id=hypothesis.hypothesis_id,
        )
        return event

    def withdraw_hypothesis(
        self, hypothesis_id: str, *, reason: str, at: datetime
    ) -> ErrorHypothesis:
        _require_identifier("reason", reason)
        self._require_chronological(at)
        hypothesis = self._require_hypothesis(hypothesis_id)
        hypothesis.transition(HypothesisStatus.WITHDRAWN, reason=reason, at=at)
        self._open_probe_hypothesis_ids.discard(hypothesis_id)
        self._void_open_validations(hypothesis, reason=f"hypothesis_withdrawn:{reason}", at=at)
        self._touch(at)
        return hypothesis

    def void_hypothesis(
        self, hypothesis_id: str, *, reason: str, at: datetime
    ) -> ErrorHypothesis:
        _require_identifier("reason", reason)
        self._require_chronological(at)
        hypothesis = self._require_hypothesis(hypothesis_id)
        hypothesis.transition(HypothesisStatus.VOIDED, reason=reason, at=at)
        self._open_probe_hypothesis_ids.discard(hypothesis_id)
        self._void_open_validations(hypothesis, reason=f"hypothesis_voided:{reason}", at=at)
        self._touch(at)
        return hypothesis

    def _void_open_validations(
        self, hypothesis: ErrorHypothesis, *, reason: str, at: datetime
    ) -> None:
        for event_id in hypothesis.validation_event_ids:
            event = self.validation_events[event_id]
            if not event.is_terminal:
                event.transition(ValidationStatus.VOIDED, reason=reason, at=at)

    def _require_hypothesis(self, hypothesis_id: str) -> ErrorHypothesis:
        hypothesis = self.hypotheses.get(hypothesis_id)
        if hypothesis is None:
            raise InvalidSubmission(f"unknown hypothesis_id: {hypothesis_id}")
        return hypothesis

    def performance_for(self, diagnostic_unit_id: str) -> DiagnosticUnitPerformance:
        _require_identifier("diagnostic_unit_id", diagnostic_unit_id)
        evidence = [
            attempt
            for attempt in self.attempts
            if attempt.diagnostic_unit_id == diagnostic_unit_id
            and attempt.independent_evidence
        ]
        successes = [attempt for attempt in evidence if attempt.correct]
        failures = [attempt for attempt in evidence if not attempt.correct]
        updated_at = evidence[-1].answered_at if evidence else None

        if failures:
            last_failure = failures[-1]
            successes_after_failure = [
                item for item in successes if item.global_graded_ordinal > last_failure.global_graded_ordinal
            ]
            if (
                any(
                    item.global_graded_ordinal < last_failure.global_graded_ordinal
                    for item in successes
                )
                or len({item.evidence_family_id for item in failures}) >= 2
            ) and not successes_after_failure:
                status = PerformanceStatus.UNSTABLE
                reasons = ("independent_failure_after_success_or_across_two_families",)
            else:
                status, reasons = self._success_status(successes_after_failure)
        else:
            status, reasons = self._success_status(successes)

        return DiagnosticUnitPerformance(
            diagnostic_unit_id=diagnostic_unit_id,
            status=status,
            reason_codes=reasons,
            independent_success_attempt_ids=tuple(item.attempt_id for item in successes),
            independent_failure_attempt_ids=tuple(item.attempt_id for item in failures),
            independent_family_ids=tuple(item.evidence_family_id for item in evidence),
            updated_at=updated_at,
        )

    @staticmethod
    def _success_status(
        successes: list[ScoredAttempt],
    ) -> tuple[PerformanceStatus, tuple[str, ...]]:
        if not successes:
            return (
                PerformanceStatus.EVIDENCE_INSUFFICIENT,
                ("no_independent_success_after_latest_failure",),
            )
        if len(successes) == 1:
            return (
                PerformanceStatus.ONE_INDEPENDENT_SUCCESS,
                ("one_unprompted_unexposed_family_success",),
            )
        first_success_at = successes[0].answered_at
        delayed_successes = [
            item
            for item in successes[1:]
            if item.answered_at >= first_success_at + timedelta(hours=DELAYED_VALIDATION_HOURS)
        ]
        if delayed_successes:
            return (
                PerformanceStatus.RECENTLY_STABLE,
                ("repeated_success_plus_cross_family_success_after_24_hours",),
            )
        return (
            PerformanceStatus.REPEATED_INDEPENDENT_SUCCESS,
            ("two_cross_family_successes_without_delayed_confirmation",),
        )
