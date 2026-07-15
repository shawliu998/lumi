from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_domains.practice_v2 import (
    CURRENT_DENOMINATOR_SIGNATURE,
    DROPPED_NEGATIVE_SIGNATURE,
    RATIO_WITHOUT_MINUS_ONE_SIGNATURE,
    REQUIRED_ERROR_SIGNATURES,
    PracticeValidationError,
    are_independent,
    load_practice_catalog,
    load_practice_package,
    load_question_version,
    safe_question_view,
    score_question_version,
    validate_independent_evidence,
    validate_practice_package,
)


ROOT = Path(__file__).resolve().parents[1]
PRACTICE_ROOT = ROOT / "practice_v2"
PACKAGE_ID = "lumi.xingce.growth-rate.practice-v2"


def _contains_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return bool(set(value) & forbidden) or any(
            _contains_key(child, forbidden) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(child, forbidden) for child in value)
    return False


class PracticeV2ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_practice_catalog(PRACTICE_ROOT)
        cls.package = load_practice_package(PACKAGE_ID, practice_root=PRACTICE_ROOT)
        cls.questions = {question["question_id"]: question for question in cls.package["questions"]}

    def test_manifest_pins_one_versioned_package(self) -> None:
        self.assertEqual(len(self.catalog), 1)
        entry = self.catalog[0]
        self.assertEqual(entry["package_id"], PACKAGE_ID)
        self.assertEqual(entry["version"], "1.0.0")
        self.assertEqual(entry["diagnostic_unit_id"], "xingce.data-analysis.direct-growth-rate")

    def test_package_has_eighteen_core_and_eight_spacing_questions(self) -> None:
        counts = self.catalog[0]["counts"]
        self.assertEqual(counts["questions"], 26)
        self.assertEqual(counts["core"], 18)
        self.assertEqual(counts["filler"], 8)
        self.assertGreaterEqual(counts["evidence_families"], 6)

    def test_every_question_is_a_versioned_question_version(self) -> None:
        for question in self.package["questions"]:
            self.assertEqual(question["schema_version"], "hermes.question-version.v2")
            self.assertEqual(question["version"], "1.0.0")
            self.assertTrue(question["material_group_id"])
            self.assertTrue(question["evidence_family_id"])
            self.assertTrue(question["content_source_id"])
            self.assertEqual(
                set(question["role_eligibility"]),
                {
                    "regular_practice",
                    "near_transfer",
                    "delayed_validation",
                    "reserved_unexposed",
                    "filler",
                    "evidence_eligible",
                },
            )

    def test_three_observable_error_signatures_are_declared(self) -> None:
        ids = {item["signature_id"] for item in self.package["error_signatures"]}
        self.assertEqual(ids, REQUIRED_ERROR_SIGNATURES)
        for item in self.package["error_signatures"]:
            self.assertEqual(item["semantics"], "observed_option_pattern_not_mental_cause")

    def test_wrong_option_mapping_is_total_and_never_labels_correct_option(self) -> None:
        for question in self.package["questions"]:
            scoring = question["scoring"]
            expected = set(question["options"]) - {scoring["correct_option"]}
            self.assertEqual(set(scoring["error_option_mappings"]), expected)
            self.assertNotIn(scoring["correct_option"], scoring["error_option_mappings"])

    def test_core_growth_calculations_are_deterministically_recomputable(self) -> None:
        core = [q for q in self.package["questions"] if not q["role_eligibility"]["filler"]]
        for question in core:
            calculation = question["calculation"]
            expected = round(
                (calculation["current_value"] - calculation["base_value"])
                / calculation["base_value"]
                * 100,
                calculation["rounding_decimals"],
            )
            self.assertEqual(expected, calculation["expected_rate_percent"])
            self.assertEqual(
                question["options"][question["scoring"]["correct_option"]],
                question["scoring"]["canonical_answer"],
            )

    def test_four_delayed_items_are_reserved_and_pairwise_independent(self) -> None:
        delayed = [
            question
            for question in self.package["questions"]
            if question["role_eligibility"]["delayed_validation"]
        ]
        self.assertEqual(len(delayed), 4)
        for question in delayed:
            roles = question["role_eligibility"]
            self.assertTrue(roles["reserved_unexposed"])
            self.assertFalse(roles["regular_practice"])
            self.assertFalse(roles["near_transfer"])
        validate_independent_evidence(
            self.package,
            [question["question_id"] for question in delayed],
        )

    def test_independence_requires_different_family_and_material(self) -> None:
        same_family = self.questions["xingce.data.growth.v2.q01"], self.questions["xingce.data.growth.v2.q02"]
        same_material = self.questions["xingce.data.growth.v2.q03"], self.questions["xingce.data.growth.v2.q04"]
        independent = self.questions["xingce.data.growth.v2.q01"], self.questions["xingce.data.growth.v2.q05"]
        self.assertFalse(are_independent(*same_family))
        self.assertFalse(are_independent(*same_material))
        self.assertTrue(are_independent(*independent))

    def test_filler_is_excluded_from_independent_target_evidence(self) -> None:
        with self.assertRaisesRegex(PracticeValidationError, "filler or ineligible"):
            validate_independent_evidence(self.package, ["xingce.data.filler.v2.q01"])

    def test_safe_catalog_and_question_view_do_not_leak_answers(self) -> None:
        forbidden = {
            "scoring",
            "correct_option",
            "canonical_answer",
            "error_option_mappings",
            "feedback",
            "calculation",
            "cause_candidate_ids",
        }
        self.assertFalse(_contains_key(self.catalog, forbidden))
        question = self.questions["xingce.data.growth.v2.q01"]
        view = safe_question_view(question)
        self.assertFalse(_contains_key(view, forbidden))
        self.assertEqual(set(view["options"]), {"A", "B", "C", "D"})
        self.assertNotIn("material_group_id", view)
        self.assertNotIn("evidence_family_id", view)
        self.assertNotIn("role_eligibility", view)

    def test_deterministic_scoring_emits_observation_not_ground_truth_cause(self) -> None:
        question = self.questions["xingce.data.growth.v2.q01"]
        passing = score_question_version(question, "b")
        current_denominator = score_question_version(question, "C")
        self.assertTrue(passing["correct"])
        self.assertIsNone(passing["observed_error_signature_id"])
        self.assertEqual(passing["cause_candidate_ids"], [])
        self.assertFalse(current_denominator["correct"])
        self.assertEqual(
            current_denominator["observed_error_signature_id"],
            CURRENT_DENOMINATOR_SIGNATURE,
        )
        self.assertEqual(len(current_denominator["cause_candidate_ids"]), 2)
        self.assertNotIn("correct_option", current_denominator)

    def test_each_signature_is_covered_across_multiple_families(self) -> None:
        families = {signature_id: set() for signature_id in REQUIRED_ERROR_SIGNATURES}
        for question in self.package["questions"]:
            if question["role_eligibility"]["filler"]:
                continue
            for mapping in question["scoring"]["error_option_mappings"].values():
                if mapping["signature_id"]:
                    families[mapping["signature_id"]].add(question["evidence_family_id"])
        self.assertGreaterEqual(len(families[CURRENT_DENOMINATOR_SIGNATURE]), 6)
        self.assertGreaterEqual(len(families[RATIO_WITHOUT_MINUS_ONE_SIGNATURE]), 6)
        self.assertGreaterEqual(len(families[DROPPED_NEGATIVE_SIGNATURE]), 4)

    def test_provenance_is_original_limited_and_rights_gated(self) -> None:
        source = self.package["content_sources"][0]
        self.assertEqual(source["content_origin"], "synthetic_original")
        self.assertEqual(source["source_use"], "concept_structure_reference")
        self.assertEqual(source["reference_page_range"]["pdf_start"], 3)
        self.assertEqual(source["reference_page_range"]["pdf_end"], 5)
        self.assertEqual(source["rights_status"], "rights_review_required")
        self.assertEqual(source["authorization_status"], "internal_mvp_only")
        self.assertFalse(source["source_text_included"])

    def test_interventions_are_versioned_controlled_assets(self) -> None:
        interventions = self.package["interventions"]
        tutorials = interventions["microtutorials"]
        self.assertEqual(len(tutorials), 3)
        covered = set()
        for tutorial in tutorials:
            self.assertEqual(tutorial["schema_version"], "hermes.intervention-asset.v2")
            self.assertGreaterEqual(tutorial["estimated_seconds"], 30)
            self.assertLessEqual(tutorial["estimated_seconds"], 60)
            self.assertEqual(tutorial["authorization_status"], "internal_mvp_only")
            self.assertEqual(tutorial["review_status"], "human_review_required")
            covered.update(tutorial["target_signature_ids"])
        self.assertEqual(covered, REQUIRED_ERROR_SIGNATURES)

        probe = interventions["probes"][0]
        self.assertTrue(probe["optional"])
        self.assertTrue(probe["uses_session_slot"])
        self.assertEqual(set(probe["options"]), set(probe["option_results"]))
        supported = {
            result["supported_cause_id"]
            for result in probe["option_results"].values()
            if result["supported_cause_id"] is not None
        }
        self.assertEqual(supported, set(probe["candidate_cause_ids"]))

    def test_question_loader_returns_a_manifest_authorized_copy(self) -> None:
        loaded = load_question_version(
            "xingce.data.growth.v2.q01",
            practice_root=PRACTICE_ROOT,
        )
        self.assertEqual(loaded, self.questions["xingce.data.growth.v2.q01"])
        loaded["prompt"] = "mutated"
        again = load_question_version(
            "xingce.data.growth.v2.q01",
            practice_root=PRACTICE_ROOT,
        )
        self.assertNotEqual(again["prompt"], "mutated")


