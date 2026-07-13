from __future__ import annotations

import unittest

from hermes_domains.xingce_adaptive_policy import (
    Observation,
    diagnose_entry,
    independent_transfer_proposal,
    resolve_probe,
)
from hermes_domains.xingce_coverage import load_coverage_matrix
from xingce_adaptive_fixtures import documents_for


class XingceAdaptivePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        subtype = next(row for row in load_coverage_matrix()["subtypes"] if row["id"] == "xingce.verbal.logical_cloze")
        self.manifest, self.records_document, _, _ = documents_for(subtype)
        self.records = self.records_document["records"]

    def test_wrong_entry_keeps_multiple_candidate_causes_unconfirmed(self) -> None:
        decision = diagnose_entry(
            self.records, scorer=self.manifest["scorer"], entry_record_id="D01",
            observation=Observation("B", "high", 18),
        )
        self.assertFalse(decision.correct)
        self.assertEqual(decision.next_step, "probe")
        self.assertEqual([candidate.status for candidate in decision.candidates], ["unconfirmed", "unconfirmed"])
        self.assertEqual(decision.probe_record_id, "P01")

    def test_probe_selects_authored_teaching_and_unseen_transfer_without_confirmation(self) -> None:
        entry = diagnose_entry(self.records, scorer=self.manifest["scorer"], entry_record_id="D01", observation=Observation("B", "low", 13))
        probe = resolve_probe(self.records, scorer=self.manifest["scorer"], entry=entry, observation=Observation("A", "medium", 9))
        self.assertEqual(probe.target_cause_id, "cause-1")
        self.assertEqual(probe.teaching_record_id, "T01")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))

    def test_only_unassisted_correct_transfer_can_propose_a_state_delta(self) -> None:
        entry = diagnose_entry(self.records, scorer=self.manifest["scorer"], entry_record_id="D01", observation=Observation("B", "low", 13))
        probe = resolve_probe(self.records, scorer=self.manifest["scorer"], entry=entry, observation=Observation("A", "medium", 9))
        passed = independent_transfer_proposal(self.records, scorer=self.manifest["scorer"], entry=entry, probe=probe, observation=Observation("A", "high", 15))
        self.assertTrue(passed["eligible"])
        self.assertTrue(passed["state_delta"]["requires_deterministic_committer"])
        self.assertEqual(passed["state_delta"]["candidate_status"], "unconfirmed")
        assisted = independent_transfer_proposal(self.records, scorer=self.manifest["scorer"], entry=entry, probe=probe, observation=Observation("A", "high", 15, hint_count=1))
        self.assertFalse(assisted["eligible"])
        self.assertEqual(assisted["reason"], "transfer_was_assisted")
        failed = independent_transfer_proposal(self.records, scorer=self.manifest["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 15))
        self.assertFalse(failed["eligible"])
        self.assertEqual(failed["reason"], "independent_transfer_not_passed")

    def test_correct_entry_never_invents_no_error_or_mastery(self) -> None:
        decision = diagnose_entry(self.records, scorer=self.manifest["scorer"], entry_record_id="D01", observation=Observation("A", "high", 12))
        self.assertTrue(decision.correct)
        self.assertEqual(decision.candidates, ())
        self.assertEqual(decision.next_step, "review_or_stop")

    def test_every_declared_subtype_profile_has_an_executable_unassisted_transfer_path(self) -> None:
        for subtype in load_coverage_matrix()["subtypes"]:
            with self.subTest(subtype=subtype["id"]):
                manifest, document, _, _ = documents_for(subtype)
                records = document["records"]
                entry_response = "999" if manifest["scorer"] == "authored_numeric_v1" else "B"
                entry = diagnose_entry(records, scorer=manifest["scorer"], entry_record_id="D01", observation=Observation(entry_response, "low", 10))
                probe = resolve_probe(records, scorer=manifest["scorer"], entry=entry, observation=Observation("A", "medium", 8))
                transfer_response = "12" if manifest["scorer"] == "authored_numeric_v1" else "A"
                proposal = independent_transfer_proposal(records, scorer=manifest["scorer"], entry=entry, probe=probe, observation=Observation(transfer_response, "high", 12))
                self.assertTrue(proposal["eligible"])
                self.assertEqual(proposal["state_delta"]["kind"], "bounded_independent_transfer_evidence")


if __name__ == "__main__":
    unittest.main()
