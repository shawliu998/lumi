from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from hermes_practice import (
    NEXT_SCOPE_POLICY_ID,
    NEXT_SCOPE_POLICY_VERSION,
    QuestionRole,
    ScoredAttempt,
    recommend_next_scope,
)


BASE = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)
VERBAL = "xingce.verbal.core"
JUDGMENT = "xingce.judgment.core"
MIXED = "xingce.mixed.core"
V1 = "xingce.verbal.skill-one"
V2 = "xingce.verbal.skill-two"
J1 = "xingce.judgment.skill-one"
J2 = "xingce.judgment.skill-two"


def scope_records() -> list[dict[str, object]]:
    return [
        {"scope_id": VERBAL, "diagnostic_unit_ids": [V1, V2], "title": "言语"},
        {
            "scope_id": JUDGMENT,
            "diagnostic_unit_ids": [J1, J2],
            "title": "判断",
        },
        {
            "scope_id": MIXED,
            "diagnostic_unit_ids": [V1, V2, J1, J2],
            "title": "混合",
        },
    ]


def attempt(
    number: int,
    *,
    session: str | None = None,
    question: str | None = None,
    unit: str = V1,
    family: str | None = None,
    correct: bool = False,
    independent: bool = True,
    minutes: int | None = None,
    signature: str | None = "signature-one",
    causes: tuple[str, ...] = ("cause-one",),
) -> dict[str, object]:
    return {
        "attempt_id": f"attempt-{number:03d}",
        "session_id": session or f"session-{number:03d}",
        "question_id": question or f"question-{number:03d}",
        "diagnostic_unit_id": unit,
        "evidence_family_id": family or f"family-{number:03d}",
        "correct": correct,
        "independent_evidence": independent,
        "answered_at": (
            BASE + timedelta(minutes=number if minutes is None else minutes)
        ).isoformat(),
        "error_signature_id": None if correct else signature,
        "cause_candidates": () if correct else causes,
        # Extra service snapshot fields are intentionally ignored.
        "question_version_id": "1.0.1",
        "response_time_seconds": 22,
    }


def recommend(
    attempts: list[dict[str, object] | ScoredAttempt],
    *,
    current: str | None = MIXED,
    scopes: list[dict[str, object]] | None = None,
    limit: int = 16,
) -> dict[str, object]:
    return recommend_next_scope(
        attempts=attempts,
        scopes=scopes or scope_records(),
        current_scope_id=current,
        mixed_scope_id=MIXED,
        decided_at=BASE + timedelta(days=1),
        recent_question_limit=limit,
    )


