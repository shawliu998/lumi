from __future__ import annotations

import hashlib
from contextlib import closing
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication
from hermes_service.xingce_question_bank import (
    QuestionBankAssetUnavailable,
    QuestionBankConflict,
    XingceQuestionBankCatalog,
    configured_export_root,
)


SCHEMA = """
CREATE TABLE questions (
  question_id TEXT PRIMARY KEY, release_state TEXT NOT NULL,
  module TEXT NOT NULL, year INTEGER, region TEXT, paper_title TEXT,
  question_no INTEGER, type TEXT, stem_text TEXT NOT NULL,
  material_text TEXT NOT NULL, requirement_text TEXT NOT NULL,
  difficulty TEXT, option_count INTEGER NOT NULL, has_assets INTEGER NOT NULL, content_signature TEXT NOT NULL
);
CREATE TABLE options (
  option_id TEXT PRIMARY KEY, question_id TEXT NOT NULL, label TEXT NOT NULL,
  option_order INTEGER NOT NULL, option_text TEXT NOT NULL
);
CREATE TABLE answer_keys (question_id TEXT PRIMARY KEY, answer_labels TEXT NOT NULL);
CREATE TABLE explanations (question_id TEXT PRIMARY KEY, explanation_text TEXT NOT NULL);
CREATE TABLE subtype_catalog (subtype_id TEXT PRIMARY KEY, display_name TEXT NOT NULL);
CREATE TABLE question_subtypes (question_id TEXT PRIMARY KEY, subtype_id TEXT NOT NULL);
CREATE VIEW ready_questions AS SELECT question_id,module,year,region,paper_title,question_no,type,stem_text,material_text,requirement_text,difficulty,option_count,has_assets,content_signature FROM questions WHERE release_state='ready';
CREATE VIEW ready_question_subtypes AS SELECT s.* FROM question_subtypes s JOIN questions q USING(question_id) WHERE q.release_state='ready';
CREATE VIEW ready_options AS SELECT o.* FROM options o JOIN questions q USING(question_id) WHERE q.release_state='ready';
CREATE VIEW ready_answer_keys AS SELECT a.* FROM answer_keys a JOIN questions q USING(question_id) WHERE q.release_state='ready';
CREATE VIEW ready_explanations AS SELECT e.* FROM explanations e JOIN questions q USING(question_id) WHERE q.release_state='ready';
"""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export(root: Path, *, ready_has_assets: bool = False) -> Path:
    export = root / "versioned export with spaces"
    export.mkdir(parents=True)
    schema = export / "schema.sql"
    schema.write_text(SCHEMA, encoding="utf-8")
    database = export / "lumi-question-bank.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO subtype_catalog VALUES (?,?)", ("xingce.verbal.main_idea", "主旨概括"))
        rows = [
            ("q_ready", "ready", "言语理解", 2025, "国考", "2025 国考", 1, "single", "作者意在说明什么？", "材料中的增长并非偶然。", "请选择最恰当的一项。", "中等", 4, int(ready_has_assets), "a" * 64),
            ("q_review", "needs_review", "言语理解", 2024, "某省", "待审题本", 2, "single", "这道题尚待审核", "待审材料", "请选择。", "未知", 2, 0, "b" * 64),
        ]
        connection.executemany("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.executemany(
            "INSERT INTO question_subtypes VALUES (?,?)",
            (("q_ready", "xingce.verbal.main_idea"), ("q_review", "xingce.verbal.main_idea")),
        )
        options = [
            ("r_a", "q_ready", "A", 1, "强调长期积累"),
            ("r_b", "q_ready", "B", 2, "否认现实变化"),
            ("r_c", "q_ready", "C", 3, "只介绍一个数字"),
            ("r_d", "q_ready", "D", 4, "讨论无关问题"),
            ("n_a", "q_review", "A", 1, "待审 A"),
            ("n_b", "q_review", "B", 2, "待审 B"),
        ]
        connection.executemany("INSERT INTO options VALUES (?,?,?,?,?)", options)
        connection.executemany("INSERT INTO answer_keys VALUES (?,?)", (("q_ready", "A"), ("q_review", "B")))
        connection.executemany("INSERT INTO explanations VALUES (?,?)", (("q_ready", "材料的中心是长期积累。"), ("q_review", "待审私有解析")))
    manifest = {
        "manifest_schema": "lumi.xingce-full-bank-export.v1",
        "schema_version": 1,
        "export_id": "cleaned17-test",
        "export_version": "1.0.0",
        "generated_at": "2026-07-14T00:00:00+00:00",
        "counts": {"questions": 2, "questions_ready": 1, "questions_needs_review": 1},
        "files": [
            {"role": "schema", "path": "schema.sql", "sha256": _digest(schema), "bytes": schema.stat().st_size},
            {"role": "database", "path": "lumi-question-bank.sqlite3", "sha256": _digest(database), "bytes": database.stat().st_size},
        ],
        "checksum_index": {
            "path": "SHA256SUMS",
            "algorithm": "sha256",
            "covers": ["manifest.json", "schema.sql", "lumi-question-bank.sqlite3"],
        },
    }
    manifest_path = export / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    (export / "SHA256SUMS").write_text(
        "".join(
            f"{_digest(export / filename)}  {filename}\n"
            for filename in ("manifest.json", "schema.sql", "lumi-question-bank.sqlite3")
        ),
        encoding="ascii",
    )
    return export


class QuestionBankCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.export = _export(self.root)
        self.ledger = self.root / "sidecar.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def catalog(self) -> XingceQuestionBankCatalog:
        return XingceQuestionBankCatalog(self.export, attempt_database=self.ledger)

    def test_missing_and_tampered_exports_are_honestly_unavailable(self) -> None:
        missing = XingceQuestionBankCatalog(None, attempt_database=self.ledger)
        self.assertEqual(missing.status()["reason"], "export_not_configured")
        (self.export / "schema.sql").write_text("tampered", encoding="utf-8")
        status = self.catalog().status()
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "integrity_validation_failed")
        self.assertNotIn(str(self.export), json.dumps(status))

    def test_each_required_artifact_is_checksum_bound(self) -> None:
        for filename in ("manifest.json", "schema.sql", "lumi-question-bank.sqlite3"):
            with self.subTest(filename=filename):
                export = _export(self.root / filename.replace(".", "-"))
                with (export / filename).open("ab") as handle:
                    handle.write(b"tamper")
                self.assertFalse(
                    XingceQuestionBankCatalog(export, attempt_database=self.ledger).available
                )

    def test_controlled_default_pointer_resolution_never_falls_back_to_factory(self) -> None:
        home = self.root / "home"
        self.assertIsNone(configured_export_root(None, home=home))
        current = home / "Library" / "Application Support" / "com.lumi.learning" / "content" / "xingce-full-bank" / "current"
        current.mkdir(parents=True)
        self.assertEqual(configured_export_root(None, home=home), current)
        explicit = self.root / "explicit-missing"
        self.assertEqual(configured_export_root(explicit, home=home), explicit)

    def test_status_and_list_expose_only_ready_safe_metadata(self) -> None:
        catalog = self.catalog()
        status = catalog.status()
        self.assertTrue(status["available"])
        self.assertEqual(status["export"]["counts"], {"total": 2, "ready": 1, "needs_review": 1})
        self.assertEqual(status["export"]["access_counts"], {"direct_practice_ready": 1, "asset_gated": 0})
        result = catalog.list_questions(q="增长", page=1, page_size=10)
        self.assertEqual([item["question_id"] for item in result["items"]], ["q_ready"])
        self.assertEqual(result["pagination"]["total_items"], 1)
        self.assertEqual(result["filters"]["subtype_id"], "")
        serialized = json.dumps(result, ensure_ascii=False).lower()
        for forbidden in ("answer", "explanation", "is_correct", "待审私有解析", str(self.export).lower()):
            self.assertNotIn(forbidden, serialized)

    def test_detail_redacts_scoring_and_needs_review_is_not_addressable(self) -> None:
        catalog = self.catalog()
        detail = catalog.question("q_ready")
        self.assertEqual(detail["question"]["options"][0], {"label": "A", "text": "强调长期积累"})
        serialized = json.dumps(detail, ensure_ascii=False).lower()
        self.assertNotIn("answer", serialized)
        self.assertNotIn("explanation", serialized)
        with self.assertRaises(KeyError):
            catalog.question("q_review")

    def test_attempt_reveals_answer_only_after_submission_and_is_idempotent(self) -> None:
        catalog = self.catalog()
        payload = dict(
            selected_response="A",
            confidence="high",
            elapsed_seconds=12,
            command_id="c_" + "A" * 40,
        )
        first = catalog.attempt("q_ready", **payload)
        self.assertTrue(first["correct"])
        self.assertEqual(first["answer"], "A")
        self.assertEqual(first["explanation"], "材料的中心是长期积累。")
        self.assertTrue(first["practice_only"])
        self.assertTrue(first["evidence_proposal_only"])
        self.assertFalse(first["learner_state_updated"])
        replay = catalog.attempt("q_ready", **payload)
        self.assertEqual(replay["attempt_id"], first["attempt_id"])
        self.assertTrue(replay["idempotent_replay"])
        with self.assertRaises(QuestionBankConflict):
            catalog.attempt("q_ready", **{**payload, "selected_response": "B"})
        with self.assertRaises(KeyError):
            catalog.attempt("q_review", **payload)

    def test_asset_question_is_visible_but_cannot_be_scored_without_bundle(self) -> None:
        separate = self.root / "asset-case"
        separate.mkdir()
        export = _export(separate, ready_has_assets=True)
        catalog = XingceQuestionBankCatalog(export, attempt_database=separate / "attempts.sqlite3")
        self.assertEqual(catalog.status()["export"]["access_counts"], {"direct_practice_ready": 0, "asset_gated": 1})
        detail = catalog.question("q_ready")
        self.assertEqual(
            detail["attempt"],
            {
                "allowed": False,
                "reason": "asset_not_bundled",
                "mode": "practice_only",
                "evidence_proposal_only": True,
                "writes_learner_state": False,
            },
        )
        self.assertEqual(detail["question"]["assets"], [])
        with self.assertRaises(QuestionBankAssetUnavailable):
            catalog.attempt(
                "q_ready",
                selected_response="A",
                confidence="medium",
                elapsed_seconds=1,
                command_id="c_" + "C" * 40,
            )

    def test_query_validation_is_closed_and_bounded(self) -> None:
        catalog = self.catalog()
        for kwargs in ({"page": 0}, {"page": 1_000_001}, {"page_size": 101}, {"q": "x" * 101}, {"subtype_id": "bad/value"}):
            with self.assertRaises(ValueError):
                catalog.list_questions(**kwargs)
        # SQL wildcard input is literal rather than an accidental match-all.
        self.assertEqual(catalog.list_questions(q="%")['items'], [])


class QuestionBankHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        export = _export(root)
        application = SidecarApplication(root / "sidecar.sqlite3", xingce_full_bank_export=export)
        self.server = create_server(application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            self.base + path,
            method=method,
            data=data,
            headers={} if body is None else {"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()

    def test_four_stable_routes_and_capability_are_available(self) -> None:
        status, metadata = self.request("GET", "/v1/xingce/question-bank")
        self.assertEqual(status, 200)
        self.assertTrue(metadata["available"])
        status, listing = self.request("GET", "/v1/xingce/question-bank/questions?page=1&page_size=1")
        self.assertEqual(status, 200)
        self.assertEqual(listing["items"][0]["question_id"], "q_ready")
        status, detail = self.request("GET", "/v1/xingce/question-bank/questions/q_ready")
        self.assertEqual(status, 200)
        self.assertNotIn("answer", json.dumps(detail).lower())
        status, attempt = self.request(
            "POST",
            "/v1/xingce/question-bank/questions/q_ready/attempts",
            {"selected_response": "B", "confidence": "medium", "elapsed_seconds": 20, "command_id": "c_" + "B" * 40},
        )
        self.assertEqual(status, 201)
        self.assertFalse(attempt["correct"])
        self.assertEqual(attempt["answer"], "A")
        status, capabilities = self.request("GET", "/v1/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(capabilities["endpoints"]["xingce_question_bank"], "GET /v1/xingce/question-bank")

    def test_closed_query_and_needs_review_isolation(self) -> None:
        status, error = self.request("GET", "/v1/xingce/question-bank/questions?offset=0")
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "invalid_query")
        status, error = self.request("GET", "/v1/xingce/question-bank/questions/q_review")
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "question_not_found")

    def test_asset_attempt_http_fails_closed(self) -> None:
        root = Path(self.temporary.name) / "asset-http"
        root.mkdir()
        export = _export(root, ready_has_assets=True)
        application = SidecarApplication(root / "sidecar.sqlite3", xingce_full_bank_export=export)
        server = create_server(application, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        previous = self.base
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            status, error = self.request(
                "POST",
                "/v1/xingce/question-bank/questions/q_ready/attempts",
                {"selected_response": "A", "confidence": "low", "elapsed_seconds": 1, "command_id": "c_" + "C" * 40},
            )
            self.assertEqual(status, 409)
            self.assertEqual(error["error"]["code"], "question_assets_not_bundled")
        finally:
            self.base = previous
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
