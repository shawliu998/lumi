from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from hermes_service.xingce_question_assets import (
    QuestionAssetNotFound,
    QuestionAssetUnavailable,
    XingceQuestionAssetCatalog,
    configured_asset_export_root,
)


SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE question_asset_policy(question_id TEXT PRIMARY KEY,dependency_state TEXT,required_asset_count INTEGER,bundled_required_asset_count INTEGER,explanation_asset_count INTEGER,unreferenced_asset_count INTEGER,can_attempt INTEGER);
CREATE TABLE asset_bindings(asset_id TEXT PRIMARY KEY,question_id TEXT,source_kind TEXT,availability TEXT,content_sha256 TEXT,media_type TEXT,relative_path TEXT);
CREATE TABLE asset_placements(asset_id TEXT,placement TEXT,option_label TEXT);
"""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fixture(root: Path, question_database_sha256: str, *, include_explanation: bool = True) -> Path:
    export = root / "asset export"
    blob_dir = export / "blobs" / "ab"
    blob_dir.mkdir(parents=True)
    blob = blob_dir / ("a" * 64 + ".png")
    blob.write_bytes(b"\x89PNG\r\n\x1a\nasset-body")
    schema = export / "schema.sql"
    schema.write_text(SCHEMA, encoding="utf-8")
    database = export / "lumi-question-assets.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO metadata VALUES (?,?)", ("source_question_database_sha256", question_database_sha256))
        policies = [
            ("q_ready", "bundled_complete", 1, 1, 0, 0, 1),
        ]
        bindings = [
            ("asset_required", "q_ready", "local", "bundled", _digest(blob), "image/png", f"blobs/ab/{'a' * 64}.png"),
        ]
        placements = [("asset_required", "stem", "")]
        if include_explanation:
            policies.append(("q_explanation", "not_required_for_attempt", 0, 0, 1, 0, 1))
            bindings.append(("asset_explanation", "q_explanation", "https", "remote_not_bundled", None, "", ""))
            placements.append(("asset_explanation", "explanation", ""))
        connection.executemany(
            "INSERT INTO question_asset_policy VALUES (?,?,?,?,?,?,?)",
            policies,
        )
        connection.executemany(
            "INSERT INTO asset_bindings VALUES (?,?,?,?,?,?,?)",
            bindings,
        )
        connection.executemany(
            "INSERT INTO asset_placements VALUES (?,?,?)",
            placements,
        )
    manifest = {
        "manifest_schema": "lumi.xingce-offline-assets-export.v1",
        "schema_version": 1,
        "export_id": "fixture-assets",
        "export_version": "fixture-v1",
        "generated_at": "2026-07-14T00:00:00Z",
        "source_question_export": {"database_sha256": question_database_sha256},
        "counts": {
            "flagged_asset_questions": 2 if include_explanation else 1,
            "attempt_unlocked": 2 if include_explanation else 1,
            "attempt_blocked": 0,
        },
        "files": [
            {"path": "schema.sql", "role": "schema", "sha256": _digest(schema), "bytes": schema.stat().st_size},
            {"path": "lumi-question-assets.sqlite3", "role": "catalog", "sha256": _digest(database), "bytes": database.stat().st_size},
        ],
        "blobs": [{"path": f"blobs/ab/{'a' * 64}.png", "sha256": _digest(blob), "bytes": blob.stat().st_size, "media_type": "image/png"}],
    }
    manifest_path = export / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    paths = ("manifest.json", "schema.sql", "lumi-question-assets.sqlite3", f"blobs/ab/{'a' * 64}.png")
    (export / "SHA256SUMS").write_text("".join(f"{_digest(export / path)}  {path}\n" for path in paths), encoding="ascii")
    return export


class QuestionAssetCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.question_hash = "b" * 64
        self.export = build_fixture(self.root, self.question_hash)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_status_policy_projection_and_required_binary_are_verified(self) -> None:
        catalog = XingceQuestionAssetCatalog(self.export, question_database_sha256=self.question_hash)
        self.assertTrue(catalog.available)
        self.assertEqual(catalog.status()["counts"]["attempt_unlocked"], 2)
        self.assertTrue(catalog.policy("q_ready")["can_attempt"])
        asset = catalog.required_assets("q_ready")[0]
        self.assertEqual(asset["path"], "/v1/xingce/question-bank/assets/asset_required")
        self.assertEqual(asset["placements"], [{"placement": "stem", "option_label": ""}])
        binary = catalog.binary("asset_required")
        self.assertEqual(binary["media_type"], "image/png")
        self.assertEqual(hashlib.sha256(binary["content"]).hexdigest(), binary["content_sha256"])
        with self.assertRaises(QuestionAssetNotFound):
            catalog.binary("asset_explanation")

    def test_wrong_source_hash_and_tampering_fail_closed_without_path_leakage(self) -> None:
        wrong = XingceQuestionAssetCatalog(self.export, question_database_sha256="c" * 64)
        self.assertFalse(wrong.available)
        self.assertEqual(wrong.status()["reason"], "asset_integrity_validation_failed")
        blob = next((self.export / "blobs").rglob("*.png"))
        blob.write_bytes(b"tampered")
        tampered = XingceQuestionAssetCatalog(self.export, question_database_sha256=self.question_hash)
        self.assertFalse(tampered.available)
        self.assertNotIn(str(self.root), json.dumps(tampered.status()))

    def test_required_assets_are_reverified_after_catalog_startup(self) -> None:
        catalog = XingceQuestionAssetCatalog(
            self.export,
            question_database_sha256=self.question_hash,
        )
        self.assertEqual(
            [asset["asset_id"] for asset in catalog.verified_required_assets("q_ready")],
            ["asset_required"],
        )
        blob = next((self.export / "blobs").rglob("*.png"))
        blob.write_bytes(b"changed-after-startup")
        with self.assertRaises(QuestionAssetUnavailable):
            catalog.verified_required_assets("q_ready")

    def test_controlled_pointer_resolution_has_no_factory_fallback(self) -> None:
        home = self.root / "home"
        self.assertIsNone(configured_asset_export_root(None, home=home))
        current = home / "Library" / "Application Support" / "com.lumi.learning" / "content" / "xingce-question-assets" / "current"
        current.mkdir(parents=True)
        self.assertEqual(configured_asset_export_root(None, home=home), current)


if __name__ == "__main__":
    unittest.main()
