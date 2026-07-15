from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from hermes_practice import (
    FIXED_SESSION_SIZE,
    HypothesisStatus,
    InvalidSubmission,
    InvalidTransition,
    PerformanceStatus,
    PracticePolicyEngine,
    QuestionCandidate,
    QuestionRole,
    RecommendationAction,
    SessionStatus,
    ValidationKind,
    ValidationStatus,
)


BASE = datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc)
GROWTH = "xingce.data.growth.direct-rate"


def question(
    number: int,
    *,
    unit: str = GROWTH,
    family: str | None = None,
    material: str | None = None,
    roles: frozenset[QuestionRole] | None = None,
) -> QuestionCandidate:
    return QuestionCandidate(
        question_id=f"q-{number:03d}",
        diagnostic_unit_id=unit,
        evidence_family_id=family or f"family-{number:03d}",
        material_group_id=material or f"material-{number:03d}",
        eligible_roles=roles or frozenset({QuestionRole.PRACTICE}),
    )


class PracticePolicyV2Tests(unittest.TestCase):
    def answer(
        self,
        engine: PracticePolicyEngine,
        candidate: QuestionCandidate,
        *,
        at: datetime,
        correct: bool = True,
        answer: str = "A",
        signature: str | None = None,
        causes: tuple[str, ...] = (),
        hints: int = 0,
    ):
        decision = engine.recommend_next([candidate], at=at)
        self.assertEqual(decision.action, RecommendationAction.SERVE_QUESTION)
        return engine.submit_answer(
            decision.decision_id,
            answer=answer,
            is_correct=correct,
            error_signature_id=signature,
            cause_candidates=causes,
            hints_used=hints,
            at=at + timedelta(seconds=10),
        )

    def make_supported_hypothesis(
        self,
        engine: PracticePolicyEngine,
        *,
        start: datetime = BASE,
        ambiguous: bool = False,
    ):
        causes = ("wrong_denominator", "ratio_not_rate") if ambiguous else (
            "wrong_denominator",
        )
        first = self.answer(
            engine,
            question(1, family="f-1", material="m-1"),
            at=start,
            correct=False,
            answer="B",
            signature="uses_current_value_as_denominator",
            causes=causes,
        )
        second = self.answer(
            engine,
            question(2, family="f-2", material="m-2"),
            at=start + timedelta(minutes=1),
            correct=False,
            answer="C",
            signature="uses_current_value_as_denominator",
            causes=causes,
        )
        hypothesis = engine.hypotheses[second.hypothesis_id]
        return first, second, hypothesis

    def make_near_transfer_pass(
        self,
    ) -> tuple[PracticePolicyEngine, object, object, datetime]:
        engine = PracticePolicyEngine()
        engine.start_session("s-1", started_at=BASE)
        _, second, hypothesis = self.make_supported_hypothesis(engine)
        self.assertEqual(
            second.feedback_decision.action,
            RecommendationAction.SHOW_MICRO_TUTORIAL,
        )
        near_event = engine.record_tutorial_shown(
            hypothesis.hypothesis_id,
            asset_id="growth-denominator-v1",
            at=BASE + timedelta(minutes=2),
        )
        self.answer(
            engine,
            question(10, unit="filler", family="ff-1", material="fm-1"),
            at=BASE + timedelta(minutes=3),
        )
        self.answer(
            engine,
            question(11, unit="filler", family="ff-2", material="fm-2"),
            at=BASE + timedelta(minutes=4),
        )
        near_candidate = question(
            12,
            family="f-3",
            material="m-3",
            roles=frozenset({QuestionRole.NEAR_TRANSFER}),
        )
        presented = engine.recommend_next(
            [near_candidate], at=BASE + timedelta(minutes=5)
        )
        self.assertEqual(presented.validation_event_id, near_event.validation_event_id)
        result = engine.submit_answer(
            presented.decision_id,
            answer="A",
            is_correct=True,
            at=BASE + timedelta(minutes=5, seconds=10),
        )
        self.assertEqual(near_event.status, ValidationStatus.PASSED)
        delayed = next(
            event
            for event in engine.validation_events.values()
            if event.kind is ValidationKind.DELAYED
        )
        return engine, hypothesis, delayed, result.attempt.answered_at

    def test_fixed_eight_answer_only_and_early_exit(self) -> None:
        engine = PracticePolicyEngine()
        session = engine.start_session("s-fixed", started_at=BASE)
        self.assertEqual(session.target_count, FIXED_SESSION_SIZE)
        first_decision = engine.recommend_next([question(1)], at=BASE)
        self.assertEqual(engine.pending_question_decision, first_decision)
        with self.assertRaises(InvalidSubmission):
            engine.submit_answer(
                first_decision.decision_id,
                answer="  ",
                is_correct=True,
                at=BASE + timedelta(seconds=1),
            )
        engine.submit_answer(
            first_decision.decision_id,
            answer="A",
            is_correct=True,
            at=BASE + timedelta(seconds=2),
        )
        for index in range(2, 9):
            self.answer(
                engine,
                question(index),
                at=BASE + timedelta(minutes=index),
            )
        self.assertEqual(session.item_count, 8)
        self.assertEqual(session.graded_count, 8)
        self.assertEqual(session.status, SessionStatus.COMPLETED)
        with self.assertRaises(InvalidTransition):
            engine.recommend_next([question(9)], at=BASE + timedelta(minutes=9))

        second = engine.start_session(
            "s-early", started_at=BASE + timedelta(hours=1)
        )
        self.answer(engine, question(9), at=BASE + timedelta(hours=1, minutes=1))
        engine.end_session_early(at=BASE + timedelta(hours=1, minutes=2))
        self.assertEqual(second.status, SessionStatus.ENDED_EARLY)
        self.assertEqual(second.item_count, 1)

    def test_repetition_requires_distinct_family_and_material(self) -> None:
        engine = PracticePolicyEngine()
        engine.start_session("s-repeat", started_at=BASE)
        first = self.answer(
            engine,
            question(1, family="family-a", material="shared-material"),
            at=BASE,
            correct=False,
            signature="wrong_base",
            causes=("base_period_confusion",),
        )
        second = self.answer(
            engine,
            question(2, family="family-b", material="shared-material"),
            at=BASE + timedelta(minutes=1),
            correct=False,
            signature="wrong_base",
            causes=("base_period_confusion",),
        )
        self.assertEqual(first.feedback_decision.action, RecommendationAction.LIGHT_FEEDBACK)
        self.assertEqual(second.feedback_decision.action, RecommendationAction.LIGHT_FEEDBACK)
        hypothesis = engine.hypotheses[first.hypothesis_id]
        self.assertEqual(hypothesis.status, HypothesisStatus.EVIDENCE_INSUFFICIENT)

        third = self.answer(
            engine,
            question(3, family="family-b", material="new-material"),
            at=BASE + timedelta(minutes=2),
            correct=False,
            signature="wrong_base",
            causes=("base_period_confusion",),
        )
        self.assertEqual(
            third.feedback_decision.action,
            RecommendationAction.SHOW_MICRO_TUTORIAL,
        )
        self.assertEqual(hypothesis.status, HypothesisStatus.SUPPORTED)
        self.assertEqual(hypothesis.supporting_family_ids, {"family-a", "family-b"})
        self.assertEqual(
            hypothesis.supporting_material_group_ids,
            {"shared-material", "new-material"},
        )

    def test_ambiguous_error_uses_optional_probe_and_skip_consumes_one_slot(self) -> None:
        engine = PracticePolicyEngine()
        session = engine.start_session("s-probe-skip", started_at=BASE)
        _, second, hypothesis = self.make_supported_hypothesis(
            engine, ambiguous=True
        )
        self.assertEqual(second.feedback_decision.action, RecommendationAction.SHOW_PROBE)
        self.assertEqual(
            hypothesis.status, HypothesisStatus.AWAITING_DISAMBIGUATION
        )
        self.assertEqual(
            engine.open_probe_hypothesis_ids, (hypothesis.hypothesis_id,)
        )
        paused = engine.recommend_next(
            [question(99)], at=BASE + timedelta(minutes=1, seconds=30)
        )
        self.assertEqual(paused.action, RecommendationAction.SHOW_PROBE)
        self.assertEqual(session.item_count, 2)
        self.assertIsNone(engine.pending_question_decision)
        skipped = engine.skip_probe(
            hypothesis.hypothesis_id, at=BASE + timedelta(minutes=2)
        )
        self.assertTrue(skipped.skipped)
        self.assertEqual(session.item_count, 3)
        self.assertEqual(session.graded_count, 2)
        self.assertEqual(engine.global_graded_count, 2)
        self.assertEqual(engine.open_probe_hypothesis_ids, ())
        with self.assertRaises(InvalidTransition):
            engine.skip_probe(
                hypothesis.hypothesis_id, at=BASE + timedelta(minutes=3)
            )

        answered_engine = PracticePolicyEngine()
        answered_session = answered_engine.start_session(
            "s-probe-answer", started_at=BASE
        )
        _, _, answered_hypothesis = self.make_supported_hypothesis(
            answered_engine, ambiguous=True
        )
        probe = answered_engine.submit_probe_answer(
            answered_hypothesis.hypothesis_id,
            answer="第一种步骤",
            supported_cause_id="wrong_denominator",
            at=BASE + timedelta(minutes=2),
        )
        self.assertFalse(probe.skipped)
        self.assertEqual(probe.decision.action, RecommendationAction.SHOW_MICRO_TUTORIAL)
        self.assertEqual(answered_hypothesis.status, HypothesisStatus.SUPPORTED)
        self.assertEqual(answered_session.item_count, 3)
        self.assertEqual(answered_session.graded_count, 3)

    def test_probe_opened_on_slot_eight_carries_into_the_next_fixed_session(self) -> None:
        engine = PracticePolicyEngine()
        first_session = engine.start_session("s-probe-at-eight", started_at=BASE)
        for index in range(1, 7):
            self.answer(
                engine,
                question(index, unit="filler"),
                at=BASE + timedelta(minutes=index),
            )
        causes = ("wrong_denominator", "ratio_not_rate")
        self.answer(
            engine,
            question(7, family="probe-f-1", material="probe-m-1"),
            at=BASE + timedelta(minutes=7),
            correct=False,
            signature="uses_current_value_as_denominator",
            causes=causes,
        )
        eighth = self.answer(
            engine,
            question(8, family="probe-f-2", material="probe-m-2"),
            at=BASE + timedelta(minutes=8),
            correct=False,
            signature="uses_current_value_as_denominator",
            causes=causes,
        )
        self.assertEqual(first_session.status, SessionStatus.COMPLETED)
        self.assertEqual(eighth.feedback_decision.action, RecommendationAction.SHOW_PROBE)

        second_session = engine.start_session(
            "s-probe-carried", started_at=BASE + timedelta(hours=1)
        )
        carried = engine.recommend_next(
            [question(9)], at=BASE + timedelta(hours=1, minutes=1)
        )
        self.assertEqual(carried.action, RecommendationAction.SHOW_PROBE)
        self.assertEqual(carried.slot, 1)
        skipped = engine.skip_probe(
            carried.hypothesis_id,
            at=BASE + timedelta(hours=1, minutes=2),
        )
        self.assertTrue(skipped.skipped)
        self.assertEqual(second_session.item_count, 1)
        next_question = engine.recommend_next(
            [question(9)], at=BASE + timedelta(hours=1, minutes=3)
        )
        self.assertEqual(next_question.action, RecommendationAction.SERVE_QUESTION)
        self.assertEqual(next_question.slot, 2)

    def test_near_transfer_crosses_session_without_extending_fixed_eight(self) -> None:
        engine = PracticePolicyEngine()
        first_session = engine.start_session("s-late", started_at=BASE)
        for index in range(1, 7):
            self.answer(
                engine,
                question(index, unit="filler"),
                at=BASE + timedelta(minutes=index),
            )
        first = self.answer(
            engine,
            question(7, family="gf-1", material="gm-1"),
            at=BASE + timedelta(minutes=7),
            correct=False,
            signature="wrong_base",
            causes=("base_confusion",),
        )
        second = self.answer(
            engine,
            question(8, family="gf-2", material="gm-2"),
            at=BASE + timedelta(minutes=8),
            correct=False,
            signature="wrong_base",
            causes=("base_confusion",),
        )
        hypothesis = engine.hypotheses[first.hypothesis_id]
        self.assertEqual(second.feedback_decision.action, RecommendationAction.SHOW_MICRO_TUTORIAL)
        self.assertEqual(first_session.status, SessionStatus.COMPLETED)
        event = engine.record_tutorial_shown(
            hypothesis.hypothesis_id,
            asset_id="base-v1",
            at=BASE + timedelta(minutes=9),
        )
        schedule_decision = engine.decisions[-1]
        self.assertIn(
            "deferred_across_session_without_extending_fixed_eight",
            schedule_decision.reason_codes,
        )

        next_session = engine.start_session(
            "s-next", started_at=BASE + timedelta(hours=1)
        )
        self.answer(
            engine,
            question(20, unit="filler-2"),
            at=BASE + timedelta(hours=1, minutes=1),
        )
        self.assertEqual(event.status, ValidationStatus.SCHEDULED)
        self.answer(
            engine,
            question(21, unit="filler-2"),
            at=BASE + timedelta(hours=1, minutes=2),
        )
        transfer = question(
            22,
            family="gf-3",
            material="gm-3",
            roles=frozenset({QuestionRole.NEAR_TRANSFER}),
        )
        decision = engine.recommend_next(
            [transfer], at=BASE + timedelta(hours=1, minutes=3)
        )
        self.assertEqual(decision.role, QuestionRole.NEAR_TRANSFER)
        self.assertEqual(decision.validation_event_id, event.validation_event_id)
        self.assertEqual(decision.slot, 3)
        self.assertEqual(next_session.target_count, 8)

    def test_near_transfer_expires_after_four_intervening_graded_items(self) -> None:
        engine = PracticePolicyEngine()
        engine.start_session("s-expiry", started_at=BASE)
        _, _, hypothesis = self.make_supported_hypothesis(engine)
        event = engine.record_tutorial_shown(
            hypothesis.hypothesis_id,
            asset_id="tutorial-v1",
            at=BASE + timedelta(minutes=2),
        )
        for index in range(5):
            self.answer(
                engine,
                question(30 + index, unit="filler"),
                at=BASE + timedelta(minutes=3 + index),
            )
        engine.refresh_validations(at=BASE + timedelta(minutes=9))
        self.assertEqual(event.status, ValidationStatus.INCONCLUSIVE)
        self.assertEqual(
            event.transitions[-1].reason,
            "near_transfer_window_missed_without_extending_session",
        )
        replacement = next(
            item
            for item in engine.validation_events.values()
            if item.replacement_of_event_id == event.validation_event_id
        )
        self.assertEqual(replacement.kind, ValidationKind.NEAR_TRANSFER)
        self.assertEqual(replacement.status, ValidationStatus.SCHEDULED)
        self.assertEqual(
            replacement.scheduled_after_graded_count,
            engine.global_graded_count,
        )

    def test_delayed_validation_requires_24_hours_and_cross_family_material(self) -> None:
        engine, hypothesis, delayed, near_passed_at = self.make_near_transfer_pass()
        engine.end_session_early(at=near_passed_at + timedelta(minutes=1))
        engine.refresh_validations(at=near_passed_at + timedelta(hours=23, minutes=59))
        self.assertEqual(delayed.status, ValidationStatus.SCHEDULED)

        due = near_passed_at + timedelta(hours=24)
        engine.start_session("s-delayed", started_at=due)
        same_material = question(
            40,
            family="f-4",
            material="m-3",
            roles=frozenset({QuestionRole.DELAYED_VALIDATION}),
        )
        independent = question(
            41,
            family="f-4",
            material="m-4",
            roles=frozenset({QuestionRole.DELAYED_VALIDATION}),
        )
        decision = engine.recommend_next([same_material, independent], at=due)
        self.assertEqual(decision.question_id, independent.question_id)
        self.assertEqual(decision.role, QuestionRole.DELAYED_VALIDATION)
        result = engine.submit_answer(
            decision.decision_id,
            answer="A",
            is_correct=True,
            at=due + timedelta(seconds=10),
        )
        self.assertEqual(delayed.status, ValidationStatus.PASSED)
        self.assertEqual(
            hypothesis.status, HypothesisStatus.RESOLVED_AFTER_VALIDATION
        )
        self.assertEqual(result.performance.status, PerformanceStatus.RECENTLY_STABLE)

    def test_helped_validation_is_inconclusive_and_cannot_resolve_hypothesis(self) -> None:
        engine, hypothesis, delayed, near_passed_at = self.make_near_transfer_pass()
        engine.end_session_early(at=near_passed_at + timedelta(minutes=1))
        due = near_passed_at + timedelta(hours=24)
        engine.start_session("s-helped-delayed", started_at=due)
        candidate = question(
            42,
            family="f-4",
            material="m-4",
            roles=frozenset({QuestionRole.DELAYED_VALIDATION}),
        )
        decision = engine.recommend_next([candidate], at=due)
        result = engine.submit_answer(
            decision.decision_id,
            answer="A",
            is_correct=True,
            hints_used=1,
            at=due + timedelta(seconds=10),
        )
        self.assertEqual(delayed.status, ValidationStatus.INCONCLUSIVE)
        self.assertEqual(hypothesis.status, HypothesisStatus.WEAKENED_BY_TRANSFER)
        self.assertFalse(result.attempt.independent_evidence)
        replacement = next(
            item
            for item in engine.validation_events.values()
            if item.replacement_of_event_id == delayed.validation_event_id
        )
        self.assertEqual(replacement.kind, ValidationKind.DELAYED)
        self.assertEqual(replacement.status, ValidationStatus.SCHEDULED)
        self.assertEqual(replacement.due_at, result.attempt.answered_at)
        self.assertIn(result.attempt.evidence_family_id, replacement.excluded_family_ids)
        self.assertIn(
            result.attempt.material_group_id,
            replacement.excluded_material_group_ids,
        )
        self.assertEqual(
            result.performance.status, PerformanceStatus.ONE_INDEPENDENT_SUCCESS
        )

    def test_ending_after_validation_presentation_schedules_an_independent_replacement(self) -> None:
        engine, hypothesis, delayed, near_passed_at = self.make_near_transfer_pass()
        engine.end_session_early(at=near_passed_at + timedelta(minutes=1))
        due = near_passed_at + timedelta(hours=24)
        engine.start_session("s-abandon-validation", started_at=due)
        candidate = question(
            43,
            family="f-abandoned",
            material="m-abandoned",
            roles=frozenset({QuestionRole.DELAYED_VALIDATION}),
        )
        decision = engine.recommend_next([candidate], at=due)
        self.assertEqual(decision.validation_event_id, delayed.validation_event_id)
        engine.end_session_early(at=due + timedelta(seconds=5))
        self.assertEqual(delayed.status, ValidationStatus.INCONCLUSIVE)
        replacement = next(
            item
            for item in engine.validation_events.values()
            if item.replacement_of_event_id == delayed.validation_event_id
        )
        self.assertEqual(replacement.kind, ValidationKind.DELAYED)
        self.assertEqual(replacement.due_at, due + timedelta(seconds=5))
        self.assertIn("f-abandoned", replacement.excluded_family_ids)
        self.assertIn("m-abandoned", replacement.excluded_material_group_ids)
        self.assertEqual(hypothesis.status, HypothesisStatus.WEAKENED_BY_TRANSFER)

    def test_help_exposure_family_and_material_do_not_add_positive_evidence(self) -> None:
        engine = PracticePolicyEngine()
        engine.start_session("s-evidence", started_at=BASE)
        first = self.answer(
            engine,
            question(1, family="f-1", material="m-1"),
            at=BASE,
        )
        self.assertTrue(first.attempt.independent_evidence)
        self.assertEqual(
            first.performance.status, PerformanceStatus.ONE_INDEPENDENT_SUCCESS
        )

        same_family = self.answer(
            engine,
            question(2, family="f-1", material="m-2"),
            at=BASE + timedelta(minutes=1),
        )
        self.assertFalse(same_family.attempt.independent_evidence)
        self.assertIn(
            "evidence_family_already_used",
            same_family.attempt.independent_ineligibility_reasons,
        )
        same_material = self.answer(
            engine,
            question(3, family="f-2", material="m-1"),
            at=BASE + timedelta(minutes=2),
        )
        self.assertFalse(same_material.attempt.independent_evidence)
        self.assertIn(
            "material_group_already_used",
            same_material.attempt.independent_ineligibility_reasons,
        )
        helped = self.answer(
            engine,
            question(4, family="f-3", material="m-3"),
            at=BASE + timedelta(minutes=3),
            hints=1,
        )
        self.assertFalse(helped.attempt.independent_evidence)
        self.assertIn(
            "help_used_on_question", helped.attempt.independent_ineligibility_reasons
        )
        exposed = self.answer(
            engine,
            question(1, family="f-1", material="m-1"),
            at=BASE + timedelta(minutes=4),
        )
        self.assertFalse(exposed.attempt.independent_evidence)
        self.assertIn(
            "question_previously_exposed",
            exposed.attempt.independent_ineligibility_reasons,
        )
        second = self.answer(
            engine,
            question(5, family="f-4", material="m-4"),
            at=BASE + timedelta(minutes=5),
        )
        self.assertEqual(
            second.performance.status,
            PerformanceStatus.REPEATED_INDEPENDENT_SUCCESS,
        )
        delayed = self.answer(
            engine,
            question(6, family="f-5", material="m-5"),
            at=BASE + timedelta(hours=25, minutes=5),
        )
        self.assertEqual(delayed.performance.status, PerformanceStatus.RECENTLY_STABLE)
        self.assertEqual(
            len(delayed.performance.independent_success_attempt_ids), 3
        )

    def test_helped_error_cannot_create_or_confirm_a_cause_hypothesis(self) -> None:
        engine = PracticePolicyEngine()
        engine.start_session("s-helped-error", started_at=BASE)
        helped = self.answer(
            engine,
            question(1, family="f-helped", material="m-helped"),
            at=BASE,
            correct=False,
            signature="wrong_base",
            causes=("base_period_confusion",),
            hints=1,
        )
        self.assertFalse(helped.attempt.independent_evidence)
        self.assertIsNone(helped.hypothesis_id)
        self.assertEqual(helped.feedback_decision.action, RecommendationAction.LIGHT_FEEDBACK)
        self.assertIn(
            "error_signature_observed_without_independent_evidence",
            helped.feedback_decision.reason_codes,
        )
        self.assertEqual(engine.hypotheses, {})

        independent = self.answer(
            engine,
            question(2, family="f-independent", material="m-independent"),
            at=BASE + timedelta(minutes=1),
            correct=False,
            signature="wrong_base",
            causes=("base_period_confusion",),
        )
        hypothesis = engine.hypotheses[independent.hypothesis_id]
        self.assertEqual(hypothesis.status, HypothesisStatus.EVIDENCE_INSUFFICIENT)
        self.assertEqual(hypothesis.supporting_family_ids, {"f-independent"})

    def test_policy_rejects_backdated_answers_and_inconsistent_error_metadata(self) -> None:
        engine = PracticePolicyEngine()
        engine.start_session("s-input-integrity", started_at=BASE)
        decision = engine.recommend_next([question(1)], at=BASE + timedelta(minutes=1))
        with self.assertRaises(InvalidTransition):
            engine.submit_answer(
                decision.decision_id,
                answer="A",
                is_correct=True,
                at=BASE + timedelta(seconds=30),
            )
        with self.assertRaises(InvalidSubmission):
            engine.submit_answer(
                decision.decision_id,
                answer="A",
                is_correct=True,
                error_signature_id="impossible_on_correct_answer",
                at=BASE + timedelta(minutes=1, seconds=1),
            )
        with self.assertRaises(InvalidSubmission):
            engine.submit_answer(
                decision.decision_id,
                answer="B",
                is_correct=False,
                cause_candidates=("cause_without_signature",),
                at=BASE + timedelta(minutes=1, seconds=1),
            )
        accepted = engine.submit_answer(
            decision.decision_id,
            answer="A",
            is_correct=True,
            at=BASE + timedelta(minutes=1, seconds=1),
        )
        self.assertTrue(accepted.attempt.correct)

    def test_hypothesis_withdrawal_voids_validation_and_new_episode_is_created(self) -> None:
        engine = PracticePolicyEngine()
        engine.start_session("s-withdraw", started_at=BASE)
        _, _, hypothesis = self.make_supported_hypothesis(engine)
        event = engine.record_tutorial_shown(
            hypothesis.hypothesis_id,
            asset_id="tutorial-v1",
            at=BASE + timedelta(minutes=2),
        )
        with self.assertRaises(InvalidTransition):
            event.transition(
                ValidationStatus.PASSED,
                reason="illegal_shortcut",
                at=BASE + timedelta(minutes=3),
            )
        engine.withdraw_hypothesis(
            hypothesis.hypothesis_id,
            reason="content_mapping_retracted",
            at=BASE + timedelta(minutes=3),
        )
        self.assertEqual(hypothesis.status, HypothesisStatus.WITHDRAWN)
        self.assertEqual(event.status, ValidationStatus.VOIDED)
        with self.assertRaises(InvalidTransition):
            engine.withdraw_hypothesis(
                hypothesis.hypothesis_id,
                reason="duplicate_retraction",
                at=BASE + timedelta(minutes=4),
            )
        with self.assertRaises(InvalidTransition):
            hypothesis.transition(
                HypothesisStatus.RESOLVED_AFTER_VALIDATION,
                reason="illegal_terminal_jump",
                at=BASE + timedelta(minutes=4),
            )

        third = self.answer(
            engine,
            question(50, family="f-new-1", material="m-new-1"),
            at=BASE + timedelta(minutes=5),
            correct=False,
            signature=hypothesis.error_signature_id,
            causes=("wrong_denominator",),
        )
        fourth = self.answer(
            engine,
            question(51, family="f-new-2", material="m-new-2"),
            at=BASE + timedelta(minutes=6),
            correct=False,
            signature=hypothesis.error_signature_id,
            causes=("wrong_denominator",),
        )
        replacement = engine.hypotheses[fourth.hypothesis_id]
        self.assertNotEqual(replacement.hypothesis_id, hypothesis.hypothesis_id)
        self.assertEqual(replacement.episode, 2)
        self.assertEqual(third.feedback_decision.action, RecommendationAction.LIGHT_FEEDBACK)
        self.assertEqual(fourth.feedback_decision.action, RecommendationAction.SHOW_MICRO_TUTORIAL)


if __name__ == "__main__":
    unittest.main()
