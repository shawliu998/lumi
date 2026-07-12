from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hermes_domains.reasoning_pack import (
    DEFAULT_DRAFT_PACK_ROOT,
    ReasoningPackError,
    load_reviewed_reasoning_pack,
    pack_checksums,
    record_sha256,
    reviewed_manifest_sha256,
    validate_reasoning_pack,
    validate_reviewed_reasoning_pack,
)


class ReasoningPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "lumi-conditional-reasoning-v0"
        shutil.copytree(DEFAULT_DRAFT_PACK_ROOT, self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read_json(self, name: str) -> dict:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def write_json(self, name: str, value: dict) -> None:
        (self.root / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def refresh_artifact_checksum(self, name: str) -> None:
        manifest = self.read_json("manifest.json")
        digest = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        for artifact in manifest["artifacts"]:
            if artifact["path"] == name:
                artifact["sha256"] = digest
                break
        else:
            self.fail(f"missing manifest artifact {name}")
        self.write_json("manifest.json", manifest)

    def make_reviewed_release(self) -> None:
        """Turn a disposable copy into a deliberately reviewed future pack."""

        reviewed_version = "0.1.0-reviewed-test"
        for name in ("skill-graph.json", "misconception-taxonomy.json"):
            document = self.read_json(name)
            document["pack_version"] = reviewed_version
            document["review_status"] = "release_ready"
            self.write_json(name, document)

        records = self.read_json("records.json")
        records["pack_version"] = reviewed_version
        records["review_status"] = "release_ready"
        for record in records["records"]:
            record["review_status"] = "release_ready"
            record["record_sha256"] = record_sha256(record)
        self.write_json("records.json", records)

        manifest = self.read_json("manifest.json")
        manifest["pack_version"] = reviewed_version
        manifest["status"] = "release_ready"
        manifest["release_ready"] = True
        manifest["runtime_registration"] = "allowed_after_human_review"
        manifest["rights"]["distribution"] = "release_distribution_allowed"
        manifest["human_review_gate"] = {
            "required": True,
            "production_load_allowed": True,
            "policy": "Two independent humans review the exact hash-bound release payload before a future runtime registration step.",
            "review_attestations": [],
        }
        self.write_json("manifest.json", manifest)
        for artifact in manifest["artifacts"]:
            self.refresh_artifact_checksum(artifact["path"])

        manifest = self.read_json("manifest.json")
        artifact_hashes = {artifact["path"]: artifact["sha256"] for artifact in manifest["artifacts"]}
        record_hashes = {record["record_id"]: record["record_sha256"] for record in records["records"]}
        manifest_hash = reviewed_manifest_sha256(manifest)
        manifest["human_review_gate"]["review_attestations"] = [
            {
                "review_kind": "logic",
                "status": "approved",
                "reviewer_id": "logic-reviewer-01",
                "reviewed_at": "2026-07-12T08:30:00Z",
                "checklist": ["unique_answer", "formalization", "transfer_independence"],
                "manifest_sha256": manifest_hash,
                "artifact_hashes": artifact_hashes,
                "record_hashes": record_hashes,
            },
            {
                "review_kind": "editorial_rights",
                "status": "approved",
                "reviewer_id": "rights-reviewer-02",
                "reviewed_at": "2026-07-12T08:45:00Z",
                "checklist": ["original_wording", "clarity", "license_scope"],
                "manifest_sha256": manifest_hash,
                "artifact_hashes": artifact_hashes,
                "record_hashes": record_hashes,
            },
        ]
        self.write_json("manifest.json", manifest)

    def refresh_attestation_manifest_and_artifacts(self) -> None:
        """Refresh only bindings that a reviewer would need to sign again."""

        manifest = self.read_json("manifest.json")
        artifact_hashes = {artifact["path"]: artifact["sha256"] for artifact in manifest["artifacts"]}
        manifest_hash = reviewed_manifest_sha256(manifest)
        for attestation in manifest["human_review_gate"]["review_attestations"]:
            attestation["manifest_sha256"] = manifest_hash
            attestation["artifact_hashes"] = artifact_hashes
        self.write_json("manifest.json", manifest)

    def test_validates_complete_unregistered_draft(self) -> None:
        summary = validate_reasoning_pack(self.root)

        self.assertEqual(summary["status"], "draft_unreviewed")
        self.assertFalse(summary["production_load_allowed"])
        self.assertEqual(summary["record_count"], 12)
        self.assertIn("manifest.json", summary["checksums"])
        self.assertEqual(summary["checksums"], pack_checksums(self.root))

    def test_every_record_is_original_unreviewed_and_auditable(self) -> None:
        document = self.read_json("records.json")
        for record in document["records"]:
            self.assertEqual(record["content_origin"], "original_lumi")
            self.assertEqual(record["review_status"], "draft_unreviewed")
            self.assertEqual(record["record_sha256"], record_sha256(record))
            if record["role"] == "teaching_asset":
                self.assertTrue(record["logic_rule"])
                self.assertTrue(record["teaching_content"])
            else:
                self.assertTrue(record["formalization"])
                self.assertTrue(record["answer_proof"])
                self.assertIn(record["correct_option"], record["options"])
                self.assertTrue(record["assessment_format"])
                if record["role"] == "probe":
                    self.assertEqual(set(record["candidate_evidence_map"]), {"A", "B", "C", "D"})
                    for outcomes in record["candidate_evidence_map"].values():
                        self.assertEqual(set(outcomes), set(record["candidate_misconception_ids"]))

    def test_assessment_answer_positions_and_transfer_formats_are_auditable(self) -> None:
        records = self.read_json("records.json")["records"]
        assessments = [record for record in records if record["role"] != "teaching_asset"]
        counts = {option: sum(record["correct_option"] == option for record in assessments) for option in "ABCD"}
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        self.assertTrue(all(counts.values()))
        entries_by_skills = {
            tuple(record["target_skill_ids"]): record
            for record in assessments
            if record["role"] in {"entry_diagnostic", "routing_diagnostic"}
        }
        for transfer in (record for record in assessments if record["role"] == "independent_transfer"):
            entry = entries_by_skills[tuple(transfer["target_skill_ids"])]
            self.assertNotEqual(transfer["assessment_format"], entry["assessment_format"])

    def test_p02_supports_role_hypothesis_only_with_an_explicit_necessary_to_sufficient_error(self) -> None:
        records = self.read_json("records.json")["records"]
        probe = next(record for record in records if record["record_id"] == "P02")
        teaching = next(record for record in records if record["record_id"] == "T02")

        self.assertEqual(probe["candidate_evidence_map"]["A"], {"M-ROLE": "support", "M-READ": "insufficient"})
        self.assertIn("必要条件", probe["options"]["A"])
        self.assertIn("一定", probe["options"]["A"])
        self.assertEqual(probe["candidate_evidence_map"]["D"], {"M-ROLE": "refute", "M-READ": "refute"})
        self.assertIn("已登记", probe["options"]["D"])
        self.assertIn("未领取", probe["options"]["D"])
        self.assertNotIn("发生前", teaching["teaching_content"])
        self.assertIn("凡是领取设备的人都已登记", teaching["teaching_content"])

    def test_rejects_probe_without_complete_option_level_evidence_map(self) -> None:
        records = self.read_json("records.json")
        probe = next(record for record in records["records"] if record["record_id"] == "P02")
        del probe["candidate_evidence_map"]["A"]["M-READ"]
        probe["record_sha256"] = record_sha256(probe)
        self.write_json("records.json", records)
        self.refresh_artifact_checksum("records.json")

        with self.assertRaisesRegex(ReasoningPackError, "candidate evidence must cover exactly"):
            validate_reasoning_pack(self.root)

    def test_rejects_artifact_byte_drift(self) -> None:
        graph = self.read_json("skill-graph.json")
        graph["skills"][0]["description"] += " 已被篡改。"
        self.write_json("skill-graph.json", graph)

        with self.assertRaisesRegex(ReasoningPackError, "artifact checksum mismatch: skill-graph.json"):
            validate_reasoning_pack(self.root)

    def test_rejects_semantic_record_drift_even_if_artifact_checksum_is_refreshed(self) -> None:
        records = self.read_json("records.json")
        records["records"][0]["options"]["A"] = "被篡改的答案文字。"
        self.write_json("records.json", records)
        self.refresh_artifact_checksum("records.json")

        with self.assertRaisesRegex(ReasoningPackError, "record checksum mismatch: D01"):
            validate_reasoning_pack(self.root)

    def test_rejects_transfer_that_reuses_an_earlier_independence_group(self) -> None:
        records = self.read_json("records.json")
        by_id = {record["record_id"]: record for record in records["records"]}
        by_id["V01"]["independence_group"] = by_id["D01"]["independence_group"]
        by_id["V01"]["record_sha256"] = record_sha256(by_id["V01"])
        self.write_json("records.json", records)
        self.refresh_artifact_checksum("records.json")

        with self.assertRaisesRegex(ReasoningPackError, "distinct independence group"):
            validate_reasoning_pack(self.root)

    def test_rejects_a_probe_that_cannot_separate_competing_candidates(self) -> None:
        records = self.read_json("records.json")
        probe = next(record for record in records["records"] if record["record_id"] == "P01")
        probe["candidate_misconception_ids"] = ["M-DIR"]
        probe["discriminates"] = ["M-DIR"]
        probe["record_sha256"] = record_sha256(probe)
        self.write_json("records.json", records)
        self.refresh_artifact_checksum("records.json")

        with self.assertRaisesRegex(ReasoningPackError, "at least two candidate"):
            validate_reasoning_pack(self.root)

    def test_rejects_release_ready_bypass_without_human_review(self) -> None:
        manifest = copy.deepcopy(self.read_json("manifest.json"))
        manifest["status"] = "release_ready"
        manifest["release_ready"] = True
        manifest["runtime_registration"] = "allowed"
        self.write_json("manifest.json", manifest)

        with self.assertRaisesRegex(ReasoningPackError, "must remain draft_unreviewed"):
            validate_reasoning_pack(self.root)

    def test_reviewed_loader_fails_closed_for_the_actual_draft(self) -> None:
        with self.assertRaisesRegex(ReasoningPackError, "only accepts release_ready"):
            validate_reviewed_reasoning_pack(self.root)

    def test_reviewed_loader_requires_two_independent_hash_bound_reviews(self) -> None:
        self.make_reviewed_release()

        summary = validate_reviewed_reasoning_pack(self.root)
        self.assertTrue(summary["production_load_allowed"])
        self.assertEqual(summary["review_kinds"], ["editorial_rights", "logic"])

        public = load_reviewed_reasoning_pack(self.root)
        private = load_reviewed_reasoning_pack(self.root, projection="private")
        self.assertEqual(public["projection"], "public")
        self.assertEqual(private["projection"], "private")
        self.assertEqual(len(public["records"]), len(private["records"]))
        self.assertEqual(public["records"][0]["record_id"], "D01")
        self.assertEqual(private["records"][0]["correct_option"], "A")

    def test_reviewed_loader_rejects_artifact_hash_drift(self) -> None:
        self.make_reviewed_release()
        graph = self.read_json("skill-graph.json")
        graph["skills"][0]["description"] += " 未经审核的篡改。"
        self.write_json("skill-graph.json", graph)

        with self.assertRaisesRegex(ReasoningPackError, "release artifact checksum mismatch: skill-graph.json"):
            validate_reviewed_reasoning_pack(self.root)

    def test_reviewed_loader_rejects_manifest_payload_drift(self) -> None:
        self.make_reviewed_release()
        manifest = self.read_json("manifest.json")
        manifest["purpose"] += " 未经重新审核的范围变化。"
        self.write_json("manifest.json", manifest)

        with self.assertRaisesRegex(ReasoningPackError, "manifest hash does not match reviewed manifest"):
            validate_reviewed_reasoning_pack(self.root)

    def test_reviewed_loader_rejects_record_binding_drift_after_other_bindings_refresh(self) -> None:
        self.make_reviewed_release()
        records = self.read_json("records.json")
        records["records"][0]["prompt"] += " 未经重新审核的改动。"
        records["records"][0]["record_sha256"] = record_sha256(records["records"][0])
        self.write_json("records.json", records)
        self.refresh_artifact_checksum("records.json")
        self.refresh_attestation_manifest_and_artifacts()

        with self.assertRaisesRegex(ReasoningPackError, "record hashes do not match exact records"):
            validate_reviewed_reasoning_pack(self.root)

    def test_reviewed_loader_rejects_missing_or_reused_reviewers(self) -> None:
        self.make_reviewed_release()
        manifest = self.read_json("manifest.json")
        manifest["human_review_gate"]["review_attestations"] = manifest["human_review_gate"]["review_attestations"][:1]
        self.write_json("manifest.json", manifest)
        with self.assertRaisesRegex(ReasoningPackError, "requires exactly logic and editorial_rights"):
            validate_reviewed_reasoning_pack(self.root)

        self.make_reviewed_release()
        manifest = self.read_json("manifest.json")
        manifest["human_review_gate"]["review_attestations"][1]["reviewer_id"] = "logic-reviewer-01"
        self.write_json("manifest.json", manifest)
        with self.assertRaisesRegex(ReasoningPackError, "different reviewer_id"):
            validate_reviewed_reasoning_pack(self.root)

    def test_reviewed_loader_rejects_a_single_candidate_probe(self) -> None:
        self.make_reviewed_release()
        records = self.read_json("records.json")
        probe = next(record for record in records["records"] if record["record_id"] == "P01")
        probe["candidate_misconception_ids"] = ["M-DIR"]
        probe["discriminates"] = ["M-DIR"]
        probe["record_sha256"] = record_sha256(probe)
        self.write_json("records.json", records)
        self.refresh_artifact_checksum("records.json")
        manifest = self.read_json("manifest.json")
        record_hashes = {record["record_id"]: record["record_sha256"] for record in records["records"]}
        for attestation in manifest["human_review_gate"]["review_attestations"]:
            attestation["record_hashes"] = record_hashes
        self.write_json("manifest.json", manifest)
        self.refresh_attestation_manifest_and_artifacts()

        with self.assertRaisesRegex(ReasoningPackError, "at least two candidate"):
            validate_reviewed_reasoning_pack(self.root)

    def test_reviewed_loader_rejects_unknown_attestation_fields_and_public_projection_leaks(self) -> None:
        self.make_reviewed_release()
        manifest = self.read_json("manifest.json")
        manifest["human_review_gate"]["review_attestations"][0]["surprise"] = "forbidden"
        self.write_json("manifest.json", manifest)
        with self.assertRaisesRegex(ReasoningPackError, "contains unknown fields: surprise"):
            validate_reviewed_reasoning_pack(self.root)

        self.make_reviewed_release()
        public = load_reviewed_reasoning_pack(self.root, projection="public")
        rendered = json.dumps(public, ensure_ascii=False, sort_keys=True)
        for sensitive in ("correct_option", "answer_proof", "distractor_map", "candidate_evidence_map", "selected_when"):
            self.assertNotIn(sensitive, rendered)


if __name__ == "__main__":
    unittest.main()
