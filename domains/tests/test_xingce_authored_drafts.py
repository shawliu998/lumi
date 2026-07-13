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
            CONTENT_ROOT / "verbal" / "lumi-main-idea-v0",
            CONTENT_ROOT / "verbal" / "lumi-detail-inference-v0",
            CONTENT_ROOT / "verbal" / "lumi-sentence-order-v0",
            CONTENT_ROOT / "quantitative" / "lumi-number-sequence-v0",
            CONTENT_ROOT / "quantitative" / "lumi-math-operations-v0",
            CONTENT_ROOT / "judgment" / "lumi-analogy-reasoning-v0",
            CONTENT_ROOT / "judgment" / "lumi-graphic-reasoning-v0",
            CONTENT_ROOT / "data_analysis" / "lumi-text-material-v0",
            CONTENT_ROOT / "data_analysis" / "lumi-table-material-v0",
            CONTENT_ROOT / "data_analysis" / "lumi-chart-material-v0",
            CONTENT_ROOT / "data_analysis" / "lumi-composite-material-v0",
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

    def test_analogy_draft_uses_relation_proof_and_an_unseen_tool_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "judgment" / "lumi-analogy-reasoning-v0")
        entry = diagnose_entry(pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("C", "low", 15))
        probe = resolve_probe(pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("B", "medium", 8))
        self.assertEqual(probe.teaching_record_id, "T-LVL")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))
        transfer = independent_transfer_proposal(pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("A", "high", 10))
        self.assertTrue(transfer["eligible"])

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

    def test_text_material_draft_keeps_material_visible_and_teaches_before_an_unseen_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "data_analysis" / "lumi-text-material-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 20)
        )
        self.assertFalse(entry.correct)
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("A", "medium", 9)
        )
        self.assertEqual(probe.teaching_record_id, "T-SER")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 18)
        )
        self.assertTrue(transfer["eligible"])
        self.assertEqual(transfer["state_delta"]["candidate_status"], "unconfirmed")

    def test_table_material_draft_uses_a_scoped_accessible_table_before_unseen_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "data_analysis" / "lumi-table-material-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 17)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("A", "low", 8)
        )
        self.assertEqual(probe.teaching_record_id, "T-ROWCOL")
        self.assertEqual(probe.transfer_record_id, "V01")
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 14)
        )
        self.assertTrue(transfer["eligible"])

    def test_chart_material_draft_binds_accessible_chart_data_to_a_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "data_analysis" / "lumi-chart-material-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 16)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("A", "low", 7)
        )
        self.assertEqual(probe.teaching_record_id, "T-SER")
        self.assertEqual(probe.transfer_record_id, "V01")
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 12)
        )
        self.assertTrue(transfer["eligible"])

    def test_composite_material_draft_aligns_narrative_scope_with_table_before_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "data_analysis" / "lumi-composite-material-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 19)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("A", "low", 8)
        )
        self.assertEqual(probe.teaching_record_id, "T-ALIGN")
        self.assertEqual(probe.transfer_record_id, "V01")
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 13)
        )
        self.assertTrue(transfer["eligible"])

    def test_graphic_reasoning_draft_uses_hashed_accessible_diagrams_and_unseen_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "judgment" / "lumi-graphic-reasoning-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 16)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("D", "low", 8)
        )
        self.assertEqual(probe.teaching_record_id, "T-FEATURE")
        self.assertEqual(probe.transfer_record_id, "V01")
        self.assertTrue(all(row["status"] == "unconfirmed" for row in probe.evidence_updates))
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("A", "high", 14)
        )
        self.assertTrue(transfer["eligible"])

    def test_main_idea_draft_distinguishes_examples_from_claims_before_unseen_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "verbal" / "lumi-main-idea-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 20)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("B", "low", 10)
        )
        self.assertEqual(probe.teaching_record_id, "T-EXAMPLE")
        self.assertEqual(probe.transfer_record_id, "V01")
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("C", "high", 15)
        )
        self.assertTrue(transfer["eligible"])

    def test_detail_inference_draft_withholds_causal_and_scope_leaps_before_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "verbal" / "lumi-detail-inference-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("A", "medium", 22)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("A", "low", 9)
        )
        self.assertEqual(probe.teaching_record_id, "T-UNSTATED")
        self.assertEqual(probe.transfer_record_id, "V01")
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 14)
        )
        self.assertTrue(transfer["eligible"])

    def test_sentence_order_draft_distinguishes_reference_and_connection_before_transfer(self) -> None:
        pack = load_xingce_adaptive_pack(CONTENT_ROOT / "verbal" / "lumi-sentence-order-v0")
        entry = diagnose_entry(
            pack["records"], scorer=pack["scorer"], entry_record_id="D01", observation=Observation("B", "medium", 23)
        )
        probe = resolve_probe(
            pack["records"], scorer=pack["scorer"], entry=entry, observation=Observation("A", "low", 9)
        )
        self.assertEqual(probe.teaching_record_id, "T-REF")
        self.assertEqual(probe.transfer_record_id, "V01")
        transfer = independent_transfer_proposal(
            pack["records"], scorer=pack["scorer"], entry=entry, probe=probe, observation=Observation("B", "high", 16)
        )
        self.assertTrue(transfer["eligible"])


if __name__ == "__main__":
    unittest.main()
