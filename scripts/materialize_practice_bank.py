#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
DOMAINS = WORKSPACE / "domains"
if str(DOMAINS) not in sys.path:
    sys.path.insert(0, str(DOMAINS))

from hermes_domains.practice_bank_v3 import load_practice_bank  # noqa: E402
from hermes_domains.practice_v3_common import MODULE_ORDER, MODULE_SCOPES  # noqa: E402


def _outside_workspace(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == WORKSPACE or WORKSPACE in resolved.parents:
        raise SystemExit(
            "bulk question-bank exports must stay outside the Lumi Git workspace; "
            "choose a local application-data or exchange directory"
        )
    return resolved


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, value: object) -> tuple[str, int]:
    """Atomically write canonical export bytes and return their integrity metadata."""

    payload = _json_bytes(value)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def materialize(output: Path) -> dict[str, object]:
    bank = load_practice_bank()
    destination = _outside_workspace(output) / bank["bank_id"] / bank["version"]
    destination.mkdir(parents=True, exist_ok=True)
    destination = _outside_workspace(destination)

    files: list[dict[str, object]] = []
    for module in MODULE_ORDER:
        scope_id = MODULE_SCOPES[module]
        questions = [item for item in bank["questions"] if item["module_id"] == scope_id]
        filename = f"{module}.questions.json"
        file_sha256, size_bytes = _write_json(
            destination / filename,
            {
                "schema_version": "lumi.materialized-question-module.v1",
                "bank_id": bank["bank_id"],
                "bank_version": bank["version"],
                "scope_id": scope_id,
                "question_count": len(questions),
                "questions": questions,
            },
        )
        files.append(
            {
                "path": filename,
                "scope_id": scope_id,
                "question_count": len(questions),
                "sha256": file_sha256,
                "size_bytes": size_bytes,
            }
        )

    manifest = {
        "schema_version": "lumi.materialized-practice-bank.v1",
        "bank_id": bank["bank_id"],
        "version": bank["version"],
        "generator_version": bank["generator_version"],
        "generated_sha256": bank["generated_sha256"],
        "question_count": len(bank["questions"]),
        "files": files,
    }
    _write_json(destination / "manifest.json", manifest)
    return {"output": str(destination), **manifest}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize Lumi's manifest-pinned 320-item practice bank outside Git."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "Lumi" / "content-packs",
        help="base directory outside the Lumi repository",
    )
    arguments = parser.parse_args()
    print(json.dumps(materialize(arguments.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
