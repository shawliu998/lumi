from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import quote

from .xingce_question_assets import (
    QuestionAssetNotFound,
    QuestionAssetUnavailable,
    XingceQuestionAssetCatalog,
)


MANIFEST_SCHEMA = "lumi.xingce-full-bank-export.v1"
DATABASE_FILENAME = "lumi-question-bank.sqlite3"
SCHEMA_FILENAME = "schema.sql"
CHECKSUM_FILENAME = "SHA256SUMS"
QUESTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
COMMAND_ID_PATTERN = re.compile(r"^c_[A-P]{40}$")
SUBTYPE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_QUERY_LENGTH = 100
MAX_PAGE_SIZE = 100
MAX_PAGE = 1_000_000
LOCAL_SOURCE_MARKER = re.compile(r"\[本地原卷页图：[^\]]+\]")
LOCAL_ABSOLUTE_PATH = re.compile(r"/(?:Users|Volumes)/[^\s\]\)<>\"']+")


class QuestionBankUnavailable(RuntimeError):
    pass


class QuestionBankRequestError(ValueError):
    pass


class QuestionBankNotFound(KeyError):
    pass


class QuestionBankConflict(RuntimeError):
    pass


class QuestionBankAssetUnavailable(RuntimeError):
    pass


def configured_export_root(
    explicit: str | Path | None,
    *,
    home: Path | None = None,
) -> Path | None:
    """Resolve an explicit export or the controlled per-user content pointer.

    The mutable question-bank factory is deliberately not a fallback. A missing
    pointer is a supported unavailable state; integrity is checked by the
    catalog before any content can be queried.
    """

    if explicit is not None:
        return Path(explicit).expanduser()
    root = (home or Path.home()) / "Library" / "Application Support" / "com.lumi.learning" / "content" / "xingce-full-bank" / "current"
    return root if root.exists() else None


