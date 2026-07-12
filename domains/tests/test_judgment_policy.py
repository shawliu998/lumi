from __future__ import annotations

import copy
import json
import unittest

from hermes_domains import (
    CALIBRATION_STATUS,
    POLICY_ID,
    POLICY_VERSION,
    EntryObservation,
    HistoricalCandidateEvidence,
    JudgmentPolicyError,
    diagnose_entry,
    resolve_probe,
)
from hermes_domains.reasoning_pack import DEFAULT_DRAFT_PACK_ROOT


def draft_records() -> list[dict]:
    document = json.loads((DEFAULT_DRAFT_PACK_ROOT / "records.json").read_text(encoding="utf-8"))
    return document["records"]


class JudgmentPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = draft_records()

    @staticmethod
    def wrong_direction_observation() -> EntryObservation:
        return EntryObservation(
            selected_option="B",
            correct_option="A",
            confidence="low",
            elapsed_seconds=8.5,
            hint_count=0,
        )

    def test_wrong_entry_keeps_facts_separate_and_candidates_unconfirmed(self) -> None:
        decision = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )

        self.assertEqual(decision.next_action, "probe")
        self.assertGreaterEqual(len(decision.candidate_causes), 2)
        self.assertEqual(tuple(cause.cause_id for cause in decision.candidate_causes), ("M-DIR", "M-READ"))
        self.assertTrue(all(cause.status == "unconfirmed" for cause in decision.candidate_causes))
        self.assertTrue(all(not cause.is_ground_truth for cause in decision.candidate_causes))
        self.assertTrue(all(fact.kind != "candidate_cause" for fact in decision.facts))
        self.assertTrue(all(cause.evidence_fact_ids for cause in decision.candidate_causes))
        self.assertEqual(decision.policy_id, POLICY_ID)
        self.assertEqual(decision.policy_version, POLICY_VERSION)
        self.assertEqual(decision.calibration_status, CALIBRATION_STATUS)

    def test_probe_selection_covers_candidates_minimally_and_is_deterministic(self) -> None:
        first = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )
        second = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )

        self.assertEqual(first.probe_plan, second.probe_plan)
        self.assertEqual(first.probe_plan.selected_probe_id, "P01")
        actions = {action.record_id: action for action in first.probe_plan.candidate_actions}
        self.assertEqual(set(actions), {"P01", "P02", "P03"})
        self.assertTrue(actions["P01"].selected)
        self.assertEqual(actions["P01"].coverage, ("M-DIR", "M-READ"))
        self.assertIn("最小探查", actions["P01"].why_selected or "")
        self.assertFalse(actions["P02"].selected)
        self.assertTrue(actions["P02"].why_not_selected)
        self.assertFalse(actions["P03"].selected)
        self.assertTrue(actions["P03"].why_not_selected)

    def test_no_single_probe_covering_both_candidates_abstains(self) -> None:
        records = copy.deepcopy(self.records)
        for record in records:
            if record["record_id"] == "P01":
                record["discriminates"] = ["M-DIR", "M-INF"]
            elif record["record_id"] == "P02":
                record["discriminates"] = ["M-ROLE", "M-INF"]
            elif record["record_id"] == "P03":
                record["discriminates"] = ["M-INF", "M-ROLE"]

        decision = diagnose_entry(
            records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )

        self.assertEqual(decision.next_action, "abstain")
        self.assertIsNone(decision.probe_plan.selected_probe_id)
        self.assertGreaterEqual(len(decision.candidate_causes), 2)
        self.assertTrue(all(cause.status == "unconfirmed" for cause in decision.candidate_causes))
        self.assertTrue(all(not action.selected for action in decision.probe_plan.candidate_actions))
        self.assertIn("没有一题", decision.probe_plan.why_selected)

    def test_probe_never_confirms_then_selects_linked_teaching_and_independent_transfer(self) -> None:
        decision = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )
        resolution = resolve_probe(self.records, decision=decision, selected_option="A")

        updates = {update.cause_id: update for update in resolution.evidence_updates}
        self.assertEqual(updates["M-DIR"].outcome, "support")
        self.assertEqual(updates["M-READ"].outcome, "insufficient")
        self.assertTrue(all(update.outcome in {"support", "refute", "insufficient"} for update in updates.values()))
        self.assertTrue(all(update.status == "unconfirmed" for update in updates.values()))
        self.assertTrue(all(not update.is_ground_truth for update in updates.values()))

        self.assertEqual(resolution.teaching_plan.selected_asset_id, "T01")
        self.assertEqual(resolution.teaching_plan.target_cause_id, "M-DIR")
        self.assertIn("候选仍未确认", resolution.teaching_plan.why_selected)
        self.assertEqual(resolution.transfer_plan.selected_transfer_id, "V01")
        self.assertEqual(
            resolution.transfer_plan.target_skill_ids,
            (
                "xingce.judgment.conditional.language_direction",
                "xingce.judgment.conditional.necessary_sufficient_role",
            ),
        )
        self.assertTrue(resolution.transfer_plan.requires_no_hints)
        self.assertNotIn(resolution.transfer_plan.independence_group, resolution.transfer_plan.excluded_independence_groups)
        self.assertIn("独立组", resolution.transfer_plan.why_selected)

    def test_probe_that_refutes_both_candidates_abstains_from_teaching(self) -> None:
        decision = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )
        resolution = resolve_probe(self.records, decision=decision, selected_option="C")

        self.assertEqual({update.outcome for update in resolution.evidence_updates}, {"refute"})
        self.assertTrue(resolution.teaching_plan.is_abstention)
        self.assertIn("没有支持任何候选", resolution.teaching_plan.why_selected)

    def test_authored_option_level_evidence_map_overrides_generic_distractor_labels(self) -> None:
        records = copy.deepcopy(self.records)
        probe = next(record for record in records if record["record_id"] == "P01")
        # The distractor is still labelled reversed_implication, but this
        # authored test mapping explicitly withholds causal support.  The
        # deterministic policy must follow the map rather than infer causes
        # from English label tokens.
        probe["candidate_evidence_map"]["A"] = {
            "M-DIR": "insufficient",
            "M-READ": "insufficient",
        }
        decision = diagnose_entry(
            records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
        )
        resolution = resolve_probe(records, decision=decision, selected_option="A")
        self.assertEqual({update.outcome for update in resolution.evidence_updates}, {"insufficient"})
        self.assertTrue(resolution.teaching_plan.is_abstention)

    def test_history_cannot_teach_without_current_probe_support(self) -> None:
        decision = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
            historical_context=(HistoricalCandidateEvidence("M-DIR", supported_count=99),),
        )
        resolution = resolve_probe(self.records, decision=decision, selected_option="B")
        self.assertTrue(resolution.teaching_plan.is_abstention)
        self.assertFalse(resolution.teaching_plan.history_used_for_tie_break)

    def test_history_breaks_only_a_current_supported_teaching_tie(self) -> None:
        records = copy.deepcopy(self.records)
        probe = next(record for record in records if record["record_id"] == "P01")
        probe["candidate_evidence_map"]["A"] = {"M-DIR": "support", "M-READ": "support"}
        teaching = next(record for record in records if record["record_id"] == "T01")
        teaching["candidate_misconception_ids"] = ["M-DIR", "M-READ"]
        decision = diagnose_entry(
            records,
            entry_record_id="D01",
            observation=self.wrong_direction_observation(),
            historical_context=(
                HistoricalCandidateEvidence("M-DIR", supported_count=1),
                HistoricalCandidateEvidence("M-READ", supported_count=3),
            ),
        )
        resolution = resolve_probe(records, decision=decision, selected_option="A")
        self.assertEqual(resolution.teaching_plan.target_cause_id, "M-READ")
        self.assertTrue(resolution.teaching_plan.history_used_for_tie_break)
        self.assertIn("既往探查观察", resolution.teaching_plan.why_selected)

    def test_correct_entry_creates_no_cause_and_does_not_open_probe(self) -> None:
        decision = diagnose_entry(
            self.records,
            entry_record_id="D01",
            observation=EntryObservation(
                selected_option="A",
                correct_option="A",
                confidence="high",
                elapsed_seconds=17,
                hint_count=0,
            ),
        )

        self.assertEqual(decision.next_action, "retention_or_abstain")
        self.assertEqual(decision.candidate_causes, ())
        self.assertTrue(decision.probe_plan.is_abstention)
        self.assertEqual(decision.probe_plan.candidate_actions, ())
        with self.assertRaisesRegex(JudgmentPolicyError, "requires a decision with a selected probe"):
            resolve_probe(self.records, decision=decision, selected_option="A")


if __name__ == "__main__":
    unittest.main()
