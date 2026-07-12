from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hermes_domains.reasoning_pack import (
    DEFAULT_DRAFT_PACK_ROOT,
    record_sha256,
    reviewed_manifest_sha256,
)
from hermes_runtime.learner_state import LearnerStateStore
from hermes_service.judgment_session import (
    JudgmentContentUnavailable,
    JudgmentSessionConfig,
    JudgmentSessionConflict,
    JudgmentSessionError,
    JudgmentSessionService,
    judgment_pack_status,
)
from hermes_service.api import create_server
from hermes_service.application import SidecarApplication


class JudgmentSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "reviewed-pack"
        shutil.copytree(DEFAULT_DRAFT_PACK_ROOT, self.root)
        self.database = Path(self.temporary.name) / "lumi.sqlite3"
        self._make_reviewed_release()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read(self, name: str) -> dict:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def write(self, name: str, value: dict) -> None:
        (self.root / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _refresh_artifact(self, name: str) -> None:
        manifest = self.read("manifest.json")
        digest = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        for artifact in manifest["artifacts"]:
            if artifact["path"] == name:
                artifact["sha256"] = digest
                break
        self.write("manifest.json", manifest)

    def _make_reviewed_release(self) -> None:
        version = "0.1.0-reviewed-test"
        for name in ("skill-graph.json", "misconception-taxonomy.json"):
            document = self.read(name)
            document["pack_version"] = version
            document["review_status"] = "release_ready"
            self.write(name, document)
        records = self.read("records.json")
        records["pack_version"] = version
        records["review_status"] = "release_ready"
        for record in records["records"]:
            record["review_status"] = "release_ready"
            record["record_sha256"] = record_sha256(record)
        self.write("records.json", records)
        manifest = self.read("manifest.json")
        manifest["pack_version"] = version
        manifest["status"] = "release_ready"
        manifest["release_ready"] = True
        manifest["runtime_registration"] = "allowed_after_human_review"
        manifest["rights"]["distribution"] = "release_distribution_allowed"
        manifest["human_review_gate"] = {
            "required": True,
            "production_load_allowed": True,
            "policy": "Temporary test-only reviewers bind this copied release. No repository draft is approved.",
            "review_attestations": [],
        }
        self.write("manifest.json", manifest)
        for artifact in manifest["artifacts"]:
            self._refresh_artifact(artifact["path"])
        manifest = self.read("manifest.json")
        artifact_hashes = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
        record_hashes = {item["record_id"]: item["record_sha256"] for item in records["records"]}
        manifest_hash = reviewed_manifest_sha256(manifest)
        manifest["human_review_gate"]["review_attestations"] = [
            {
                "review_kind": "logic", "status": "approved", "reviewer_id": "test-logic-reviewer",
                "reviewed_at": "2026-07-12T10:00:00Z", "checklist": ["unique_answer", "formalization"],
                "manifest_sha256": manifest_hash, "artifact_hashes": artifact_hashes, "record_hashes": record_hashes,
            },
            {
                "review_kind": "editorial_rights", "status": "approved", "reviewer_id": "test-rights-reviewer",
                "reviewed_at": "2026-07-12T10:01:00Z", "checklist": ["original_wording", "license_scope"],
                "manifest_sha256": manifest_hash, "artifact_hashes": artifact_hashes, "record_hashes": record_hashes,
            },
        ]
        self.write("manifest.json", manifest)

    def service(self, *, origin: str = "evaluation_fixture", namespace: str = "eval:judgment:test") -> JudgmentSessionService:
        return JudgmentSessionService(
            self.database,
            reviewed_pack_root=self.root,
            config=JudgmentSessionConfig(namespace_id=namespace, evidence_origin=origin, learner_id="test-learner"),
            today_provider=lambda: __import__("datetime").date(2026, 7, 12),
        )

    def test_repository_draft_is_honestly_unavailable(self) -> None:
        status = judgment_pack_status(DEFAULT_DRAFT_PACK_ROOT)
        self.assertEqual(status["reason"], "content_review_required")
        with self.assertRaises(JudgmentContentUnavailable):
            JudgmentSessionService(self.database, reviewed_pack_root=DEFAULT_DRAFT_PACK_ROOT)

    def test_full_wrong_probe_transfer_passes_with_public_receipt_and_replay(self) -> None:
        service = self.service()
        started = service.start(entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=12, rationale="我以为登记就一定能领取。")
        self.assertEqual(started["stage"], "awaiting_probe")
        self.assertGreaterEqual(len(started["candidate_causes"]), 2)
        self.assertTrue(all(item["status"] == "unconfirmed" for item in started["candidate_causes"]))
        self.assertEqual(
            {fact["kind"] for fact in started["observed_facts"]},
            {"selected_option", "correctness", "confidence", "elapsed_seconds", "hint_count"},
        )
        self.assertNotIn("converse", json.dumps(started, ensure_ascii=False))
        self.assertEqual(started["probe"]["record_id"], "P01")

        probed = service.answer_probe(
            session_id=started["session_id"], expected_version=1, expected_stage="awaiting_probe",
            selected_option="A", confidence="medium", elapsed_seconds=9, command_id="c_probe_replay_0001",
        )
        self.assertEqual(probed["stage"], "awaiting_transfer")
        self.assertEqual(probed["teaching"]["asset"]["record_id"], "T01")
        self.assertEqual(probed["transfer"]["record_id"], "V01")
        self.assertTrue(all(item["status"] == "unconfirmed" for item in probed["probe"]["evidence_updates"]))

        completed = service.answer_transfer(
            session_id=started["session_id"], expected_version=2, expected_stage="awaiting_transfer",
            selected_option="D", confidence="high", elapsed_seconds=14, command_id="c_transfer_replay_0001",
        )
        self.assertEqual(completed["stage"], "completed")
        self.assertEqual(completed["review_task"]["kind"], "delayed_retention")
        self.assertEqual(completed["review_task"]["due_on"], "2026-07-15")
        self.assertTrue(all(item["state_delta"]["commit_status"] == "committed" for item in completed["state_receipts"]))
        reopened = service.workspace()
        self.assertEqual(reopened["review_plan"], [completed["review_task"]])
        rendered = json.dumps({"entry": started, "probe": probed, "done": completed}, ensure_ascii=False)
        for private_key in ("correct_option", "answer_proof", "distractor_map", "candidate_evidence_map", "formalization", "selected_when"):
            self.assertNotIn(private_key, rendered)
        replay = service.replay(started["session_id"])
        self.assertTrue(replay["trace_verified"])
        self.assertEqual(replay["event_count"], 4)
        self.assertEqual(replay["timeline"][-1]["stage_after"], "completed")
        self.assertEqual(replay["timeline"][0]["result"]["entry"]["selected_option"], "B")
        self.assertEqual(replay["timeline"][1]["result"]["probe"]["selected_option"], "A")
        self.assertEqual(replay["timeline"][-1]["result"]["transfer"]["selected_option"], "D")

    def test_first_answer_command_replays_exactly_without_duplicate_observation(self) -> None:
        service = self.service()
        first = service.start(
            entry_record_id="D01",
            selected_option="B",
            confidence="low",
            elapsed_seconds=12,
            command_id="c_entry_retry_0001",
        )
        replay = service.start(
            entry_record_id="D01",
            selected_option="B",
            confidence="low",
            elapsed_seconds=12,
            command_id="c_entry_retry_0001",
        )
        self.assertEqual(replay, first)
        self.assertEqual(service.replay(first["session_id"])["event_count"], 1)
        with self.assertRaisesRegex(JudgmentSessionConflict, "different first answer"):
            service.start(
                entry_record_id="D01",
                selected_option="A",
                confidence="low",
                elapsed_seconds=12,
                command_id="c_entry_retry_0001",
            )

    def test_routing_diagnostic_reaches_the_inference_path(self) -> None:
        service = self.service()
        workspace = service.workspace()
        self.assertEqual({item["record_id"] for item in workspace["entry_items"]}, {"D01", "D02"})
        started = service.start(
            entry_record_id="D02",
            selected_option="A",
            confidence="medium",
            elapsed_seconds=10,
            command_id="c_entry_inference_0001",
        )
        self.assertEqual(started["stage"], "awaiting_probe")
        self.assertEqual(started["probe"]["record_id"], "P03")

    def test_prior_probe_observations_are_local_replay_context_not_a_diagnosis(self) -> None:
        service = self.service()
        first = service.start(
            entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=12,
            command_id="c_history_first_entry_0001",
        )
        service.answer_probe(
            session_id=first["session_id"], expected_version=1, expected_stage="awaiting_probe",
            selected_option="A", confidence="medium", elapsed_seconds=8,
            command_id="c_history_first_probe_0001",
        )
        # A similarly named historical cause from another authored pack
        # version is intentionally not eligible to influence this session.
        learner_store = LearnerStateStore(self.database)
        try:
            learner_store.append_hypothesis(
                {
                    "schema_version": "lumi.diagnosis-hypothesis.v1",
                    "hypothesis_id": "dxh_history_other_pack_version",
                    "namespace_id": "eval:judgment:test",
                    "evidence_origin": "evaluation_fixture",
                    "learner_id": "test-learner",
                    "episode_id": "episode_history_other_pack_version",
                    "skill_id": "xingce.judgment.conditional.language_direction",
                    "cause_id": "M-READ",
                    "status": "supported",
                    "pack_id": "lumi-conditional-reasoning-v0",
                    "pack_version": "0.0.9-other-draft",
                    "evidence_refs": [f"evt_{first['session_id']}_probe"],
                }
            )
        finally:
            learner_store.close()
        second = service.start(
            entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=11,
            command_id="c_history_second_entry_0001",
        )
        by_cause = {candidate["cause_id"]: candidate for candidate in second["candidate_causes"]}
        self.assertEqual(by_cause["M-DIR"]["status"], "unconfirmed")
        self.assertEqual(by_cause["M-DIR"]["prior_probe_observations"]["supported_count"], 1)
        self.assertEqual(by_cause["M-READ"]["prior_probe_observations"]["supported_count"], 0)
        self.assertIn("不能单独触发教学", by_cause["M-DIR"]["prior_probe_observations"]["usage"])

    def test_transfer_commit_resumes_after_the_observation_event_is_durable(self) -> None:
        service = self.service()
        started = service.start(
            entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=12
        )
        service.answer_probe(
            session_id=started["session_id"], expected_version=1, expected_stage="awaiting_probe",
            selected_option="A", confidence="medium", elapsed_seconds=9, command_id="c_probe_resume_0001",
        )
        original_commit = service._commit_transfer

        def interrupted_commit(*args: object, **kwargs: object) -> list[dict]:
            raise JudgmentSessionError("simulated interruption after durable observation")

        service._commit_transfer = interrupted_commit  # type: ignore[method-assign]
        try:
            with self.assertRaisesRegex(JudgmentSessionError, "simulated interruption"):
                service.answer_transfer(
                    session_id=started["session_id"], expected_version=2,
                    expected_stage="awaiting_transfer", selected_option="D", confidence="high",
                    elapsed_seconds=14, command_id="c_transfer_resume_0001",
                )
        finally:
            service._commit_transfer = original_commit  # type: ignore[method-assign]

        interrupted = service.replay(started["session_id"])
        self.assertEqual(interrupted["event_count"], 3)
        self.assertEqual(interrupted["timeline"][-1]["stage_after"], "committing_transfer")
        resumed = service.answer_transfer(
            session_id=started["session_id"], expected_version=2,
            expected_stage="awaiting_transfer", selected_option="D", confidence="high",
            elapsed_seconds=14, command_id="c_transfer_resume_0001",
        )
        self.assertEqual(resumed["stage"], "completed")
        self.assertEqual(service.replay(started["session_id"])["event_count"], 4)
        self.assertEqual(service.workspace()["review_plan"], [resumed["review_task"]])

    def test_failed_transfer_is_withheld_and_command_replay_is_exact(self) -> None:
        service = self.service()
        started = service.start(entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=12)
        service.answer_probe(
            session_id=started["session_id"], expected_version=1, expected_stage="awaiting_probe",
            selected_option="A", confidence="medium", elapsed_seconds=9, command_id="c_probe_failed_0001",
        )
        completed = service.answer_transfer(
            session_id=started["session_id"], expected_version=2, expected_stage="awaiting_transfer",
            selected_option="B", confidence="high", elapsed_seconds=14, command_id="c_transfer_failed_0001",
        )
        self.assertEqual(completed["review_task"]["kind"], "independent_retry")
        self.assertTrue(all(item["state_delta"]["mastery_delta"] == 0 for item in completed["state_receipts"]))
        self.assertTrue(all(item["state_delta"]["commit_status"] == "withheld" for item in completed["state_receipts"]))
        replayed = service.answer_transfer(
            session_id=started["session_id"], expected_version=2, expected_stage="awaiting_transfer",
            selected_option="B", confidence="high", elapsed_seconds=14, command_id="c_transfer_failed_0001",
        )
        self.assertEqual(replayed, completed)
        with self.assertRaises(JudgmentSessionConflict):
            service.answer_transfer(
                session_id=started["session_id"], expected_version=2, expected_stage="awaiting_transfer",
                selected_option="A", confidence="high", elapsed_seconds=14, command_id="c_transfer_failed_0001",
            )

    def test_stale_or_cross_origin_commands_cannot_change_an_evaluation_session(self) -> None:
        evaluation = self.service()
        started = evaluation.start(entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=12)
        with self.assertRaises(JudgmentSessionConflict):
            evaluation.answer_probe(
                session_id=started["session_id"], expected_version=0, expected_stage="awaiting_probe",
                selected_option="B", confidence="medium", elapsed_seconds=9, command_id="c_probe_stale_0001",
            )
        synthetic = self.service(origin="synthetic_isolated", namespace="synthetic:judgment:test")
        synthetic_started = synthetic.start(entry_record_id="D01", selected_option="B", confidence="low", elapsed_seconds=12)
        with self.assertRaisesRegex(Exception, "different evidence namespace"):
            synthetic.replay(started["session_id"])
        with self.assertRaisesRegex(Exception, "different evidence namespace"):
            evaluation.replay(synthetic_started["session_id"])

    def test_http_routes_are_closed_and_use_only_the_private_evaluation_origin(self) -> None:
        unavailable = SidecarApplication(self.database)
        server = create_server(unavailable, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, workspace = self.http(server, "GET", "/v1/judgment/workspace")
            self.assertEqual(status, 200)
            self.assertFalse(workspace["available"])
            status, error = self.http(
                server,
                "POST",
                "/v1/judgment/sessions",
                {"entry_record_id": "D01", "selected_option": "B", "confidence": "low", "elapsed_seconds": 8, "command_id": "c_http_unavailable_0001"},
            )
            self.assertEqual(status, 409)
            self.assertEqual(error["error"]["code"], "content_review_required")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        core = self.service()
        application = SidecarApplication(
            self.database,
            attempt_evidence_origin="evaluation_fixture",
            judgment_session_service=core,
        )
        server = create_server(application, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, error = self.http(
                server,
                "POST",
                "/v1/judgment/sessions",
                {"entry_record_id": "D01", "selected_option": "B", "confidence": "low", "elapsed_seconds": 8, "command_id": "c_http_leak_0001", "leak": True},
            )
            self.assertEqual(status, 400)
            self.assertEqual(error["error"]["code"], "invalid_body")
            status, started = self.http(
                server,
                "POST",
                "/v1/judgment/sessions",
                {"entry_record_id": "D01", "selected_option": "B", "confidence": "low", "elapsed_seconds": 8, "command_id": "c_http_entry_0001"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(started["stage"], "awaiting_probe")
            status, stale = self.http(
                server,
                "POST",
                f"/v1/judgment/sessions/{started['session_id']}/probe",
                {"expected_version": 0, "expected_stage": "awaiting_probe", "selected_option": "A", "confidence": "medium", "elapsed_seconds": 5, "command_id": "c_http_stale_0001"},
            )
            self.assertEqual(status, 409)
            self.assertEqual(stale["error"]["code"], "judgment_session_conflict")
            status, probed = self.http(
                server,
                "POST",
                f"/v1/judgment/sessions/{started['session_id']}/probe",
                {"expected_version": 1, "expected_stage": "awaiting_probe", "selected_option": "A", "confidence": "medium", "elapsed_seconds": 5, "command_id": "c_http_probe_0001"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(probed["stage"], "awaiting_transfer")
            status, completed = self.http(
                server,
                "POST",
                f"/v1/judgment/sessions/{started['session_id']}/transfer",
                {"expected_version": 2, "expected_stage": "awaiting_transfer", "selected_option": "D", "confidence": "high", "elapsed_seconds": 5, "command_id": "c_http_transfer_0001"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(completed["stage"], "completed")
            status, replay = self.http(server, "GET", f"/v1/judgment/sessions/{started['session_id']}/replay")
            self.assertEqual(status, 200)
            self.assertTrue(replay["trace_verified"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def http(server: object, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        port = server.server_address[1]  # type: ignore[attr-defined]
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"http://127.0.0.1:{port}{path}",
            method=method,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read().decode("utf-8"))
            finally:
                error.close()


if __name__ == "__main__":
    unittest.main()
