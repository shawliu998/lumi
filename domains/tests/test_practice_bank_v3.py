from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from hermes_domains.practice_bank_v3 import (
    DEFAULT_SCOPE_ID,
    EXPECTED_TOTAL,
    generate_practice_bank,
    load_practice_bank,
    load_scope_catalog,
    safe_bank_catalog,
    validate_practice_bank,
)
from hermes_domains.practice_v3_data_analysis import verify_data_analysis_question
from hermes_domains.practice_v3_quantitative import verify_quantitative_question
from hermes_domains.practice_v3_common import (
    MIXED_SCOPE_ID,
    MODULE_SCOPES,
    PracticeBankValidationError,
    safe_question_view,
    score_question,
)
from scripts.materialize_practice_bank import materialize


class PracticeBankV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bank = load_practice_bank()
        cls.questions = cls.bank["questions"]

    def test_manifest_pins_exactly_320_versions_across_four_modules(self) -> None:
        self.assertEqual(len(self.questions), EXPECTED_TOTAL)
        counts = Counter(item["module_id"] for item in self.questions)
        self.assertEqual(counts, Counter({scope: 80 for scope in MODULE_SCOPES.values()}))
        self.assertEqual(len({item["question_id"] for item in self.questions}), 320)
        self.assertEqual({item["version"] for item in self.questions}, {"1.0.1"})
        self.assertRegex(self.bank["generated_sha256"], r"^[0-9a-f]{64}$")

    def test_each_module_has_eight_units_ten_versions_and_balanced_keys(self) -> None:
        for module_scope in MODULE_SCOPES.values():
            questions = [item for item in self.questions if item["module_id"] == module_scope]
            units = Counter(item["diagnostic_unit_id"] for item in questions)
            keys = Counter(item["scoring"]["correct_option"] for item in questions)
            self.assertEqual(len(units), 8)
            self.assertEqual(set(units.values()), {10})
            self.assertEqual(keys, Counter({key: 20 for key in "ABCD"}))

    def test_answer_keys_are_balanced_without_the_question_id_modulo_leak(self) -> None:
        for module_scope in MODULE_SCOPES.values():
            questions = sorted(
                (item for item in self.questions if item["module_id"] == module_scope),
                key=lambda item: item["generation"]["local_index"],
            )
            keys = [item["scoring"]["correct_option"] for item in questions]
            self.assertNotEqual(keys, ["ABCD"[index % 4] for index in range(80)])
            for start in range(0, 80, 4):
                self.assertEqual(set(keys[start : start + 4]), set("ABCD"))

        mixed = sorted(self.questions, key=lambda item: item["question_id"])
        self.assertEqual(
            Counter(item["scoring"]["correct_option"] for item in mixed[:8]),
            Counter({key: 2 for key in "ABCD"}),
        )

    def test_every_module_reserves_sixteen_delayed_items(self) -> None:
        for module_scope in MODULE_SCOPES.values():
            questions = [item for item in self.questions if item["module_id"] == module_scope]
            regular = [item for item in questions if item["role_eligibility"]["regular_practice"]]
            delayed = [item for item in questions if item["role_eligibility"]["delayed_validation"]]
            self.assertEqual(len(regular), 64)
            self.assertEqual(len(delayed), 16)
            self.assertTrue(all(item["role_eligibility"]["reserved_unexposed"] for item in delayed))
            self.assertTrue(all(not item["role_eligibility"]["regular_practice"] for item in delayed))

    def test_eight_item_order_pairs_four_units_with_independent_evidence(self) -> None:
        for module_scope in MODULE_SCOPES.values():
            regular = sorted(
                (
                    item
                    for item in self.questions
                    if item["module_id"] == module_scope
                    and item["role_eligibility"]["regular_practice"]
                ),
                key=lambda item: item["question_id"],
            )[:8]
            units: dict[str, list[dict]] = defaultdict(list)
            for item in regular:
                units[item["diagnostic_unit_id"]].append(item)
            self.assertEqual(sorted(len(items) for items in units.values()), [2, 2, 2, 2])
            for items in units.values():
                self.assertNotEqual(items[0]["evidence_family_id"], items[1]["evidence_family_id"])
                self.assertNotEqual(items[0]["material_group_id"], items[1]["material_group_id"])

    def test_mixed_order_rotates_all_four_modules(self) -> None:
        regular = sorted(
            (item for item in self.questions if item["role_eligibility"]["regular_practice"]),
            key=lambda item: item["question_id"],
        )[:8]
        counts = Counter(item["module_id"] for item in regular)
        self.assertEqual(counts, Counter({scope: 2 for scope in MODULE_SCOPES.values()}))

    def test_each_signature_has_independent_family_and_material_evidence(self) -> None:
        observed: dict[str, tuple[set[str], set[str]]] = {}
        for question in self.questions:
            for mapping in question["scoring"]["error_option_mappings"].values():
                signature = mapping["signature_id"]
                if not signature:
                    continue
                families, materials = observed.setdefault(signature, (set(), set()))
                families.add(question["evidence_family_id"])
                materials.add(question["material_group_id"])
        declared = {item["signature_id"] for item in self.bank["error_signatures"]}
        self.assertEqual(set(observed), declared)
        self.assertTrue(all(len(families) >= 2 and len(materials) >= 2 for families, materials in observed.values()))

    def test_delayed_families_are_unseen_and_each_stimulus_has_its_own_material_group(self) -> None:
        self.assertEqual(
            len({item["material_group_id"] for item in self.questions}),
            EXPECTED_TOTAL,
        )
        by_unit: dict[str, list[dict]] = defaultdict(list)
        for question in self.questions:
            by_unit[question["diagnostic_unit_id"]].append(question)
        for questions in by_unit.values():
            regular_families = {
                item["evidence_family_id"]
                for item in questions
                if item["role_eligibility"]["regular_practice"]
            }
            delayed_families = {
                item["evidence_family_id"]
                for item in questions
                if item["role_eligibility"]["delayed_validation"]
            }
            self.assertTrue(regular_families.isdisjoint(delayed_families))
            self.assertEqual(len({item["material_group_id"] for item in questions}), 10)

    def test_definition_items_do_not_copy_the_correct_option_into_the_stem(self) -> None:
        definitions = [
            item
            for item in self.questions
            if item["verification"]["adapter"] == "judgment_definition_constraints_v1"
        ]
        self.assertEqual(len(definitions), 10)
        for question in definitions:
            self.assertNotIn(question["scoring"]["canonical_answer"], question["prompt"])

    def test_safe_projection_and_catalog_never_leak_authoring_evidence(self) -> None:
        protected = {
            "correct_option", "canonical_answer", "error_option", "signature_id", "cause_candidate_ids",
            "verification", "generation", "evidence_family", "material_group", "scoring",
        }
        for question in self.questions:
            view = safe_question_view(question)
            serialized = json.dumps(view, ensure_ascii=False).lower()
            self.assertTrue(all(token not in serialized for token in protected))
        catalog = safe_bank_catalog()
        serialized = json.dumps(catalog, ensure_ascii=False).lower()
        self.assertNotIn("correct_option", serialized)
        self.assertNotIn("verification", serialized)

        sample_path = Path(__file__).resolve().parents[1] / "practice_v3" / "samples.safe.json"
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
        self.assertEqual(sample["sample_count"], 8)
        self.assertEqual(
            sample["items"],
            [safe_question_view(question) for question in self.questions[:8]],
        )

    def test_deterministic_scorer_emits_observation_not_causal_truth(self) -> None:
        for question in self.questions:
            correct = score_question(question, question["scoring"]["correct_option"])
            self.assertTrue(correct["correct"])
            self.assertIsNone(correct["observed_error_signature_id"])
            targeted = next(
                option
                for option, mapping in question["scoring"]["error_option_mappings"].items()
                if mapping["signature_id"]
            )
            wrong = score_question(question, targeted)
            self.assertFalse(wrong["correct"])
            self.assertTrue(wrong["observed_error_signature_id"])
            self.assertTrue(wrong["cause_candidate_ids"])
            self.assertNotIn("ground_truth", wrong)

    def test_scope_catalog_exposes_four_modules_plus_one_reused_mixed_pool(self) -> None:
        scopes = load_scope_catalog()
        self.assertEqual({item["scope_id"] for item in scopes}, {*MODULE_SCOPES.values(), MIXED_SCOPE_ID})
        self.assertEqual(DEFAULT_SCOPE_ID, MODULE_SCOPES["data-analysis"])
        mixed = next(item for item in scopes if item["scope_id"] == MIXED_SCOPE_ID)
        self.assertEqual(mixed["question_count"], 320)
        self.assertEqual(len(mixed["diagnostic_unit_ids"]), 32)

    def test_tampering_with_question_content_fails_semantic_validation(self) -> None:
        tampered = copy.deepcopy(self.bank)
        tampered.pop("generated_sha256")
        tampered["questions"][0]["scoring"]["canonical_answer"] = "被篡改"
        with self.assertRaises(PracticeBankValidationError):
            validate_practice_bank(tampered)

    def test_tampering_with_generation_slot_or_common_contract_fails_closed(self) -> None:
        slot_tampered = copy.deepcopy(self.bank)
        slot_tampered.pop("generated_sha256")
        slot_tampered["questions"][0]["generation"]["variant"] = 1
        with self.assertRaises(PracticeBankValidationError):
            validate_practice_bank(slot_tampered)

        status_tampered = copy.deepcopy(self.bank)
        status_tampered.pop("generated_sha256")
        status_tampered["questions"][0]["status"] = "published_external"
        with self.assertRaises(PracticeBankValidationError):
            validate_practice_bank(status_tampered)

    def test_arithmetic_oracles_reject_zero_division_inconsistent_and_tied_inputs(self) -> None:
        work = copy.deepcopy(
            next(
                item
                for item in self.questions
                if item["verification"]["adapter"] == "qty.work.parallel.v1"
            )
        )
        work["verification"]["solo_a"] = 0
        with self.assertRaises(PracticeBankValidationError):
            verify_quantitative_question(work)

        remainder = copy.deepcopy(
            next(
                item
                for item in self.questions
                if item["verification"]["adapter"] == "qty.remainder.constraints.v1"
            )
        )
        remainder["verification"].update(
            {"modulus_a": 2, "residue_a": 0, "modulus_b": 4, "residue_b": 1}
        )
        with self.assertRaises(PracticeBankValidationError):
            verify_quantitative_question(remainder)

        comparison = copy.deepcopy(
            next(
                item
                for item in self.questions
                if item["verification"]["adapter"] == "data.growth.compare.v1"
            )
        )
        comparison["verification"]["rows"][1].update({"base": 200, "current": 300})
        with self.assertRaises(PracticeBankValidationError):
            verify_data_analysis_question(comparison)

        share = copy.deepcopy(
            next(
                item
                for item in self.questions
                if item["verification"]["adapter"] == "data.share.base.v1"
            )
        )
        share["verification"]["part_rate_percent"] = -100
        with self.assertRaises(PracticeBankValidationError):
            verify_data_analysis_question(share)

    def test_manifest_digest_mismatch_fails_closed(self) -> None:
        root = Path(__file__).resolve().parents[1] / "practice_v3"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest["generated_sha256"] = "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.json"
            target.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(PracticeBankValidationError):
                load_practice_bank(Path(temporary))

    def test_manifest_rejects_unpinned_source_metadata(self) -> None:
        root = Path(__file__).resolve().parents[1] / "practice_v3"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest["content_sources"][0]["unexpected"] = "not-pinned"
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.json"
            target.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(PracticeBankValidationError):
                load_practice_bank(Path(temporary))

    def test_materialized_module_files_have_reproducible_integrity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = materialize(Path(temporary))
            destination = Path(str(result["output"]))
            disk_manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(disk_manifest["generated_sha256"], self.bank["generated_sha256"])
            self.assertEqual(disk_manifest["question_count"], EXPECTED_TOTAL)
            self.assertEqual(len(disk_manifest["files"]), 4)
            for record in disk_manifest["files"]:
                payload = (destination / record["path"]).read_bytes()
                self.assertEqual(record["size_bytes"], len(payload))
                self.assertEqual(record["sha256"], hashlib.sha256(payload).hexdigest())
                module = json.loads(payload.decode("utf-8"))
                self.assertEqual(module["question_count"], 80)

    def test_sources_are_taxonomy_only_and_external_release_remains_gated(self) -> None:
        for source in self.bank["content_sources"]:
            self.assertEqual(source["content_origin"], "synthetic_original")
            self.assertEqual(source["source_use"], "concept_structure_reference")
            self.assertFalse(source["source_text_included"])
            self.assertEqual(source["authorization_status"], "internal_mvp_only")
            self.assertEqual(source["review_status"], "human_review_required_before_external_release")


if __name__ == "__main__":
    unittest.main()