class XingceQuestionBankCatalog:
    """Hash-verified, immutable reader for a versioned Xingce SQLite export."""

    def __init__(
        self,
        export_root: str | Path | None,
        *,
        attempt_database: str | Path,
        asset_export_root: str | Path | None = None,
    ) -> None:
        self._root = None if export_root is None else Path(export_root).expanduser()
        self._attempt_database = str(attempt_database)
        self._lock = threading.Lock()
        self._manifest: dict[str, Any] | None = None
        self._database: Path | None = None
        self._database_sha256: str | None = None
        self._unavailable_reason = "export_not_configured"
        self._columns: dict[str, str] = {}
        self._assets: XingceQuestionAssetCatalog | None = None
        if self._root is not None:
            try:
                self._load()
            except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
                # Do not expose a local path or low-level parser detail through
                # product metadata. The entire catalog remains closed.
                self._manifest = None
                self._database = None
                self._database_sha256 = None
                self._columns = {}
                self._unavailable_reason = "integrity_validation_failed"
        if self.available:
            assert self._database_sha256 is not None
            self._assets = XingceQuestionAssetCatalog(
                asset_export_root,
                question_database_sha256=self._database_sha256,
            )

    @property
    def available(self) -> bool:
        return self._manifest is not None and self._database is not None

    def status(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "schema_version": "lumi.xingce-question-bank-status.v1",
            "available": self.available,
            "status": "available" if self.available else "unavailable",
            "practice_contract": {
                "mode": "practice_only",
                "evidence_proposal_only": True,
                "writes_learner_state": False,
            },
        }
        if not self.available:
            base["reason"] = self._unavailable_reason
            return base
        assert self._manifest is not None
        counts = self._public_counts()
        access_counts = self._access_counts()
        if access_counts["direct_practice_ready"] + access_counts["asset_gated"] != counts["ready"]:
            raise QuestionBankUnavailable("question access counts do not match ready count")
        base["export"] = {
            "export_id": self._manifest["export_id"],
            "export_version": self._manifest["export_version"],
            "schema_version": self._manifest["manifest_schema"],
            "data_schema_version": self._manifest["schema_version"],
            "generated_at": self._manifest["generated_at"],
            "counts": counts,
            "access_counts": access_counts,
            "subtypes": self._subtype_counts(),
            "offline_assets": (
                self._assets.status()
                if self._assets is not None
                else {
                    "schema_version": "lumi.xingce-question-assets-status.v1",
                    "available": False,
                    "status": "unavailable",
                    "reason": "question_bank_unavailable",
                }
            ),
        }
        return base

    def list_questions(
        self,
        *,
        subtype_id: Any = None,
        q: Any = None,
        page: Any = 1,
        page_size: Any = 20,
    ) -> dict[str, Any]:
        self._require_available()
        subtype = self._optional_subtype(subtype_id)
        search = self._optional_search(q)
        page_value = self._positive_int(page, "page")
        page_size_value = self._positive_int(page_size, "page_size")
        if page_value > MAX_PAGE:
            raise QuestionBankRequestError(f"page must not exceed {MAX_PAGE}")
        if page_size_value > MAX_PAGE_SIZE:
            raise QuestionBankRequestError(f"page_size must not exceed {MAX_PAGE_SIZE}")
        where, parameters = self._where(subtype, search)
        offset = (page_value - 1) * page_size_value
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM ready_questions q JOIN ready_question_subtypes qs ON qs.question_id=q.question_id {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT q.question_id, qs.subtype_id,
                       sc.{self._columns['subtype_name']} AS subtype_name,
                       q.{self._columns['module']} AS module,
                       q.{self._columns['year']} AS year,
                       q.{self._columns['region']} AS region,
                       q.{self._columns['paper_title']} AS paper_title,
                       q.{self._columns['question_number']} AS question_number,
                       q.{self._columns['question_type']} AS question_type,
                       q.{self._columns['stem']} AS stem,
                       q.{self._columns['material']} AS material,
                       q.{self._columns['requirement']} AS requirement,
                       q.{self._columns['option_count']} AS option_count,
                       q.{self._columns['has_assets']} AS has_assets
                FROM ready_questions q
                JOIN ready_question_subtypes qs ON qs.question_id=q.question_id
                JOIN subtype_catalog sc ON sc.subtype_id=qs.subtype_id
                {where}
                ORDER BY q.question_id
                LIMIT ? OFFSET ?
                """,
                (*parameters, page_size_value, offset),
            ).fetchall()
        items = [self._list_item(row) for row in rows]
        return {
            "schema_version": "lumi.xingce-question-bank-list.v1",
            "items": items,
            "pagination": {
                "page": page_value,
                "page_size": page_size_value,
                "total_items": total,
                "total_pages": (total + page_size_value - 1) // page_size_value,
            },
            "filters": {"subtype_id": subtype or "", "q": search or ""},
        }

    def question(self, question_id: Any) -> dict[str, Any]:
        self._require_available()
        identifier = self._question_id(question_id)
        with self._connect() as connection:
            row = self._question_row(connection, identifier)
            options = self._options(connection, identifier)
        if row is None:
            raise QuestionBankNotFound(identifier)
        policy = self._attempt_policy(row)
        try:
            required_assets = self._verified_required_assets(identifier, policy)
        except QuestionBankAssetUnavailable:
            policy = {
                **policy,
                "allowed": False,
                "dependency_state": "asset_runtime_unavailable",
            }
            required_assets = []
        question = self._detail_item(
            row,
            options,
            assets=required_assets,
            asset_delivery=(
                "bundled"
                if required_assets
                else "not_required"
                if policy["allowed"]
                else "not_bundled"
            ),
        )
        attempt = {
            "allowed": policy["allowed"],
            "mode": "practice_only",
            "evidence_proposal_only": True,
            "writes_learner_state": False,
            "asset_dependency_state": policy["dependency_state"],
        }
        if not policy["allowed"]:
            attempt["reason"] = (
                "asset_runtime_unavailable"
                if policy["dependency_state"] == "asset_runtime_unavailable"
                else "asset_not_bundled"
            )
        return {
            "schema_version": "lumi.xingce-question-bank-question.v1",
            "question": question,
            "attempt": attempt,
        }

    def attempt(
        self,
        question_id: Any,
        *,
        selected_response: Any,
        confidence: Any,
        elapsed_seconds: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        self._require_available()
        identifier = self._question_id(question_id)
        if not isinstance(command_id, str) or COMMAND_ID_PATTERN.fullmatch(command_id) is None:
            raise QuestionBankRequestError("command_id must use the public c_ identifier profile")
        if not isinstance(confidence, str) or confidence not in {"low", "medium", "high"}:
            raise QuestionBankRequestError("confidence must be low, medium, or high")
        if isinstance(elapsed_seconds, bool) or not isinstance(elapsed_seconds, (int, float)) or not 0 <= elapsed_seconds <= 7200:
            raise QuestionBankRequestError("elapsed_seconds must be a number in [0, 7200]")
        with self._connect() as connection:
            row = self._question_row(connection, identifier)
            if row is None:
                raise QuestionBankNotFound(identifier)
            policy = self._attempt_policy(row)
            if not policy["allowed"]:
                raise QuestionBankAssetUnavailable("question assets are not bundled")
            self._verified_required_assets(identifier, policy)
            options = self._options(connection, identifier)
            answer_row = connection.execute(
                f"SELECT {self._columns['answer']} AS answer FROM ready_answer_keys WHERE question_id=?",
                (identifier,),
            ).fetchone()
            explanation_row = connection.execute(
                f"SELECT {self._columns['explanation']} AS explanation FROM ready_explanations WHERE question_id=?",
                (identifier,),
            ).fetchone()
        if answer_row is None:
            raise QuestionBankUnavailable("ready question has no isolated answer key")
        labels = [str(option["label"]) for option in options]
        selected = self._canonical_response(selected_response, labels)
        answer = self._canonical_response(answer_row["answer"], labels)
        correct = selected == answer
        explanation = None if explanation_row is None else _public_text(explanation_row["explanation"])
        if explanation is not None and not isinstance(explanation, str):
            raise QuestionBankUnavailable("ready question explanation is invalid")
        assert self._manifest is not None and self._database_sha256 is not None
        result = self._record_attempt(
            command_id=command_id,
            question_id=identifier,
            selected_response=selected,
            confidence=confidence,
            elapsed_seconds=float(elapsed_seconds),
            correct=correct,
            export_version=self._manifest["export_version"],
            database_sha256=self._database_sha256,
        )
        return {
            "schema_version": "lumi.xingce-question-bank-attempt.v1",
            "attempt_id": result["attempt_id"],
            "command_id": command_id,
            "question_id": identifier,
            "correct": correct,
            "selected_response": selected,
            "answer": answer,
            "explanation": explanation,
            "confidence": confidence,
            "elapsed_seconds": float(elapsed_seconds),
            "practice_only": True,
            "evidence_proposal_only": True,
            "learner_state_updated": False,
            "created_at": result["created_at"],
            "idempotent_replay": result["idempotent_replay"],
            "explanation_media_status": (
                "text_only"
                if policy["explanation_asset_count"] > 0
                else "not_required"
            ),
        }

    def _load(self) -> None:
        assert self._root is not None
        root = self._root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("export root is not a directory")
        manifest_path = root / "manifest.json"
        checksum_path = root / CHECKSUM_FILENAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("manifest_schema") != MANIFEST_SCHEMA
            or manifest.get("schema_version") != 1
        ):
            raise ValueError("unsupported full-bank manifest schema")
        for field in ("export_id", "export_version", "generated_at"):
            if not isinstance(manifest.get(field), str) or not manifest[field]:
                raise ValueError(f"manifest {field} is invalid")
        files = self._manifest_files(manifest)
        if SCHEMA_FILENAME not in files or DATABASE_FILENAME not in files:
            raise ValueError("manifest does not bind schema and database")
        if files[SCHEMA_FILENAME]["role"] != "schema" or files[DATABASE_FILENAME]["role"] != "database":
            raise ValueError("manifest artifact roles are invalid")
        checksum_index = manifest.get("checksum_index")
        if (
            not isinstance(checksum_index, dict)
            or checksum_index.get("path") != CHECKSUM_FILENAME
            or checksum_index.get("algorithm") != "sha256"
            or checksum_index.get("covers") != ["manifest.json", SCHEMA_FILENAME, DATABASE_FILENAME]
        ):
            raise ValueError("manifest checksum index is invalid")
        checksums = self._checksum_file(checksum_path)
        required = {"manifest.json", SCHEMA_FILENAME, DATABASE_FILENAME}
        if not required.issubset(checksums):
            raise ValueError("checksum file does not bind every required artifact")
        for filename in required:
            path = root / filename
            actual = _sha256(path)
            if actual != checksums[filename]:
                raise ValueError("artifact checksum mismatch")
            if filename in files:
                declared = files[filename]
                if actual != declared["sha256"] or path.stat().st_size != declared["bytes"]:
                    raise ValueError("manifest artifact metadata mismatch")
        database = root / DATABASE_FILENAME
        if (root / f"{DATABASE_FILENAME}-wal").exists() or (root / f"{DATABASE_FILENAME}-journal").exists():
            raise ValueError("export database is not a sealed SQLite artifact")
        self._database = database
        self._database_sha256 = checksums[DATABASE_FILENAME]
        self._manifest = manifest
        with self._connect() as connection:
            quick = connection.execute("PRAGMA quick_check").fetchone()
            if quick is None or quick[0] != "ok":
                raise ValueError("SQLite quick check failed")
            required_objects = {
                "ready_questions",
                "ready_options",
                "ready_answer_keys",
                "ready_explanations",
                "ready_question_subtypes",
                "subtype_catalog",
            }
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE name IN (?,?,?,?,?,?)",
                    tuple(sorted(required_objects)),
                )
            }
            if existing != required_objects:
                raise ValueError("SQLite export contract is incomplete")
            self._bind_columns(connection)
            leaked = connection.execute(
                "SELECT 1 FROM ready_questions q LEFT JOIN ready_answer_keys a ON a.question_id=q.question_id WHERE a.question_id IS NULL LIMIT 1"
            ).fetchone()
            if leaked is not None:
                raise ValueError("ready question lacks an answer key")
            missing_explanation = connection.execute(
                "SELECT 1 FROM ready_questions q LEFT JOIN ready_explanations e ON e.question_id=q.question_id WHERE e.question_id IS NULL LIMIT 1"
            ).fetchone()
            if missing_explanation is not None:
                raise ValueError("ready question lacks an explanation")
            counts = self._public_counts()
            access_counts = self._access_counts(connection)
            if access_counts["direct_practice_ready"] + access_counts["asset_gated"] != counts["ready"]:
                raise ValueError("question access counts do not match ready count")

    def _bind_columns(self, connection: sqlite3.Connection) -> None:
        self._columns = {
            "subtype_name": self._column(connection, "subtype_catalog", ("label", "display_name", "name", "subtype_name")),
            "module": self._column(connection, "ready_questions", ("module",)),
            "year": self._column(connection, "ready_questions", ("year",)),
            "region": self._column(connection, "ready_questions", ("region",)),
            "paper_title": self._column(connection, "ready_questions", ("paper_title",)),
            "question_number": self._column(connection, "ready_questions", ("question_no", "question_number")),
            "question_type": self._column(connection, "ready_questions", ("question_type", "type", "answer_type")),
            "stem": self._column(connection, "ready_questions", ("stem_text", "stem")),
            "material": self._column(connection, "ready_questions", ("material_text", "material")),
            "requirement": self._column(connection, "ready_questions", ("requirement_text", "requirement")),
            "difficulty": self._column(connection, "ready_questions", ("difficulty",)),
            "option_count": self._column(connection, "ready_questions", ("option_count",)),
            "has_assets": self._column(connection, "ready_questions", ("has_assets",)),
            "content_signature": self._column(connection, "ready_questions", ("content_signature", "content_hash")),
            "option_label": self._column(connection, "ready_options", ("label", "option_label")),
            "option_text": self._column(connection, "ready_options", ("option_text", "text")),
            "option_order": self._column(connection, "ready_options", ("option_order", "sort_order")),
            "answer": self._column(connection, "ready_answer_keys", ("answer_labels", "answer_label", "answer")),
            "explanation": self._column(connection, "ready_explanations", ("explanation_text", "explanation")),
        }

    @staticmethod
    def _column(connection: sqlite3.Connection, object_name: str, candidates: Iterable[str]) -> str:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({object_name})")}
        for candidate in candidates:
            if candidate in columns:
                return candidate
        raise ValueError(f"{object_name} is missing a required public column")

    @staticmethod
    def _manifest_files(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        raw = manifest.get("files")
        if not isinstance(raw, list):
            raise ValueError("manifest files must be a list")
        result: dict[str, dict[str, Any]] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("manifest file entry is invalid")
            path = item.get("path")
            role = item.get("role")
            digest = item.get("sha256")
            size = item.get("bytes")
            if (
                not isinstance(path, str)
                or "/" in path
                or path in result
                or role not in {"schema", "database"}
                or not isinstance(digest, str)
                or SHA256_PATTERN.fullmatch(digest) is None
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size < 0
            ):
                raise ValueError("manifest file entry is invalid")
            result[path] = {"role": role, "sha256": digest, "bytes": size}
        return result

    @staticmethod
    def _checksum_file(path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for raw in path.read_text(encoding="ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", raw)
            if match is None or match.group(2) in result:
                raise ValueError("checksum file is invalid")
            result[match.group(2)] = match.group(1)
        return result

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._database is None:
            raise QuestionBankUnavailable("full question bank is unavailable")
        uri = f"file:{quote(str(self._database), safe='/')}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            yield connection
        finally:
            connection.close()

    def _question_row(self, connection: sqlite3.Connection, identifier: str) -> sqlite3.Row | None:
        return connection.execute(
            f"""
            SELECT q.question_id, qs.subtype_id,
                   sc.{self._columns['subtype_name']} AS subtype_name,
                   q.{self._columns['module']} AS module,
                   q.{self._columns['year']} AS year,
                   q.{self._columns['region']} AS region,
                   q.{self._columns['paper_title']} AS paper_title,
                   q.{self._columns['question_number']} AS question_number,
                   q.{self._columns['question_type']} AS question_type,
                   q.{self._columns['stem']} AS stem,
                   q.{self._columns['material']} AS material,
                   q.{self._columns['requirement']} AS requirement,
                   q.{self._columns['difficulty']} AS difficulty,
                   q.{self._columns['option_count']} AS option_count,
                   q.{self._columns['has_assets']} AS has_assets,
                   q.{self._columns['content_signature']} AS content_signature
            FROM ready_questions q
            JOIN ready_question_subtypes qs ON qs.question_id=q.question_id
            JOIN subtype_catalog sc ON sc.subtype_id=qs.subtype_id
            WHERE q.question_id=?
            """,
            (identifier,),
        ).fetchone()

    def _options(self, connection: sqlite3.Connection, identifier: str) -> list[sqlite3.Row]:
        return connection.execute(
            f"SELECT {self._columns['option_label']} AS label, {self._columns['option_text']} AS text FROM ready_options WHERE question_id=? ORDER BY {self._columns['option_order']}, label",
            (identifier,),
        ).fetchall()

    def _where(self, subtype: str | None, search: str | None) -> tuple[str, tuple[Any, ...]]:
        terms: list[str] = []
        parameters: list[Any] = []
        if subtype is not None:
            terms.append("qs.subtype_id=?")
            parameters.append(subtype)
        if search is not None:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            terms.append(
                f"(q.{self._columns['stem']} LIKE ? ESCAPE '\\' OR q.{self._columns['material']} LIKE ? ESCAPE '\\' OR q.{self._columns['paper_title']} LIKE ? ESCAPE '\\')"
            )
            parameters.extend((pattern, pattern, pattern))
        return ("WHERE " + " AND ".join(terms) if terms else "", tuple(parameters))

    def _list_item(self, row: sqlite3.Row) -> dict[str, Any]:
        stem = _public_text(row["stem"])
        material = _public_text(row["material"])
        requirement = _public_text(row["requirement"])
        preview = stem.strip() or material.strip() or requirement.strip() or "题目内容依赖尚未打包的本地资源"
        return {
            "question_id": row["question_id"],
            "subtype_id": row["subtype_id"],
            "subtype_name": row["subtype_name"],
            "module": row["module"],
            "year": row["year"],
            "region": row["region"],
            "paper_title": row["paper_title"],
            "question_number": row["question_number"],
            "question_type": row["question_type"],
            "stem_preview": preview[:240],
            "has_material": bool(material.strip()),
            "option_count": row["option_count"],
            "has_assets": bool(row["has_assets"]),
        }

    def _detail_item(
        self,
        row: sqlite3.Row,
        options: list[sqlite3.Row],
        *,
        assets: list[dict[str, Any]],
        asset_delivery: str,
    ) -> dict[str, Any]:
        stem = _public_text(row["stem"])
        material = _public_text(row["material"])
        requirement = _public_text(row["requirement"])
        preview = stem.strip() or material.strip() or requirement.strip() or "题目内容依赖尚未打包的本地资源"
        return {
            "question_id": row["question_id"],
            "subtype_id": row["subtype_id"],
            "subtype_name": row["subtype_name"],
            "module": row["module"],
            "year": row["year"],
            "region": row["region"],
            "paper_title": row["paper_title"],
            "question_number": row["question_number"],
            "question_type": row["question_type"],
            "material": material,
            "stem": stem,
            "requirement": requirement,
            "stem_preview": preview[:240],
            "has_material": bool(material.strip()),
            "option_count": row["option_count"],
            "difficulty": row["difficulty"],
            "content_signature": row["content_signature"],
            "options": [
                {"label": option["label"], "text": _public_text(option["text"])}
                for option in options
            ],
            "has_assets": bool(row["has_assets"]),
            "assets": assets,
            "asset_delivery": asset_delivery,
        }

    def _public_counts(self) -> dict[str, int]:
        assert self._manifest is not None
        counts = self._manifest.get("counts")
        if not isinstance(counts, dict):
            raise QuestionBankUnavailable("full question bank count metadata is unavailable")
        result: dict[str, int] = {}
        for public, candidates in {
            "total": ("questions", "total_questions", "total"),
            "ready": ("questions_ready", "ready_questions", "ready"),
            "needs_review": ("questions_needs_review", "needs_review_questions", "needs_review"),
        }.items():
            value = next((counts[key] for key in candidates if key in counts), None)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise QuestionBankUnavailable("full question bank count metadata is invalid")
            result[public] = value
        return result

    def _subtype_counts(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT sc.subtype_id, sc.{self._columns['subtype_name']} AS name,
                       COUNT(q.question_id) AS ready_count
                FROM subtype_catalog sc
                LEFT JOIN ready_question_subtypes qs ON qs.subtype_id=sc.subtype_id
                LEFT JOIN ready_questions q ON q.question_id=qs.question_id
                GROUP BY sc.subtype_id, sc.{self._columns['subtype_name']}
                ORDER BY sc.subtype_id
                """
            ).fetchall()
        return [
            {"subtype_id": row["subtype_id"], "name": row["name"], "ready_count": row["ready_count"]}
            for row in rows
        ]

    def _access_counts(self, connection: sqlite3.Connection | None = None) -> dict[str, int]:
        def project(active: sqlite3.Connection) -> dict[str, int]:
            row = active.execute(
                f"SELECT COUNT(*) AS total, SUM(CASE WHEN {self._columns['has_assets']}=0 THEN 1 ELSE 0 END) AS direct, SUM(CASE WHEN {self._columns['has_assets']}<>0 THEN 1 ELSE 0 END) AS gated FROM ready_questions"
            ).fetchone()
            if self._assets is not None and self._assets.available:
                asset_counts = self._assets.status()["counts"]
                if asset_counts["flagged_asset_questions"] != int(row["gated"] or 0):
                    raise QuestionBankUnavailable("offline asset policy count does not match the question bank")
                return {
                    "direct_practice_ready": int(row["direct"] or 0) + asset_counts["attempt_unlocked"],
                    "asset_gated": asset_counts["attempt_blocked"],
                }
            return {
                "direct_practice_ready": int(row["direct"] or 0),
                "asset_gated": int(row["gated"] or 0),
            }

        if connection is not None:
            return project(connection)
        with self._connect() as active:
            return project(active)

    def _attempt_policy(self, row: sqlite3.Row) -> dict[str, Any]:
        if not bool(row["has_assets"]):
            return {
                "allowed": True,
                "dependency_state": "not_required",
                "required_asset_count": 0,
                "explanation_asset_count": 0,
            }
        if self._assets is None or not self._assets.available:
            return {
                "allowed": False,
                "dependency_state": "asset_export_unavailable",
                "required_asset_count": 1,
                "explanation_asset_count": 0,
            }
        try:
            policy = self._assets.policy(str(row["question_id"]))
        except QuestionAssetNotFound:
            return {
                "allowed": False,
                "dependency_state": "asset_policy_missing",
                "required_asset_count": 1,
                "explanation_asset_count": 0,
            }
        return {
            "allowed": policy["can_attempt"],
            "dependency_state": policy["dependency_state"],
            "required_asset_count": policy["required_asset_count"],
            "explanation_asset_count": policy["explanation_asset_count"],
        }

    def _verified_required_assets(
        self,
        question_id: str,
        policy: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if not policy["allowed"] or policy["required_asset_count"] == 0:
            return []
        if self._assets is None or not self._assets.available:
            raise QuestionBankAssetUnavailable("offline question assets are unavailable")
        try:
            assets = self._assets.verified_required_assets(question_id)
        except (QuestionAssetNotFound, QuestionAssetUnavailable) as error:
            raise QuestionBankAssetUnavailable(str(error)) from None
        if len(assets) != policy["required_asset_count"]:
            raise QuestionBankAssetUnavailable(
                "required question assets do not match the attempt policy"
            )
        return assets

    def asset_binary(self, asset_id: Any) -> dict[str, Any]:
        self._require_available()
        if not isinstance(asset_id, str) or not asset_id:
            raise QuestionBankRequestError("asset_id is invalid")
        if self._assets is None or not self._assets.available:
            raise QuestionBankAssetUnavailable("offline question assets are unavailable")
        try:
            return self._assets.binary(asset_id)
        except QuestionAssetNotFound as error:
            raise QuestionBankNotFound(str(error)) from None
        except QuestionAssetUnavailable as error:
            raise QuestionBankAssetUnavailable(str(error)) from None

    def _record_attempt(self, **record: Any) -> dict[str, Any]:
        attempt_id = "qb_" + hashlib.sha256(
            f"{record['database_sha256']}:{record['command_id']}".encode("utf-8")
        ).hexdigest()[:40]
        created_at = datetime.now(timezone.utc).isoformat()
        Path(self._attempt_database).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(sqlite3.connect(self._attempt_database, timeout=5)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS xingce_question_bank_attempts (
                    command_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL UNIQUE,
                    question_id TEXT NOT NULL,
                    export_version TEXT NOT NULL,
                    database_sha256 TEXT NOT NULL,
                    selected_response TEXT NOT NULL,
                    confidence TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
                    elapsed_seconds REAL NOT NULL,
                    correct INTEGER NOT NULL CHECK (correct IN (0,1)),
                    created_at TEXT NOT NULL
                )
                """
            )
            existing = connection.execute(
                "SELECT * FROM xingce_question_bank_attempts WHERE command_id=?",
                (record["command_id"],),
            ).fetchone()
            expected = (
                record["question_id"], record["export_version"], record["database_sha256"],
                record["selected_response"], record["confidence"], record["elapsed_seconds"], int(record["correct"]),
            )
            if existing is not None:
                actual = tuple(existing[index] for index in range(2, 9))
                if actual != expected:
                    raise QuestionBankConflict("command_id was already used for different attempt evidence")
                return {"attempt_id": existing[1], "created_at": existing[9], "idempotent_replay": True}
            connection.execute(
                "INSERT INTO xingce_question_bank_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (record["command_id"], attempt_id, *expected, created_at),
            )
        return {"attempt_id": attempt_id, "created_at": created_at, "idempotent_replay": False}

    def _require_available(self) -> None:
        if not self.available:
            raise QuestionBankUnavailable("full question bank is unavailable")

    @staticmethod
    def _positive_int(value: Any, name: str) -> int:
        if isinstance(value, bool):
            raise QuestionBankRequestError(f"{name} must be a positive integer")
        if isinstance(value, str):
            if re.fullmatch(r"[1-9][0-9]*", value) is None:
                raise QuestionBankRequestError(f"{name} must be a positive integer")
            value = int(value)
        if not isinstance(value, int) or value < 1:
            raise QuestionBankRequestError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _question_id(value: Any) -> str:
        if not isinstance(value, str) or QUESTION_ID_PATTERN.fullmatch(value) is None:
            raise QuestionBankRequestError("question_id is invalid")
        return value

    @staticmethod
    def _optional_subtype(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or SUBTYPE_ID_PATTERN.fullmatch(value) is None:
            raise QuestionBankRequestError("subtype_id is invalid")
        return value

    @staticmethod
    def _optional_search(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_QUERY_LENGTH:
            raise QuestionBankRequestError(f"q must be non-empty text up to {MAX_QUERY_LENGTH} characters")
        return value.strip()

    @staticmethod
    def _canonical_response(value: Any, option_labels: list[str]) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise QuestionBankRequestError("selected_response must be non-empty text up to 64 characters")
        allowed = {label.strip().upper() for label in option_labels if isinstance(label, str) and label.strip()}
        raw = value.strip().upper()
        tokens = [token for token in re.split(r"[,，、;；|/\s]+", raw) if token]
        if len(tokens) == 1 and tokens[0] not in allowed and all(character in allowed for character in tokens[0]):
            tokens = list(tokens[0])
        if not tokens or len(set(tokens)) != len(tokens) or any(token not in allowed for token in tokens):
            raise QuestionBankRequestError("selected_response must contain only declared option labels")
        return ",".join(sorted(tokens))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = LOCAL_SOURCE_MARKER.sub("题目材料见下方离线原卷页图。", value)
    return LOCAL_ABSOLUTE_PATH.sub("[本地资源]", text)
