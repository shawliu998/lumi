from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import unittest

from hermes_domains.xingce_adaptive_pack import DRAFT_STATUS, load_xingce_adaptive_pack
from hermes_domains.xingce_adaptive_policy import Observation, diagnose_entry, independent_transfer_proposal, resolve_probe
from hermes_domains.xingce_coverage import load_coverage_matrix


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


def _response_for(record: dict, *, correct: bool) -> str:
    if record.get("response_mode") == "numeric":
        target = Decimal(str(record["answer_spec"]["target"]))
        return str(target if correct else target + 1)
    answer = record["correct_option"]
    if correct:
        return answer
    return next(option["label"] for option in record["options"] if option["label"] != answer)


class XingceAllTypeCoverageTests(unittest.TestCase):
    def test_every_coverage_row_has_exactly_one_pack_or_released_pack(self) -> None:
        matrix = load_coverage_matrix()
        rows = {row["id"]: row for row in matrix["subtypes"]}
        drafts = [load_xingce_adaptive_pack(root) for root in _adaptive_draft_roots()]
        draft_ids = [pack["subtype_id"] for pack in drafts]
        self.assertEqual(len(draft_ids), len(set(draft_ids)))

        released = [row for row in matrix["subtypes"] if row.get("release", {}).get("state") == "released"]
        released_ids = [row["id"] for row in released]
        self.assertEqual(set(rows), set(draft_ids).union(released_ids))
        self.assertEqual(set(draft_ids).intersection(released_ids), set())
        self.assertEqual(len(drafts), 30)
        self.assertEqual(released_ids, ["xingce.judgment.conditional_logic"])

        release = released[0]["release"]
        release_manifest = next(RELEASE_ROOT.rglob("manifest.json"))
        release_document = json.loads(release_manifest.read_text(encoding="utf-8"))
        self.assertEqual(release_document["pack_id"], release["pack_id"])
        self.assertEqual(release_document["pack_version"], release["pack_version"])

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
