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
from xingce_adaptive_fixtures import documents_for


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
