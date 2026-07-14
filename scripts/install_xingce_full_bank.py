#!/usr/bin/env python3
"""Install a pinned Lumi question-bank export into controlled app data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIN = ROOT / "domains/content/xingce/full-question-bank.release.v1.json"
DEFAULT_DESTINATION = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lumi.learning"
    / "content"
    / "xingce-full-bank"
)
REQUIRED_FILES = ("manifest.json", "schema.sql", "SHA256SUMS", "lumi-question-bank.sqlite3")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class InstallError(RuntimeError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise InstallError(f"{path.name} must contain a JSON object")
    return document


def checksum_index(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
        if match is None or match.group(2) in result:
            raise InstallError("SHA256SUMS is invalid")
        result[match.group(2)] = match.group(1)
    return result


def verify_export(source: Path, pin: Mapping[str, Any]) -> dict[str, Any]:
    source = source.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise InstallError("source export is not a directory")
    for filename in REQUIRED_FILES:
        path = source / filename
        if not path.is_file() or path.is_symlink():
            raise InstallError(f"required sealed file is missing: {filename}")
    release = pin.get("export")
    counts = pin.get("counts")
    if not isinstance(release, dict) or not isinstance(counts, dict):
        raise InstallError("release pin is incomplete")
    expected = {
        "manifest.json": release.get("manifest_sha256"),
        "schema.sql": release.get("schema_sha256"),
        "lumi-question-bank.sqlite3": release.get("database_sha256"),
    }
    if any(not isinstance(value, str) or SHA256.fullmatch(value) is None for value in expected.values()):
        raise InstallError("release pin contains an invalid digest")
    checksums = checksum_index(source / "SHA256SUMS")
    for filename, expected_digest in expected.items():
        if checksums.get(filename) != expected_digest or digest(source / filename) != expected_digest:
            raise InstallError(f"pinned checksum mismatch: {filename}")
    database_bytes = release.get("database_bytes")
    if isinstance(database_bytes, bool) or not isinstance(database_bytes, int):
        raise InstallError("release pin database size is invalid")
    if (source / "lumi-question-bank.sqlite3").stat().st_size != database_bytes:
        raise InstallError("pinned database size mismatch")
    manifest = load_json(source / "manifest.json")
    if (
        manifest.get("manifest_schema") != release.get("manifest_schema")
        or manifest.get("export_id") != release.get("export_id")
        or manifest.get("export_version") != release.get("export_version")
    ):
        raise InstallError("export identity does not match the release pin")
    manifest_counts = manifest.get("counts")
    if not isinstance(manifest_counts, dict) or {
        "questions_total": manifest_counts.get("questions"),
        "questions_ready": manifest_counts.get("questions_ready"),
        "questions_needs_review": manifest_counts.get("questions_needs_review"),
    } != {key: counts.get(key) for key in ("questions_total", "questions_ready", "questions_needs_review")}:
        raise InstallError("export counts do not match the release pin")
    return manifest


def install(source: Path, destination_root: Path, pin_path: Path) -> dict[str, Any]:
    pin = load_json(pin_path.expanduser().resolve(strict=True))
    if pin.get("schema_version") != "lumi.xingce-full-bank-release.v1":
        raise InstallError("unsupported release pin")
    manifest = verify_export(source, pin)
    release_id = pin.get("release_id")
    if not isinstance(release_id, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,96}", release_id) is None:
        raise InstallError("release_id is not path-safe")
    destination_root = destination_root.expanduser()
    versions = destination_root / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    destination = versions / release_id
    installed_now = False
    if destination.exists():
        verify_export(destination, pin)
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{release_id}-", dir=versions))
        try:
            for filename in REQUIRED_FILES:
                copied = temporary / filename
                shutil.copyfile(source / filename, copied)
                copied.chmod(0o444)
            verify_export(temporary, pin)
            os.replace(temporary, destination)
            installed_now = True
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    next_link = destination_root / f".current-{os.getpid()}"
    if next_link.exists() or next_link.is_symlink():
        next_link.unlink()
    next_link.symlink_to(Path("versions") / release_id, target_is_directory=True)
    os.replace(next_link, destination_root / "current")
    return {
        "schema_version": "lumi.xingce-full-bank-install.v1",
        "release_id": release_id,
        "export_version": manifest["export_version"],
        "installed_now": installed_now,
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="versioned export directory")
    parser.add_argument("--destination-root", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--pin", type=Path, default=DEFAULT_PIN)
    args = parser.parse_args()
    print(json.dumps(install(args.source, args.destination_root, args.pin), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
