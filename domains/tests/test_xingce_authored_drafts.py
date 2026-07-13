from __future__ import annotations

from pathlib import Path
import unittest

from hermes_domains.xingce_adaptive_pack import XingceAdaptivePackError, load_xingce_adaptive_pack
from hermes_domains.xingce_adaptive_policy import Observation, diagnose_entry, independent_transfer_proposal, resolve_probe


CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content" / "xingce"


class XingceAuthoredDraftTests(unittest.TestCase):
    def test_checked_in_drafts_validate_but_cannot_be_registered(self) -> None:
        roots = (
            CONTENT_ROOT / "judgment" / "lumi-definition-reasoning-v0",
            CONTENT_ROOT / "verbal" / "lumi-logical-cloze-v0",
            CONTENT_ROOT / "quantitative" / "lumi-number-sequence-v0",
            CONTENT_ROOT / "quantitative" / "lumi-math-operations-v0",
        )
        for root in roots:
            with self.subTest(pack=root.name):
                pack = load_xingce_adaptive_pack(root)
                self.assertEqual(pack["status"], "draft_unreviewed")
                with self.assertRaisesRegex(XingceAdaptivePackError, "content_review_required"):
                    load_xingce_adaptive_pack(root, require_reviewed=True)

    def test_logical_cloze_draft_reaches_candidate_specific_teaching_then_unseen_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "verbal" / "lumi-logical-cloze-v0")
        entry = diagnose_entry(
            pack["records"],
            scorer=pack["scorer"],
            entry_record_id="D01",
            observation=Observation("B", "medium", 18),
        )
        probe = resolve_probe(
            pack["records"],
            scorer=pack["scorer"],
            entry=entry,
            observation=Observation("B", "medium", 9),
        )
        self.assertEqual(probe.teaching_record_id, "T01")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))
        transfer = independent_transfer_proposal(
            pack["records"],
            scorer=pack["scorer"],
            entry=entry,
            probe=probe,
            observation=Observation("B", "high", 11),
        )
        self.assertTrue(transfer["eligible"])
        self.assertEqual(transfer["state_delta"]["candidate_status"], "unconfirmed")

    def test_math_operations_draft_separates_rate_base_scope_and_calculation_candidates(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "quantitative" / "lumi-math-operations-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("480", "medium", 21)
        )
        self.assertFalse(entry.correct)
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("288", "medium", 11)
        )
        self.assertEqual(probe.teaching_record_id, "T-SCOPE")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("100", "high", 24)
        )
        self.assertTrue(transfer["eligible"])
        self.assertEqual(transfer["state_delta"]["candidate_status"], "unconfirmed")

    def test_number_sequence_draft_uses_numeric_probe_and_unseen_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "quantitative" / "lumi-number-sequence-v0")
        entry = diagnose_entry(
            pack["records"],
            scorer=pack["scorer"],
            entry_record_id="D01",
            observation=Observation("35", "medium", 18),
        )
        self.assertFalse(entry.correct)
        probe = resolve_probe(
            pack["records"],
            scorer=pack["scorer"],
            entry=entry,
            observation=Observation("35", "medium", 9),
        )
        self.assertEqual(probe.teaching_record_id, "T-STEP")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))
        transfer = independent_transfer_proposal(
            pack["records"],
            scorer=pack["scorer"],
            entry=entry,
            probe=probe,
            observation=Observation("39", "high", 11),
        )
        self.assertTrue(transfer["eligible"])
        self.assertEqual(transfer["state_delta"]["candidate_status"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()
