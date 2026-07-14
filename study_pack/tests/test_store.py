from __future__ import annotations

import base64
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from helpers import (
    CHINESE_SOURCE,
    SequentialIdFactory,
    make_encrypted_pdf,
    make_text_pdf,
    opaque_id,
)
from lumi_study_pack.models import CommandConflict, StudyPackError, VersionConflict
from lumi_study_pack.store import StudyPackStore


class StudyPackStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "packs.sqlite3"
        self.ids = SequentialIdFactory()
        self.store = StudyPackStore(
            self.database,
            id_factory=self.ids,
            clock=lambda: "2026-07-11T00:00:00+00:00",
        )
        self.command_counter = 1000

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def command(self) -> str:
        self.command_counter += 1
        return opaque_id("c_", self.command_counter)

    def create(self, *, command_id: str | None = None, text: str = CHINESE_SOURCE):
        return self.store.create_pack(
            title="本地学习材料",
            source={"kind": "pasted_text", "text": text},
            command_id=command_id or self.command(),
        )

    def publish(self):
        created = self.create()
        reviewed = self.store.request_review(
            pack_id=created["pack_id"],
            expected_version=1,
            command_id=self.command(),
        )
        published = self.store.publish(
            pack_id=created["pack_id"],
            expected_version=2,
            command_id=self.command(),
        )
        return created, reviewed, published

    def private_practice_content(self, artifact_id: str) -> dict:
        row = self.store._connection.execute(  # type: ignore[attr-defined]
            "SELECT content_json FROM study_pack_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        return json.loads(row[0])

    def test_full_pasted_flow_survives_restart_without_pre_answer_leakage(self) -> None:
        created = self.create()
        self.assertEqual(created["lifecycle"], "draft")
        self.assertEqual(created["schema_version"], "lumi.study-pack-detail.v1")
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["source"]["extraction_state"], "accepted")
        self.assertEqual(created["attempt_history"], [])
        self.assertEqual(
            set(created["links"]), {"self", "commands", "replay"}
        )
        self.assertFalse(created["idempotent_replay"])
        practice = next(
            item
            for item in created["artifacts"]
            if item["artifact_type"] == "study_pack.practice_item"
        )
        self.assertEqual(
            set(practice["content"]),
            {"schema_version", "item_kind", "prompt", "scorer"},
        )
        self.assertEqual(set(practice["links"]), {"launch"})
        self.assertTrue(
            any(
                item["artifact_type"] == "study_pack.one_page_notes"
                and "claims" in item["content"]
                for item in created["artifacts"]
            )
        )
        with self.assertRaises(StudyPackError) as draft_launch:
            self.store.launch_item(practice["artifact_id"])
        self.assertEqual(draft_launch.exception.code, "artifact_not_published")

        reviewed = self.store.request_review(
            pack_id=created["pack_id"],
            expected_version=1,
            command_id=self.command(),
        )
        self.assertEqual(reviewed["lifecycle"], "review")
        self.assertTrue(reviewed["review"]["accepted"])
        self.assertEqual(
            reviewed["review"]["decision_count"], len(reviewed["artifacts"])
        )
        published = self.store.publish(
            pack_id=created["pack_id"],
            expected_version=2,
            command_id=self.command(),
        )
        self.assertEqual(published["lifecycle"], "published")
        self.assertEqual(published["version"], 3)

        note = next(
            item
            for item in published["artifacts"]
            if item["artifact_type"] == "study_pack.one_page_notes"
        )
        span_id = note["content"]["citations"][0]["span_ref"]
        citation = self.store.resolve_citation(published["pack_id"], span_id)
        self.assertTrue(citation["verified"])
        self.assertEqual(
            citation["excerpt"], note["content"]["claims"][0]
        )

        launch = self.store.launch_item(practice["artifact_id"])
        self.assertEqual(launch["evidence_origin"], "human_local_interactive")
        private = self.private_practice_content(practice["artifact_id"])
        serialized_launch = json.dumps(launch, ensure_ascii=False)
        for forbidden in ("answer", "explanation", "citations", "span_ref"):
            self.assertNotIn(f'"{forbidden}"', serialized_launch)
        self.assertNotIn(private["answer"], serialized_launch)
        attempt = self.store.attempt_item(
            artifact_id=practice["artifact_id"],
            learner_answer=private["answer"],
            expected_pack_version=3,
            expected_artifact_version=1,
            command_id=self.command(),
        )
        self.assertTrue(attempt["result"]["correct"])
        self.assertEqual(
            attempt["schema_version"], "lumi.study-pack-attempt-result.v1"
        )
        self.assertEqual(
            attempt["attempt"]["schema_version"], "lumi.study-pack-attempt.v1"
        )
        self.assertEqual(set(attempt["links"]), {"pack", "replay"})
        self.assertEqual(attempt["answer"], private["answer"])
        self.assertEqual(attempt["attempt"]["evidence_origin"], "human_local_interactive")
        self.assertEqual(attempt["attempt"]["activity_kind"], "within_pack_practice")
        saved_origin = self.store._connection.execute(  # type: ignore[attr-defined]
            "SELECT evidence_origin FROM study_pack_attempts WHERE attempt_id = ?",
            (attempt["attempt"]["attempt_id"],),
        ).fetchone()[0]
        self.assertEqual(saved_origin, "human_local_interactive")
        history = self.store.get_pack(created["pack_id"])["attempt_history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(
            set(history[0]),
            {
                "schema_version",
                "attempt",
                "prompt",
                "learner_answer",
                "result",
                "answer",
                "explanation",
                "cited_source_context",
                "created_at",
            },
        )
        self.assertEqual(history[0]["learner_answer"], private["answer"])
        self.assertEqual(history[0]["answer"], private["answer"])
        self.assertTrue(history[0]["result"]["correct"])
        self.assertEqual(history[0]["attempt"]["attempt_id"], attempt["attempt"]["attempt_id"])
        self.assertTrue(history[0]["cited_source_context"])
        self.assertTrue(
            all("slice_sha256" in item for item in history[0]["cited_source_context"])
        )
        accepted_event = self.store.events(created["pack_id"])[-1]
        self.assertEqual(
            accepted_event.payload["attempt"]["evidence_origin"],
            "human_local_interactive",
        )
        self.assertTrue(
            self.store.recompute_attempt(attempt["attempt"]["attempt_id"])[
                "matches_saved"
            ]
        )
        event_text = json.dumps(
            [item.payload for item in self.store.events(created["pack_id"])],
            ensure_ascii=False,
        )
        self.assertNotIn(private["answer"], event_text)
        self.assertNotIn(CHINESE_SOURCE, event_text)
        self.assertTrue(self.store.verify_event_chain(created["pack_id"]))

        pack_id = created["pack_id"]
        self.store.close()
        self.store = StudyPackStore(
            self.database,
            id_factory=SequentialIdFactory(),
            clock=lambda: "2026-07-12T00:00:00+00:00",
        )
        replay = self.store.replay(pack_id)
        self.assertTrue(replay["trace_verified"])
        self.assertTrue(replay["projection_verified"])
        self.assertEqual(replay["frames"][-1]["state"]["version"], 4)
        self.assertEqual(
            self.store.get_pack(pack_id)["attempt_history"][0]["learner_answer"],
            private["answer"],
        )

    def test_evaluation_fixture_origin_is_constructor_owned_and_not_human_evidence(
        self,
    ) -> None:
        evaluation_database = Path(self.temporary.name) / "evaluation-packs.sqlite3"
        evaluation_store = StudyPackStore(
            evaluation_database,
            id_factory=SequentialIdFactory(),
            clock=lambda: "2026-07-11T00:00:00+00:00",
            attempt_evidence_origin="evaluation_fixture",
        )
        try:
            created = evaluation_store.create_pack(
                title="本地评测材料",
                source={"kind": "pasted_text", "text": CHINESE_SOURCE},
                command_id=opaque_id("c_", 2001),
            )
            evaluation_store.request_review(
                pack_id=created["pack_id"],
                expected_version=1,
                command_id=opaque_id("c_", 2002),
            )
            published = evaluation_store.publish(
                pack_id=created["pack_id"],
                expected_version=2,
                command_id=opaque_id("c_", 2003),
            )
            practice = next(
                item
                for item in published["artifacts"]
                if item["artifact_type"] == "study_pack.practice_item"
            )
            answer = json.loads(
                evaluation_store._connection.execute(  # type: ignore[attr-defined]
                    "SELECT content_json FROM study_pack_artifacts WHERE artifact_id = ?",
                    (practice["artifact_id"],),
                ).fetchone()[0]
            )["answer"]
            launch = evaluation_store.launch_item(practice["artifact_id"])
            self.assertEqual(launch["evidence_origin"], "evaluation_fixture")
            with self.assertRaises(TypeError):
                evaluation_store.attempt_item(
                    artifact_id=practice["artifact_id"],
                    learner_answer=answer,
                    expected_pack_version=3,
                    expected_artifact_version=1,
                    command_id=opaque_id("c_", 2004),
                    evidence_origin="human_local_interactive",  # type: ignore[call-arg]
                )
            result = evaluation_store.attempt_item(
                artifact_id=practice["artifact_id"],
                learner_answer=answer,
                expected_pack_version=3,
                expected_artifact_version=1,
                command_id=opaque_id("c_", 2004),
            )
            self.assertEqual(
                result["attempt"]["evidence_origin"], "evaluation_fixture"
            )
            self.assertEqual(
                evaluation_store.get_pack(created["pack_id"])["attempt_history"], []
            )
            self.assertNotEqual(
                result["attempt"]["evidence_origin"], "human_local_interactive"
            )
            self.assertEqual(
                result["learning_projection_writes"],
                {
                    "kt": False,
                    "misconception": False,
                    "today_plan": False,
                    "review_schedule": False,
                },
            )
            saved_origin = evaluation_store._connection.execute(  # type: ignore[attr-defined]
                "SELECT evidence_origin FROM study_pack_attempts"
            ).fetchone()[0]
            self.assertEqual(saved_origin, "evaluation_fixture")
            accepted_event = evaluation_store.events(created["pack_id"])[-1]
            self.assertEqual(
                accepted_event.payload["attempt"]["evidence_origin"],
                "evaluation_fixture",
            )
            replay = evaluation_store.replay(created["pack_id"])
            self.assertEqual(
                replay["frames"][-1]["state"]["attempts"][0]["evidence_origin"],
                "evaluation_fixture",
            )
            serialized_evidence = json.dumps(
                {
                    "launch": launch,
                    "result": result,
                    "event": accepted_event.payload,
                    "replay": replay,
                },
                ensure_ascii=False,
            )
            self.assertNotIn("human_local_interactive", serialized_evidence)
        finally:
            evaluation_store.close()

    def test_human_attempt_history_fails_closed_on_integrity_mismatch(self) -> None:
        _, _, published = self.publish()
        practice = next(
            item
            for item in published["artifacts"]
            if item["artifact_type"] == "study_pack.practice_item"
        )
        private = self.private_practice_content(practice["artifact_id"])
        attempt = self.store.attempt_item(
            artifact_id=practice["artifact_id"],
            learner_answer=private["answer"],
            expected_pack_version=3,
            expected_artifact_version=1,
            command_id=self.command(),
        )
        attempt_id = attempt["attempt"]["attempt_id"]
        pack_id = published["pack_id"]
        connection = self.store._connection  # type: ignore[attr-defined]
        connection.execute("DROP TRIGGER study_pack_attempts_no_update")

        original = connection.execute(
            "SELECT artifact_version, score, scorer_id FROM study_pack_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        mutations = (
            ("artifact_version", 99, original["artifact_version"]),
            ("score", 0.25, original["score"]),
            ("scorer_id", "untrusted@9", original["scorer_id"]),
        )
        for column, invalid_value, original_value in mutations:
            with self.subTest(column=column):
                connection.execute(
                    f"UPDATE study_pack_attempts SET {column} = ? WHERE attempt_id = ?",
                    (invalid_value, attempt_id),
                )
                with self.assertRaises(StudyPackError) as caught:
                    self.store.get_pack(pack_id)
                self.assertEqual(caught.exception.code, "attempt_history_invalid")
                connection.execute(
                    f"UPDATE study_pack_attempts SET {column} = ? WHERE attempt_id = ?",
                    (original_value, attempt_id),
                )

        connection.execute("DROP TRIGGER study_pack_artifact_content_immutable")
        stored_content = connection.execute(
            "SELECT content_json FROM study_pack_artifacts WHERE artifact_id = ?",
            (practice["artifact_id"],),
        ).fetchone()[0]
        tampered_content = json.loads(stored_content)
        tampered_content["explanation"] += "篡改"
        connection.execute(
            "UPDATE study_pack_artifacts SET content_json = ? WHERE artifact_id = ?",
            (json.dumps(tampered_content, ensure_ascii=False), practice["artifact_id"]),
        )
        with self.assertRaises(StudyPackError) as digest_error:
            self.store.get_pack(pack_id)
        self.assertEqual(digest_error.exception.code, "attempt_history_invalid")

    def test_constructor_rejects_unknown_attempt_origin_before_creating_storage(
        self,
    ) -> None:
        invalid_database = Path(self.temporary.name) / "invalid-origin.sqlite3"
        with self.assertRaises(ValueError):
            StudyPackStore(
                invalid_database,
                attempt_evidence_origin="synthetic_from_request",
            )
        self.assertFalse(invalid_database.exists())

    def test_real_text_pdf_create_review_publish_and_page_citation_after_restart(self) -> None:
        raw = make_text_pdf(
            [
                "First source statement explains local evidence.",
                "Second source statement describes exact scoring.",
                "Third source statement requires citation checks.",
                "Fourth source statement supports delayed review.",
            ]
        )
        created = self.store.create_pack(
            title="PDF material",
            source={
                "kind": "text_pdf",
                "pdf_base64": base64.b64encode(raw).decode("ascii"),
            },
            command_id=self.command(),
        )
        self.assertEqual(created["source"]["parser_name"], "pypdf")
        self.assertEqual(created["source"]["parser_version"], "6.10.0")
        pack_id = created["pack_id"]
        self.store.close()
        self.store = StudyPackStore(self.database, id_factory=SequentialIdFactory())
        reviewed = self.store.request_review(
            pack_id=pack_id, expected_version=1, command_id=self.command()
        )
        published = self.store.publish(
            pack_id=pack_id, expected_version=2, command_id=self.command()
        )
        self.assertTrue(reviewed["review"]["accepted"])
        card = next(
            item
            for item in published["artifacts"]
            if item["artifact_type"] == "study_pack.knowledge_card"
        )
        span_id = card["content"]["citations"][0]["span_ref"]
        citation = self.store.resolve_citation(pack_id, span_id)
        self.assertEqual(citation["locator_kind"], "page")
        self.assertEqual(citation["locator_index"], 1)
        self.assertTrue(citation["verified"])

    def test_command_receipts_conflicts_stale_versions_and_double_cas(self) -> None:
        command_id = self.command()
        created = self.create(command_id=command_id)
        replayed = self.create(command_id=command_id)
        self.assertEqual(replayed["pack_id"], created["pack_id"])
        self.assertTrue(replayed["idempotent_replay"])
        with self.assertRaises(CommandConflict):
            self.store.create_pack(
                title="different title",
                source={"kind": "pasted_text", "text": CHINESE_SOURCE},
                command_id=command_id,
            )
        review_command = self.command()
        reviewed = self.store.request_review(
            pack_id=created["pack_id"], expected_version=1, command_id=review_command
        )
        replayed_review = self.store.request_review(
            pack_id=created["pack_id"], expected_version=1, command_id=review_command
        )
        self.assertTrue(replayed_review["idempotent_replay"])
        self.assertEqual(replayed_review["version"], reviewed["version"])
        with self.assertRaises(VersionConflict):
            self.store.publish(
                pack_id=created["pack_id"], expected_version=1, command_id=self.command()
            )
        published = self.store.publish(
            pack_id=created["pack_id"], expected_version=2, command_id=self.command()
        )
        practice = next(
            item
            for item in published["artifacts"]
            if item["artifact_type"] == "study_pack.practice_item"
        )
        answer = self.private_practice_content(practice["artifact_id"])["answer"]
        with self.assertRaises(StudyPackError) as empty_answer:
            self.store.attempt_item(
                artifact_id=practice["artifact_id"],
                learner_answer="   ",
                expected_pack_version=3,
                expected_artifact_version=1,
                command_id=self.command(),
            )
        self.assertEqual(empty_answer.exception.code, "invalid_answer")
        with self.assertRaises(StudyPackError) as large_answer:
            self.store.attempt_item(
                artifact_id=practice["artifact_id"],
                learner_answer="x" * 20_001,
                expected_pack_version=3,
                expected_artifact_version=1,
                command_id=self.command(),
            )
        self.assertEqual(large_answer.exception.code, "answer_too_large")
        attempt_command = self.command()
        attempted = self.store.attempt_item(
            artifact_id=practice["artifact_id"],
            learner_answer=answer,
            expected_pack_version=3,
            expected_artifact_version=1,
            command_id=attempt_command,
        )
        replay_attempt = self.store.attempt_item(
            artifact_id=practice["artifact_id"],
            learner_answer=answer,
            expected_pack_version=3,
            expected_artifact_version=1,
            command_id=attempt_command,
        )
        self.assertTrue(replay_attempt["idempotent_replay"])
        self.assertEqual(
            replay_attempt["attempt"]["attempt_id"], attempted["attempt"]["attempt_id"]
        )
        with self.assertRaises(CommandConflict):
            self.store.attempt_item(
                artifact_id=practice["artifact_id"],
                learner_answer="different",
                expected_pack_version=3,
                expected_artifact_version=1,
                command_id=attempt_command,
            )
        with self.assertRaises(VersionConflict):
            self.store.attempt_item(
                artifact_id=practice["artifact_id"],
                learner_answer=answer,
                expected_pack_version=3,
                expected_artifact_version=1,
                command_id=self.command(),
            )
        with self.assertRaises(StudyPackError) as artifact_stale:
            self.store.attempt_item(
                artifact_id=practice["artifact_id"],
                learner_answer=answer,
                expected_pack_version=4,
                expected_artifact_version=2,
                command_id=self.command(),
            )
        self.assertEqual(artifact_stale.exception.code, "stale_version")

    def test_create_receipt_replays_without_reinvoking_pdf_parser(self) -> None:
        raw = make_text_pdf(
            [
                "First statement provides enough local source evidence.",
                "Second statement supports deterministic practice generation.",
                "Third statement allows exact citation verification.",
                "Fourth statement supports a bounded review task.",
            ]
        )
        source = {
            "kind": "text_pdf",
            "pdf_base64": base64.b64encode(raw).decode("ascii"),
        }
        command_id = self.command()
        created = self.store.create_pack(
            title="Durable PDF receipt", source=source, command_id=command_id
        )

        class ParserMustNotRun:
            def extract(self, pdf_bytes: bytes, deadline_seconds: float):
                raise AssertionError("durable receipt replay invoked the PDF parser")

        self.store._pdf_backend = ParserMustNotRun()  # type: ignore[attr-defined]
        replayed = self.store.create_pack(
            title="Durable PDF receipt", source=source, command_id=command_id
        )
        self.assertEqual(replayed["pack_id"], created["pack_id"])
        self.assertTrue(replayed["idempotent_replay"])

    def test_concurrent_publish_across_connections_accepts_one_write(self) -> None:
        created = self.create()
        self.store.request_review(
            pack_id=created["pack_id"], expected_version=1, command_id=self.command()
        )
        pack_id = created["pack_id"]
        barrier = threading.Barrier(3)

        def publish(command_id: str):
            store = StudyPackStore(self.database)
            barrier.wait(timeout=3)
            try:
                return store.publish(
                    pack_id=pack_id, expected_version=2, command_id=command_id
                )
            except StudyPackError as error:
                return error
            finally:
                store.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(publish, opaque_id("c_", 2001)),
                executor.submit(publish, opaque_id("c_", 2002)),
            ]
            barrier.wait(timeout=3)
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sum(isinstance(item, dict) for item in results), 1)
        self.assertEqual(sum(isinstance(item, VersionConflict) for item in results), 1)
        self.assertEqual(
            sum(item.kind == "pack_published" for item in self.store.events(pack_id)), 1
        )
        self.assertTrue(self.store.verify_event_chain(pack_id))

    def test_insufficient_source_and_verifier_disagreement_quarantine_permanently(self) -> None:
        insufficient = self.create(text="只有一个足够长但无法形成练习包的句子。")
        self.assertEqual(insufficient["lifecycle"], "quarantined")
        self.assertEqual(insufficient["quarantine_reason"], "source_insufficient_for_pack")
        self.assertTrue(all(value == 0 for value in insufficient["artifact_counts"].values()))
        with self.assertRaises(StudyPackError) as invalid_publish:
            self.store.publish(
                pack_id=insufficient["pack_id"],
                expected_version=1,
                command_id=self.command(),
            )
        self.assertEqual(invalid_publish.exception.code, "invalid_transition")

        created = self.create()
        artifact = created["artifacts"][0]
        self.store._connection.execute(  # type: ignore[attr-defined]
            "DROP TRIGGER study_pack_artifact_content_immutable"
        )
        self.store._connection.execute(  # type: ignore[attr-defined]
            "UPDATE study_pack_artifacts SET content_json = ? WHERE artifact_id = ?",
            ("{}", artifact["artifact_id"]),
        )
        quarantined = self.store.request_review(
            pack_id=created["pack_id"], expected_version=1, command_id=self.command()
        )
        self.assertEqual(quarantined["lifecycle"], "quarantined")
        self.assertFalse(quarantined["review"]["accepted"])
        self.assertIn("artifact_digest_mismatch", quarantined["review"]["reason_codes"])
        with self.assertRaises(StudyPackError) as cannot_publish:
            self.store.publish(
                pack_id=created["pack_id"],
                expected_version=2,
                command_id=self.command(),
            )
        self.assertEqual(cannot_publish.exception.code, "invalid_transition")

    def test_parse_and_identifier_failures_leave_all_authoritative_rows_empty(self) -> None:
        invalid_cases = [
            {"kind": "pasted_text", "text": ""},
            {"kind": "pasted_text", "text": "\ud800"},
            {"kind": "pasted_text", "text": "x", "path": "/tmp/private"},
            {"kind": "text_pdf", "pdf_base64": "***"},
            {
                "kind": "text_pdf",
                "pdf_base64": base64.b64encode(b"not-pdf").decode("ascii"),
            },
            {
                "kind": "text_pdf",
                "pdf_base64": base64.b64encode(make_encrypted_pdf()).decode("ascii"),
            },
            {
                "kind": "text_pdf",
                "pdf_base64": base64.b64encode(make_text_pdf([])).decode("ascii"),
            },
        ]
        for index, source in enumerate(invalid_cases, start=1):
            with self.subTest(index=index):
                with self.assertRaises(StudyPackError):
                    self.store.create_pack(
                        title="invalid", source=source, command_id=self.command()
                    )
        with self.assertRaises(StudyPackError) as invalid_command:
            self.store.create_pack(
                title="invalid command",
                source={"kind": "pasted_text", "text": CHINESE_SOURCE},
                command_id="c_13800138000@example.com/Users/private",
            )
        self.assertEqual(invalid_command.exception.code, "invalid_command_id")
        with self.assertRaises(StudyPackError) as invalid_title:
            self.store.create_pack(
                title="\ud800",
                source={"kind": "pasted_text", "text": CHINESE_SOURCE},
                command_id=self.command(),
            )
        self.assertEqual(invalid_title.exception.code, "invalid_source_body")
        for table in (
            "study_packs",
            "source_documents",
            "source_spans",
            "study_pack_artifacts",
            "study_pack_events",
            "study_pack_command_receipts",
        ):
            count = self.store._connection.execute(  # type: ignore[attr-defined]
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            self.assertEqual(count, 0, table)

    def test_source_span_artifact_and_event_history_are_immutable(self) -> None:
        created = self.create()
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(  # type: ignore[attr-defined]
                "UPDATE source_spans SET slice_sha256 = ? WHERE pack_id = ?",
                ("0" * 64, created["pack_id"]),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(  # type: ignore[attr-defined]
                "UPDATE source_documents SET normalized_text = 'tampered' WHERE pack_id = ?",
                (created["pack_id"],),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(  # type: ignore[attr-defined]
                "DELETE FROM study_pack_events WHERE pack_id = ?", (created["pack_id"],)
            )
        self.assertTrue(self.store.verify_event_chain(created["pack_id"]))

    def test_study_pack_never_mutates_external_learning_projection_tables(self) -> None:
        self.store.close()
        connection = sqlite3.connect(self.database)
        connection.executescript(
            """
            CREATE TABLE trace_events (value TEXT);
            CREATE TABLE kt_state (value TEXT);
            CREATE TABLE misconception_dossier (value TEXT);
            CREATE TABLE today_plans (value TEXT);
            CREATE TABLE review_schedule_tasks (value TEXT);
            INSERT INTO trace_events VALUES ('sentinel');
            INSERT INTO kt_state VALUES ('sentinel');
            INSERT INTO misconception_dossier VALUES ('sentinel');
            INSERT INTO today_plans VALUES ('sentinel');
            INSERT INTO review_schedule_tasks VALUES ('sentinel');
            """
        )
        connection.commit()
        connection.close()
        self.store = StudyPackStore(self.database, id_factory=SequentialIdFactory())
        _, _, published = self.publish()
        practice = next(
            item
            for item in published["artifacts"]
            if item["artifact_type"] == "study_pack.practice_item"
        )
        answer = self.private_practice_content(practice["artifact_id"])["answer"]
        self.store.attempt_item(
            artifact_id=practice["artifact_id"],
            learner_answer=answer,
            expected_pack_version=3,
            expected_artifact_version=1,
            command_id=self.command(),
        )
        for table in (
            "trace_events",
            "kt_state",
            "misconception_dossier",
            "today_plans",
            "review_schedule_tasks",
        ):
            value = self.store._connection.execute(  # type: ignore[attr-defined]
                f"SELECT value FROM {table}"
            ).fetchone()[0]
            self.assertEqual(value, "sentinel", table)
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in Path("study_pack/lumi_study_pack").glob("*.py")
        )
        self.assertNotIn("hermes_runtime", source)
        self.assertNotIn("hermes_kt", source)
        self.assertNotIn("hermes_service", source)
        self.assertNotIn("shenlun-agent-platform", source)

    def test_all_public_entity_ids_use_the_20_byte_ap_profile(self) -> None:
        created, reviewed, published = self.publish()
        identifiers = [
            created["pack_id"],
            created["source"]["document_id"],
            *[item["artifact_id"] for item in created["artifacts"]],
            *[item["decision_id"] for item in reviewed["review"]["decision_refs"]],
        ]
        for value in identifiers:
            self.assertRegex(value, r"^(?:p_|d_|a_|v_)[A-P]{40}$")
        practice = next(
            item
            for item in published["artifacts"]
            if item["artifact_type"] == "study_pack.practice_item"
        )
        with self.assertRaises(StudyPackError) as semantic_id:
            self.store.launch_item("a_growth-rate-review")
        self.assertEqual(semantic_id.exception.code, "invalid_entity_id")


if __name__ == "__main__":
    unittest.main()
