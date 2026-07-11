from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .generation import GeneratedPack, TaxonomySnapshot, generate_extractive_pack
from .models import (
    ARTIFACT_TYPES,
    GENERATOR_ID,
    VERIFIER_ID,
    Artifact,
    CandidateSkillLink,
    CommandConflict,
    OpaqueIdFactory,
    PackEvent,
    PracticeAttempt,
    SourceDocument,
    SourceSpan,
    StudyPackError,
    VerifierDecision,
    VersionConflict,
    canonical_json,
    content_digest,
    sha256_bytes,
    sha256_text,
    validate_command_id,
    validate_entity_id,
)
from .parsing import PdfBackend, ParsedSource, parse_source
from .verification import normalized_exact, score_practice, verify_artifact_set


PACK_PROJECTION_SCHEMA = "lumi.study-pack-detail.v1"
EVENT_SCHEMA = "lumi.study-pack-event.v1"
ATTEMPT_SCHEMA = "lumi.study-pack-attempt-result.v1"
HUMAN_ATTEMPT_EVIDENCE_ORIGIN = "human_local_interactive"
EVALUATION_ATTEMPT_EVIDENCE_ORIGIN = "evaluation_fixture"
ATTEMPT_EVIDENCE_ORIGINS = frozenset(
    {
        HUMAN_ATTEMPT_EVIDENCE_ORIGIN,
        EVALUATION_ATTEMPT_EVIDENCE_ORIGIN,
    }
)


