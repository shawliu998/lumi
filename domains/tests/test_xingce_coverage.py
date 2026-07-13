from __future__ import annotations

import copy
import unittest

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

    def test_declares_every_canonical_module_and_does_not_overclaim_completion(self) -> None:
        summary = coverage_summary(DEFAULT_COVERAGE_MATRIX)
        self.assertEqual(summary["total_subtypes"], 31)
        self.assertEqual(summary["released_subtypes"], 1)
        self.assertEqual(summary["reviewed_release_ready_subtypes"], 30)
        self.assertEqual(summary["planned_subtypes"], 0)
        self.assertTrue(summary["content_release_ready"])
        self.assertFalse(summary["is_complete"])
        self.assertEqual(
            set(summary["modules"]),
            {"verbal", "quantitative", "judgment", "data_analysis", "common_knowledge", "political_theory"},
        )
        self.assertTrue(all(module["total"] >= 1 for module in summary["modules"].values()))

    def test_only_reviewed_conditional_pack_is_counted_as_released(self) -> None:
        released = [
            item for item in self.matrix["subtypes"] if item.get("release", {}).get("state") == "released"
        ]
        self.assertEqual([item["id"] for item in released], ["xingce.judgment.conditional_logic"])
        self.assertEqual(released[0]["release"]["pack_id"], "lumi-conditional-reasoning-v0")

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


if __name__ == "__main__":
    unittest.main()
