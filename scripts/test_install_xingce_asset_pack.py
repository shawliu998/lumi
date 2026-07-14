from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest


from install_xingce_asset_pack import AssetInstallError, install


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AssetInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        blob = self.source / "blobs" / "aa"
        blob.mkdir(parents=True)
        self.blob = blob / ("a" * 64 + ".png")
        self.blob.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        (self.source / "schema.sql").write_text("fixture", encoding="utf-8")
        (self.source / "lumi-question-assets.sqlite3").write_bytes(b"catalog")
        manifest = {
            "manifest_schema": "lumi.xingce-offline-assets-export.v1",
            "schema_version": 1,
            "export_id": "fixture-assets",
            "export_version": "fixture-v1",
            "source_question_export": {"database_sha256": "b" * 64},
            "counts": {
                "flagged_asset_questions": 1,
                "attempt_unlocked": 1,
                "attempt_blocked": 0,
                "dependency_states": {
                    "bundled_complete": 1,
                    "not_required_for_attempt": 0,
                    "required_remote": 0,
                    "required_mixed": 0,
                    "required_local_unavailable": 0,
                },
            },
            "blobs": [{
                "path": f"blobs/aa/{'a' * 64}.png",
                "sha256": digest(self.blob),
                "bytes": self.blob.stat().st_size,
                "media_type": "image/png",
            }],
        }
        manifest_path = self.source / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        paths = ("manifest.json", "schema.sql", "lumi-question-assets.sqlite3", f"blobs/aa/{'a' * 64}.png")
        sums = self.source / "SHA256SUMS"
        sums.write_text("".join(f"{digest(self.source / name)}  {name}\n" for name in paths), encoding="ascii")
        pin = {
            "schema_version": "lumi.xingce-offline-assets-release.v1",
            "release_id": "fixture-assets",
            "export": {
                "export_id": "fixture-assets",
                "export_version": "fixture-v1",
                "manifest_schema": "lumi.xingce-offline-assets-export.v1",
                "manifest_sha256": digest(manifest_path),
                "schema_sha256": digest(self.source / "schema.sql"),
                "catalog_sha256": digest(self.source / "lumi-question-assets.sqlite3"),
                "checksum_index_sha256": digest(sums),
                "source_question_database_sha256": "b" * 64,
            },
            "counts": {
                "flagged_asset_questions": 1,
                "attempt_unlocked": 1,
                "attempt_blocked": 0,
                "bundled_complete": 1,
                "not_required_for_attempt": 0,
                "required_remote": 0,
                "required_mixed": 0,
                "required_local_unavailable": 0,
                "blob_files": 1,
                "blob_bytes": self.blob.stat().st_size,
            },
        }
        self.pin = self.root / "pin.json"
        self.pin.write_text(json.dumps(pin), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_installs_and_reverifies_sealed_asset_tree(self) -> None:
        destination = self.root / "installed"
        first = install(self.source, destination, self.pin)
        self.assertTrue(first["installed_now"])
        self.assertEqual(first["attempt_unlocked"], 1)
        current = (destination / "current").resolve()
        self.assertEqual(digest(current / self.blob.relative_to(self.source)), digest(self.blob))
        second = install(self.source, destination, self.pin)
        self.assertFalse(second["installed_now"])

    def test_tampered_blob_is_rejected(self) -> None:
        self.blob.write_bytes(b"tampered")
        with self.assertRaises(AssetInstallError):
            install(self.source, self.root / "installed", self.pin)


if __name__ == "__main__":
    unittest.main()
