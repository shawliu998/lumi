from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.judgment_experiment import (  # noqa: E402
    POLICY_IDS,
    assert_redacted_output,
    commit_state_if_valid,
    frozen_manifest,
    isolated_database_path,
    run_experiment,
    verify_independent_transfer,
)
import evals.judgment_experiment.runner as experiment_runner  # noqa: E402


class JudgmentExperimentTests(unittest.TestCase):
    def test_replay_is_deterministic_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_report = run_experiment(first, seeds=(101, 102))
            second_report = run_experiment(second, seeds=(101, 102))
        self.assertEqual(
            json.dumps(first_report, sort_keys=True, separators=(",", ":")),
            json.dumps(second_report, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(first_report["manifest"]["manifest_hash"], frozen_manifest((101, 102))["manifest_hash"])
        self.assertEqual({arm["policy_id"] for arm in first_report["arms"]}, set(POLICY_IDS))

    def test_returned_artifacts_have_no_hidden_label_or_key_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = run_experiment(directory, seeds=(101,))
        assert_redacted_output(report)
        rendered = json.dumps(report, sort_keys=True)
        for forbidden in (
            "answer_key",
            "correct_option",
            "distractor_mapping",
            "hidden_ground_truth",
            "M-DIR",
            "M-ROLE",
            "M-INF",
            "M-READ",
            "NO_TARGET_CAUSE",
        ):
            self.assertNotIn(forbidden, rendered)
        for arm in report["arms"]:
            self.assertNotIn("selected_option", json.dumps(arm["trace"], sort_keys=True))
            self.assertEqual(arm["persona"]["evidence_origin"], "synthetic_isolated")

        # Policy inputs contain committed observables only; item selection is
        # resolved by the evaluator just before presentation, not exposed early.
        context = experiment_runner._policy_context(
            {
                "selected_option": "A",
                "rationale_class": "omitted",
                "confidence": "low",
                "elapsed_seconds": 11,
                "help_opened": False,
            },
            ("implication_direction", "condition_role"),
            {"session_state": "unconfirmed", "evidence_origin": "synthetic_isolated"},
        )
        rendered_context = json.dumps(context, sort_keys=True)
        self.assertNotIn("transfer-conditional-02", rendered_context)
        self.assertNotIn("probe-direction-01", rendered_context)
        self.assertNotIn("correct", rendered_context)

    def test_every_policy_arm_gets_a_fresh_synthetic_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = run_experiment(directory, seeds=(101, 102))
            manifest_hash = report["manifest"]["manifest_hash"]
            observed_database_ids = set()
            for arm in report["arms"]:
                self.assertTrue(arm["namespace_id"].startswith("synthetic:"))
                self.assertTrue(arm["synthetic"])
                self.assertEqual(arm["evidence_origin"], "synthetic_isolated")
                self.assertNotIn("human", arm["namespace_id"])
                observed_database_ids.add(arm["database_id"])
                db_path = isolated_database_path(
                    directory, manifest_hash, arm["policy_id"], arm["seed"]
                )
                self.assertTrue(db_path.is_file())
                with sqlite3.connect(db_path) as connection:
                    values = dict(connection.execute("SELECT key, value FROM synthetic_run_metadata"))
                self.assertEqual(values["synthetic"], "true")
                self.assertEqual(values["evidence_origin"], "synthetic_isolated")
                self.assertTrue(values["namespace_id"].startswith("synthetic:"))
                self.assertNotIn("human", " ".join(values.values()).lower())
            self.assertEqual(len(observed_database_ids), len(report["arms"]))
            self.assertEqual(report["origin_barrier"]["human_database_access"], "not_configured")

    def test_state_commits_only_after_valid_unhinted_independent_transfer(self) -> None:
        state_before = {
            "session_state": "unconfirmed",
            "independent_evidence_count": 0,
        }
        valid = {
            "role": "immediate_transfer",
            "scoreable": True,
            "scored_correct": True,
            "hint_count": 0,
            "help_opened": False,
            "repeated": False,
            "item_id": "transfer-new",
            "independence_group": "transfer-new-group",
        }
        state_after, receipt = commit_state_if_valid(
            state_before, valid, ("entry-old",), ("entry-group",)
        )
        self.assertEqual(receipt["outcome"], "committed")
        self.assertEqual(state_after["independent_evidence_count"], 1)

        for invalid in (
            {**valid, "hint_count": 1},
            {**valid, "help_opened": True},
            {**valid, "repeated": True},
            {**valid, "scored_correct": False},
            {**valid, "item_id": "entry-old"},
            {**valid, "independence_group": "entry-group"},
        ):
            withheld_state, withheld_receipt = commit_state_if_valid(
                state_before, invalid, ("entry-old",), ("entry-group",)
            )
            self.assertEqual(withheld_receipt["outcome"], "withheld")
            self.assertEqual(withheld_state, state_before)
            self.assertFalse(
                verify_independent_transfer(
                    invalid, ("entry-old",), ("entry-group",)
                )["allowed"]
            )


if __name__ == "__main__":
    unittest.main()
