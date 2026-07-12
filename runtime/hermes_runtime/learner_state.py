"""Append-only, provenance-isolated learner-state projections.

This module is intentionally independent from the existing trace and schedule
stores.  It is the small committer boundary proposed for the first judgment
reasoning pack: immutable facts, hypotheses and decisions may be recorded, but
only a deterministic, independently verified transfer can raise a skill's
mastery projection.

It does *not* make the projection authoritative over the trace.  A future
integration must still link the evidence ids below to verified trace events.
Keeping this store separate for now prevents a partial migration from changing
the existing EventStore or ReviewSchedule contracts.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .store import open_sqlite_connection, retry_sqlite_locked


LEARNER_STATE_SCHEMA_VERSION = "lumi.learner-state-projection.v1"
STATE_UPDATE_POLICY_VERSION = "judgment-state-update.v1"
ALLOWED_EVIDENCE_ORIGINS = frozenset(
    {
        "human_local_interactive",
        "evaluation_fixture",
        "synthetic_isolated",
    }
)
_ORIGIN_NAMESPACE_PREFIX = {
    "human_local_interactive": "human:",
    "evaluation_fixture": "eval:",
    "synthetic_isolated": "synthetic:",
}
_HYPOTHESIS_STATUSES = frozenset(
    {"unconfirmed", "supported", "refuted", "insufficient"}
)
_VERIFICATION_OUTCOMES = frozenset({"passed", "failed", "inconclusive"})
_VERIFICATION_KINDS = frozenset({"unseen_transfer", "delayed_retention"})
_FORBIDDEN_POPULATION_FIELDS = frozenset(
    {"cohort", "peer", "peers", "common_error_rate", "population_rate"}
)


class LearnerStateError(RuntimeError):
    """Base error for the isolated learner-state projection."""


class LearnerStateValidationError(LearnerStateError):
    """Raised when a fact, reference, or state transition violates the contract."""


class LearnerStateVersionConflict(LearnerStateError):
    """Raised when a compare-and-append request is based on a stale skill state."""

    def __init__(self, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"learner state version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class LearnerStateIdempotencyConflict(LearnerStateError):
    """Raised when an immutable id is replayed with different evidence or semantics."""


class LearnerStateStore:
    """SQLite append-only learner-state records with strict provenance isolation.

    The projection is keyed by ``(namespace_id, learner_id, skill_id)``.  Every
    call that can append a snapshot uses ``BEGIN IMMEDIATE`` and checks the
    requested version inside that transaction, so separate local processes
    cannot silently overwrite one another.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._connection = open_sqlite_connection(self.path)
        retry_sqlite_locked(self._create_schema)

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS learner_state_evidence_events (
                event_id TEXT PRIMARY KEY,
                namespace_id TEXT NOT NULL,
                evidence_origin TEXT NOT NULL,
                kind TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS learner_state_evidence_namespace_idx
                ON learner_state_evidence_events(namespace_id, evidence_origin, event_id);

            CREATE TABLE IF NOT EXISTS learner_state_hypotheses (
                hypothesis_id TEXT PRIMARY KEY,
                namespace_id TEXT NOT NULL,
                evidence_origin TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                cause_id TEXT NOT NULL,
                hypothesis_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS learner_state_hypothesis_namespace_idx
                ON learner_state_hypotheses(namespace_id, evidence_origin, episode_id);

            CREATE TABLE IF NOT EXISTS learner_state_policy_decisions (
                decision_id TEXT PRIMARY KEY,
                namespace_id TEXT NOT NULL,
                evidence_origin TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                state_snapshot_id TEXT,
                decision_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS learner_state_decision_namespace_idx
                ON learner_state_policy_decisions(namespace_id, evidence_origin, episode_id);

            CREATE TABLE IF NOT EXISTS learner_state_verifications (
                verification_id TEXT PRIMARY KEY,
                namespace_id TEXT NOT NULL,
                evidence_origin TEXT NOT NULL,
                learner_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                evidence_event_id TEXT NOT NULL,
                verification_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS learner_state_verification_namespace_idx
                ON learner_state_verifications(
                    namespace_id, evidence_origin, learner_id, skill_id, evidence_event_id
                );

            CREATE TABLE IF NOT EXISTS learner_state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                namespace_id TEXT NOT NULL,
                evidence_origin TEXT NOT NULL,
                learner_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                verification_id TEXT NOT NULL,
                evidence_event_id TEXT NOT NULL,
                state_version INTEGER NOT NULL CHECK(state_version > 0),
                previous_snapshot_id TEXT,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(namespace_id, learner_id, skill_id, state_version),
                UNIQUE(namespace_id, learner_id, skill_id, verification_id, evidence_event_id)
            );
            CREATE INDEX IF NOT EXISTS learner_state_snapshot_current_idx
                ON learner_state_snapshots(namespace_id, learner_id, skill_id, state_version DESC);

            CREATE TRIGGER IF NOT EXISTS learner_state_evidence_no_update
            BEFORE UPDATE ON learner_state_evidence_events BEGIN
                SELECT RAISE(ABORT, 'learner-state evidence is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_evidence_no_delete
            BEFORE DELETE ON learner_state_evidence_events BEGIN
                SELECT RAISE(ABORT, 'learner-state evidence is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_hypotheses_no_update
            BEFORE UPDATE ON learner_state_hypotheses BEGIN
                SELECT RAISE(ABORT, 'learner-state hypotheses are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_hypotheses_no_delete
            BEFORE DELETE ON learner_state_hypotheses BEGIN
                SELECT RAISE(ABORT, 'learner-state hypotheses are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_decisions_no_update
            BEFORE UPDATE ON learner_state_policy_decisions BEGIN
                SELECT RAISE(ABORT, 'learner-state decisions are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_decisions_no_delete
            BEFORE DELETE ON learner_state_policy_decisions BEGIN
                SELECT RAISE(ABORT, 'learner-state decisions are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_verifications_no_update
            BEFORE UPDATE ON learner_state_verifications BEGIN
                SELECT RAISE(ABORT, 'learner-state verifications are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_verifications_no_delete
            BEFORE DELETE ON learner_state_verifications BEGIN
                SELECT RAISE(ABORT, 'learner-state verifications are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_snapshots_no_update
            BEFORE UPDATE ON learner_state_snapshots BEGIN
                SELECT RAISE(ABORT, 'learner-state snapshots are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS learner_state_snapshots_no_delete
            BEFORE DELETE ON learner_state_snapshots BEGIN
                SELECT RAISE(ABORT, 'learner-state snapshots are append-only');
            END;
            """
        )

    def append_evidence(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Append one immutable fact without allowing an inferred cause as fact."""

        normalized = _normalized_mapping(event, "evidence event")
        event_id = _required_id(normalized, "event_id")
        namespace_id, evidence_origin = _identity_from(normalized)
        kind = _required_id(normalized, "kind")
        if "cause_id" in normalized or "hypothesis" in normalized:
            raise LearnerStateValidationError(
                "evidence facts cannot carry a cause or hypothesis label"
            )
        _reject_population_fields(normalized)
        encoded = _canonical_json(normalized)
        created_at = _now()
        existing = self._connection.execute(
            "SELECT event_json FROM learner_state_evidence_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["event_json"]) != encoded:
                raise LearnerStateIdempotencyConflict(
                    f"evidence event id is already bound to different content: {event_id}"
                )
            return normalized
        self._connection.execute(
            """
            INSERT INTO learner_state_evidence_events
                (event_id, namespace_id, evidence_origin, kind, event_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, namespace_id, evidence_origin, kind, encoded, created_at),
        )
        return normalized

    def append_hypothesis(self, hypothesis: Mapping[str, Any]) -> dict[str, Any]:
        """Append an explicitly uncertain diagnostic hypothesis with local evidence."""

        normalized = _normalized_mapping(hypothesis, "diagnosis hypothesis")
        hypothesis_id = _required_id(normalized, "hypothesis_id")
        namespace_id, evidence_origin = _identity_from(normalized)
        episode_id = _required_id(normalized, "episode_id")
        skill_id = _required_id(normalized, "skill_id")
        cause_id = _required_id(normalized, "cause_id")
        status = _required_id(normalized, "status")
        if status not in _HYPOTHESIS_STATUSES:
            raise LearnerStateValidationError("hypothesis status is invalid")
        _reject_population_fields(normalized)
        self._validate_evidence_refs(
            normalized.get("evidence_refs"), namespace_id, evidence_origin
        )
        encoded = _canonical_json(normalized)
        created_at = _now()
        existing = self._connection.execute(
            "SELECT hypothesis_json FROM learner_state_hypotheses WHERE hypothesis_id = ?",
            (hypothesis_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["hypothesis_json"]) != encoded:
                raise LearnerStateIdempotencyConflict(
                    f"hypothesis id is already bound to different content: {hypothesis_id}"
                )
            return normalized
        self._connection.execute(
            """
            INSERT INTO learner_state_hypotheses
                (hypothesis_id, namespace_id, evidence_origin, episode_id, skill_id,
                 cause_id, hypothesis_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hypothesis_id,
                namespace_id,
                evidence_origin,
                episode_id,
                skill_id,
                cause_id,
                encoded,
                created_at,
            ),
        )
        return normalized

    def append_policy_decision(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        """Append a policy choice and its exact evidence/snapshot basis."""

        normalized = _normalized_mapping(decision, "policy decision")
        decision_id = _required_id(normalized, "decision_id")
        namespace_id, evidence_origin = _identity_from(normalized)
        episode_id = _required_id(normalized, "episode_id")
        _required_id(normalized, "decision_type")
        _required_id(normalized, "selected_action_id")
        _reject_population_fields(normalized)
        self._validate_evidence_refs(
            normalized.get("evidence_refs"), namespace_id, evidence_origin
        )
        snapshot_id = normalized.get("state_snapshot_id")
        if snapshot_id is not None:
            snapshot_id = _short_string(snapshot_id, "state_snapshot_id")
            self._validate_snapshot_ref(snapshot_id, namespace_id, evidence_origin)
        encoded = _canonical_json(normalized)
        created_at = _now()
        existing = self._connection.execute(
            "SELECT decision_json FROM learner_state_policy_decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["decision_json"]) != encoded:
                raise LearnerStateIdempotencyConflict(
                    f"decision id is already bound to different content: {decision_id}"
                )
            return normalized
        self._connection.execute(
            """
            INSERT INTO learner_state_policy_decisions
                (decision_id, namespace_id, evidence_origin, episode_id, state_snapshot_id,
                 decision_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                namespace_id,
                evidence_origin,
                episode_id,
                snapshot_id,
                encoded,
                created_at,
            ),
        )
        return normalized

    def commit_verification(
        self,
        *,
        namespace_id: str,
        evidence_origin: str,
        learner_id: str,
        skill_id: str,
        verification_id: str,
        evidence_event_id: str,
        expected_state_version: int,
        outcome: str,
        unseen_from_content_signatures: Sequence[str],
        verification_kind: str = "unseen_transfer",
        mastery_increment: float = 0.04,
        state_update_policy_version: str = STATE_UPDATE_POLICY_VERSION,
    ) -> dict[str, Any]:
        """Atomically append one verification receipt and per-skill state snapshot.

        The scorer facts are read from the immutable evidence event.  Callers
        cannot self-report an independent, unhinted pass through this API.
        Replaying the same ``verification_id`` plus ``evidence_event_id`` returns
        the original immutable receipt; a changed replay fails closed.
        """

        namespace_id, evidence_origin = _validate_identity(namespace_id, evidence_origin)
        learner_id = _short_string(learner_id, "learner_id")
        skill_id = _short_string(skill_id, "skill_id")
        verification_id = _short_string(verification_id, "verification_id")
        evidence_event_id = _short_string(evidence_event_id, "evidence_event_id")
        if not isinstance(expected_state_version, int) or expected_state_version < 0:
            raise LearnerStateValidationError("expected_state_version must be a non-negative integer")
        if outcome not in _VERIFICATION_OUTCOMES:
            raise LearnerStateValidationError("verification outcome is invalid")
        if verification_kind not in _VERIFICATION_KINDS:
            raise LearnerStateValidationError("verification kind is invalid")
        if not isinstance(mastery_increment, (int, float)) or not 0 < float(mastery_increment) <= 1:
            raise LearnerStateValidationError("mastery_increment must be in (0, 1]")
        state_update_policy_version = _short_string(
            state_update_policy_version, "state_update_policy_version"
        )
        unseen_from = _normalized_content_signatures(unseen_from_content_signatures)
        event = self._load_matching_evidence(
            evidence_event_id, namespace_id, evidence_origin
        )
        verification = self._build_verification(
            namespace_id=namespace_id,
            evidence_origin=evidence_origin,
            learner_id=learner_id,
            skill_id=skill_id,
            verification_id=verification_id,
            evidence_event_id=evidence_event_id,
            event=event,
            outcome=outcome,
            verification_kind=verification_kind,
            unseen_from_content_signatures=unseen_from,
            state_update_policy_version=state_update_policy_version,
        )
        verification_encoded = _canonical_json(verification)
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            existing_verification = connection.execute(
                """
                SELECT verification_json FROM learner_state_verifications
                WHERE verification_id = ?
                """,
                (verification_id,),
            ).fetchone()
            if existing_verification is not None and (
                str(existing_verification["verification_json"]) != verification_encoded
            ):
                raise LearnerStateIdempotencyConflict(
                    f"verification id is already bound to different evidence: {verification_id}"
                )

            existing_snapshot = connection.execute(
                """
                SELECT snapshot_json FROM learner_state_snapshots
                WHERE namespace_id = ? AND learner_id = ? AND skill_id = ?
                  AND verification_id = ? AND evidence_event_id = ?
                """,
                (namespace_id, learner_id, skill_id, verification_id, evidence_event_id),
            ).fetchone()
            if existing_snapshot is not None:
                if existing_verification is None:
                    raise LearnerStateValidationError(
                        "snapshot is missing its immutable verification receipt"
                    )
                connection.execute("COMMIT")
                return json.loads(str(existing_snapshot["snapshot_json"]))

            latest = connection.execute(
                """
                SELECT snapshot_id, state_version, snapshot_json
                FROM learner_state_snapshots
                WHERE namespace_id = ? AND learner_id = ? AND skill_id = ?
                ORDER BY state_version DESC LIMIT 1
                """,
                (namespace_id, learner_id, skill_id),
            ).fetchone()
            actual_version = int(latest["state_version"]) if latest is not None else 0
            if actual_version != expected_state_version:
                raise LearnerStateVersionConflict(expected_state_version, actual_version)

            previous_snapshot = (
                json.loads(str(latest["snapshot_json"])) if latest is not None else None
            )
            snapshot = self._build_snapshot(
                namespace_id=namespace_id,
                evidence_origin=evidence_origin,
                learner_id=learner_id,
                skill_id=skill_id,
                verification=verification,
                previous_snapshot=previous_snapshot,
                mastery_increment=float(mastery_increment),
                state_update_policy_version=state_update_policy_version,
            )
            snapshot_encoded = _canonical_json(snapshot)
            created_at = str(snapshot["created_at"])
            if existing_verification is None:
                connection.execute(
                    """
                    INSERT INTO learner_state_verifications
                        (verification_id, namespace_id, evidence_origin, learner_id, skill_id,
                         evidence_event_id, verification_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        verification_id,
                        namespace_id,
                        evidence_origin,
                        learner_id,
                        skill_id,
                        evidence_event_id,
                        verification_encoded,
                        created_at,
                    ),
                )
            connection.execute(
                """
                INSERT INTO learner_state_snapshots
                    (snapshot_id, namespace_id, evidence_origin, learner_id, skill_id,
                     verification_id, evidence_event_id, state_version, previous_snapshot_id,
                     snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot["snapshot_id"],
                    namespace_id,
                    evidence_origin,
                    learner_id,
                    skill_id,
                    verification_id,
                    evidence_event_id,
                    snapshot["state_version"],
                    snapshot["previous_snapshot_id"],
                    snapshot_encoded,
                    created_at,
                ),
            )
            connection.execute("COMMIT")
            return snapshot
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def current_snapshot(
        self, *, namespace_id: str, evidence_origin: str, learner_id: str, skill_id: str
    ) -> dict[str, Any] | None:
        """Return the latest immutable state receipt for one isolated skill projection."""

        namespace_id, evidence_origin = _validate_identity(namespace_id, evidence_origin)
        learner_id = _short_string(learner_id, "learner_id")
        skill_id = _short_string(skill_id, "skill_id")
        row = self._connection.execute(
            """
            SELECT snapshot_json FROM learner_state_snapshots
            WHERE namespace_id = ? AND evidence_origin = ? AND learner_id = ? AND skill_id = ?
            ORDER BY state_version DESC LIMIT 1
            """,
            (namespace_id, evidence_origin, learner_id, skill_id),
        ).fetchone()
        return json.loads(str(row["snapshot_json"])) if row is not None else None

    def replay_snapshots(
        self, *, namespace_id: str, evidence_origin: str, learner_id: str, skill_id: str
    ) -> list[dict[str, Any]]:
        """Return immutable snapshot receipts in version order without mutation."""

        namespace_id, evidence_origin = _validate_identity(namespace_id, evidence_origin)
        learner_id = _short_string(learner_id, "learner_id")
        skill_id = _short_string(skill_id, "skill_id")
        rows = self._connection.execute(
            """
            SELECT snapshot_json FROM learner_state_snapshots
            WHERE namespace_id = ? AND evidence_origin = ? AND learner_id = ? AND skill_id = ?
            ORDER BY state_version
            """,
            (namespace_id, evidence_origin, learner_id, skill_id),
        ).fetchall()
        return [json.loads(str(row["snapshot_json"])) for row in rows]

    def replay_policy_decisions(
        self,
        *,
        namespace_id: str,
        evidence_origin: str,
        learner_id: str,
    ) -> list[dict[str, Any]]:
        """Read this learner's immutable policy ledger in creation order.

        Existing decision rows predate an explicit learner id.  They are not
        projected into this new workspace query: only decisions that bind the
        requested local learner in their immutable payload are eligible.
        """

        namespace_id, evidence_origin = _validate_identity(namespace_id, evidence_origin)
        learner_id = _short_string(learner_id, "learner_id")
        rows = self._connection.execute(
            """
            SELECT decision_json FROM learner_state_policy_decisions
            WHERE namespace_id = ? AND evidence_origin = ?
            ORDER BY created_at, decision_id
            """,
            (namespace_id, evidence_origin),
        ).fetchall()
        decisions = [json.loads(str(row["decision_json"])) for row in rows]
        return [decision for decision in decisions if decision.get("learner_id") == learner_id]

    def replay_hypotheses(
        self,
        *,
        namespace_id: str,
        evidence_origin: str,
        learner_id: str,
    ) -> list[dict[str, Any]]:
        """Return one learner's append-only diagnostic observations in order.

        Historical diagnosis is deliberately weaker than learner state: callers
        receive individual, still-unconfirmed hypothesis records rather than a
        latent-trait score.  Earlier rows that did not bind a learner id remain
        readable in storage but cannot influence this projection.
        """

        namespace_id, evidence_origin = _validate_identity(namespace_id, evidence_origin)
        learner_id = _short_string(learner_id, "learner_id")
        rows = self._connection.execute(
            """
            SELECT hypothesis_json FROM learner_state_hypotheses
            WHERE namespace_id = ? AND evidence_origin = ?
            ORDER BY created_at, hypothesis_id
            """,
            (namespace_id, evidence_origin),
        ).fetchall()
        hypotheses = [json.loads(str(row["hypothesis_json"])) for row in rows]
        return [hypothesis for hypothesis in hypotheses if hypothesis.get("learner_id") == learner_id]

    def _validate_evidence_refs(
        self,
        refs: Any,
        namespace_id: str,
        evidence_origin: str,
    ) -> None:
        if not isinstance(refs, list) or not refs:
            raise LearnerStateValidationError("evidence_refs must be a non-empty list")
        for event_id in refs:
            self._load_matching_evidence(
                _short_string(event_id, "evidence_ref"), namespace_id, evidence_origin
            )

    def _load_matching_evidence(
        self, event_id: str, namespace_id: str, evidence_origin: str
    ) -> dict[str, Any]:
        row = self._connection.execute(
            """
            SELECT namespace_id, evidence_origin, event_json
            FROM learner_state_evidence_events WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            raise LearnerStateValidationError(f"evidence event is unavailable: {event_id}")
        if (
            str(row["namespace_id"]) != namespace_id
            or str(row["evidence_origin"]) != evidence_origin
        ):
            raise LearnerStateValidationError(
                "evidence references must match namespace_id and evidence_origin"
            )
        return json.loads(str(row["event_json"]))

    def _validate_snapshot_ref(
        self, snapshot_id: str, namespace_id: str, evidence_origin: str
    ) -> None:
        row = self._connection.execute(
            """
            SELECT namespace_id, evidence_origin FROM learner_state_snapshots
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise LearnerStateValidationError(f"state snapshot is unavailable: {snapshot_id}")
        if (
            str(row["namespace_id"]) != namespace_id
            or str(row["evidence_origin"]) != evidence_origin
        ):
            raise LearnerStateValidationError(
                "state snapshot references must match namespace_id and evidence_origin"
            )

    def _build_verification(
        self,
        *,
        namespace_id: str,
        evidence_origin: str,
        learner_id: str,
        skill_id: str,
        verification_id: str,
        evidence_event_id: str,
        event: Mapping[str, Any],
        outcome: str,
        verification_kind: str,
        unseen_from_content_signatures: Sequence[str],
        state_update_policy_version: str,
    ) -> dict[str, Any]:
        if event.get("kind") != "verification":
            raise LearnerStateValidationError(
                "mastery verification must reference an evidence event of kind verification"
            )
        observed = event.get("observed")
        content_ref = event.get("content_ref")
        if not isinstance(observed, Mapping) or not isinstance(content_ref, Mapping):
            raise LearnerStateValidationError(
                "verification evidence must include observed facts and a content_ref"
            )
        independent = observed.get("independently_answered") is True
        hint_count = observed.get("hint_count")
        if not isinstance(hint_count, int) or hint_count < 0:
            raise LearnerStateValidationError("verification evidence hint_count must be non-negative")
        correct = observed.get("correct") is True
        content_signature = _short_string(
            content_ref.get("content_signature"), "content_ref.content_signature"
        )
        content_role = _short_string(
            content_ref.get("role"), "content_ref.role"
        )
        expected_role = (
            "transfer" if verification_kind == "unseen_transfer" else "delayed_review"
        )
        if content_role != expected_role:
            raise LearnerStateValidationError(
                "verification content role does not match verification_kind"
            )
        if content_signature in unseen_from_content_signatures:
            raise LearnerStateValidationError(
                "verification content must differ from first/probe/teaching content"
            )
        eligible = (
            outcome == "passed"
            and correct
            and independent
            and hint_count == 0
            and verification_kind == "unseen_transfer"
        )
        withheld_reason: str | None = None
        if not eligible:
            if outcome != "passed" or not correct:
                withheld_reason = "verification_not_passed"
            elif not independent:
                withheld_reason = "not_independently_answered"
            elif hint_count > 0:
                withheld_reason = "assisted_verification"
            else:
                withheld_reason = "not_unseen_transfer"
        return {
            "schema_version": "lumi.verification-result.v1",
            "verification_id": verification_id,
            "namespace_id": namespace_id,
            "evidence_origin": evidence_origin,
            "learner_id": learner_id,
            "skill_id": skill_id,
            "attempt_evidence_ref": evidence_event_id,
            "verification_kind": verification_kind,
            "unseen_from_content_signatures": list(unseen_from_content_signatures),
            "content_signature": content_signature,
            "independent": independent,
            "hint_count": hint_count,
            "outcome": outcome,
            "state_update_eligibility": "eligible" if eligible else "withheld",
            "withheld_reason": withheld_reason,
            "committer": {
                "name": "learner_state_updater",
                "policy_version": state_update_policy_version,
            },
        }

    @staticmethod
    def _build_snapshot(
        *,
        namespace_id: str,
        evidence_origin: str,
        learner_id: str,
        skill_id: str,
        verification: Mapping[str, Any],
        previous_snapshot: Mapping[str, Any] | None,
        mastery_increment: float,
        state_update_policy_version: str,
    ) -> dict[str, Any]:
        previous_mastery = 0.0
        previous_evidence_count = 0
        previous_snapshot_id: str | None = None
        if previous_snapshot is not None:
            mastery = previous_snapshot.get("mastery")
            if not isinstance(mastery, Mapping):
                raise LearnerStateValidationError("previous snapshot mastery is invalid")
            previous_mastery = float(mastery["value"])
            previous_evidence_count = int(mastery["evidence_count"])
            previous_snapshot_id = _short_string(
                previous_snapshot.get("snapshot_id"), "previous snapshot id"
            )
        eligible = verification["state_update_eligibility"] == "eligible"
        mastery_delta = min(mastery_increment, 1.0 - previous_mastery) if eligible else 0.0
        mastery_after = round(previous_mastery + mastery_delta, 12)
        if eligible and mastery_delta > 0:
            status = "independent_transfer_supported"
            commit_status = "committed"
        elif eligible:
            status = "independent_transfer_supported"
            commit_status = "committed"
        else:
            status = "needs_recheck" if previous_evidence_count else "evidence_limited"
            commit_status = "withheld"
        state_version = (int(previous_snapshot["state_version"]) + 1) if previous_snapshot else 1
        snapshot_identity = "\x1f".join(
            (
                namespace_id,
                learner_id,
                skill_id,
                str(verification["verification_id"]),
                str(verification["attempt_evidence_ref"]),
            )
        )
        snapshot_id = "lssnap_" + hashlib.sha256(
            snapshot_identity.encode("utf-8")
        ).hexdigest()[:24]
        return {
            "schema_version": "lumi.learner-state-snapshot.v1",
            "snapshot_id": snapshot_id,
            "namespace_id": namespace_id,
            "evidence_origin": evidence_origin,
            "learner_id": learner_id,
            "skill_id": skill_id,
            "state_version": state_version,
            "previous_snapshot_id": previous_snapshot_id,
            "trigger": {
                "verification_id": verification["verification_id"],
                "evidence_event_id": verification["attempt_evidence_ref"],
            },
            "mastery": {
                "value": mastery_after,
                "uncertainty": round(1.0 / (previous_evidence_count + 2), 12),
                "evidence_count": previous_evidence_count + 1,
                "status": status,
                "model": {
                    "name": "bounded-independent-transfer-rule",
                    "version": state_update_policy_version,
                    "calibration_status": "engineering_unvalidated",
                },
            },
            "state_delta": {
                "mastery_delta": mastery_delta,
                "commit_status": commit_status,
                "withheld_reason": verification["withheld_reason"],
            },
            "verification": dict(verification),
            "committer": {
                "name": "learner_state_updater",
                "policy_version": state_update_policy_version,
            },
            "created_at": _now(),
        }


def _identity_from(value: Mapping[str, Any]) -> tuple[str, str]:
    return _validate_identity(value.get("namespace_id"), value.get("evidence_origin"))


def _validate_identity(namespace_id: Any, evidence_origin: Any) -> tuple[str, str]:
    namespace = _short_string(namespace_id, "namespace_id")
    origin = _short_string(evidence_origin, "evidence_origin")
    if origin not in ALLOWED_EVIDENCE_ORIGINS:
        raise LearnerStateValidationError("evidence_origin is invalid")
    if not namespace.startswith(_ORIGIN_NAMESPACE_PREFIX[origin]):
        raise LearnerStateValidationError(
            "namespace_id must use the required prefix for evidence_origin"
        )
    return namespace, origin


def _normalized_mapping(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LearnerStateValidationError(f"{name} must be a mapping")
    normalized = dict(value)
    _reject_population_fields(normalized)
    return normalized


def _required_id(value: Mapping[str, Any], key: str) -> str:
    return _short_string(value.get(key), key)


def _short_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise LearnerStateValidationError(f"{name} must be a short non-empty string")
    return value.strip()


def _normalized_content_signatures(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise LearnerStateValidationError(
            "unseen_from_content_signatures must be a non-empty sequence"
        )
    normalized = tuple(
        _short_string(value, "unseen_from_content_signatures") for value in values
    )
    if not normalized or len(set(normalized)) != len(normalized):
        raise LearnerStateValidationError(
            "unseen_from_content_signatures must be non-empty and unique"
        )
    return normalized


def _reject_population_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_POPULATION_FIELDS:
                raise LearnerStateValidationError(
                    "cohort/peer population fields are unavailable in learner-state records"
                )
            _reject_population_fields(item)
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_population_fields(item)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
