from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import unittest

from hermes_domains.xingce_adaptive_pack import DRAFT_STATUS, load_xingce_adaptive_pack
from hermes_domains.xingce_adaptive_policy import Observation, diagnose_entry, independent_transfer_proposal, resolve_probe
from hermes_domains.xingce_coverage import coverage_summary, load_coverage_matrix


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = DOMAIN_ROOT / "content" / "xingce"
RELEASE_ROOT = DOMAIN_ROOT / "released"


def _adaptive_draft_roots() -> list[Path]:
    roots: list[Path] = []
    for manifest_path in CONTENT_ROOT.rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") == "lumi.xingce-adaptive-pack.v1":
            roots.append(manifest_path.parent)
    return sorted(roots)


def _adaptive_release_roots() -> list[Path]:
    roots: list[Path] = []
    for manifest_path in RELEASE_ROOT.rglob("manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") == "lumi.xingce-adaptive-pack.v1":
            roots.append(manifest_path.parent)
    return sorted(roots)


def _response_for(record: dict, *, correct: bool) -> str:
    if record.get("response_mode") == "numeric":
        target = Decimal(str(record["answer_spec"]["target"]))
        return str(target if correct else target + 1)
    answer = record["correct_option"]
    if correct:
        return answer
    return next(option["label"] for option in record["options"] if option["label"] != answer)


class XingceAllTypeCoverageTests(unittest.TestCase):
    def test_every_coverage_row_binds_a_released_immutable_pack(self) -> None:
        matrix = load_coverage_matrix()
        rows = {row["id"]: row for row in matrix["subtypes"]}
        drafts = [load_xingce_adaptive_pack(root) for root in _adaptive_draft_roots()]
        draft_ids = [pack["subtype_id"] for pack in drafts]
        self.assertEqual(len(draft_ids), len(set(draft_ids)))

        released = [row for row in matrix["subtypes"] if row.get("release", {}).get("state") == "released"]
        released_ids = [row["id"] for row in released]
        reviewed = [row for row in matrix["subtypes"] if row.get("release", {}).get("state") == "reviewed_release_ready"]
        reviewed_ids = [row["id"] for row in reviewed]
        self.assertEqual(set(rows), set(released_ids))
        self.assertEqual(set(reviewed_ids).intersection(released_ids), set())
        self.assertEqual(len(drafts), 30)
        self.assertEqual(len(reviewed), 0)
        self.assertEqual(len(released_ids), 31)

        release = next(row["release"] for row in released if row["id"] == "xingce.judgment.conditional_logic")
        release_manifest = RELEASE_ROOT / "judgment" / "lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713" / "manifest.json"
        release_document = json.loads(release_manifest.read_text(encoding="utf-8"))
        self.assertEqual(release_document["pack_id"], release["pack_id"])
        self.assertEqual(release_document["pack_version"], release["pack_version"])

        adaptive_releases = [load_xingce_adaptive_pack(root, require_reviewed=True) for root in _adaptive_release_roots()]
        self.assertEqual(len(adaptive_releases), 30)
        release_by_id = {pack["pack_id"]: pack for pack in adaptive_releases}
        self.assertEqual(len(release_by_id), 30)
        for row in released:
            if row["id"] == "xingce.judgment.conditional_logic":
                continue
            with self.subTest(subtype=row["id"]):
                declaration = row["release"]
                pack = release_by_id[declaration["pack_id"]]
                self.assertEqual(pack["pack_version"], declaration["pack_version"])
                self.assertEqual(pack["subtype_id"], row["id"])
                self.assertEqual(
                    pack["product_release"],
                    {
                        "state": "released",
                        "acceptance_basis": "owner_acceptance_waiver",
                        "accepted_at": "2026-07-14",
                        "waived_gate": "type_by_type_human_local_browser_acceptance",
                        "human_effect_evidence": "unavailable",
                        "claim_scope": "content_and_mechanism_availability_only",
                    },
                )

        summary = coverage_summary()
        self.assertEqual(summary["released_subtypes"], 31)
        self.assertEqual(summary["reviewed_release_ready_subtypes"], 0)
        self.assertEqual(summary["planned_subtypes"], 0)
        self.assertTrue(summary["content_release_ready"])
        self.assertTrue(summary["is_complete"])

    def test_every_draft_has_a_deterministic_unconfirmed_path_to_independent_transfer(self) -> None:
        for root in _adaptive_draft_roots():
            with self.subTest(pack=root.name):
                pack = load_xingce_adaptive_pack(root)
                self.assertEqual(pack["status"], DRAFT_STATUS)
                records = pack["records"]
                entry_record = next(record for record in records if record["role"] == "entry_diagnostic")
                entry = diagnose_entry(
                    records,
                    scorer=pack["scorer"],
                    entry_record_id=entry_record["record_id"],
                    observation=Observation(_response_for(entry_record, correct=False), "medium", 11),
                )
                self.assertFalse(entry.correct)
                self.assertEqual(entry.next_step, "probe")
                probe_record = next(record for record in records if record["record_id"] == entry.probe_record_id)
                probe = resolve_probe(
                    records,
                    scorer=pack["scorer"],
                    entry=entry,
                    observation=Observation(_response_for(probe_record, correct=True), "medium", 7),
                )
                self.assertTrue(probe.evidence_updates)
                self.assertTrue(all(update["status"] == "unconfirmed" for update in probe.evidence_updates))
                transfer_record = next(record for record in records if record["record_id"] == probe.transfer_record_id)
                transfer = independent_transfer_proposal(
                    records,
                    scorer=pack["scorer"],
                    entry=entry,
                    probe=probe,
                    observation=Observation(_response_for(transfer_record, correct=True), "high", 12),
                )
                self.assertTrue(transfer["eligible"])
                self.assertEqual(transfer["state_delta"]["candidate_status"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()
