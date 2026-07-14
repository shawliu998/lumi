from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from install_xingce_full_bank import InstallError, install


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> tuple[Path, Path]:
    source = root / "source"
    source.mkdir()
    schema = source / "schema.sql"
    schema.write_text("CREATE TABLE sample(id TEXT);\n", encoding="utf-8")
    database = source / "lumi-question-bank.sqlite3"
    database.write_bytes(b"sealed-test-database")
    manifest = {
        "manifest_schema": "lumi.xingce-full-bank-export.v1",
        "export_id": "test-export",
        "export_version": "v1",
        "counts": {"questions": 3, "questions_ready": 2, "questions_needs_review": 1},
    }
    manifest_path = source / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    checksums = {name: _sha(source / name) for name in ("manifest.json", "schema.sql", "lumi-question-bank.sqlite3")}
    (source / "SHA256SUMS").write_text(
        "".join(f"{value}  {name}\n" for name, value in checksums.items()),
        encoding="ascii",
    )
    pin = {
        "schema_version": "lumi.xingce-full-bank-release.v1",
        "release_id": "test-export-v1",
        "export": {
            "manifest_schema": manifest["manifest_schema"],
            "export_id": manifest["export_id"],
            "export_version": manifest["export_version"],
            "manifest_sha256": checksums["manifest.json"],
            "schema_sha256": checksums["schema.sql"],
            "database_sha256": checksums["lumi-question-bank.sqlite3"],
            "database_bytes": database.stat().st_size,
        },
        "counts": {"questions_total": 3, "questions_ready": 2, "questions_needs_review": 1},
    }
    pin_path = root / "pin.json"
    pin_path.write_text(json.dumps(pin, sort_keys=True), encoding="utf-8")
    return source, pin_path


class InstallXingceFullBankTests(unittest.TestCase):
    def test_installs_verified_version_and_atomically_points_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, pin = _fixture(root)
            destination = root / "app-data"
            result = install(source, destination, pin)
            self.assertTrue(result["verified"])
            self.assertTrue(result["installed_now"])
            self.assertEqual((destination / "current").resolve(), (destination / "versions/test-export-v1").resolve())
            self.assertEqual(install(source, destination, pin)["installed_now"], False)

    def test_rejects_drift_before_switching_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, pin = _fixture(root)
            (source / "lumi-question-bank.sqlite3").write_bytes(b"changed")
            with self.assertRaises(InstallError):
                install(source, root / "app-data", pin)
            self.assertFalse((root / "app-data/current").exists())


if __name__ == "__main__":
    unittest.main()