class NextScopePolicyTests(unittest.TestCase):
    def test_empty_evidence_keeps_current_or_uses_mixed_fallback(self) -> None:
        kept = recommend([], current=VERBAL)
        self.assertEqual(kept["decision"]["recommended_scope_id"], VERBAL)
        self.assertIn(
            "insufficient_evidence_keep_current_scope",
            kept["decision"]["reason_codes"],
        )
        self.assertEqual(kept["decision"]["evidence_refs"], [])
        self.assertEqual(kept["policy"]["id"], NEXT_SCOPE_POLICY_ID)
        self.assertEqual(kept["policy"]["version"], NEXT_SCOPE_POLICY_VERSION)
        json.dumps(kept, ensure_ascii=False)

        fallback = recommend([], current=None)
        self.assertEqual(fallback["decision"]["recommended_scope_id"], MIXED)
        self.assertIn(
            "no_current_scope_use_mixed_fallback",
            fallback["decision"]["reason_codes"],
        )

    def test_two_independent_failures_across_sessions_and_families_select_scope(self) -> None:
        result = recommend(
            [
                attempt(1, session="s-one", family="family-one"),
                attempt(2, session="s-two", family="family-two"),
            ]
        )
        self.assertEqual(result["decision"]["recommended_scope_id"], VERBAL)
        self.assertEqual(
            result["decision"]["evidence_refs"],
            ["attempt-001", "attempt-002"],
        )
        skill = result["skill_weakness_summaries"][0]
        self.assertEqual(skill["status"], "weakness_supported")
        self.assertEqual(skill["distinct_session_count"], 2)
        self.assertEqual(skill["distinct_failure_family_count"], 2)
        verbal = next(
            item for item in result["module_summaries"] if item["scope_id"] == VERBAL
        )
        self.assertEqual(verbal["status"], "weakness_supported")
        self.assertEqual(verbal["weak_skill_ids"], [V1])

    def test_same_session_family_or_non_independent_failure_cannot_redirect(self) -> None:
        cases = {
            "same_session": [
                attempt(1, session="same", family="family-one"),
                attempt(2, session="same", family="family-two"),
            ],
            "same_family": [
                attempt(1, session="s-one", family="same"),
                attempt(2, session="s-two", family="same"),
            ],
            "non_independent": [
                attempt(1, session="s-one", family="family-one"),
                attempt(
                    2,
                    session="s-two",
                    family="family-two",
                    independent=False,
                ),
            ],
        }
        for label, evidence in cases.items():
            with self.subTest(label=label):
                result = recommend(evidence, current=JUDGMENT)
                self.assertEqual(
                    result["decision"]["recommended_scope_id"], JUDGMENT
                )
                self.assertIn(
                    "no_cross_session_supported_weakness",
                    result["decision"]["reason_codes"],
                )

        excluded = recommend(cases["non_independent"])["evidence_accounting"]
        self.assertEqual(
            excluded["non_independent_excluded_from_weakness_refs"],
            ["attempt-002"],
        )

    def test_strongest_supported_module_wins_and_exact_tie_keeps_current(self) -> None:
        stronger_judgment = [
            attempt(1, session="v-s1", unit=V1, family="v-f1"),
            attempt(2, session="v-s2", unit=V1, family="v-f2"),
            attempt(3, session="j-s1", unit=J1, family="j-f1"),
            attempt(4, session="j-s2", unit=J1, family="j-f2"),
            attempt(5, session="j-s3", unit=J1, family="j-f3"),
        ]
        result = recommend(stronger_judgment, current=VERBAL)
        self.assertEqual(result["decision"]["recommended_scope_id"], JUDGMENT)

        tied = [
            attempt(1, session="v-s1", unit=V1, family="v-f1", minutes=1),
            attempt(2, session="v-s2", unit=V1, family="v-f2", minutes=4),
            attempt(3, session="j-s1", unit=J1, family="j-f1", minutes=2),
            attempt(4, session="j-s2", unit=J1, family="j-f2", minutes=4),
        ]
        kept = recommend(tied, current=VERBAL)
        self.assertEqual(kept["decision"]["recommended_scope_id"], VERBAL)
        self.assertIn(
            "deterministic_tie_kept_current_scope",
            kept["decision"]["reason_codes"],
        )

        alphabetical = recommend(tied, current=MIXED)
        self.assertEqual(alphabetical["decision"]["recommended_scope_id"], JUDGMENT)
        self.assertIn(
            "deterministic_tie_broken_by_scope_id",
            alphabetical["decision"]["reason_codes"],
        )

    def test_two_later_cross_session_successes_mark_recovery_and_prevent_redirect(self) -> None:
        result = recommend(
            [
                attempt(1, session="fail-one", family="fail-family-one"),
                attempt(2, session="fail-two", family="fail-family-two"),
                attempt(
                    3,
                    session="success-one",
                    family="success-family-one",
                    correct=True,
                ),
                attempt(
                    4,
                    session="success-two",
                    family="success-family-two",
                    correct=True,
                ),
            ],
            current=MIXED,
        )
        self.assertEqual(result["decision"]["recommended_scope_id"], MIXED)
        skill = result["skill_weakness_summaries"][0]
        self.assertEqual(skill["status"], "recovery_supported")
        self.assertEqual(skill["recovery_success_count"], 2)
        self.assertIn(
            "two_cross_session_cross_family_successes_follow_latest_failure",
            skill["reason_codes"],
        )

    def test_cause_candidates_are_ranked_reversible_hypotheses(self) -> None:
        result = recommend(
            [
                attempt(
                    1,
                    session="s-one",
                    family="family-one",
                    signature="sig-a",
                    causes=("cause-a", "cause-b"),
                ),
                attempt(
                    2,
                    session="s-two",
                    family="family-two",
                    signature="sig-a",
                    causes=("cause-a",),
                ),
            ]
        )
        hypotheses = result["skill_weakness_summaries"][0]["cause_hypotheses"]
        self.assertEqual([item["cause_id"] for item in hypotheses], ["cause-a", "cause-b"])
        self.assertEqual(hypotheses[0]["rank"], 1)
        self.assertEqual(hypotheses[0]["confidence_level"], "moderate")
        self.assertEqual(hypotheses[0]["confidence_score"], 60)
        self.assertIn("candidate_sets_are_ambiguous", hypotheses[0]["reason_codes"])
        self.assertEqual(hypotheses[1]["confidence_level"], "low")
        self.assertEqual(hypotheses[1]["confidence_score"], 25)
        self.assertTrue(
            all(
                "cause_remains_a_reversible_hypothesis" in item["reason_codes"]
                for item in hypotheses
            )
        )

    def test_recent_question_avoidance_is_deduplicated_bounded_and_soft(self) -> None:
        result = recommend(
            [
                attempt(1, question="q-one", independent=False),
                attempt(2, question="q-two", independent=False),
                attempt(3, question="q-one", independent=False),
                attempt(4, question="q-three", independent=False),
            ],
            limit=2,
        )
        hints = result["serving_hints"]
        self.assertEqual(hints["soft_avoid_question_ids"], ["q-three", "q-one"])
        self.assertEqual(hints["limit"], 2)
        self.assertIn("recent_question_avoidance_is_soft", hints["reason_codes"])
        self.assertIn(
            "soft_constraint_may_be_relaxed_if_pool_is_exhausted",
            hints["reason_codes"],
        )

    def test_input_order_and_identical_duplicates_do_not_change_output(self) -> None:
        evidence = [
            attempt(1, session="s-one", family="family-one"),
            attempt(2, session="s-two", family="family-two"),
        ]
        first = recommend_next_scope(
            attempts=evidence,
            scopes=scope_records(),
            current_scope_id=MIXED,
            mixed_scope_id=MIXED,
            decided_at="2026-07-16T08:00:00Z",
        )
        second = recommend_next_scope(
            attempts=[evidence[1], evidence[0], dict(evidence[0])],
            scopes=list(reversed(scope_records())),
            current_scope_id=MIXED,
            mixed_scope_id=MIXED,
            decided_at=datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(first, second)

    def test_scored_attempt_dataclass_is_accepted_without_adapter(self) -> None:
        scored = ScoredAttempt(
            attempt_id="attempt-real",
            session_id="session-real",
            source_decision_id="decision-real",
            question_id="question-real",
            diagnostic_unit_id=V1,
            evidence_family_id="family-real",
            material_group_id="material-real",
            role=QuestionRole.PRACTICE,
            answer="A",
            correct=False,
            hints_used=0,
            was_previously_exposed=False,
            independent_evidence=True,
            independent_ineligibility_reasons=(),
            error_signature_id="signature-real",
            cause_candidates=("cause-real",),
            answered_at=BASE,
            global_graded_ordinal=1,
            session_item_ordinal=1,
        )
        result = recommend([scored])
        self.assertEqual(
            result["skill_weakness_summaries"][0]["evidence_refs"],
            ["attempt-real"],
        )

    def test_out_of_catalog_evidence_is_accounted_but_cannot_redirect(self) -> None:
        outside = attempt(1, unit="another.domain.skill")
        result = recommend([outside], current=VERBAL)
        self.assertEqual(result["decision"]["recommended_scope_id"], VERBAL)
        self.assertEqual(
            result["evidence_accounting"]["out_of_catalog_evidence_refs"],
            ["attempt-001"],
        )
        self.assertEqual(result["evidence_accounting"]["independent_in_scope_count"], 0)

    def test_invalid_or_ambiguous_inputs_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "later than decided_at"):
            recommend_next_scope(
                attempts=[attempt(1, minutes=10)],
                scopes=scope_records(),
                current_scope_id=MIXED,
                mixed_scope_id=MIXED,
                decided_at=BASE,
            )

        conflicting = attempt(1)
        changed = dict(conflicting)
        changed["question_id"] = "different-question"
        with self.assertRaisesRegex(ValueError, "conflicting duplicate attempt_id"):
            recommend([conflicting, changed])

        overlapping = scope_records()
        overlapping[1] = {"scope_id": JUDGMENT, "diagnostic_unit_ids": [V1, J1]}
        with self.assertRaisesRegex(ValueError, "multiple module scopes"):
            recommend([], scopes=overlapping)

        unmapped_mixed = scope_records()
        unmapped_mixed[2] = {
            "scope_id": MIXED,
            "diagnostic_unit_ids": [V1, V2, J1, J2, "unmapped.skill"],
        }
        with self.assertRaisesRegex(ValueError, "unmapped diagnostic units"):
            recommend([], scopes=unmapped_mixed)

        with self.assertRaisesRegex(ValueError, "unknown current_scope_id"):
            recommend([], current="unknown.scope")

        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            recommend_next_scope(
                attempts=[],
                scopes=scope_records(),
                current_scope_id=MIXED,
                mixed_scope_id=MIXED,
                decided_at=datetime(2026, 7, 15, 8, 0),
            )

        with self.assertRaisesRegex(ValueError, "must be an integer"):
            recommend([], limit=True)

        inconsistent_correct = attempt(1, correct=True)
        inconsistent_correct["error_signature_id"] = "unexpected-signature"
        with self.assertRaisesRegex(ValueError, "correct attempt evidence"):
            recommend([inconsistent_correct])

        cause_without_signature = attempt(1)
        cause_without_signature["error_signature_id"] = None
        with self.assertRaisesRegex(ValueError, "cause candidates require"):
            recommend([cause_without_signature])


if __name__ == "__main__":
    unittest.main()