class StudyPackStore:
    """Independent, local-only Study Pack authority.

    This module has no import or write boundary to KT, misconception, TodayPlan,
    ReviewSchedule, the general agent trace, network, OCR, or protected repos.
    """

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        id_factory: Callable[[str], str] | None = None,
        pdf_backend: PdfBackend | None = None,
        taxonomy: TaxonomySnapshot | None = None,
        clock: Callable[[], str] | None = None,
        attempt_evidence_origin: str = HUMAN_ATTEMPT_EVIDENCE_ORIGIN,
    ) -> None:
        if (
            not isinstance(attempt_evidence_origin, str)
            or attempt_evidence_origin not in ATTEMPT_EVIDENCE_ORIGINS
        ):
            raise ValueError(
                "attempt_evidence_origin must be human_local_interactive "
                "or evaluation_fixture"
            )
        self.path = str(path)
        self._connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._id_factory = id_factory or OpaqueIdFactory()
        self._pdf_backend = pdf_backend
        self._taxonomy = taxonomy
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._attempt_evidence_origin = attempt_evidence_origin
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS study_packs (
                pack_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                lifecycle TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version > 0),
                document_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                normalized_source_sha256 TEXT NOT NULL,
                artifact_set_digest TEXT,
                generator_id TEXT NOT NULL,
                quarantine_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS study_packs_immutable_context
            BEFORE UPDATE ON study_packs
            WHEN NEW.pack_id IS NOT OLD.pack_id
              OR NEW.title IS NOT OLD.title
              OR NEW.document_id IS NOT OLD.document_id
              OR NEW.source_version IS NOT OLD.source_version
              OR NEW.normalized_source_sha256 IS NOT OLD.normalized_source_sha256
              OR NEW.artifact_set_digest IS NOT OLD.artifact_set_digest
              OR NEW.generator_id IS NOT OLD.generator_id
              OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'StudyPack context is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS study_packs_no_delete
            BEFORE DELETE ON study_packs
            BEGIN SELECT RAISE(ABORT, 'StudyPacks cannot be deleted'); END;

            CREATE TABLE IF NOT EXISTS source_documents (
                document_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                pack_id TEXT NOT NULL UNIQUE REFERENCES study_packs(pack_id),
                input_kind TEXT NOT NULL,
                media_type TEXT NOT NULL,
                original_sha256 TEXT NOT NULL,
                normalized_sha256 TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                locator_count INTEGER NOT NULL,
                codepoint_count INTEGER NOT NULL,
                parser_name TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                normalization_name TEXT NOT NULL,
                normalization_version TEXT NOT NULL,
                extraction_state TEXT NOT NULL,
                warning_codes_json TEXT NOT NULL,
                original_blob BLOB NOT NULL,
                normalized_text TEXT NOT NULL,
                segments_json TEXT NOT NULL,
                PRIMARY KEY(document_id, source_version)
            );
            CREATE TRIGGER IF NOT EXISTS source_documents_no_update
            BEFORE UPDATE ON source_documents
            BEGIN SELECT RAISE(ABORT, 'source versions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS source_documents_no_delete
            BEFORE DELETE ON source_documents
            BEGIN SELECT RAISE(ABORT, 'source versions cannot be deleted'); END;

            CREATE TABLE IF NOT EXISTS source_spans (
                span_id TEXT PRIMARY KEY,
                pack_id TEXT NOT NULL REFERENCES study_packs(pack_id),
                document_id TEXT NOT NULL,
                source_version INTEGER NOT NULL,
                normalized_source_sha256 TEXT NOT NULL,
                locator_kind TEXT NOT NULL,
                locator_index INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                slice_sha256 TEXT NOT NULL,
                FOREIGN KEY(document_id, source_version)
                    REFERENCES source_documents(document_id, source_version)
            );
            CREATE TRIGGER IF NOT EXISTS source_spans_no_update
            BEFORE UPDATE ON source_spans
            BEGIN SELECT RAISE(ABORT, 'source spans are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS source_spans_no_delete
            BEFORE DELETE ON source_spans
            BEGIN SELECT RAISE(ABORT, 'source spans cannot be deleted'); END;

            CREATE TABLE IF NOT EXISTS study_pack_artifacts (
                artifact_id TEXT PRIMARY KEY,
                pack_id TEXT NOT NULL REFERENCES study_packs(pack_id),
                artifact_version INTEGER NOT NULL,
                artifact_type TEXT NOT NULL,
                lifecycle TEXT NOT NULL,
                content_json TEXT NOT NULL,
                content_digest TEXT NOT NULL,
                generator_id TEXT NOT NULL,
                generator_metadata_json TEXT NOT NULL,
                UNIQUE(pack_id, artifact_id, artifact_version)
            );
            CREATE INDEX IF NOT EXISTS study_pack_artifact_type_idx
                ON study_pack_artifacts(pack_id, artifact_type, artifact_id);
            CREATE TRIGGER IF NOT EXISTS study_pack_artifact_content_immutable
            BEFORE UPDATE ON study_pack_artifacts
            WHEN NEW.artifact_id IS NOT OLD.artifact_id
              OR NEW.pack_id IS NOT OLD.pack_id
              OR NEW.artifact_version IS NOT OLD.artifact_version
              OR NEW.artifact_type IS NOT OLD.artifact_type
              OR NEW.content_json IS NOT OLD.content_json
              OR NEW.content_digest IS NOT OLD.content_digest
              OR NEW.generator_id IS NOT OLD.generator_id
              OR NEW.generator_metadata_json IS NOT OLD.generator_metadata_json
            BEGIN SELECT RAISE(ABORT, 'artifact versions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS study_pack_artifacts_no_delete
            BEFORE DELETE ON study_pack_artifacts
            BEGIN SELECT RAISE(ABORT, 'artifact versions cannot be deleted'); END;

            CREATE TABLE IF NOT EXISTS candidate_skill_links (
                pack_id TEXT NOT NULL REFERENCES study_packs(pack_id),
                artifact_id TEXT NOT NULL REFERENCES study_pack_artifacts(artifact_id),
                label TEXT NOT NULL,
                skill_id TEXT,
                status TEXT NOT NULL,
                taxonomy_version TEXT,
                taxonomy_digest TEXT,
                PRIMARY KEY(pack_id, artifact_id, label)
            );
            CREATE TRIGGER IF NOT EXISTS candidate_skill_links_no_update
            BEFORE UPDATE ON candidate_skill_links
            BEGIN SELECT RAISE(ABORT, 'candidate skill links are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS candidate_skill_links_no_delete
            BEFORE DELETE ON candidate_skill_links
            BEGIN SELECT RAISE(ABORT, 'candidate skill links cannot be deleted'); END;

            CREATE TABLE IF NOT EXISTS verifier_decisions (
                decision_id TEXT PRIMARY KEY,
                pack_id TEXT NOT NULL REFERENCES study_packs(pack_id),
                artifact_id TEXT NOT NULL REFERENCES study_pack_artifacts(artifact_id),
                artifact_version INTEGER NOT NULL,
                artifact_digest TEXT NOT NULL,
                verifier_id TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                reason_codes_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS verifier_decisions_no_update
            BEFORE UPDATE ON verifier_decisions
            BEGIN SELECT RAISE(ABORT, 'verifier decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS verifier_decisions_no_delete
            BEFORE DELETE ON verifier_decisions
            BEGIN SELECT RAISE(ABORT, 'verifier decisions cannot be deleted'); END;

            CREATE TABLE IF NOT EXISTS study_pack_attempts (
                attempt_id TEXT PRIMARY KEY,
                pack_id TEXT NOT NULL REFERENCES study_packs(pack_id),
                artifact_id TEXT NOT NULL REFERENCES study_pack_artifacts(artifact_id),
                artifact_version INTEGER NOT NULL,
                learner_answer_text TEXT NOT NULL,
                answer_digest TEXT NOT NULL,
                correct INTEGER NOT NULL,
                score REAL NOT NULL,
                evidence_origin TEXT NOT NULL,
                activity_kind TEXT NOT NULL,
                scorer_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS study_pack_attempts_no_update
            BEFORE UPDATE ON study_pack_attempts
            BEGIN SELECT RAISE(ABORT, 'practice attempts are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS study_pack_attempts_no_delete
            BEFORE DELETE ON study_pack_attempts
            BEGIN SELECT RAISE(ABORT, 'practice attempts cannot be deleted'); END;
            CREATE TRIGGER IF NOT EXISTS study_pack_attempts_valid_evidence_origin
            BEFORE INSERT ON study_pack_attempts
            WHEN NEW.evidence_origin NOT IN ('human_local_interactive', 'evaluation_fixture')
            BEGIN SELECT RAISE(ABORT, 'practice attempt evidence origin is invalid'); END;

            CREATE TABLE IF NOT EXISTS study_pack_events (
                pack_id TEXT NOT NULL,
                seq INTEGER NOT NULL CHECK(seq > 0),
                occurred_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                PRIMARY KEY(pack_id, seq)
            );
            CREATE TRIGGER IF NOT EXISTS study_pack_events_no_update
            BEFORE UPDATE ON study_pack_events
            BEGIN SELECT RAISE(ABORT, 'Study Pack events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS study_pack_events_no_delete
            BEFORE DELETE ON study_pack_events
            BEGIN SELECT RAISE(ABORT, 'Study Pack events are append-only'); END;

            CREATE TABLE IF NOT EXISTS study_pack_command_receipts (
                command_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS study_pack_receipts_no_update
            BEFORE UPDATE ON study_pack_command_receipts
            BEGIN SELECT RAISE(ABORT, 'command receipts are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS study_pack_receipts_no_delete
            BEFORE DELETE ON study_pack_command_receipts
            BEGIN SELECT RAISE(ABORT, 'command receipts are immutable'); END;
            """
        )

    # Public mutation: creation has no caller-supplied entity IDs.
    def create_pack(
        self,
        *,
        title: Any,
        source: Mapping[str, Any],
        command_id: Any,
    ) -> dict[str, Any]:
        command = validate_command_id(command_id)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise StudyPackError("invalid_source_body", "title is invalid")
        fingerprint = _create_request_fingerprint(title, source, command)
        prior = self._receipt_replay(command, fingerprint)
        if prior is not None:
            return prior
        parsed = parse_source(source, pdf_backend=self._pdf_backend)
        pack_id = self._id_factory("p_")
        document_id = self._id_factory("d_")
        generated: GeneratedPack | None
        quarantine_reason: str | None = None
        try:
            generated = generate_extractive_pack(
                parsed,
                pack_id=pack_id,
                document_id=document_id,
                source_version=1,
                id_factory=self._id_factory,
                taxonomy=self._taxonomy,
            )
        except StudyPackError as error:
            if error.code != "source_insufficient_for_pack":
                raise
            generated = None
            quarantine_reason = error.code

        now = self._now()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._receipt_replay(command, fingerprint)
            if replay is not None:
                connection.execute("COMMIT")
                return replay
            lifecycle = "quarantined" if generated is None else "draft"
            artifact_set_digest = generated.artifact_set_digest if generated else None
            connection.execute(
                "INSERT INTO study_packs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pack_id,
                    title,
                    lifecycle,
                    1,
                    document_id,
                    1,
                    parsed.normalized_sha256,
                    artifact_set_digest,
                    GENERATOR_ID,
                    quarantine_reason,
                    now,
                    now,
                ),
            )
            document = SourceDocument(
                document_id=document_id,
                pack_id=pack_id,
                source_version=1,
                input_kind=parsed.input_kind,
                media_type=parsed.media_type,
                original_sha256=parsed.original_sha256,
                normalized_sha256=parsed.normalized_sha256,
                byte_count=len(parsed.original_bytes),
                locator_count=len(parsed.segments),
                codepoint_count=parsed.codepoint_count,
                parser_name=parsed.parser_name,
                parser_version=parsed.parser_version,
                normalization_name=parsed.normalization_name,
                normalization_version=parsed.normalization_version,
                extraction_state=(
                    "accepted_with_warnings" if parsed.warnings else "accepted"
                ),
                warning_codes=parsed.warnings,
            )
            self._insert_document(document, parsed)
            if generated is not None:
                for span in generated.spans:
                    self._insert_span(pack_id, span)
                for artifact in generated.artifacts:
                    self._insert_artifact(artifact)
                for link in generated.candidate_skill_links:
                    self._insert_skill_link(pack_id, link)
            state = self._pack_state(pack_id)
            self._append_event(
                pack_id,
                "pack_quarantined" if generated is None else "pack_created",
                {
                    "schema_version": EVENT_SCHEMA,
                    "command_id": command,
                    "result": (
                        {"status": "quarantined", "reason_code": quarantine_reason}
                        if generated is None
                        else {
                            "status": "draft",
                            "artifact_count": len(generated.artifacts),
                            "span_count": len(generated.spans),
                        }
                    ),
                    "pack_after": state,
                },
                now,
            )
            response = self._public_pack(pack_id)
            response["idempotent_replay"] = False
            self._record_receipt(command, fingerprint, response, now)
            connection.execute("COMMIT")
            return response
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def command_pack(
        self,
        *,
        pack_id: Any,
        action: Any,
        expected_version: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        if action == "request_review":
            return self.request_review(
                pack_id=pack_id,
                expected_version=expected_version,
                command_id=command_id,
            )
        if action == "publish":
            return self.publish(
                pack_id=pack_id,
                expected_version=expected_version,
                command_id=command_id,
            )
        raise StudyPackError("invalid_transition", "pack command action is unsupported")

    def request_review(
        self, *, pack_id: Any, expected_version: Any, command_id: Any
    ) -> dict[str, Any]:
        pack = validate_entity_id(pack_id, "p_")
        command = validate_command_id(command_id)
        version = _validate_expected_version(expected_version)
        fingerprint = _fingerprint(
            {
                "operation": "request_review",
                "pack_id": pack,
                "expected_version": version,
                "command_id": command,
            }
        )
        now = self._now()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._receipt_replay(command, fingerprint)
            if replay is not None:
                connection.execute("COMMIT")
                return replay
            row = self._require_pack(pack)
            self._require_version(row, version)
            if row["lifecycle"] != "draft":
                raise StudyPackError(
                    "invalid_transition", "only a draft pack can request review"
                )
            artifacts = self._load_artifacts(pack)
            spans = self._load_spans(pack)
            links = self._load_skill_links(pack)
            result = verify_artifact_set(
                artifacts,
                spans,
                links,
                resolve_span=lambda span_id: self._resolve_span(span_id, pack_id=pack),
                id_factory=self._id_factory,
                taxonomy=self._taxonomy,
                expected_artifact_set_digest=str(row["artifact_set_digest"]),
                expected_source_sha256=str(row["normalized_source_sha256"]),
            )
            for decision in result.decisions:
                self._insert_decision(decision, now)
            lifecycle = "review" if result.accepted else "quarantined"
            quarantine_reason = None if result.accepted else "deterministic_verification_failed"
            new_version = version + 1
            connection.execute(
                """
                UPDATE study_packs
                SET lifecycle = ?, version = ?, quarantine_reason = ?, updated_at = ?
                WHERE pack_id = ?
                """,
                (lifecycle, new_version, quarantine_reason, now, pack),
            )
            connection.execute(
                "UPDATE study_pack_artifacts SET lifecycle = ? WHERE pack_id = ?",
                (lifecycle, pack),
            )
            state = self._pack_state(pack)
            self._append_event(
                pack,
                "review_accepted" if result.accepted else "pack_quarantined",
                {
                    "schema_version": EVENT_SCHEMA,
                    "command_id": command,
                    "verifier_id": VERIFIER_ID,
                    "accepted": result.accepted,
                    "decision_refs": [
                        {
                            "decision_id": item.decision_id,
                            "artifact_id": item.artifact_id,
                            "artifact_digest": item.artifact_digest,
                            "accepted": item.accepted,
                            "reason_codes": list(item.reason_codes),
                        }
                        for item in result.decisions
                    ],
                    "pack_after": state,
                },
                now,
            )
            response = self._public_pack(pack)
            response["idempotent_replay"] = False
            self._record_receipt(command, fingerprint, response, now)
            connection.execute("COMMIT")
            return response
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def publish(
        self, *, pack_id: Any, expected_version: Any, command_id: Any
    ) -> dict[str, Any]:
        pack = validate_entity_id(pack_id, "p_")
        command = validate_command_id(command_id)
        version = _validate_expected_version(expected_version)
        fingerprint = _fingerprint(
            {
                "operation": "publish",
                "pack_id": pack,
                "expected_version": version,
                "command_id": command,
            }
        )
        now = self._now()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._receipt_replay(command, fingerprint)
            if replay is not None:
                connection.execute("COMMIT")
                return replay
            row = self._require_pack(pack)
            self._require_version(row, version)
            if row["lifecycle"] != "review":
                raise StudyPackError(
                    "invalid_transition", "only an accepted review can publish"
                )
            artifacts = self._load_artifacts(pack)
            if not artifacts or not all(self._has_exact_acceptance(item) for item in artifacts):
                raise StudyPackError(
                    "invalid_transition", "artifact review is incomplete or stale"
                )
            new_version = version + 1
            connection.execute(
                "UPDATE study_packs SET lifecycle = 'published', version = ?, updated_at = ? WHERE pack_id = ?",
                (new_version, now, pack),
            )
            connection.execute(
                "UPDATE study_pack_artifacts SET lifecycle = 'published' WHERE pack_id = ?",
                (pack,),
            )
            state = self._pack_state(pack)
            self._append_event(
                pack,
                "pack_published",
                {
                    "schema_version": EVENT_SCHEMA,
                    "command_id": command,
                    "accepted_artifact_digests": [
                        item.content_digest for item in sorted(artifacts, key=lambda value: value.artifact_id)
                    ],
                    "pack_after": state,
                },
                now,
            )
            response = self._public_pack(pack)
            response["idempotent_replay"] = False
            self._record_receipt(command, fingerprint, response, now)
            connection.execute("COMMIT")
            return response
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def launch_item(self, artifact_id: Any) -> dict[str, Any]:
        artifact_key = validate_entity_id(artifact_id, "a_")
        row = self._connection.execute(
            """
            SELECT a.*, p.lifecycle AS pack_lifecycle, p.version AS pack_version
            FROM study_pack_artifacts a
            JOIN study_packs p ON p.pack_id = a.pack_id
            WHERE a.artifact_id = ?
            """,
            (artifact_key,),
        ).fetchone()
        if row is None:
            raise StudyPackError("artifact_unsupported", "practice artifact does not exist")
        if row["pack_lifecycle"] == "quarantined" or row["lifecycle"] == "quarantined":
            raise StudyPackError("artifact_quarantined", "quarantined artifact cannot launch")
        if row["pack_lifecycle"] != "published" or row["lifecycle"] != "published":
            raise StudyPackError("artifact_not_published", "artifact is not published")
        if row["artifact_type"] != "study_pack.practice_item":
            raise StudyPackError("artifact_unsupported", "artifact is not a practice item")
        content = json.loads(row["content_json"])
        return {
            "schema_version": "lumi.study-pack-launch.v1",
            "pack_id": str(row["pack_id"]),
            "pack_version": int(row["pack_version"]),
            "artifact_id": artifact_key,
            "artifact_version": int(row["artifact_version"]),
            "item_kind": content["item_kind"],
            "prompt": content["prompt"],
            "scorer": content["scorer"],
            "evidence_origin": self._attempt_evidence_origin,
            "activity_kind": "within_pack_practice",
        }

    def attempt_item(
        self,
        *,
        artifact_id: Any,
        learner_answer: Any,
        expected_pack_version: Any,
        expected_artifact_version: Any,
        command_id: Any,
    ) -> dict[str, Any]:
        artifact_key = validate_entity_id(artifact_id, "a_")
        command = validate_command_id(command_id)
        pack_version = _validate_expected_version(expected_pack_version)
        artifact_version = _validate_expected_version(expected_artifact_version)
        if not isinstance(learner_answer, str) or not learner_answer.strip():
            raise StudyPackError("invalid_answer", "learner answer cannot be empty")
        if len(learner_answer) > 20_000:
            raise StudyPackError("answer_too_large", "learner answer is too large")
        answer_digest = sha256_text(normalized_exact(learner_answer))
        fingerprint = _fingerprint(
            {
                "operation": "attempt_item",
                "artifact_id": artifact_key,
                "expected_pack_version": pack_version,
                "expected_artifact_version": artifact_version,
                "command_id": command,
                "learner_answer_digest": answer_digest,
                "evidence_origin": self._attempt_evidence_origin,
            }
        )
        now = self._now()
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._receipt_replay(command, fingerprint)
            if replay is not None:
                connection.execute("COMMIT")
                return replay
            row = connection.execute(
                """
                SELECT a.*, p.lifecycle AS pack_lifecycle, p.version AS pack_version
                FROM study_pack_artifacts a
                JOIN study_packs p ON p.pack_id = a.pack_id
                WHERE a.artifact_id = ?
                """,
                (artifact_key,),
            ).fetchone()
            if row is None or row["artifact_type"] != "study_pack.practice_item":
                raise StudyPackError("artifact_unsupported", "practice artifact does not exist")
            if row["pack_lifecycle"] == "quarantined" or row["lifecycle"] == "quarantined":
                raise StudyPackError("artifact_quarantined", "quarantined artifact cannot launch")
            if row["pack_lifecycle"] != "published" or row["lifecycle"] != "published":
                raise StudyPackError("artifact_not_published", "artifact is not published")
            if int(row["pack_version"]) != pack_version:
                raise VersionConflict(pack_version, int(row["pack_version"]))
            if int(row["artifact_version"]) != artifact_version:
                raise StudyPackError(
                    "stale_version", "expected_artifact_version is stale"
                )
            content = json.loads(row["content_json"])
            correct, score = score_practice(content, learner_answer)
            attempt = PracticeAttempt(
                attempt_id=self._id_factory("t_"),
                pack_id=str(row["pack_id"]),
                artifact_id=artifact_key,
                artifact_version=int(row["artifact_version"]),
                answer_digest=answer_digest,
                correct=correct,
                score=score,
                evidence_origin=self._attempt_evidence_origin,
                activity_kind="within_pack_practice",
                scorer_id=f"{content['scorer']['kind']}@{content['scorer']['version']}",
            )
            connection.execute(
                "INSERT INTO study_pack_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    attempt.attempt_id,
                    attempt.pack_id,
                    attempt.artifact_id,
                    attempt.artifact_version,
                    learner_answer,
                    attempt.answer_digest,
                    int(attempt.correct),
                    attempt.score,
                    attempt.evidence_origin,
                    attempt.activity_kind,
                    attempt.scorer_id,
                    now,
                ),
            )
            new_version = pack_version + 1
            connection.execute(
                "UPDATE study_packs SET version = ?, updated_at = ? WHERE pack_id = ?",
                (new_version, now, attempt.pack_id),
            )
            contexts = []
            for citation in content["citations"]:
                excerpt, span = self._resolve_span_with_record(
                    str(citation["span_ref"]), pack_id=attempt.pack_id
                )
                contexts.append(
                    {
                        "field_pointer": citation["field_pointer"],
                        "span_id": span.span_id,
                        "locator_kind": span.locator_kind,
                        "locator_index": span.locator_index,
                        "start_offset": span.start_offset,
                        "end_offset": span.end_offset,
                        "excerpt": excerpt,
                    }
                )
            state = self._pack_state(attempt.pack_id)
            self._append_event(
                attempt.pack_id,
                "practice_answer_accepted",
                {
                    "schema_version": EVENT_SCHEMA,
                    "command_id": command,
                    "attempt": attempt.to_dict(),
                    "mastery_write_capability": False,
                    "misconception_write_capability": False,
                    "schedule_write_capability": False,
                    "pack_after": state,
                },
                now,
            )
            response = {
                "schema_version": ATTEMPT_SCHEMA,
                "pack_id": attempt.pack_id,
                "pack_version": new_version,
                "attempt": attempt.to_dict(),
                "result": {"correct": correct, "score": score, "max_score": 1.0},
                "answer": content["answer"],
                "explanation": content["explanation"],
                "cited_source_context": contexts,
                "learning_projection_writes": {
                    "kt": False,
                    "misconception": False,
                    "today_plan": False,
                    "review_schedule": False,
                },
                "idempotent_replay": False,
                "links": {
                    "pack": f"/v1/study-packs/{attempt.pack_id}",
                    "replay": f"/v1/study-packs/{attempt.pack_id}/replay",
                },
            }
            self._record_receipt(command, fingerprint, response, now)
            connection.execute("COMMIT")
            return response
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def list_packs(self) -> dict[str, Any]:
        rows = self._connection.execute(
            "SELECT pack_id, title, lifecycle, version, created_at, updated_at FROM study_packs ORDER BY created_at, pack_id"
        ).fetchall()
        return {
            "schema_version": "lumi.study-pack-list.v1",
            "count": len(rows),
            "items": [
                {
                    "pack_id": str(row["pack_id"]),
                    "title": str(row["title"]),
                    "lifecycle": str(row["lifecycle"]),
                    "version": int(row["version"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
            ],
        }

    def get_pack(self, pack_id: Any) -> dict[str, Any]:
        pack = validate_entity_id(pack_id, "p_")
        self._require_pack(pack)
        return self._public_pack(pack)

    def resolve_citation(self, pack_id: Any, span_id: Any) -> dict[str, Any]:
        pack = validate_entity_id(pack_id, "p_")
        span_key = validate_entity_id(span_id, "s_")
        row = self._require_pack(pack)
        if row["lifecycle"] != "published":
            raise StudyPackError("artifact_not_published", "citation source is not published")
        excerpt, span = self._resolve_span_with_record(span_key, pack_id=pack)
        span_payload = span.to_dict()
        span_payload.pop("schema_version", None)
        return {
            "schema_version": "lumi.source-citation.v1",
            "verified": True,
            **span_payload,
            "excerpt": excerpt,
        }

    def replay(self, pack_id: Any) -> dict[str, Any]:
        pack = validate_entity_id(pack_id, "p_")
        events = self.events(pack)
        if not events:
            raise StudyPackError("invalid_entity_id", "Study Pack does not exist")
        if not self.verify_event_chain(pack):
            raise StudyPackError("citation_unresolved", "Study Pack event chain is invalid")
        frames = [
            {"seq": event.seq, "kind": event.kind, "state": event.payload["pack_after"]}
            for event in events
            if isinstance(event.payload.get("pack_after"), dict)
        ]
        if not frames or canonical_json(frames[-1]["state"]) != canonical_json(
            self._pack_state(pack)
        ):
            raise StudyPackError(
                "citation_unresolved", "Study Pack replay does not match its projection"
            )
        return {
            "schema_version": "lumi.study-pack-replay.v1",
            "pack_id": pack,
            "trace_verified": True,
            "projection_verified": True,
            "frame_count": len(frames),
            "frames": frames,
        }

    def recompute_attempt(self, attempt_id: Any) -> dict[str, Any]:
        attempt_key = validate_entity_id(attempt_id, "t_")
        row = self._connection.execute(
            """
            SELECT t.*, a.content_json
            FROM study_pack_attempts t
            JOIN study_pack_artifacts a ON a.artifact_id = t.artifact_id
            WHERE t.attempt_id = ?
            """,
            (attempt_key,),
        ).fetchone()
        if row is None:
            raise StudyPackError("invalid_entity_id", "practice attempt does not exist")
        content = json.loads(row["content_json"])
        correct, score = score_practice(content, str(row["learner_answer_text"]))
        return {
            "attempt_id": attempt_key,
            "recomputed_correct": correct,
            "recomputed_score": score,
            "matches_saved": (
                correct == bool(row["correct"]) and score == float(row["score"])
            ),
        }

    def events(self, pack_id: str) -> list[PackEvent]:
        rows = self._connection.execute(
            "SELECT * FROM study_pack_events WHERE pack_id = ? ORDER BY seq", (pack_id,)
        ).fetchall()
        return [
            PackEvent(
                pack_id=str(row["pack_id"]),
                seq=int(row["seq"]),
                occurred_at=str(row["occurred_at"]),
                kind=str(row["kind"]),
                payload=json.loads(row["payload_json"]),
                previous_hash=str(row["previous_hash"]),
                event_hash=str(row["event_hash"]),
            )
            for row in rows
        ]

    def verify_event_chain(self, pack_id: str) -> bool:
        previous_hash = "GENESIS"
        for event in self.events(pack_id):
            encoded = canonical_json(event.payload)
            expected = _event_hash(
                event.pack_id,
                event.seq,
                event.occurred_at,
                event.kind,
                encoded,
                previous_hash,
            )
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False
            previous_hash = event.event_hash
        return True

    def _public_pack(self, pack_id: str) -> dict[str, Any]:
        pack = self._require_pack(pack_id)
        document = self._connection.execute(
            "SELECT * FROM source_documents WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        artifacts = self._load_artifacts(pack_id)
        public_artifacts = []
        for artifact in artifacts:
            envelope = artifact.to_dict(include_private=False)
            if artifact.artifact_type == "study_pack.practice_item":
                envelope["content"] = {
                    "schema_version": artifact.content["schema_version"],
                    "item_kind": artifact.content["item_kind"],
                    "prompt": artifact.content["prompt"],
                    "scorer": artifact.content["scorer"],
                }
                envelope["links"] = {
                    "launch": f"/v1/study-pack-items/{artifact.artifact_id}/launch"
                }
            else:
                envelope["content"] = artifact.content
            public_artifacts.append(envelope)
        decisions = self._connection.execute(
            """
            SELECT decision_id, artifact_id, artifact_version, artifact_digest,
                   verifier_id, accepted, reason_codes_json
            FROM verifier_decisions WHERE pack_id = ? ORDER BY decision_id
            """,
            (pack_id,),
        ).fetchall()
        decision_refs = [
            {
                "decision_id": str(row["decision_id"]),
                "artifact_id": str(row["artifact_id"]),
                "artifact_version": int(row["artifact_version"]),
                "artifact_digest": str(row["artifact_digest"]),
                "verifier_id": str(row["verifier_id"]),
                "accepted": bool(row["accepted"]),
                "reason_codes": json.loads(row["reason_codes_json"]),
            }
            for row in decisions[:10]
        ]
        return {
            "schema_version": PACK_PROJECTION_SCHEMA,
            "pack_id": pack_id,
            "title": str(pack["title"]),
            "lifecycle": str(pack["lifecycle"]),
            "version": int(pack["version"]),
            "source": {
                "document_id": str(document["document_id"]),
                "source_version": int(document["source_version"]),
                "input_kind": str(document["input_kind"]),
                "media_type": str(document["media_type"]),
                "original_sha256": str(document["original_sha256"]),
                "normalized_sha256": str(document["normalized_sha256"]),
                "byte_count": int(document["byte_count"]),
                "locator_count": int(document["locator_count"]),
                "codepoint_count": int(document["codepoint_count"]),
                "parser_name": str(document["parser_name"]),
                "parser_version": str(document["parser_version"]),
                "normalization_name": str(document["normalization_name"]),
                "normalization_version": str(document["normalization_version"]),
                "extraction_state": str(document["extraction_state"]),
                "warning_codes": json.loads(document["warning_codes_json"]),
            },
            "artifact_set_digest": pack["artifact_set_digest"],
            "artifact_counts": {
                artifact_type: sum(item.artifact_type == artifact_type for item in artifacts)
                for artifact_type in sorted(ARTIFACT_TYPES)
            },
            "artifacts": public_artifacts,
            "candidate_skill_links": [
                item.to_dict() for item in self._load_skill_links(pack_id)
            ],
            "review": {
                "accepted": bool(decisions)
                and all(bool(row["accepted"]) for row in decisions),
                "decision_count": len(decisions),
                "accepted_count": sum(bool(row["accepted"]) for row in decisions),
                "decision_refs": decision_refs,
                "reason_codes": sorted(
                    {
                        reason
                        for row in decisions
                        for reason in json.loads(row["reason_codes_json"])
                    }
                ),
            },
            "quarantine_reason": pack["quarantine_reason"],
            "generator": {
                "id": str(pack["generator_id"]),
                "model_calls": 0,
                "network_calls": 0,
                "ocr_calls": 0,
            },
            "learning_projection_writes": {
                "kt": False,
                "misconception": False,
                "today_plan": False,
                "review_schedule": False,
            },
            "created_at": str(pack["created_at"]),
            "updated_at": str(pack["updated_at"]),
            "links": {
                "self": f"/v1/study-packs/{pack_id}",
                "commands": f"/v1/study-packs/{pack_id}/commands",
                "replay": f"/v1/study-packs/{pack_id}/replay",
            },
        }

    def _pack_state(self, pack_id: str) -> dict[str, Any]:
        pack = self._require_pack(pack_id)
        artifacts = self._load_artifacts(pack_id)
        decision_rows = self._connection.execute(
            """
            SELECT decision_id, artifact_id, artifact_version, artifact_digest,
                   verifier_id, accepted, reason_codes_json
            FROM verifier_decisions WHERE pack_id = ? ORDER BY decision_id
            """,
            (pack_id,),
        ).fetchall()
        attempt_rows = self._connection.execute(
            """
            SELECT attempt_id, artifact_id, artifact_version, answer_digest,
                   correct, score, evidence_origin, activity_kind, scorer_id
            FROM study_pack_attempts WHERE pack_id = ? ORDER BY attempt_id
            """,
            (pack_id,),
        ).fetchall()
        return {
            "schema_version": "lumi.study-pack-projection-state.v1",
            "pack_id": pack_id,
            "lifecycle": str(pack["lifecycle"]),
            "version": int(pack["version"]),
            "document_ref": {
                "document_id": str(pack["document_id"]),
                "source_version": int(pack["source_version"]),
                "normalized_source_sha256": str(pack["normalized_source_sha256"]),
            },
            "artifact_set_digest": pack["artifact_set_digest"],
            "quarantine_reason": pack["quarantine_reason"],
            "artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "artifact_version": item.artifact_version,
                    "artifact_type": item.artifact_type,
                    "lifecycle": item.lifecycle,
                    "content_digest": item.content_digest,
                }
                for item in sorted(artifacts, key=lambda value: value.artifact_id)
            ],
            "decisions": [
                {
                    "decision_id": str(row["decision_id"]),
                    "artifact_id": str(row["artifact_id"]),
                    "artifact_version": int(row["artifact_version"]),
                    "artifact_digest": str(row["artifact_digest"]),
                    "verifier_id": str(row["verifier_id"]),
                    "accepted": bool(row["accepted"]),
                    "reason_codes": json.loads(row["reason_codes_json"]),
                }
                for row in decision_rows
            ],
            "attempts": [
                {
                    "attempt_id": str(row["attempt_id"]),
                    "artifact_id": str(row["artifact_id"]),
                    "artifact_version": int(row["artifact_version"]),
                    "answer_digest": str(row["answer_digest"]),
                    "correct": bool(row["correct"]),
                    "score": float(row["score"]),
                    "evidence_origin": str(row["evidence_origin"]),
                    "activity_kind": str(row["activity_kind"]),
                    "scorer_id": str(row["scorer_id"]),
                }
                for row in attempt_rows
            ],
        }

    def _insert_document(self, document: SourceDocument, parsed: ParsedSource) -> None:
        self._connection.execute(
            "INSERT INTO source_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document.document_id,
                document.source_version,
                document.pack_id,
                document.input_kind,
                document.media_type,
                document.original_sha256,
                document.normalized_sha256,
                document.byte_count,
                document.locator_count,
                document.codepoint_count,
                document.parser_name,
                document.parser_version,
                document.normalization_name,
                document.normalization_version,
                document.extraction_state,
                canonical_json(list(document.warning_codes)),
                parsed.original_bytes,
                parsed.normalized_text,
                canonical_json([segment.to_dict() for segment in parsed.segments]),
            ),
        )

    def _insert_span(self, pack_id: str, span: SourceSpan) -> None:
        self._connection.execute(
            "INSERT INTO source_spans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                span.span_id,
                pack_id,
                span.document_id,
                span.source_version,
                span.normalized_source_sha256,
                span.locator_kind,
                span.locator_index,
                span.start_offset,
                span.end_offset,
                span.slice_sha256,
            ),
        )

    def _insert_artifact(self, artifact: Artifact) -> None:
        self._connection.execute(
            "INSERT INTO study_pack_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.artifact_id,
                artifact.pack_id,
                artifact.artifact_version,
                artifact.artifact_type,
                artifact.lifecycle,
                canonical_json(artifact.content),
                artifact.content_digest,
                artifact.generator_id,
                canonical_json(artifact.generator_metadata),
            ),
        )

    def _insert_skill_link(self, pack_id: str, link: CandidateSkillLink) -> None:
        self._connection.execute(
            "INSERT INTO candidate_skill_links VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                pack_id,
                link.artifact_id,
                link.label,
                link.skill_id,
                link.status,
                link.taxonomy_version,
                link.taxonomy_digest,
            ),
        )

    def _insert_decision(self, decision: VerifierDecision, created_at: str) -> None:
        self._connection.execute(
            "INSERT INTO verifier_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.decision_id,
                decision.pack_id,
                decision.artifact_id,
                decision.artifact_version,
                decision.artifact_digest,
                decision.verifier_id,
                int(decision.accepted),
                canonical_json(list(decision.reason_codes)),
                created_at,
            ),
        )

    def _load_artifacts(self, pack_id: str) -> list[Artifact]:
        rows = self._connection.execute(
            "SELECT * FROM study_pack_artifacts WHERE pack_id = ? ORDER BY artifact_id",
            (pack_id,),
        ).fetchall()
        return [
            Artifact(
                artifact_id=str(row["artifact_id"]),
                pack_id=str(row["pack_id"]),
                artifact_version=int(row["artifact_version"]),
                artifact_type=str(row["artifact_type"]),
                lifecycle=str(row["lifecycle"]),
                content=json.loads(row["content_json"]),
                content_digest=str(row["content_digest"]),
                generator_id=str(row["generator_id"]),
                generator_metadata=json.loads(row["generator_metadata_json"]),
            )
            for row in rows
        ]

    def _load_spans(self, pack_id: str) -> list[SourceSpan]:
        rows = self._connection.execute(
            "SELECT * FROM source_spans WHERE pack_id = ? ORDER BY span_id", (pack_id,)
        ).fetchall()
        return [_span_from_row(row) for row in rows]

    def _load_skill_links(self, pack_id: str) -> list[CandidateSkillLink]:
        rows = self._connection.execute(
            "SELECT * FROM candidate_skill_links WHERE pack_id = ? ORDER BY artifact_id, label",
            (pack_id,),
        ).fetchall()
        return [
            CandidateSkillLink(
                artifact_id=str(row["artifact_id"]),
                label=str(row["label"]),
                skill_id=str(row["skill_id"]) if row["skill_id"] is not None else None,
                status=str(row["status"]),
                taxonomy_version=(
                    str(row["taxonomy_version"])
                    if row["taxonomy_version"] is not None
                    else None
                ),
                taxonomy_digest=(
                    str(row["taxonomy_digest"])
                    if row["taxonomy_digest"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def _resolve_span(self, span_id: str, *, pack_id: str) -> str:
        return self._resolve_span_with_record(span_id, pack_id=pack_id)[0]

    def _resolve_span_with_record(
        self, span_id: str, *, pack_id: str
    ) -> tuple[str, SourceSpan]:
        row = self._connection.execute(
            "SELECT * FROM source_spans WHERE span_id = ? AND pack_id = ?",
            (span_id, pack_id),
        ).fetchone()
        if row is None:
            raise StudyPackError("citation_unresolved", "citation span does not exist")
        span = _span_from_row(row)
        document = self._connection.execute(
            """
            SELECT * FROM source_documents
            WHERE document_id = ? AND source_version = ? AND pack_id = ?
            """,
            (span.document_id, span.source_version, pack_id),
        ).fetchone()
        if document is None:
            raise StudyPackError("citation_unresolved", "citation source does not exist")
        original_blob = bytes(document["original_blob"])
        normalized_text = str(document["normalized_text"])
        if (
            sha256_bytes(original_blob) != document["original_sha256"]
            or sha256_text(normalized_text) != document["normalized_sha256"]
            or span.normalized_source_sha256 != document["normalized_sha256"]
        ):
            raise StudyPackError("citation_unresolved", "citation source hash mismatch")
        segments = json.loads(document["segments_json"])
        segment = next(
            (
                item
                for item in segments
                if item.get("locator_kind") == span.locator_kind
                and item.get("locator_index") == span.locator_index
            ),
            None,
        )
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise StudyPackError("citation_unresolved", "citation locator does not resolve")
        text = segment["text"]
        if not 0 <= span.start_offset < span.end_offset <= len(text):
            raise StudyPackError("citation_unresolved", "citation offsets are invalid")
        excerpt = text[span.start_offset : span.end_offset]
        if sha256_text(excerpt) != span.slice_sha256:
            raise StudyPackError("citation_unresolved", "citation slice hash mismatch")
        return excerpt, span

    def _has_exact_acceptance(self, artifact: Artifact) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM verifier_decisions
            WHERE pack_id = ? AND artifact_id = ? AND artifact_version = ?
              AND artifact_digest = ? AND verifier_id = ? AND accepted = 1
            """,
            (
                artifact.pack_id,
                artifact.artifact_id,
                artifact.artifact_version,
                artifact.content_digest,
                VERIFIER_ID,
            ),
        ).fetchone()
        return row is not None

    def _require_pack(self, pack_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM study_packs WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        if row is None:
            raise StudyPackError("invalid_entity_id", "Study Pack does not exist")
        return row

    @staticmethod
    def _require_version(row: sqlite3.Row, expected_version: int) -> None:
        actual = int(row["version"])
        if actual != expected_version:
            raise VersionConflict(expected_version, actual)

    def _append_event(
        self,
        pack_id: str,
        kind: str,
        payload: Mapping[str, Any],
        occurred_at: str,
    ) -> PackEvent:
        encoded = canonical_json(payload)
        row = self._connection.execute(
            "SELECT seq, event_hash FROM study_pack_events WHERE pack_id = ? ORDER BY seq DESC LIMIT 1",
            (pack_id,),
        ).fetchone()
        seq = int(row["seq"]) + 1 if row else 1
        previous_hash = str(row["event_hash"]) if row else "GENESIS"
        event_hash = _event_hash(
            pack_id, seq, occurred_at, kind, encoded, previous_hash
        )
        self._connection.execute(
            "INSERT INTO study_pack_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pack_id, seq, occurred_at, kind, encoded, previous_hash, event_hash),
        )
        return PackEvent(
            pack_id,
            seq,
            occurred_at,
            kind,
            dict(payload),
            previous_hash,
            event_hash,
        )

    def _receipt_replay(self, command_id: str, fingerprint: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT request_fingerprint, response_json FROM study_pack_command_receipts WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        if row["request_fingerprint"] != fingerprint:
            raise CommandConflict()
        response = json.loads(row["response_json"])
        response["idempotent_replay"] = True
        return response

    def _record_receipt(
        self, command_id: str, fingerprint: str, response: Mapping[str, Any], created_at: str
    ) -> None:
        self._connection.execute(
            "INSERT INTO study_pack_command_receipts VALUES (?, ?, ?, ?)",
            (command_id, fingerprint, canonical_json(response), created_at),
        )

    def _now(self) -> str:
        value = self._clock()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise StudyPackError("invalid_source_body", "clock returned invalid time") from None
        if parsed.tzinfo is None:
            raise StudyPackError("invalid_source_body", "clock must include timezone")
        return parsed.astimezone(timezone.utc).isoformat()


def _span_from_row(row: sqlite3.Row) -> SourceSpan:
    return SourceSpan(
        span_id=str(row["span_id"]),
        document_id=str(row["document_id"]),
        source_version=int(row["source_version"]),
        normalized_source_sha256=str(row["normalized_source_sha256"]),
        locator_kind=str(row["locator_kind"]),
        locator_index=int(row["locator_index"]),
        start_offset=int(row["start_offset"]),
        end_offset=int(row["end_offset"]),
        slice_sha256=str(row["slice_sha256"]),
    )


def _validate_expected_version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StudyPackError("stale_version", "expected_version must be positive")
    return value


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _create_request_fingerprint(
    title: str, source: Mapping[str, Any], command_id: str
) -> str:
    if not isinstance(source, Mapping) or not isinstance(source.get("kind"), str):
        raise StudyPackError("invalid_source_body", "source union is invalid")
    if source["kind"] == "pasted_text":
        if set(source) != {"kind", "text"} or not isinstance(source.get("text"), str):
            raise StudyPackError("invalid_source_body", "pasted source body is invalid")
        payload_digest = _utf8_request_digest(source["text"])
    elif source["kind"] == "text_pdf":
        if set(source) != {"kind", "pdf_base64"} or not isinstance(
            source.get("pdf_base64"), str
        ):
            raise StudyPackError("invalid_source_body", "PDF source body is invalid")
        payload_digest = _utf8_request_digest(source["pdf_base64"])
    else:
        raise StudyPackError("invalid_source_body", "source kind is unsupported")
    return _fingerprint(
        {
            "operation": "create_pack",
            "command_id": command_id,
            "title_sha256": _utf8_request_digest(title),
            "source_kind": source["kind"],
            "source_payload_sha256": payload_digest,
        }
    )


def _utf8_request_digest(value: str) -> str:
    try:
        return sha256_text(value)
    except UnicodeEncodeError:
        raise StudyPackError(
            "invalid_source_body", "request text is not valid Unicode"
        ) from None


def _event_hash(
    pack_id: str,
    seq: int,
    occurred_at: str,
    kind: str,
    encoded: str,
    previous_hash: str,
) -> str:
    canonical = "\x1f".join(
        (pack_id, str(seq), occurred_at, kind, encoded, previous_hash)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
