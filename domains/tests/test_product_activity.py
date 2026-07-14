from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from hermes_domains import (
    ProductActivityError,
    load_product_activity,
    validate_product_activity_runtime,
)


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ROOT = DOMAIN_ROOT / "content" / "xingce" / "p031-data-analysis-v1"
MANIFEST_PATH = RELEASE_ROOT / "manifest.json"
OVERLAY_PATH = RELEASE_ROOT / "pedagogical-overlay.json"
PAYLOAD_PATH = DOMAIN_ROOT / "local_content" / "xingce" / "p031-data-analysis-v1.json"


def contains_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return bool(forbidden.intersection(value)) or any(contains_key(child, forbidden) for child in value.values())
    if isinstance(value, list):
        return any(contains_key(child, forbidden) for child in value)
    return False


class ProductActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        payload_items = []
        for index, item in enumerate(manifest["items"]):
            answer = "C" if item["diagnostic_role"] == "first_answer" else "B"
            payload_items.append(
                {
                    "question_id": item["question_id"],
                    "diagnostic_role": item["diagnostic_role"],
                    "candidate_skills": item["candidate_skills"],
                    "source": {
                        key: item[key]
                        for key in (
                            "source_question_key", "source_question_id", "paper_id", "paper_title",
                            "year", "question_no", "source_site", "source_url", "content_signature",
                            "content_answer_signature",
                        )
                    },
                    "material_text": f"local material {index}",
                    "stem_text": f"local stem {index}",
                    "options": [{"label": label, "text": f"option {label}-{index}"} for label in "ABCD"],
                    "answer_labels": answer,
                    "explanation_text": f"private explanation {index}",
                }
            )
        self.payload = {
            "schema_version": "lumi.xingce-local-payload.v0",
            "release_id": manifest["release_id"],
            "distribution": "local_only",
            "source_manifest_sha256": manifest["source_bundle"]["manifest_sha256"],
            "items": payload_items,
        }
        self.payload_path = self.write_document(self.temp_root, "payload.json", self.payload)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_document(self, root: Path, name: str, document: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def test_compiles_real_first_and_transfer_items(self) -> None:
        activity = load_product_activity(self.payload_path)
        fixture = activity.to_runtime_fixture()
        self.assertEqual(activity.first_question_id, "q_70b9e63de33ef42509e4")
        self.assertEqual(activity.transfer_question_id, "q_b1cb2eb7c07136fa2b07")
        self.assertNotEqual(activity.first_content_signature, activity.transfer_content_signature)
        self.assertEqual(fixture["provenance"]["content_origin"], "local_versioned_export")
        self.assertEqual(fixture["provenance"]["distribution"], "local_only")
        self.assertEqual(fixture["task"]["item_id"], activity.first_question_id)
        self.assertEqual(fixture["independent_verify"]["item_id"], activity.transfer_question_id)
        self.assertEqual(fixture["independent_verify"]["novelty_status"], "unseen_parallel_item")
        self.assertEqual(fixture["independent_verify"]["pass_condition"]["scorer"], "exact_option_v1")
        self.assertEqual(len(fixture["assistance_ladder"]["steps"]), 6)
        self.assertIn("local stem 0", fixture["task"]["prompt"])
        self.assertIn("local stem 1", fixture["independent_verify"]["prompt"])
        self.assertTrue(all(not item["is_ground_truth"] for item in fixture["diagnosis"]["candidate_causes"]))

    def test_public_view_never_leaks_answers_or_explanations(self) -> None:
        public = load_product_activity(self.payload_path).public_view()
        forbidden = {"answer_labels", "correct_option", "explanation_text", "content_answer_signature"}
        self.assertFalse(contains_key(public, forbidden))
        encoded = json.dumps(public, ensure_ascii=False)
        for item in self.payload["items"][:2]:
            self.assertNotIn(item["explanation_text"], encoded)

    def test_rejects_release_hash_drift(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            changed_manifest = copy.deepcopy(manifest)
            changed_manifest["purpose"] = "drifted"
            path = self.write_document(root, "manifest.json", changed_manifest)
            with self.assertRaisesRegex(ProductActivityError, "release manifest checksum mismatch"):
                load_product_activity(self.payload_path, manifest_path=path, overlay_path=OVERLAY_PATH)

    def test_rejects_source_hash_drift(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["source_manifest_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_document(Path(temporary), "payload.json", payload)
            with self.assertRaisesRegex(ProductActivityError, "source bundle checksum mismatch"):
                load_product_activity(path)

    def test_rejects_item_signature_drift(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["items"][0]["source"]["content_signature"] = "drifted"
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_document(Path(temporary), "payload.json", payload)
            with self.assertRaisesRegex(ProductActivityError, "content_signature mismatch"):
                load_product_activity(path)

    def test_rejects_same_question_as_transfer(self) -> None:
        overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
        overlay["activities"][0]["transfer_question_id"] = overlay["activities"][0]["first_question_id"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_copy = root / "manifest.json"
            manifest_copy.write_bytes(MANIFEST_PATH.read_bytes())
            overlay_path = self.write_document(root, "overlay.json", overlay)
            with self.assertRaisesRegex(ProductActivityError, "question_id must differ"):
                load_product_activity(self.payload_path, manifest_path=manifest_copy, overlay_path=overlay_path)

    def test_runtime_validator_rejects_same_content_signature(self) -> None:
        fixture = load_product_activity(self.payload_path).to_runtime_fixture()
        fixture["provenance"]["transfer_item"]["content_signature"] = fixture["provenance"]["first_item"]["content_signature"]
        with self.assertRaisesRegex(ProductActivityError, "content signatures must differ"):
            validate_product_activity_runtime(fixture)

    def test_runtime_validator_rejects_incomplete_probe_pedagogy(self) -> None:
        fixture = load_product_activity(self.payload_path).to_runtime_fixture()
        fixture["probe"].pop("assessment")
        with self.assertRaisesRegex(ProductActivityError, "assessment"):
            validate_product_activity_runtime(fixture)

    def test_committed_overlay_has_no_source_question_or_answer_fields(self) -> None:
        overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
        self.assertFalse(contains_key(overlay, {"material_text", "stem_text", "explanation_text", "options", "answer_labels", "correct_option"}))

    @unittest.skipUnless(PAYLOAD_PATH.exists(), "ignored local Xingce payload has not been generated")
    def test_generated_local_payload_compiles(self) -> None:
        activity = load_product_activity(PAYLOAD_PATH)
        self.assertIn("2020年，全国城市供水总量约为", activity.to_runtime_fixture()["task"]["prompt"])


if __name__ == "__main__":
    unittest.main()
