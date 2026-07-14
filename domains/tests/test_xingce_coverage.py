from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hermes_domains import xingce_coverage
from hermes_domains.xingce_coverage import (
    DEFAULT_COVERAGE_MATRIX,
    XingceCoverageError,
    coverage_summary,
    load_coverage_matrix,
    validate_coverage_matrix,
)


class XingceCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = load_coverage_matrix(DEFAULT_COVERAGE_MATRIX)

    def test_declares_every_canonical_module_and_records_bounded_owner_release(self) -> None:
        summary = coverage_summary(DEFAULT_COVERAGE_MATRIX)
        self.assertEqual(summary["total_subtypes"], 31)
        self.assertEqual(summary["released_subtypes"], 31)
        self.assertEqual(summary["reviewed_release_ready_subtypes"], 0)
        self.assertEqual(summary["planned_subtypes"], 0)
        self.assertTrue(summary["content_release_ready"])
        self.assertTrue(summary["is_complete"])
        self.assertEqual(
            set(summary["modules"]),
            {"verbal", "quantitative", "judgment", "data_analysis", "common_knowledge", "political_theory"},
        )
        self.assertTrue(all(module["total"] >= 1 for module in summary["modules"].values()))

    def test_every_release_records_the_waiver_and_absence_of_human_effect_evidence(self) -> None:
        released = [
            item for item in self.matrix["subtypes"] if item.get("release", {}).get("state") == "released"
        ]
        self.assertEqual(len(released), 31)
        for item in released:
            with self.subTest(subtype=item["id"]):
                declaration = item["release"]
                self.assertEqual(declaration["acceptance_basis"], "owner_acceptance_waiver")
                self.assertEqual(declaration["accepted_at"], "2026-07-14")
                self.assertEqual(declaration["waived_gate"], "type_by_type_human_local_browser_acceptance")
                self.assertEqual(declaration["human_effect_evidence"], "unavailable")
                self.assertEqual(declaration["claim_scope"], "content_and_mechanism_availability_only")

    def test_default_matrix_path_can_be_relocated_for_a_frozen_read_only_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            relocated = Path(directory) / "coverage-matrix.v1.json"
            relocated.write_text("{}", encoding="utf-8")
            with patch.object(xingce_coverage, "DEFAULT_COVERAGE_MATRIX", relocated):
                with self.assertRaisesRegex(XingceCoverageError, "missing schema_version"):
                    load_coverage_matrix()

    def test_visual_and_material_types_cannot_drop_immutable_evidence_requirements(self) -> None:
        broken = copy.deepcopy(self.matrix)
        graphic = next(item for item in broken["subtypes"] if item["id"] == "xingce.judgment.graphic_reasoning")
        graphic["content_requirements"].remove("asset_checksum")
        with self.assertRaisesRegex(XingceCoverageError, "visual subtype"):
            validate_coverage_matrix(broken)

        broken = copy.deepcopy(self.matrix)
        table = next(item for item in broken["subtypes"] if item["id"] == "xingce.data.table_material")
        table["content_requirements"].remove("material_checksum")
        with self.assertRaisesRegex(XingceCoverageError, "material subtype"):
            validate_coverage_matrix(broken)

    def test_planned_row_cannot_claim_a_pack_and_every_type_needs_competing_causes(self) -> None:
        broken = copy.deepcopy(self.matrix)
        verbal = next(item for item in broken["subtypes"] if item["id"] == "xingce.verbal.logical_cloze")
        verbal["release"] = {"state": "planned", "pack_id": "not-reviewed"}
        with self.assertRaisesRegex(XingceCoverageError, "planned subtype"):
            validate_coverage_matrix(broken)

        broken = copy.deepcopy(self.matrix)
        verbal = next(item for item in broken["subtypes"] if item["id"] == "xingce.verbal.logical_cloze")
        verbal["misconception_dimensions"] = ["semantic_collocation"]
        with self.assertRaisesRegex(XingceCoverageError, "at least two"):
            validate_coverage_matrix(broken)

    def test_release_cannot_omit_the_owner_decision_or_invent_human_effect_evidence(self) -> None:
        broken = copy.deepcopy(self.matrix)
        verbal = next(item for item in broken["subtypes"] if item["id"] == "xingce.verbal.logical_cloze")
        verbal["release"].pop("acceptance_basis")
        with self.assertRaisesRegex(XingceCoverageError, "owner_acceptance_waiver"):
            validate_coverage_matrix(broken)

        broken = copy.deepcopy(self.matrix)
        verbal = next(item for item in broken["subtypes"] if item["id"] == "xingce.verbal.logical_cloze")
        verbal["release"]["human_effect_evidence"] = "proven"
        with self.assertRaisesRegex(XingceCoverageError, "cannot claim human-effect evidence"):
            validate_coverage_matrix(broken)


if __name__ == "__main__":
    unittest.main()
