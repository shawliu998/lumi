from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .state import AgentState


@dataclass(frozen=True, slots=True)
class TraceEvent:
    run_id: str
    seq: int
    occurred_at: str
    kind: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class TraceVersionConflict(RuntimeError):
    def __init__(self, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"trace version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


def retry_sqlite_locked(operation: Any) -> Any:
    """Retry only SQLite's short-lived initialization lock contention.

    Setting WAL mode and idempotent DDL can raise ``database is locked``
    immediately even when the connection has a busy timeout.  The local
    sidecar may open trace and schedule stores concurrently, so initialization
    must be restartable instead of leaking a transient lock as HTTP 500.
    """

    delays = (0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.0)
    for attempt in range(len(delays) + 1):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if (
                attempt == len(delays)
                or ("locked" not in message and "busy" not in message)
            ):
                raise
            time.sleep(delays[attempt])
    raise AssertionError("unreachable SQLite retry state")


def open_sqlite_connection(path: str | Path) -> sqlite3.Connection:
    """Open one local SQLite connection with race-safe WAL initialization."""

    connection = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")

    def ensure_wal() -> None:
        current = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if current in {"wal", "memory"}:
            return
        result = str(
            connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        ).lower()
        if result != "wal":
            raise sqlite3.OperationalError("unable to enable SQLite WAL mode")

    try:
        retry_sqlite_locked(ensure_wal)
    except Exception:
        connection.close()
        raise
    return connection


class EventStore:
    """SQLite append-only trace store with a per-run tamper-evident hash chain."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = open_sqlite_connection(self.path)
        retry_sqlite_locked(self._create_schema)

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL CHECK(seq > 0),
                occurred_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                PRIMARY KEY (run_id, seq),
                UNIQUE (event_hash)
            );
            CREATE INDEX IF NOT EXISTS trace_events_kind_idx
                ON trace_events(run_id, kind, seq);
            CREATE TRIGGER IF NOT EXISTS trace_events_no_update
            BEFORE UPDATE ON trace_events BEGIN
                SELECT RAISE(ABORT, 'trace_events is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS trace_events_no_delete
            BEFORE DELETE ON trace_events BEGIN
                SELECT RAISE(ABORT, 'trace_events is append-only');
            END;
            CREATE TABLE IF NOT EXISTS content_snapshots (
                content_hash TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                content_json TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS content_snapshots_no_update
            BEFORE UPDATE ON content_snapshots BEGIN
                SELECT RAISE(ABORT, 'content_snapshots is immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS content_snapshots_no_delete
            BEFORE DELETE ON content_snapshots BEGIN
                SELECT RAISE(ABORT, 'content_snapshots is immutable');
            END;
            """
        )

    def append(self, run_id: str, kind: str, payload: Mapping[str, Any]) -> TraceEvent:
        safe_payload = redact(dict(payload))
        encoded = json.dumps(safe_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        occurred_at = datetime.now(timezone.utc).isoformat()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT seq, event_hash FROM trace_events WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            seq = (int(row["seq"]) + 1) if row else 1
            previous_hash = str(row["event_hash"]) if row else "GENESIS"
            event_hash = _event_hash(run_id, seq, occurred_at, kind, encoded, previous_hash)
            connection.execute(
                "INSERT INTO trace_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, seq, occurred_at, kind, encoded, previous_hash, event_hash),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        return TraceEvent(run_id, seq, occurred_at, kind, safe_payload, previous_hash, event_hash)

    def append_if_version(
        self,
        run_id: str,
        expected_version: int,
        kind: str,
        payload: Mapping[str, Any],
    ) -> TraceEvent:
        """Atomically compare the latest sequence and append one event.

        This is the persistence-level CAS used by learner continuations and
        assistance delivery. It remains correct if two local SidecarApplication
        instances point at the same SQLite file; the process-local lock alone
        cannot provide that guarantee.
        """

        if expected_version < 0:
            raise ValueError("expected_version cannot be negative")
        safe_payload = redact(dict(payload))
        encoded = json.dumps(safe_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT seq, event_hash FROM trace_events WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            actual_version = int(row["seq"]) if row else 0
            if actual_version != expected_version:
                raise TraceVersionConflict(expected_version, actual_version)
            seq = actual_version + 1
            previous_hash = str(row["event_hash"]) if row else "GENESIS"
            occurred_at = datetime.now(timezone.utc).isoformat()
            event_hash = _event_hash(run_id, seq, occurred_at, kind, encoded, previous_hash)
            connection.execute(
                "INSERT INTO trace_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, seq, occurred_at, kind, encoded, previous_hash, event_hash),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        return TraceEvent(run_id, seq, occurred_at, kind, safe_payload, previous_hash, event_hash)

    def events(self, run_id: str) -> list[TraceEvent]:
        rows = self._connection.execute(
            "SELECT * FROM trace_events WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def put_content_snapshot(self, kind: str, content: Mapping[str, Any]) -> str:
        """Persist one immutable, private content snapshot by canonical hash."""

        if not kind or len(kind) > 80:
            raise ValueError("snapshot kind must be a short non-empty string")
        safe_content = redact(dict(content))
        encoded = json.dumps(
            safe_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            "INSERT OR IGNORE INTO content_snapshots VALUES (?, ?, ?, ?)",
            (content_hash, kind, created_at, encoded),
        )
        row = self._connection.execute(
            "SELECT kind, content_json FROM content_snapshots WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row is None or str(row["kind"]) != kind or str(row["content_json"]) != encoded:
            raise ValueError("content hash is already bound to a different immutable snapshot")
        return content_hash

    def load_content_snapshot(self, content_hash: str, *, kind: str | None = None) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT kind, created_at, content_json FROM content_snapshots WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row is None:
            raise KeyError(content_hash)
        actual_kind = str(row["kind"])
        if kind is not None and actual_kind != kind:
            raise KeyError(content_hash)
        return {
            "content_hash": content_hash,
            "kind": actual_kind,
            "created_at": str(row["created_at"]),
            "content": json.loads(row["content_json"]),
        }

    def run_ids(self) -> list[str]:
        rows = self._connection.execute("SELECT DISTINCT run_id FROM trace_events ORDER BY run_id").fetchall()
        return [str(row[0]) for row in rows]

    def load_state(self, run_id: str) -> AgentState:
        rows = self._connection.execute(
            "SELECT payload_json FROM trace_events WHERE run_id = ? ORDER BY seq DESC", (run_id,)
        ).fetchall()
        for row in rows:
            payload = json.loads(row[0])
            if isinstance(payload.get("state_after"), dict):
                return AgentState.from_dict(payload["state_after"])
        raise KeyError(f"run not found: {run_id}")

    def verify(self, run_id: str) -> bool:
        previous_hash = "GENESIS"
        for event in self.events(run_id):
            encoded = json.dumps(event.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected = _event_hash(
                event.run_id, event.seq, event.occurred_at, event.kind, encoded, previous_hash
            )
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False
            previous_hash = event.event_hash
        return True

    def replay(self, run_id: str) -> Iterator[dict[str, Any]]:
        """Yield recorded state snapshots without invoking tools or models."""
        if not self.verify(run_id):
            raise ValueError(f"trace hash verification failed: {run_id}")
        for event in self.events(run_id):
            state = event.payload.get("state_after")
            if state is not None:
                yield {"seq": event.seq, "kind": event.kind, "diff": event.payload.get("state_diff", []), "state": state}


def redact(value: Any, key: str = "") -> Any:
    sensitive = ("password", "secret", "token", "api_key", "authorization")
    if any(part in key.lower() for part in sensitive):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def _event_hash(run_id: str, seq: int, occurred_at: str, kind: str, encoded: str, previous_hash: str) -> str:
    canonical = "\x1f".join((run_id, str(seq), occurred_at, kind, encoded, previous_hash))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_to_event(row: sqlite3.Row) -> TraceEvent:
    return TraceEvent(
        run_id=str(row["run_id"]),
        seq=int(row["seq"]),
        occurred_at=str(row["occurred_at"]),
        kind=str(row["kind"]),
        payload=json.loads(row["payload_json"]),
        previous_hash=str(row["previous_hash"]),
        event_hash=str(row["event_hash"]),
    )
