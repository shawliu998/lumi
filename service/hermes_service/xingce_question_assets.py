from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
from typing import Any, Iterator
from urllib.parse import quote


MANIFEST_SCHEMA = "lumi.xingce-offline-assets-export.v1"
CATALOG_NAME = "lumi-question-assets.sqlite3"
CHECKSUM_NAME = "SHA256SUMS"
ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
QUESTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SAFE_BLOB_PATTERN = re.compile(r"^blobs/[0-9a-f]{2}/[0-9a-f]{64}\.(png|jpg|gif|webp)$")
MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class QuestionAssetUnavailable(RuntimeError):
    pass


class QuestionAssetNotFound(KeyError):
    pass


def configured_asset_export_root(
    explicit: str | Path | None,
    *,
    home: Path | None = None,
) -> Path | None:
    if explicit is not None:
        return Path(explicit).expanduser()
    root = (
        (home or Path.home())
        / "Library"
        / "Application Support"
        / "com.lumi.learning"
        / "content"
        / "xingce-question-assets"
        / "current"
    )
    return root if root.exists() else None


class XingceQuestionAssetCatalog:
    """Verified offline asset policy and loopback-only binary reader."""

    def __init__(self, export_root: str | Path | None, *, question_database_sha256: str) -> None:
        self._root = None if export_root is None else Path(export_root).expanduser()
        self._question_database_sha256 = question_database_sha256
        self._database: Path | None = None
        self._manifest: dict[str, Any] | None = None
        self._checksums: dict[str, str] = {}
        self._unavailable_reason = "asset_export_not_configured"
        if self._root is not None:
            try:
                self._load()
            except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
                self._database = None
                self._manifest = None
                self._checksums = {}
                self._unavailable_reason = "asset_integrity_validation_failed"

    @property
    def available(self) -> bool:
        return self._database is not None and self._manifest is not None

    def status(self) -> dict[str, Any]:
        if not self.available:
            return {
                "schema_version": "lumi.xingce-question-assets-status.v1",
                "available": False,
                "status": "unavailable",
                "reason": self._unavailable_reason,
            }
        assert self._manifest is not None
        return {
            "schema_version": "lumi.xingce-question-assets-status.v1",
            "available": True,
            "status": "available",
            "export_id": self._manifest["export_id"],
            "export_version": self._manifest["export_version"],
            "counts": self._manifest["counts"],
            "implicit_network_fetch": False,
        }

    def policy(self, question_id: str) -> dict[str, Any]:
        self._require_available()
        if QUESTION_ID_PATTERN.fullmatch(question_id) is None:
            raise QuestionAssetNotFound(question_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM question_asset_policy WHERE question_id=?",
                (question_id,),
            ).fetchone()
        if row is None:
            raise QuestionAssetNotFound(question_id)
        return {
            "dependency_state": row["dependency_state"],
            "required_asset_count": row["required_asset_count"],
            "bundled_required_asset_count": row["bundled_required_asset_count"],
            "explanation_asset_count": row["explanation_asset_count"],
            "unreferenced_asset_count": row["unreferenced_asset_count"],
            "can_attempt": bool(row["can_attempt"]),
        }

    def required_assets(self, question_id: str) -> list[dict[str, Any]]:
        policy = self.policy(question_id)
        if not policy["can_attempt"]:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT b.asset_id,b.content_sha256,b.media_type,b.relative_path,
                       p.placement,p.option_label
                FROM asset_bindings b
                JOIN asset_placements p ON p.asset_id=b.asset_id
                WHERE b.question_id=? AND b.availability='bundled'
                  AND p.placement IN ('material','stem','requirement','option')
                ORDER BY b.asset_id,p.placement,p.option_label
                """,
                (question_id,),
            ).fetchall()
        projected: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = projected.setdefault(
                row["asset_id"],
                {
                    "asset_id": row["asset_id"],
                    "content_sha256": row["content_sha256"],
                    "media_type": row["media_type"],
                    "path": f"/v1/xingce/question-bank/assets/{row['asset_id']}",
                    "placements": [],
                },
            )
            item["placements"].append(
                {"placement": row["placement"], "option_label": row["option_label"]}
            )
        return list(projected.values())

    def verified_required_assets(self, question_id: str) -> list[dict[str, Any]]:
        """Return required projections only after re-reading every binary.

        Startup verification binds the sealed export, but the controlled app-data
        directory can still change while the sidecar is running.  Both question
        display and scoring use this method so a deleted or replaced required
        image cannot leave an attempt writable.
        """

        policy = self.policy(question_id)
        if not policy["can_attempt"]:
            return []
        assets = self.required_assets(question_id)
        expected = policy["required_asset_count"]
        if (
            policy["bundled_required_asset_count"] != expected
            or len(assets) != expected
        ):
            raise QuestionAssetUnavailable(
                "required asset projection does not match its verified policy"
            )
        for asset in assets:
            binary = self.binary(asset["asset_id"])
            if (
                binary["content_sha256"] != asset["content_sha256"]
                or binary["media_type"] != asset["media_type"]
            ):
                raise QuestionAssetUnavailable(
                    "required asset projection changed during verification"
                )
        return assets

    def binary(self, asset_id: str) -> dict[str, Any]:
        self._require_available()
        if ASSET_ID_PATTERN.fullmatch(asset_id) is None:
            raise QuestionAssetNotFound(asset_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT DISTINCT b.content_sha256,b.media_type,b.relative_path
                FROM asset_bindings b
                JOIN asset_placements p ON p.asset_id=b.asset_id
                WHERE b.asset_id=? AND b.availability='bundled'
                  AND p.placement IN ('material','stem','requirement','option')
                """,
                (asset_id,),
            ).fetchone()
        if row is None:
            # Explanation-only assets are intentionally not addressable before
            # a separate post-attempt disclosure contract exists.
            raise QuestionAssetNotFound(asset_id)
        assert self._root is not None
        relative = row["relative_path"]
        if not isinstance(relative, str) or SAFE_BLOB_PATTERN.fullmatch(relative) is None:
            raise QuestionAssetUnavailable("asset catalog contains an unsafe relative path")
        try:
            path = self._root.resolve(strict=True) / relative
            if not path.is_file() or path.is_symlink():
                raise QuestionAssetUnavailable("verified asset file is unavailable")
            content = path.read_bytes()
        except OSError:
            raise QuestionAssetUnavailable("verified asset file is unavailable") from None
        actual = hashlib.sha256(content).hexdigest()
        if actual != row["content_sha256"] or self._checksums.get(relative) != actual:
            raise QuestionAssetUnavailable("asset changed after verification")
        return {
            "content": content,
            "media_type": row["media_type"],
            "content_sha256": actual,
        }

    def _load(self) -> None:
        assert self._root is not None
        root = self._root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("asset export root is not a directory")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("manifest_schema") != MANIFEST_SCHEMA
            or manifest.get("schema_version") != 1
            or manifest.get("source_question_export", {}).get("database_sha256")
            != self._question_database_sha256
        ):
            raise ValueError("asset export is not bound to this question database")
        for field in ("export_id", "export_version", "generated_at"):
            if not isinstance(manifest.get(field), str) or not manifest[field]:
                raise ValueError("asset manifest identity is invalid")
        checksums = self._checksum_file(root / CHECKSUM_NAME)
        blobs = manifest.get("blobs")
        files = manifest.get("files")
        if not isinstance(blobs, list) or not isinstance(files, list):
            raise ValueError("asset manifest file index is invalid")
        declared: dict[str, tuple[str, int, str]] = {}
        for row in files:
            if not isinstance(row, dict) or row.get("path") not in {"schema.sql", CATALOG_NAME}:
                raise ValueError("asset manifest root file is invalid")
            declared[row["path"]] = self._declared_file(row, allow_blob=False)
        if set(declared) != {"schema.sql", CATALOG_NAME}:
            raise ValueError("asset manifest omits a root file")
        for row in blobs:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str) or SAFE_BLOB_PATTERN.fullmatch(row["path"]) is None:
                raise ValueError("asset manifest blob is invalid")
            if row["path"] in declared:
                raise ValueError("asset manifest repeats a path")
            declared[row["path"]] = self._declared_file(row, allow_blob=True)
        if set(checksums) != {"manifest.json", *declared}:
            raise ValueError("asset checksum index does not match the manifest")
        if hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest() != checksums["manifest.json"]:
            raise ValueError("asset manifest checksum mismatch")
        for relative, (expected, size, media_type) in declared.items():
            path = root / relative
            if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
                raise ValueError("asset file metadata mismatch")
            actual = _sha256(path)
            if actual != expected or checksums.get(relative) != actual:
                raise ValueError("asset file checksum mismatch")
            if relative.startswith("blobs/") and media_type not in MEDIA_TYPES:
                raise ValueError("asset media type is not supported")
        database = root / CATALOG_NAME
        self._root = root
        self._database = database
        self._manifest = manifest
        self._checksums = checksums
        with self._connect() as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("asset catalog quick_check failed")
            source_hash = connection.execute(
                "SELECT value FROM metadata WHERE key='source_question_database_sha256'"
            ).fetchone()
            if source_hash is None or source_hash[0] != self._question_database_sha256:
                raise ValueError("asset catalog source binding mismatch")
            counts = connection.execute(
                "SELECT COUNT(*),SUM(can_attempt),SUM(CASE WHEN can_attempt=0 THEN 1 ELSE 0 END) FROM question_asset_policy"
            ).fetchone()
            declared_counts = manifest.get("counts")
            if not isinstance(declared_counts, dict) or tuple(counts) != (
                declared_counts.get("flagged_asset_questions"),
                declared_counts.get("attempt_unlocked"),
                declared_counts.get("attempt_blocked"),
            ):
                raise ValueError("asset catalog policy counts do not match manifest")
            unsafe = connection.execute(
                "SELECT 1 FROM asset_bindings WHERE relative_path LIKE '/%' OR relative_path LIKE '%://%' LIMIT 1"
            ).fetchone()
            if unsafe is not None:
                raise ValueError("asset catalog exposes a source path or URL")

    @staticmethod
    def _declared_file(row: dict[str, Any], *, allow_blob: bool) -> tuple[str, int, str]:
        digest = row.get("sha256")
        size = row.get("bytes")
        media_type = row.get("media_type", "")
        if (
            not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 1
            or allow_blob and media_type not in MEDIA_TYPES
        ):
            raise ValueError("asset manifest file metadata is invalid")
        return digest, size, media_type

    @staticmethod
    def _checksum_file(path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in path.read_text(encoding="ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
            if match is None or match.group(2) in result:
                raise ValueError("asset checksum index is invalid")
            relative = PurePosixPath(match.group(2))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("asset checksum path escapes the export")
            result[str(relative)] = match.group(1)
        return result

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._database is None:
            raise QuestionAssetUnavailable("offline question assets are unavailable")
        uri = f"file:{quote(str(self._database), safe='/')}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _require_available(self) -> None:
        if not self.available:
            raise QuestionAssetUnavailable("offline question assets are unavailable")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
