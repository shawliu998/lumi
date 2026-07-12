#!/usr/bin/env python3
"""Serve an isolated, browser-QA-only reviewed copy of the judgment pack.

The repository's authored pack stays ``draft_unreviewed``.  This harness copies
it to a temporary directory, creates two *test-only* hash-bound attestations,
and starts the real loopback sidecar with an ``evaluation_fixture`` namespace.
It is for component/browser checks only: its temporary database, pack, and
attestation identifiers must never be treated as human review or product data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from hermes_domains.reasoning_pack import (
    DEFAULT_DRAFT_PACK_ROOT,
    record_sha256,
    reviewed_manifest_sha256,
    validate_reviewed_reasoning_pack,
)
from hermes_service.api import create_server
from hermes_service.application import SidecarApplication


QA_PACK_VERSION = "0.1.0-browser-qa"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_test_only_reviewed_copy(root: Path) -> None:
    """Construct a release-shaped copy that never mutates the authored draft."""

    for name in ("skill-graph.json", "misconception-taxonomy.json"):
        document = _read_json(root / name)
        document["pack_version"] = QA_PACK_VERSION
        document["review_status"] = "release_ready"
        _write_json(root / name, document)

    records = _read_json(root / "records.json")
    records["pack_version"] = QA_PACK_VERSION
    records["review_status"] = "release_ready"
    for record in records["records"]:
        record["review_status"] = "release_ready"
        record["record_sha256"] = record_sha256(record)
    _write_json(root / "records.json", records)

    manifest = _read_json(root / "manifest.json")
    manifest["pack_version"] = QA_PACK_VERSION
    manifest["status"] = "release_ready"
    manifest["release_ready"] = True
    manifest["runtime_registration"] = "allowed_after_human_review"
    manifest["rights"]["distribution"] = "release_distribution_allowed"
    manifest["human_review_gate"] = {
        "required": True,
        "production_load_allowed": True,
        "policy": "QA-only synthetic attestations bind this disposable copy; no repository draft is approved.",
        "review_attestations": [],
    }
    for artifact in manifest["artifacts"]:
        artifact["sha256"] = _sha256(root / artifact["path"])
    _write_json(root / "manifest.json", manifest)

    artifact_hashes = {artifact["path"]: artifact["sha256"] for artifact in manifest["artifacts"]}
    record_hashes = {record["record_id"]: record["record_sha256"] for record in records["records"]}
    manifest_hash = reviewed_manifest_sha256(manifest)
    manifest["human_review_gate"]["review_attestations"] = [
        {
            "review_kind": "logic",
            "status": "approved",
            "reviewer_id": "qa-synthetic-logic-reviewer",
            "reviewed_at": "2026-07-13T00:00:00Z",
            "checklist": ["test_only", "no_human_approval"],
            "manifest_sha256": manifest_hash,
            "artifact_hashes": artifact_hashes,
            "record_hashes": record_hashes,
        },
        {
            "review_kind": "editorial_rights",
            "status": "approved",
            "reviewer_id": "qa-synthetic-rights-reviewer",
            "reviewed_at": "2026-07-13T00:00:01Z",
            "checklist": ["test_only", "no_human_approval"],
            "manifest_sha256": manifest_hash,
            "artifact_hashes": artifact_hashes,
            "record_hashes": record_hashes,
        },
    ]
    _write_json(root / "manifest.json", manifest)
    validate_reviewed_reasoning_pack(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lumi judgment browser QA harness")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lumi-judgment-browser-qa-") as directory:
        temporary_root = Path(directory)
        pack_root = temporary_root / "reviewed-pack"
        database = temporary_root / "evaluation-fixture.sqlite3"
        shutil.copytree(DEFAULT_DRAFT_PACK_ROOT, pack_root)
        _make_test_only_reviewed_copy(pack_root)
        application = SidecarApplication(
            database,
            attempt_evidence_origin="evaluation_fixture",
            evaluation_projection_enabled=True,
            review_commit_evidence_origins=frozenset({"evaluation_fixture"}),
            judgment_pack_root=pack_root,
        )
        server = create_server(application, port=args.port)
        print(
            f"Lumi judgment browser QA sidecar on http://127.0.0.1:{server.server_address[1]} "
            "(test-only reviewed copy; evaluation_fixture only)",
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
