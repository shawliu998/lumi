from __future__ import annotations

import hashlib
import json
import sqlite3
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


class EventStore:
    """SQLite append-only trace store with a per-run tamper-evident hash chain."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

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

    def events(self, run_id: str) -> list[TraceEvent]:
        rows = self._connection.execute(
            "SELECT * FROM trace_events WHERE run_id = ? ORDER BY seq", (run_id,)
        ).fetchall()
        return [_row_to_event(row) for row in rows]

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
