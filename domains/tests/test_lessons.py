from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_domains import (
    LessonValidationError,
    load_lesson_catalog,
    load_lesson_document,
    score_attempt,
    validate_fixture,
    validate_lesson,
)


ROOT = Path(__file__).resolve().parents[1]
LESSON_ROOT = ROOT / "lessons"
LESSON_ID = "xingce.data-analysis.growth-rate.lesson-01"
SKILL_IDS = {
    "xingce.data.growth.compute-rate",
}


class LessonContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_lesson_catalog(LESSON_ROOT)
        cls.lesson = cls.catalog[0]

    def test_manifest_loads_the_versioned_growth_rate_lesson(self) -> None:
        self.assertEqual(len(self.catalog), 1)
        self.assertEqual(self.lesson["schema_version"], "hermes.lesson.v1")
        self.assertEqual(self.lesson["lesson_id"], LESSON_ID)
        self.assertEqual(self.lesson["version"], "1.0.0")
        self.assertEqual(set(self.lesson["skill_ids"]), SKILL_IDS)
        self.assertGreaterEqual(self.lesson["estimated_minutes"], 5)
        self.assertLessEqual(self.lesson["estimated_minutes"], 8)
        self.assertEqual(len(self.lesson["skill_ids"]), 1)

    def test_method_card_stays_deliberately_small(self) -> None:
        card = self.lesson["method_card"]
        self.assertEqual(
            set(card),
            {"definition", "formula", "applicability", "common_mistake"},
        )
        self.assertEqual(set(card["common_mistake"]), {"label", "explanation"})
        self.assertTrue(card["definition"])
        self.assertTrue(card["formula"])

    def test_worked_example_has_steps_and_weak_to_strong_hints(self) -> None:
        example = self.lesson["worked_example"]
        self.assertGreaterEqual(len(example["steps"]), 2)
        hints = example["hint_ladder"]
        self.assertGreaterEqual(len(hints), 2)
        self.assertEqual([hint["level"] for hint in hints], list(range(1, len(hints) + 1)))
        self.assertEqual(
            [hint["reveal_rank"] for hint in hints],
            sorted(hint["reveal_rank"] for hint in hints),
        )

    def test_two_runs_provide_four_distinct_questions_and_two_transfers(self) -> None:
        fixtures = self.lesson["practice_fixtures"]
        self.assertEqual(len(fixtures), 2)
        prompts: list[str] = []
        for fixture in fixtures:
            validate_fixture(fixture)
            prompts.extend((fixture["task"]["prompt"], fixture["independent_verify"]["prompt"]))
            self.assertNotEqual(fixture["task"]["prompt"], fixture["independent_verify"]["prompt"])
            self.assertEqual({skill["skill_id"] for skill in fixture["skills"]}, SKILL_IDS)
            passing = score_attempt(fixture, fixture["samples"]["passing_response"])
            failing = score_attempt(fixture, fixture["samples"]["failing_response"])
            self.assertTrue(passing.passed)
            self.assertFalse(failing.passed)
        self.assertEqual(len(prompts), 4)
        self.assertEqual(len(set(prompts)), 4)
        self.assertNotIn(self.lesson["worked_example"]["prompt"], prompts)

    def test_completion_depends_on_practice_not_reading(self) -> None:
        policy = self.lesson["completion_policy"]
        self.assertGreaterEqual(policy["minimum_questions"], 3)
        self.assertEqual(policy["consecutive_verified_transfers"], 2)
        self.assertIs(policy["lesson_reading_changes_mastery"], False)
        self.assertGreater(policy["hinted_evidence_discount"], 0)
        self.assertLess(policy["hinted_evidence_discount"], 1)

    def test_provenance_limits_reference_use_to_concept_structure(self) -> None:
        provenance = self.lesson["provenance"]
        self.assertEqual(provenance["content_origin"], "synthetic_original")
        self.assertEqual(provenance["source_use"], "concept_structure_only")
        self.assertEqual(provenance["rights_status"], "internal_review_required")
        self.assertEqual(provenance["review_status"], "internal_review_required")
        self.assertIs(provenance["source_text_included"], False)
        self.assertEqual(provenance["source_page_range"]["pdf_start"], 3)
        self.assertEqual(provenance["source_page_range"]["pdf_end"], 10)

    def test_document_loads_by_id_and_manifest_path(self) -> None:
        by_id = load_lesson_document(LESSON_ID, lesson_root=LESSON_ROOT)
        by_path = load_lesson_document(
            "xingce_growth_rate.lesson.v1.json",
            lesson_root=LESSON_ROOT,
        )
        self.assertEqual(by_id, by_path)


class LessonFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lesson = load_lesson_catalog(LESSON_ROOT)[0]

    def test_rejects_unknown_schema_fields(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["unreviewed_extension"] = True
        with self.assertRaisesRegex(LessonValidationError, "unknown fields"):
            validate_lesson(lesson)

    def test_rejects_non_monotonic_hint_ladder(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["worked_example"]["hint_ladder"][1]["reveal_rank"] = 1
        with self.assertRaisesRegex(LessonValidationError, "weak to strong"):
            validate_lesson(lesson)

    def test_rejects_duplicate_practice_fixture_ids(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["practice_fixtures"][1]["fixture_id"] = lesson["practice_fixtures"][0]["fixture_id"]
        with self.assertRaisesRegex(LessonValidationError, "fixture_id values must be unique"):
            validate_lesson(lesson)

    def test_rejects_reused_practice_and_verification_question(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        fixture = lesson["practice_fixtures"][0]
        fixture["independent_verify"]["prompt"] = fixture["task"]["prompt"]
        with self.assertRaisesRegex(LessonValidationError, "different prompt"):
            validate_lesson(lesson)

    def test_rejects_worked_example_reused_as_practice(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["practice_fixtures"][0]["task"]["prompt"] = lesson["worked_example"]["prompt"]
        with self.assertRaisesRegex(LessonValidationError, "worked example must differ"):
            validate_lesson(lesson)

    def test_rejects_mastery_change_from_reading(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["completion_policy"]["lesson_reading_changes_mastery"] = True
        with self.assertRaisesRegex(LessonValidationError, "must never change mastery"):
            validate_lesson(lesson)

    def test_rejects_oversized_lesson(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["estimated_minutes"] = 12
        with self.assertRaisesRegex(LessonValidationError, "between 5 and 8"):
            validate_lesson(lesson)

    def test_rejects_more_than_one_knowledge_component(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["skill_ids"].append("xingce.data.growth.identify-base-current")
        with self.assertRaisesRegex(LessonValidationError, "exactly one knowledge component"):
            validate_lesson(lesson)

    def test_rejects_source_text_inclusion(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["provenance"]["source_text_included"] = True
        with self.assertRaisesRegex(LessonValidationError, "must be false"):
            validate_lesson(lesson)

    def test_rejects_invalid_embedded_domain_fixture(self) -> None:
        lesson = copy.deepcopy(self.lesson)
        lesson["practice_fixtures"][0]["diagnosis"]["candidate_causes"][0]["is_ground_truth"] = True
        with self.assertRaisesRegex(LessonValidationError, "violates hermes.domain-fixture.v1"):
            validate_lesson(lesson)

    def test_rejects_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "lessons"
            shutil.copytree(LESSON_ROOT, copied_root)
            document_path = copied_root / "xingce_growth_rate.lesson.v1.json"
            document_path.write_bytes(document_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(LessonValidationError, "checksum mismatch"):
                load_lesson_catalog(copied_root)

    def test_rejects_unlisted_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "lessons"
            shutil.copytree(LESSON_ROOT, copied_root)
            (copied_root / "unreviewed.json").write_text(json.dumps({"unsafe": True}), encoding="utf-8")
            with self.assertRaisesRegex(LessonValidationError, "unlisted lesson JSON"):
                load_lesson_catalog(copied_root)

    def test_rejects_document_not_listed_in_manifest(self) -> None:
        with self.assertRaisesRegex(LessonValidationError, "not listed"):
            load_lesson_document("unknown.lesson", lesson_root=LESSON_ROOT)


if __name__ == "__main__":
    unittest.main()
