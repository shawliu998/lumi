#!/usr/bin/env python3
"""Create a hash-bound release copy from a reviewed Xingce adaptive draft.

The caller supplies a human-authored JSON transcription beside the completed
workbook.  This program never invents reviewer ids, dates, conclusions, or
signatures; it only accepts two distinct approved reviewers and copies the
immutable source into a new release directory.
"""
from __future__ import annotations

import argparse, hashlib, json, shutil
from pathlib import Path
from typing import Any

from hermes_domains.xingce_adaptive_pack import load_xingce_adaptive_pack, record_sha256, reviewed_manifest_sha256


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise ValueError(f"expected JSON object: {path}")
    return value

def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def create(source: Path, output: Path, workbook: Path, attestations: Path) -> dict[str, Any]:
    source, output, workbook, attestations = (item.resolve() for item in (source, output, workbook, attestations))
    if output.exists(): raise ValueError("release output already exists")
    if not workbook.is_file() or not attestations.is_file(): raise ValueError("completed workbook and attestation JSON are required")
    load_xingce_adaptive_pack(source)
    signed = read(attestations); rows = signed.get("reviewer_attestations")
    if not isinstance(rows, list) or len(rows) != 2: raise ValueError("exactly two reviewer attestations are required")
    kinds = {row.get("review_kind") for row in rows if isinstance(row, dict)}
    reviewers = {row.get("reviewer_id") for row in rows if isinstance(row, dict)}
    if kinds != {"logic", "editorial_rights"} or len(reviewers) != 2 or None in reviewers: raise ValueError("two different logic/editorial-rights reviewers are required")
    if any(row.get("status") != "approved" or not isinstance(row.get("reviewed_at"), str) for row in rows): raise ValueError("every reviewer attestation must be approved and dated")
    shutil.copytree(source, output)
    manifest, records, skills, taxonomy = (read(output / name) for name in ("manifest.json", "records.json", "skill-graph.json", "misconceptions.json"))
    version = str(signed.get("release_version", "")).strip()
    if not version: raise ValueError("attestation JSON must provide release_version")
    for doc in (records, skills, taxonomy): doc["pack_version"] = version; doc["review_status"] = "release_ready"
    for row in records["records"]: row["review_status"] = "release_ready"; row["record_sha256"] = record_sha256(row)
    write(output / "records.json", records); write(output / "skill-graph.json", skills); write(output / "misconceptions.json", taxonomy)
    evidence = {"schema_version":"lumi.xingce-review-evidence.v1","source_pack_id":manifest["pack_id"],"source_pack_version":manifest["pack_version"],"manual_review_workbook":{"name":workbook.name,"sha256":sha(workbook)},"reviewer_attestations":rows}
    write(output / "review-evidence.json", evidence)
    manifest.update({"pack_version":version,"status":"release_ready","release_ready":True,"runtime_registration":"allowed_after_human_review"})
    manifest["rights"]["distribution"]="release_distribution_allowed"
    manifest["human_review_gate"]={"required":True,"production_load_allowed":True,"review_attestations":[]}
    artifacts=[item for item in manifest["artifacts"] if item["path"] != "review-evidence.json"]+[{"path":"review-evidence.json","sha256":""}]
    manifest["artifacts"]=[{"path":item["path"],"sha256":sha(output/item["path"])} for item in artifacts]
    manifest["human_review_gate"]["review_attestations"]=[{**row,"manifest_sha256":reviewed_manifest_sha256(manifest)} for row in rows]
    write(output / "manifest.json", manifest)
    return load_xingce_adaptive_pack(output, require_reviewed=True)

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--source",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--review-workbook",type=Path,required=True); p.add_argument("--attestations",type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(create(args.source, args.output, args.review_workbook, args.attestations),ensure_ascii=False,indent=2))