class PracticeV2FailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = load_practice_package(PACKAGE_ID, practice_root=PRACTICE_ROOT)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "practice_v2"
            shutil.copytree(PRACTICE_ROOT, copied)
            package_path = copied / "growth_rate.practice.v2.json"
            package_path.write_bytes(package_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(PracticeValidationError, "checksum mismatch"):
                load_practice_catalog(copied)

    def test_rejects_unlisted_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "practice_v2"
            shutil.copytree(PRACTICE_ROOT, copied)
            (copied / "unreviewed.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(PracticeValidationError, "unlisted practice JSON"):
                load_practice_catalog(copied)

    def test_rejects_wrong_deterministic_answer(self) -> None:
        package = copy.deepcopy(self.package)
        package["questions"][0]["calculation"]["expected_rate_percent"] = 14
        with self.assertRaisesRegex(PracticeValidationError, "does not match"):
            validate_practice_package(package)

    def test_rejects_missing_wrong_option_mapping(self) -> None:
        package = copy.deepcopy(self.package)
        package["questions"][0]["scoring"]["error_option_mappings"].pop("A")
        with self.assertRaisesRegex(PracticeValidationError, "every and only wrong option"):
            validate_practice_package(package)

    def test_rejects_unknown_signature_or_cause_reference(self) -> None:
        package = copy.deepcopy(self.package)
        mapping = package["questions"][0]["scoring"]["error_option_mappings"]["A"]
        mapping["cause_candidate_ids"] = ["cause.unknown"]
        with self.assertRaisesRegex(PracticeValidationError, "unknown cause"):
            validate_practice_package(package)

    def test_rejects_external_authorization_claim(self) -> None:
        package = copy.deepcopy(self.package)
        package["content_sources"][0]["authorization_status"] = "external_release"
        with self.assertRaisesRegex(PracticeValidationError, "internal MVP"):
            validate_practice_package(package)

    def test_rejects_delayed_items_that_share_a_family(self) -> None:
        package = copy.deepcopy(self.package)
        delayed = [
            question
            for question in package["questions"]
            if question["role_eligibility"]["delayed_validation"]
        ]
        delayed[1]["evidence_family_id"] = delayed[0]["evidence_family_id"]
        with self.assertRaisesRegex(PracticeValidationError, "shares an evidence family"):
            validate_practice_package(package)

    def test_rejects_filler_that_emits_target_signature(self) -> None:
        package = copy.deepcopy(self.package)
        filler = next(question for question in package["questions"] if question["role_eligibility"]["filler"])
        mapping = next(iter(filler["scoring"]["error_option_mappings"].values()))
        mapping["signature_id"] = CURRENT_DENOMINATOR_SIGNATURE
        mapping["cause_candidate_ids"] = ["cause.comparison-start-confusion"]
        with self.assertRaisesRegex(PracticeValidationError, "filler wrong options"):
            validate_practice_package(package)

    def test_rejects_microtutorial_without_human_review_gate(self) -> None:
        package = copy.deepcopy(self.package)
        package["interventions"]["microtutorials"][0]["review_status"] = "auto_approved"
        with self.assertRaisesRegex(PracticeValidationError, "human-review-required"):
            validate_practice_package(package)

    def test_rejects_probe_that_cannot_disambiguate_two_causes(self) -> None:
        package = copy.deepcopy(self.package)
        probe = package["interventions"]["probes"][0]
        probe["option_results"]["C"]["supported_cause_id"] = "cause.comparison-start-confusion"
        with self.assertRaisesRegex(PracticeValidationError, "distinguish at least two"):
            validate_practice_package(package)


if __name__ == "__main__":
    unittest.main()
