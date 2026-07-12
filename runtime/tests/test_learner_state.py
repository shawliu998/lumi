from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_runtime.learner_state import (
    LearnerStateStore,
    LearnerStateValidationError,
    LearnerStateVersionConflict,
)


class LearnerStateStoreTests(unittest.TestCase):
    namespace_id = "human:local-learner-01"
    evidence_origin = "human_local_interactive"
    learner_id = "local-learner-01"
    skill_id = "xingce.judgment.logic.necessary_condition"

    def setUp(self) -> None:
        self.store = LearnerStateStore(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def verification_event(
        self,
        event_id: str,
        *,
        namespace_id: str | None = None,
        evidence_origin: str | None = None,
        correct: bool = True,
        independently_answered: bool = True,
        hint_count: int = 0,
        content_signature: str = "sha256:transfer-01",
    ) -> dict[str, object]:
        return {
            "schema_version": "lumi.evidence-event.v1",
            "event_id": event_id,
            "namespace_id": namespace_id or self.namespace_id,
            "evidence_origin": evidence_origin or self.evidence_origin,
            "run_id": "run-local-01",
            "kind": "verification",
            "content_ref": {
                "pack_id": "xingce.judgment-reasoning.v1",
                "item_id": event_id,
                "content_signature": content_signature,
                "role": "transfer",
            },
            "observed": {
                "correct": correct,
                "independently_answered": independently_answered,
                "hint_count": hint_count,
            },
        }

    def commit(
        self,
        verification_id: str,
        evidence_event_id: str,
        *,
        expected_state_version: int,
        outcome: str = "passed",
        store: LearnerStateStore | None = None,
    ) -> dict[str, object]:
        return (store or self.store).commit_verification(
            namespace_id=self.namespace_id,
            evidence_origin=self.evidence_origin,
            learner_id=self.learner_id,
            skill_id=self.skill_id,
            verification_id=verification_id,
            evidence_event_id=evidence_event_id,
            expected_state_version=expected_state_version,
            outcome=outcome,
            unseen_from_content_signatures=("sha256:first-01", "sha256:teach-01"),
        )

    def test_facts_hypotheses_decisions_and_snapshots_are_all_local_to_one_origin(self) -> None:
        event = self.verification_event("evt-local-pass")
        self.store.append_evidence(event)
        self.store.append_hypothesis(
            {
                "schema_version": "lumi.diagnosis-hypothesis.v1",
                "hypothesis_id": "dxh-local-01",
                "namespace_id": self.namespace_id,
                "evidence_origin": self.evidence_origin,
                "episode_id": "episode-local-01",
                "skill_id": self.skill_id,
                "cause_id": "M-ROLE",
                "status": "unconfirmed",
                "evidence_refs": ["evt-local-pass"],
            }
        )
        snapshot = self.commit("vr-local-pass", "evt-local-pass", expected_state_version=0)
        self.store.append_policy_decision(
            {
                "schema_version": "lumi.policy-decision.v1",
                "decision_id": "pd-local-01",
                "namespace_id": self.namespace_id,
                "evidence_origin": self.evidence_origin,
                "learner_id": self.learner_id,
                "episode_id": "episode-local-01",
                "decision_type": "schedule_review",
                "selected_action_id": "review.jr.necessary.01",
                "state_snapshot_id": snapshot["snapshot_id"],
                "evidence_refs": ["evt-local-pass"],
            }
        )
        self.assertEqual(snapshot["state_delta"]["commit_status"], "committed")
        self.assertEqual(snapshot["state_delta"]["mastery_delta"], 0.04)
        self.assertEqual(snapshot["mastery"]["status"], "independent_transfer_supported")
        self.assertNotIn("cohort", repr(snapshot))
        self.assertNotIn("peer", repr(snapshot))
        decisions = self.store.replay_policy_decisions(
            namespace_id=self.namespace_id,
            evidence_origin=self.evidence_origin,
            learner_id=self.learner_id,
        )
        self.assertEqual([item["decision_id"] for item in decisions], ["pd-local-01"])

    def test_origin_cross_reference_fails_closed(self) -> None:
        self.store.append_evidence(
            self.verification_event(
                "evt-eval-only",
                namespace_id="eval:contract:run-01",
                evidence_origin="evaluation_fixture",
            )
        )
        with self.assertRaises(LearnerStateValidationError):
            self.commit("vr-cross-origin", "evt-eval-only", expected_state_version=0)
        self.assertIsNone(
            self.store.current_snapshot(
                namespace_id=self.namespace_id,
                evidence_origin=self.evidence_origin,
                learner_id=self.learner_id,
                skill_id=self.skill_id,
            )
        )

    def test_assisted_and_failed_verifications_are_withheld_with_zero_delta(self) -> None:
        self.store.append_evidence(
            self.verification_event("evt-assisted", hint_count=1)
        )
        assisted = self.commit("vr-assisted", "evt-assisted", expected_state_version=0)
        self.assertEqual(assisted["state_delta"]["commit_status"], "withheld")
        self.assertEqual(assisted["state_delta"]["mastery_delta"], 0.0)
        self.assertEqual(assisted["state_delta"]["withheld_reason"], "assisted_verification")

        self.store.append_evidence(
            self.verification_event("evt-failed", correct=False)
        )
        failed = self.commit(
            "vr-failed", "evt-failed", expected_state_version=1, outcome="failed"
        )
        self.assertEqual(failed["state_delta"]["commit_status"], "withheld")
        self.assertEqual(failed["state_delta"]["mastery_delta"], 0.0)
        self.assertEqual(failed["state_delta"]["withheld_reason"], "verification_not_passed")
        self.assertEqual(failed["mastery"]["value"], 0.0)
        self.assertEqual(
            [entry["state_version"] for entry in self.store.replay_snapshots(
                namespace_id=self.namespace_id,
                evidence_origin=self.evidence_origin,
                learner_id=self.learner_id,
                skill_id=self.skill_id,
            )],
            [1, 2],
        )

    def test_independent_unseen_unhinted_pass_commits_mastery(self) -> None:
        self.store.append_evidence(self.verification_event("evt-pass"))
        snapshot = self.commit("vr-pass", "evt-pass", expected_state_version=0)
        self.assertEqual(snapshot["state_version"], 1)
        self.assertEqual(snapshot["state_delta"], {
            "mastery_delta": 0.04,
            "commit_status": "committed",
            "withheld_reason": None,
        })
        current = self.store.current_snapshot(
            namespace_id=self.namespace_id,
            evidence_origin=self.evidence_origin,
            learner_id=self.learner_id,
            skill_id=self.skill_id,
        )
        self.assertEqual(current, snapshot)

    def test_teaching_or_probe_content_cannot_be_relabeled_as_transfer_evidence(self) -> None:
        event = self.verification_event("evt-teaching-role")
        event["content_ref"]["role"] = "teaching_asset"  # type: ignore[index]
        self.store.append_evidence(event)

        with self.assertRaisesRegex(
            LearnerStateValidationError, "role does not match verification_kind"
        ):
            self.commit("vr-teaching-role", "evt-teaching-role", expected_state_version=0)

    def test_replaying_same_verification_and_evidence_is_idempotent(self) -> None:
        self.store.append_evidence(self.verification_event("evt-idempotent"))
        first = self.commit("vr-idempotent", "evt-idempotent", expected_state_version=0)
        replay = self.commit("vr-idempotent", "evt-idempotent", expected_state_version=0)
        self.assertEqual(replay, first)
        replayed = self.store.replay_snapshots(
            namespace_id=self.namespace_id,
            evidence_origin=self.evidence_origin,
            learner_id=self.learner_id,
            skill_id=self.skill_id,
        )
        self.assertEqual(len(replayed), 1)

    def test_stale_compare_and_append_cannot_overwrite_newer_skill_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "learner-state.sqlite3"
            first = LearnerStateStore(database)
            second = LearnerStateStore(database)
            try:
                first.append_evidence(self.verification_event("evt-first"))
                self.commit(
                    "vr-first", "evt-first", expected_state_version=0, store=first
                )
                first.append_evidence(self.verification_event("evt-second"))
                with self.assertRaises(LearnerStateVersionConflict) as conflict:
                    self.commit(
                        "vr-second", "evt-second", expected_state_version=0, store=second
                    )
                self.assertEqual(conflict.exception.actual_version, 1)
                replayed = second.replay_snapshots(
                    namespace_id=self.namespace_id,
                    evidence_origin=self.evidence_origin,
                    learner_id=self.learner_id,
                    skill_id=self.skill_id,
                )
                self.assertEqual([item["trigger"]["verification_id"] for item in replayed], ["vr-first"])
            finally:
                first.close()
                second.close()

    def test_append_only_storage_rejects_update_and_delete(self) -> None:
        self.store.append_evidence(self.verification_event("evt-immutable"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(  # type: ignore[attr-defined]
                "DELETE FROM learner_state_evidence_events WHERE event_id = ?",
                ("evt-immutable",),
            )


if __name__ == "__main__":
    unittest.main()
