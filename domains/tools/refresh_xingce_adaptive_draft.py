#!/usr/bin/env python3
"""Refresh deterministic checksums for one *draft* Xingce adaptive pack.

This is deliberately narrower than the release tool: it refuses reviewed
packs, reviewer evidence, and release statuses.  Authors can use it after a
content edit to refresh record, material, chart, and artifact checksums before
running the normal validator.  It never turns a draft into a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from hermes_domains.xingce_adaptive_pack import DRAFT_STATUS, canonical_json_sha256, load_xingce_adaptive_pack, record_sha256


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _material_digest(records: list[dict[str, Any]], *, kinds: set[str] | None = None) -> str:
    payload = [
        {"record_id": record["record_id"], "source_material": record["source_material"]}
        for record in records
        if "source_material" in record and (kinds is None or record["source_material"].get("kind") in kinds)
    ]
    return canonical_json_sha256(payload)


def refresh(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest = _read(root / "manifest.json")
    if manifest.get("status") != DRAFT_STATUS or manifest.get("release_ready") is not False:
        raise ValueError("only draft_unreviewed packs may be refreshed")
    records = _read(root / "records.json")
    skills = _read(root / "skill-graph.json")
    taxonomy = _read(root / "misconceptions.json")
    rows = records.get("records")
    if not isinstance(rows, list):
        raise ValueError("records.json must contain a records list")
    for record in rows:
        if not isinstance(record, dict):
            raise ValueError("records must be objects")
        record["record_sha256"] = record_sha256(record)
    evidence = manifest.get("content_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("manifest content_evidence must be an object")
    if "material_checksum" in evidence:
        evidence["material_checksum"] = _material_digest(rows)
    if "asset_checksum" in evidence and manifest.get("form") == "material_mcq":
        evidence["asset_checksum"] = _material_digest(rows, kinds={"chart"})
    _write(root / "records.json", records)
    for document in (skills, taxonomy):
        if document.get("review_status") != DRAFT_STATUS:
            raise ValueError("draft support documents must remain draft_unreviewed")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("manifest artifacts must be a list")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise ValueError("invalid manifest artifact")
        artifact["sha256"] = _sha256(root / artifact["path"])
    _write(root / "manifest.json", manifest)
    return load_xingce_adaptive_pack(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    args = parser.parse_args()
    result = refresh(args.pack)
    print(json.dumps({key: result[key] for key in ("pack_id", "pack_version", "status", "subtype_id")}, ensure_ascii=False))
