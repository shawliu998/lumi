from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOMAIN_ROOT / "tools"))

from import_xingce_local_bundle import ImportContractError, build_local_payload


class VersionedManifestTests(unittest.TestCase):
    def test_public_manifest_contains_no_source_question_text(self) -> None:
        path = DOMAIN_ROOT / "content" / "xingce" / "p031-data-analysis-v1" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "internal_evaluation_only")
        self.assertEqual(manifest["rights"]["status"], "unverified")
        self.assertEqual(manifest["rights"]["distribution"], "local_only")
        self.assertEqual(len(manifest["items"]), 6)
        self.assertEqual(
            {item["question_id"] for item in manifest["items"]},
            set(manifest["selection"]["selected_question_ids"]),
        )
        forbidden = {"material_text", "stem_text", "explanation_text", "options", "answer_labels"}
        for item in manifest["items"]:
            self.assertTrue(forbidden.isdisjoint(item))
            self.assertTrue(item["text_sufficient_reviewed"])
            self.assertTrue(item["candidate_skills"])


class XingceLocalBundleImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source_manifest = b'{"generated_at":"test"}\n'
        (self.root / "manifest.json").write_bytes(source_manifest)
        self.source_manifest_hash = hashlib.sha256(source_manifest).hexdigest()
        self.question = {
            "question_id": "q_test",
            "material_text": "observed material",
            "stem_text": "observed stem",
            "explanation_text": "observed explanation",
            "answer_labels": "B",
            "content_signature": "content-v1",
            "content_answer_signature": "answer-v1",
            "quality_status": "ready",
            "is_import_ready": 1,
            "is_scoreable": 1,
            "has_image_options": 0,
        }
        self.options = [
            {"question_id": "q_test", "label": label, "option_order": index, "option_text": text, "is_correct": label == "B"}
            for index, (label, text) in enumerate(zip("ABCD", ["one", "two", "three", "four"]), 1)
        ]
        self.manifest = {
            "release_id": "test-release",
            "source_bundle": {"manifest_sha256": self.source_manifest_hash},
            "selection": {"selected_question_ids": ["q_test"]},
            "items": [
                {
                    "question_id": "q_test",
                    "content_signature": "content-v1",
                    "content_answer_signature": "answer-v1",
                    "diagnostic_role": "first_answer",
                    "text_sufficient_reviewed": True,
                    "candidate_skills": [{"skill_id": "skill", "confidence": 1, "review_status": "candidate"}],
                    "source_question_key": "source:1",
                    "source_question_id": "1",
                    "paper_id": "paper",
                    "paper_title": "paper title",
                    "year": 2026,
                    "question_no": 1,
                    "source_site": "source",
                    "source_url": "https://example.invalid",
                }
            ],
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_rows(self) -> None:
        (self.root / "questions.jsonl").write_text(json.dumps(self.question) + "\n", encoding="utf-8")
        (self.root / "options.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in self.options), encoding="utf-8"
        )

    def test_builds_minimal_local_payload(self) -> None:
        self.write_rows()
        payload = build_local_payload(self.manifest, self.root)
        self.assertEqual(payload["distribution"], "local_only")
        self.assertEqual(payload["items"][0]["answer_labels"], "B")
        self.assertEqual([option["label"] for option in payload["items"][0]["options"]], list("ABCD"))
        self.assertNotIn("material_html", payload["items"][0])
        self.assertNotIn("assets", payload["items"][0])

    def test_rejects_signature_drift(self) -> None:
        self.question["content_signature"] = "changed"
        self.write_rows()
        with self.assertRaisesRegex(ImportContractError, "content_signature mismatch"):
            build_local_payload(self.manifest, self.root)

    def test_rejects_image_dependent_option(self) -> None:
        self.question["has_image_options"] = 1
        self.write_rows()
        with self.assertRaisesRegex(ImportContractError, "image-dependent"):
            build_local_payload(self.manifest, self.root)

    def test_rejects_unresolvable_answer(self) -> None:
        self.options[1]["is_correct"] = False
        self.options[2]["is_correct"] = True
        self.write_rows()
        with self.assertRaisesRegex(ImportContractError, "answer cannot be resolved"):
            build_local_payload(self.manifest, self.root)


if __name__ == "__main__":
    unittest.main()
