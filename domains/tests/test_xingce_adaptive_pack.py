from __future__ import annotations

import copy
from pathlib import Path
import unittest

from hermes_domains.xingce_adaptive_pack import (
    XingceAdaptivePackError,
    load_xingce_adaptive_pack,
    public_record_projection,
    record_sha256,
    validate_xingce_adaptive_documents,
)
from hermes_domains.xingce_coverage import load_coverage_matrix


def _finalize(records: list[dict]) -> dict:
    for record in records:
        record["record_sha256"] = record_sha256(record)
    return {
        "schema_version": "lumi.xingce-adaptive-records.v1",
        "pack_id": "lumi-xingce-contract-fixture",
        "pack_version": "0.1.0-draft",
        "review_status": "draft_unreviewed",
        "records": records,
    }


def documents_for(subtype: dict) -> tuple[dict, dict, dict, dict]:
    evidence = {
        requirement: ("a" * 64 if requirement in {"asset_checksum", "material_checksum"} else f"fixture:{requirement}")
        for requirement in subtype["content_requirements"]
    }
    manifest = {
        "schema_version": "lumi.xingce-adaptive-pack.v1",
        "pack_id": "lumi-xingce-contract-fixture",
        "pack_version": "0.1.0-draft",
        "status": "draft_unreviewed",
        "release_ready": False,
        "runtime_registration": "forbidden_until_human_review",
        "subtype_id": subtype["id"],
        "module_id": subtype["module_id"],
        "form": subtype["form"],
        "scorer": subtype["scorer"],
        "policy": {
            "policy_id": "lumi.xingce-type-policy",
            "policy_version": "1.0.0",
            "candidate_status": "unconfirmed",
            "state_commit_rule": "independent_unassisted_transfer_only",
        },
        "rights": {"content_origin": "original_lumi", "distribution": "draft_no_distribution"},
        "content_evidence": evidence,
        "human_review_gate": {
            "required": True,
            "production_load_allowed": False,
            "required_reviews": [
                {"review_kind": "logic", "status": "pending", "required_checks": ["unique_answer"]},
                {"review_kind": "editorial_rights", "status": "pending", "required_checks": ["original_wording"]},
            ],
        },
        "artifacts": [
            {"path": "records.json", "sha256": "b" * 64},
            {"path": "skill-graph.json", "sha256": "c" * 64},
            {"path": "misconceptions.json", "sha256": "d" * 64},
        ],
    }
    skills = {
        "schema_version": "lumi.xingce-adaptive-skills.v1",
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "review_status": "draft_unreviewed",
        "skills": [{"skill_id": "skill-1", "label": "可检验技能", "mastery_claim": "仅由无提示迁移更新"}],
    }
    taxonomy = {
        "schema_version": "lumi.xingce-adaptive-misconceptions.v1",
        "pack_id": manifest["pack_id"],
        "pack_version": manifest["pack_version"],
        "review_status": "draft_unreviewed",
        "candidate_misconceptions": [
            {"cause_id": "cause-1", "label": "候选一", "status": "unconfirmed", "is_ground_truth": False, "target_skill_ids": ["skill-1"]},
            {"cause_id": "cause-2", "label": "候选二", "status": "unconfirmed", "is_ground_truth": False, "target_skill_ids": ["skill-1"]},
        ],
    }

    def assessment(role: str, record_id: str, group: str) -> dict:
        base = {
            "record_id": record_id,
            "role": role,
            "title": f"{role} 题",
            "target_skill_ids": ["skill-1"],
            "candidate_misconception_ids": ["cause-1", "cause-2"],
            "independence_group": group,
            "content_origin": "original_lumi",
            "review_status": "draft_unreviewed",
            "prompt": "这是经过作者审核前的占位题干。",
        }
        if subtype["scorer"] == "authored_numeric_v1" and role != "probe":
            return {**base, "response_mode": "numeric", "answer_spec": {"target": 12, "tolerance": 0}}
        return {
            **base,
            "response_mode": "single_choice",
            "options": [{"label": "A", "text": "选项一"}, {"label": "B", "text": "选项二"}],
            "correct_option": "A",
        }

    entry = assessment("entry_diagnostic", "D01", "entry-group")
    entry["route_probe_ids"] = ["P01"]
    probe = assessment("probe", "P01", "probe-group")
    probe["discriminates"] = ["cause-1", "cause-2"]
    probe["candidate_evidence_map"] = {
        "cause-1": {"A": "support", "B": "refute"},
        "cause-2": {"A": "refute", "B": "support"},
    }
    teaching = {
        "record_id": "T01",
        "role": "teaching_asset",
        "title": "针对性微课",
        "target_skill_ids": ["skill-1"],
        "candidate_misconception_ids": ["cause-1", "cause-2"],
        "independence_group": "teaching-group",
        "content_origin": "original_lumi",
        "review_status": "draft_unreviewed",
        "target_candidate_ids": ["cause-1"],
        "teaching_content": "先比较题干中的决定性条件，再回到选项逐一排除。",
    }
    transfer = assessment("independent_transfer", "V01", "transfer-group")
    transfer["requires_no_hints"] = True
    review = assessment("delayed_review", "R01", "review-group")
    review["requires_no_hints"] = True
    review["scheduled_after_days"] = 3
    review["eligible_after_transfer_ids"] = ["V01"]
    return manifest, _finalize([entry, probe, teaching, transfer, review]), skills, taxonomy


class XingceAdaptivePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = load_coverage_matrix()

    def test_contract_accepts_an_authoring_draft_for_every_declared_subtype_profile(self) -> None:
        for subtype in self.matrix["subtypes"]:
            with self.subTest(subtype=subtype["id"]):
                validate_xingce_adaptive_documents(*documents_for(subtype))

    def test_transfer_is_unseen_and_candidates_cannot_be_confirmed_by_a_pack(self) -> None:
        subtype = next(row for row in self.matrix["subtypes"] if row["id"] == "xingce.verbal.logical_cloze")
        manifest, records, skills, taxonomy = documents_for(subtype)
        records["records"][3]["independence_group"] = "entry-group"
        records["records"][3]["record_sha256"] = record_sha256(records["records"][3])
        with self.assertRaisesRegex(XingceAdaptivePackError, "unseen independence"):
            validate_xingce_adaptive_documents(manifest, records, skills, taxonomy)

        manifest, records, skills, taxonomy = documents_for(subtype)
        taxonomy["candidate_misconceptions"][0]["status"] = "confirmed"
        with self.assertRaisesRegex(XingceAdaptivePackError, "unconfirmed"):
            validate_xingce_adaptive_documents(manifest, records, skills, taxonomy)

    def test_release_requires_two_different_approved_human_reviewers(self) -> None:
        subtype = next(row for row in self.matrix["subtypes"] if row["id"] == "xingce.judgment.definition")
        manifest, records, skills, taxonomy = documents_for(subtype)
        release = copy.deepcopy(manifest)
        release.update({"status": "release_ready", "release_ready": True, "runtime_registration": "allowed_after_human_review"})
        release["rights"]["distribution"] = "release_distribution_allowed"
        release["human_review_gate"] = {
            "required": True,
            "production_load_allowed": True,
            "review_attestations": [
                {"review_kind": "logic", "status": "approved", "reviewer_id": "same", "manifest_sha256": "a" * 64},
                {"review_kind": "editorial_rights", "status": "approved", "reviewer_id": "same", "manifest_sha256": "a" * 64},
            ],
        }
        with self.assertRaisesRegex(XingceAdaptivePackError, "two different"):
            validate_xingce_adaptive_documents(release, records, skills, taxonomy)

    def test_public_projection_does_not_expose_scorer_or_candidate_routing(self) -> None:
        subtype = next(row for row in self.matrix["subtypes"] if row["id"] == "xingce.verbal.main_idea")
        _, records, _, _ = documents_for(subtype)
        projection = public_record_projection(records["records"][0])
        self.assertEqual(set(projection), {"record_id", "role", "title", "prompt", "response_mode", "options"})
        self.assertNotIn("correct_option", projection)
        self.assertNotIn("candidate_misconception_ids", projection)
        self.assertNotIn("route_probe_ids", projection)

    def test_original_definition_draft_is_complete_but_cannot_be_registered(self) -> None:
        root = Path(__file__).resolve().parents[1] / "content" / "xingce" / "judgment" / "lumi-definition-reasoning-v0"
        pack = load_xingce_adaptive_pack(root)
        self.assertEqual(pack["subtype_id"], "xingce.judgment.definition")
        with self.assertRaisesRegex(XingceAdaptivePackError, "content_review_required"):
            load_xingce_adaptive_pack(root, require_reviewed=True)


if __name__ == "__main__":
    unittest.main()
