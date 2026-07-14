#!/usr/bin/env python3
"""Create a hash-bound, locally controlled release from Lumi's reviewed draft.

The authored source remains ``draft_unreviewed`` forever.  This command creates
an immutable sibling copy with the review workbook's byte digest, the two
reviewer transcriptions, exact content hashes, and the repository owner's
direct-release authorization.  It never reads or copies question-bank data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from hermes_domains.reasoning_pack import (
    DEFAULT_DRAFT_PACK_ROOT,
    record_sha256,
    reviewed_manifest_sha256,
    validate_reasoning_pack,
    validate_reviewed_reasoning_pack,
)


RELEASE_VERSION = "0.1.0-reviewed-local-20260713"
DEFAULT_RELEASE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "released"
    / "judgment"
    / "lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713"
)
DEFAULT_REVIEW_WORKBOOK = (
    Path(__file__).resolve().parents[2]
    / "outputs"
    / "judgment-pack-review-r3-20260713"
    / "Lumi_条件逻辑题包_人工审核_第三稿.xlsx"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _review_evidence(
    *, source_root: Path, source_manifest: dict[str, Any], source_records: dict[str, Any], workbook: Path
) -> dict[str, Any]:
    """Transcribe only what the supplied manual workbook and owner authorize.

    The workbook has pseudonymous reviewer IDs ``1``/``2`` and calendar dates
    ``7.12``/``7.13``.  The release deliberately stores ``day`` precision
    rather than inventing times of day.  The owner authorization records the
    actual packaging decision in UTC.
    """

    return {
        "schema_version": "lumi.reasoning-review-evidence.v1",
        "pack_id": source_manifest["pack_id"],
        "source_pack_version": source_manifest["pack_version"],
        "source_manifest_sha256": _sha256(source_root / "manifest.json"),
        "source_artifact_hashes": {
            artifact["path"]: artifact["sha256"] for artifact in source_manifest["artifacts"]
        },
        "source_record_hashes": {
            record["record_id"]: record["record_sha256"] for record in source_records["records"]
        },
        "manual_review_workbook": {"name": workbook.name, "sha256": _sha256(workbook)},
        "owner_release_authorization": {
            "kind": "repository_owner_direct_release",
            "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "scope": "local_controlled_release",
        },
        "reviewer_transcriptions": [
            {
                "review_kind": "logic",
                "reviewer_id": "1",
                "reviewed_at": "2026-07-12",
                "reviewed_at_precision": "day",
                "decision": "已审核",
                "signature": "确认",
                "hash_confirmation": "一致",
                "notes": "无",
            },
            {
                "review_kind": "editorial_rights",
                "reviewer_id": "2",
                "reviewed_at": "2026-07-13",
                "reviewed_at_precision": "day",
                "decision": "已审核",
                "signature": "确认",
                "hash_confirmation": "一致",
                "notes": "无",
            },
        ],
    }


def create_release(*, source_root: Path, output_root: Path, review_workbook: Path) -> dict[str, Any]:
    """Write one verified release copy without altering source or workbook."""

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    review_workbook = review_workbook.resolve()
    validate_reasoning_pack(source_root)
    if not review_workbook.is_file():
        raise ValueError(f"manual review workbook is missing: {review_workbook}")
    if output_root.exists():
        raise ValueError(f"release output already exists: {output_root}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, output_root)
    source_manifest = _read_json(source_root / "manifest.json")
    source_records = _read_json(source_root / "records.json")

    for name in ("skill-graph.json", "misconception-taxonomy.json"):
        document = _read_json(output_root / name)
        document["pack_version"] = RELEASE_VERSION
        document["review_status"] = "release_ready"
        _write_json(output_root / name, document)

    records = _read_json(output_root / "records.json")
    records["pack_version"] = RELEASE_VERSION
    records["review_status"] = "release_ready"
    for record in records["records"]:
        record["review_status"] = "release_ready"
        record["record_sha256"] = record_sha256(record)
    _write_json(output_root / "records.json", records)

    manifest = _read_json(output_root / "manifest.json")
    manifest["pack_version"] = RELEASE_VERSION
    manifest["status"] = "release_ready"
    manifest["release_ready"] = True
    manifest["runtime_registration"] = "allowed_after_human_review"
    manifest["rights"]["distribution"] = "release_distribution_allowed"
    manifest["human_review_gate"] = {
        "required": True,
        "production_load_allowed": True,
        "policy": (
            "Two different owner-confirmed human reviewers approved the third-draft source. "
            "This local-controlled release binds their workbook digest, day-precision dates, "
            "and the generated release payload without changing the authored source pack."
        ),
        "review_attestations": [],
    }
    manifest["artifacts"].append({"path": "review-evidence.json", "sha256": ""})
    _write_json(output_root / "review-evidence.json", _review_evidence(
        source_root=source_root,
        source_manifest=source_manifest,
        source_records=source_records,
        workbook=review_workbook,
    ))

    for artifact in manifest["artifacts"]:
        artifact["sha256"] = _sha256(output_root / artifact["path"])
    _write_json(output_root / "manifest.json", manifest)

    artifact_hashes = {artifact["path"]: artifact["sha256"] for artifact in manifest["artifacts"]}
    record_hashes = {record["record_id"]: record["record_sha256"] for record in records["records"]}
    manifest_hash = reviewed_manifest_sha256(manifest)
    manifest["human_review_gate"]["review_attestations"] = [
        {
            "review_kind": "logic",
            "status": "approved",
            "reviewer_id": "1",
            "reviewed_at": "2026-07-12",
            "reviewed_at_precision": "day",
            "checklist": ["unique_answer", "formalization", "distractor_mapping", "transfer_independence"],
            "manifest_sha256": manifest_hash,
            "artifact_hashes": artifact_hashes,
            "record_hashes": record_hashes,
        },
        {
            "review_kind": "editorial_rights",
            "status": "approved",
            "reviewer_id": "2",
            "reviewed_at": "2026-07-13",
            "reviewed_at_precision": "day",
            "checklist": ["original_wording", "clarity", "neutral_context", "license_scope"],
            "manifest_sha256": manifest_hash,
            "artifact_hashes": artifact_hashes,
            "record_hashes": record_hashes,
        },
    ]
    _write_json(output_root / "manifest.json", manifest)
    return validate_reviewed_reasoning_pack(output_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a reviewed Lumi conditional-reasoning release copy")
    parser.add_argument("--source", type=Path, default=DEFAULT_DRAFT_PACK_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--review-workbook", type=Path, default=DEFAULT_REVIEW_WORKBOOK)
    arguments = parser.parse_args()
    print(json.dumps(
        create_release(source_root=arguments.source, output_root=arguments.output, review_workbook=arguments.review_workbook),
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
