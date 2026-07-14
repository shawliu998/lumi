#!/usr/bin/env python3
"""Install a pinned Lumi offline question-asset pack into controlled app data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIN = ROOT / "domains/content/xingce/offline-question-assets.release.v1.json"
DEFAULT_DESTINATION = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lumi.learning"
    / "content"
    / "xingce-question-assets"
)
ROOT_FILES = ("manifest.json", "schema.sql", "lumi-question-assets.sqlite3")
CHECKSUM_FILE = "SHA256SUMS"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_RELEASE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
SAFE_BLOB = re.compile(r"^blobs/[0-9a-f]{2}/[0-9a-f]{64}\.(png|jpg|gif|webp)$")


class AssetInstallError(RuntimeError):
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
        raise AssetInstallError(f"{path.name} must contain a JSON object")
    return document


def checksum_index(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        if match is None or match.group(2) in result:
            raise AssetInstallError("asset SHA256SUMS is invalid")
        relative = PurePosixPath(match.group(2))
        if relative.is_absolute() or ".." in relative.parts:
            raise AssetInstallError("asset checksum path escapes its release")
        result[str(relative)] = match.group(1)
    return result


def verify_export(source: Path, pin: Mapping[str, Any]) -> dict[str, Any]:
    source = source.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise AssetInstallError("asset source is not a directory")
    release = pin.get("export")
    expected_counts = pin.get("counts")
    if not isinstance(release, dict) or not isinstance(expected_counts, dict):
        raise AssetInstallError("asset release pin is incomplete")
    required_hashes = {
        "manifest.json": release.get("manifest_sha256"),
        "schema.sql": release.get("schema_sha256"),
        "lumi-question-assets.sqlite3": release.get("catalog_sha256"),
        CHECKSUM_FILE: release.get("checksum_index_sha256"),
    }
    if any(not isinstance(value, str) or SHA256.fullmatch(value) is None for value in required_hashes.values()):
        raise AssetInstallError("asset release pin contains an invalid digest")
    for filename, expected in required_hashes.items():
        path = source / filename
        if not path.is_file() or path.is_symlink() or digest(path) != expected:
            raise AssetInstallError(f"pinned asset checksum mismatch: {filename}")
    checksums = checksum_index(source / CHECKSUM_FILE)
    if set(ROOT_FILES) - set(checksums):
        raise AssetInstallError("asset checksum index omits a root artifact")
    manifest = load_json(source / "manifest.json")
    if (
        manifest.get("manifest_schema") != release.get("manifest_schema")
        or manifest.get("schema_version") != 1
        or manifest.get("export_id") != release.get("export_id")
        or manifest.get("export_version") != release.get("export_version")
        or manifest.get("source_question_export", {}).get("database_sha256")
        != release.get("source_question_database_sha256")
    ):
        raise AssetInstallError("asset export identity does not match its release pin")
    blobs = manifest.get("blobs")
    counts = manifest.get("counts")
    if not isinstance(blobs, list) or not isinstance(counts, dict):
        raise AssetInstallError("asset export manifest is incomplete")
    blob_paths: set[str] = set()
    blob_bytes = 0
    for row in blobs:
        if not isinstance(row, dict):
            raise AssetInstallError("asset blob entry is invalid")
        relative = row.get("path")
        expected = row.get("sha256")
        size = row.get("bytes")
        media_type = row.get("media_type")
        if (
            not isinstance(relative, str)
            or SAFE_BLOB.fullmatch(relative) is None
            or relative in blob_paths
            or not isinstance(expected, str)
            or SHA256.fullmatch(expected) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or media_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}
        ):
            raise AssetInstallError("asset blob entry is invalid")
        blob_paths.add(relative)
        blob_bytes += size
        path = source / relative
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != size
            or checksums.get(relative) != expected
            or digest(path) != expected
        ):
            raise AssetInstallError(f"asset blob checksum mismatch: {relative}")
    if set(checksums) != set(ROOT_FILES) | blob_paths:
        raise AssetInstallError("asset checksum index contains an undeclared artifact")
    for filename in ROOT_FILES:
        if checksums[filename] != required_hashes[filename] or digest(source / filename) != checksums[filename]:
            raise AssetInstallError(f"asset root artifact checksum mismatch: {filename}")
    projected = {
        "flagged_asset_questions": counts.get("flagged_asset_questions"),
        "attempt_unlocked": counts.get("attempt_unlocked"),
        "attempt_blocked": counts.get("attempt_blocked"),
        "bundled_complete": counts.get("dependency_states", {}).get("bundled_complete"),
        "not_required_for_attempt": counts.get("dependency_states", {}).get("not_required_for_attempt"),
        "required_remote": counts.get("dependency_states", {}).get("required_remote"),
        "required_mixed": counts.get("dependency_states", {}).get("required_mixed"),
        "required_local_unavailable": counts.get("dependency_states", {}).get("required_local_unavailable"),
        "blob_files": len(blob_paths),
        "blob_bytes": blob_bytes,
    }
    if projected != expected_counts:
        raise AssetInstallError("asset export counts do not match the release pin")
    return manifest


def install(source: Path, destination_root: Path, pin_path: Path) -> dict[str, Any]:
    pin = load_json(pin_path.expanduser().resolve(strict=True))
    if pin.get("schema_version") != "lumi.xingce-offline-assets-release.v1":
        raise AssetInstallError("unsupported asset release pin")
    source = source.expanduser().resolve(strict=True)
    manifest = verify_export(source, pin)
    release_id = pin.get("release_id")
    if not isinstance(release_id, str) or SAFE_RELEASE.fullmatch(release_id) is None:
        raise AssetInstallError("asset release_id is not path-safe")
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
            checksums = checksum_index(source / CHECKSUM_FILE)
            for relative in sorted((*checksums, CHECKSUM_FILE)):
                target = temporary / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / relative, target)
                target.chmod(0o444)
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
        "schema_version": "lumi.xingce-offline-assets-install.v1",
        "release_id": release_id,
        "export_version": manifest["export_version"],
        "installed_now": installed_now,
        "verified": True,
        "attempt_unlocked": manifest["counts"]["attempt_unlocked"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="versioned offline asset export directory")
    parser.add_argument("--destination-root", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--pin", type=Path, default=DEFAULT_PIN)
    args = parser.parse_args()
    print(json.dumps(install(args.source, args.destination_root, args.pin), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
