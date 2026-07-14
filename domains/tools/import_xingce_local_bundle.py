#!/usr/bin/env python3
"""Create a local-only Lumi item payload from a versioned Xingce manifest.

The public manifest contains provenance and signatures, never source question
text. This importer reads the separate question-bank factory without mutating
it and writes a compact payload under an ignored local_content directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


REQUIRED_QUESTION_FIELDS = (
    "question_id",
    "material_text",
    "stem_text",
    "explanation_text",
    "answer_labels",
    "content_signature",
    "content_answer_signature",
)
PUBLIC_TEXT_FIELDS = ("material_text", "stem_text", "explanation_text")


class ImportContractError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_selected_jsonl(path: Path, ids: set[str]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            question_id = row.get("question_id")
            if question_id in ids:
                if question_id in selected:
                    raise ImportContractError(f"duplicate question row: {question_id}")
                selected[question_id] = row
    missing = ids - selected.keys()
    if missing:
        raise ImportContractError(f"missing selected rows in {path.name}: {sorted(missing)}")
    return selected


def read_selected_options(path: Path, ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    selected = {question_id: [] for question_id in ids}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            question_id = row.get("question_id")
            if question_id in selected:
                selected[question_id].append(row)
    return selected


def build_local_payload(manifest: dict[str, Any], source_root: Path) -> dict[str, Any]:
    source_manifest = source_root / "manifest.json"
    expected_manifest_hash = manifest["source_bundle"]["manifest_sha256"]
    if sha256_file(source_manifest) != expected_manifest_hash:
        raise ImportContractError("source bundle manifest checksum mismatch")

    items = manifest["items"]
    ids = {item["question_id"] for item in items}
    if ids != set(manifest["selection"]["selected_question_ids"]):
        raise ImportContractError("selection IDs and item IDs differ")
    questions = read_selected_jsonl(source_root / "questions.jsonl", ids)
    options = read_selected_options(source_root / "options.jsonl", ids)

    payload_items = []
    for item in items:
        question_id = item["question_id"]
        question = questions[question_id]
        for field in REQUIRED_QUESTION_FIELDS:
            if not question.get(field):
                raise ImportContractError(f"{question_id} missing {field}")
        for field in ("content_signature", "content_answer_signature"):
            if question[field] != item[field]:
                raise ImportContractError(f"{question_id} {field} mismatch")
        if question.get("quality_status") != "ready":
            raise ImportContractError(f"{question_id} is not ready")
        if not question.get("is_import_ready") or not question.get("is_scoreable"):
            raise ImportContractError(f"{question_id} is not importable and scoreable")
        if question.get("has_image_options"):
            raise ImportContractError(f"{question_id} has image-dependent options")
        if not item.get("text_sufficient_reviewed"):
            raise ImportContractError(f"{question_id} lacks text-sufficiency review")

        question_options = sorted(options[question_id], key=lambda row: row["option_order"])
        labels = [row.get("label") for row in question_options]
        if len(question_options) != 4 or labels != ["A", "B", "C", "D"]:
            raise ImportContractError(f"{question_id} must have exactly A-D text options")
        if any(not row.get("option_text") for row in question_options):
            raise ImportContractError(f"{question_id} has an empty option")
        correct_labels = [row["label"] for row in question_options if row.get("is_correct")]
        if "|".join(correct_labels) != question["answer_labels"]:
            raise ImportContractError(f"{question_id} answer cannot be resolved from options")

        payload_items.append(
            {
                "question_id": question_id,
                "diagnostic_role": item["diagnostic_role"],
                "candidate_skills": item["candidate_skills"],
                "source": {
                    key: item[key]
                    for key in (
                        "source_question_key",
                        "source_question_id",
                        "paper_id",
                        "paper_title",
                        "year",
                        "question_no",
                        "source_site",
                        "source_url",
                        "content_signature",
                        "content_answer_signature",
                    )
                },
                "material_text": question["material_text"],
                "stem_text": question["stem_text"],
                "options": [
                    {"label": row["label"], "text": row["option_text"]}
                    for row in question_options
                ],
                "answer_labels": question["answer_labels"],
                "explanation_text": question["explanation_text"],
            }
        )
    return {
        "schema_version": "lumi.xingce-local-payload.v0",
        "release_id": manifest["release_id"],
        "distribution": "local_only",
        "source_manifest_sha256": expected_manifest_hash,
        "items": payload_items,
    }


def default_source_root(manifest: dict[str, Any]) -> Path:
    name_parts = manifest["source_bundle"].get("name_parts")
    if (
        not isinstance(name_parts, list)
        or len(name_parts) < 2
        or any(not isinstance(part, str) or not part for part in name_parts)
    ):
        raise ImportContractError("source bundle name_parts must contain non-empty path fragments")
    return (
        Path.home()
        / "Documents"
        / "xingcetiku"
        / "data"
        / "final"
        / "-".join(name_parts)
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parents[1]
    default_manifest = here / "content" / "xingce" / "p031-data-analysis-v1" / "manifest.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=here / "local_content" / "xingce" / "p031-data-analysis-v1.json",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    source_root = args.source_root or default_source_root(manifest)
    payload = build_local_payload(manifest, source_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "release_id": payload["release_id"],
                "items": len(payload["items"]),
                "output": str(args.output),
                "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
