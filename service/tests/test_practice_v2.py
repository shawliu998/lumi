from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication
from hermes_service.practice_v2 import (
    PRACTICE_POLICY_VERSION,
    PRACTICE_SNAPSHOT_FORMAT,
)
from hermes_runtime.store import EventStore
from hermes_practice import PracticePolicyEngine, QuestionCandidate, QuestionRole


class SmartPracticeHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sidecar.sqlite3"
        self.application = SidecarApplication(self.database)
        self.server = create_server(self.application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
        finally:
            response.close()

    def start(self) -> dict[str, Any]:
        status, payload = self.request("POST", "/v1/practice-sessions", {})
        self.assertEqual(status, 201, payload)
        return payload

    def submit(self, payload: dict[str, Any], answer: str | None = None) -> dict[str, Any]:
        question = payload["question"]
        trusted = self.application.smart_practice.questions[question["question_id"]]
        selected = answer or trusted["scoring"]["correct_option"]
        status, result = self.request(
            "POST",
            payload["links"]["answer"],
            {
                "question_id": question["question_id"],
                "question_version_id": question["question_version_id"],
                "answer": selected,
            },
        )
        self.assertEqual(status, 200, result)
        return result

    def test_start_is_fixed_eight_answer_safe_and_auditable(self) -> None:
        payload = self.start()
        self.assertEqual(payload["schema_version"], "lumi.practice-session.v2")
        self.assertEqual(payload["session"]["target_count"], 8)
        self.assertEqual(payload["session"]["answered_count"], 0)
        self.assertTrue(payload["session"]["can_end_early"])
        self.assertEqual(payload["question"]["ordinal"], 1)
        self.assertEqual(set(payload["question"]["options"]), {"A", "B", "C", "D"})
        serialized = json.dumps(payload["question"], ensure_ascii=False).lower()
        for protected in (
            "correct_option",
            "canonical_answer",
            "error_option",
            "signature_id",
            "material_group_id",
            "evidence_family_id",
            "validation",
        ):
            self.assertNotIn(protected, serialized)
        self.assertTrue(payload["audit"]["trace_verified"])
        self.assertEqual(
            payload["audit"]["policy_version"],
            "lumi.smart-practice-policy.v2.1.0",
        )

        _, capabilities = self.request("GET", "/v1/capabilities")
        self.assertEqual(capabilities["smart_practice_package"]["target_count"], 8)
        self.assertIn("answer-only-smart-practice-v2", capabilities["features"])

    def test_answer_only_submission_replays_after_service_restart(self) -> None:
        started = self.start()
        answered = self.submit(started)
        self.assertTrue(answered["result"]["correct"])
        self.assertEqual(answered["result"]["feedback"]["level"], "A")
        self.assertEqual(answered["session"]["answered_count"], 1)
        self.assertEqual(answered["question"]["ordinal"], 2)

        restarted = SidecarApplication(self.database)
        resumed = restarted.practice_session(started["session"]["session_id"])
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["session"]["answered_count"], 1)
        self.assertEqual(resumed["question"]["question_id"], answered["question"]["question_id"])

        status, trace = self.request("GET", answered["links"]["trace"])
        self.assertEqual(status, 200)
        self.assertTrue(trace["trace_verified"])
        self.assertTrue(trace["semantic_replay_verified"])
        self.assertEqual(
            [event["kind"] for event in trace["events"]],
            [
                "practice_session_started",
                "practice_question_presented",
                "practice_answer_processed",
                "practice_question_presented",
            ],
        )
        trace_text = json.dumps(trace, ensure_ascii=False).lower()
        self.assertNotIn("correct_option", trace_text)
        self.assertNotIn("canonical_answer", trace_text)
        status, replay = self.request(
            "GET",
            answered["links"]["trace"].removesuffix("/trace") + "/replay",
        )
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["semantic_replay_verified"])

    def test_hash_valid_but_semantically_forged_scoring_is_rejected_on_replay(self) -> None:
        started = self.start()
        question_view = started["question"]
        trusted = self.application.smart_practice.questions[question_view["question_id"]]
        correct_answer = trusted["scoring"]["correct_option"]
        decision_id = started["audit"]["decision_id"]
        coordinator = self.application.smart_practice.legacy
        store = EventStore(self.database)
        try:
            store.append(
                coordinator.trace_run_id,
                "practice_answer_processed",
                {
                    "schema_version": "lumi.practice-command.v2",
                    "policy_version": PRACTICE_POLICY_VERSION,
                    "content": coordinator.content_descriptor,
                    "command": {
                        "operation": "answer_submitted",
                        "session_id": started["session"]["session_id"],
                        "decision_id": decision_id,
                        "question_id": question_view["question_id"],
                        "question_version": question_view["question_version_id"],
                        "answer": correct_answer,
                        "is_correct": False,
                        "error_signature_id": None,
                        "cause_candidates": [],
                        "hints_used": 0,
                        "response_time_seconds": None,
                        "at": started["session"]["started_at"],
                        "feedback_decision_id": "decision-forged",
                    },
                    "snapshot_format": PRACTICE_SNAPSHOT_FORMAT,
                    "state_after": {},
                },
            )
            self.assertTrue(store.verify(coordinator.trace_run_id))
        finally:
            store.close()

        status, rejected = self.request(
            "GET",
            started["links"]["self"],
        )
        self.assertEqual(status, 500, rejected)
        self.assertEqual(rejected["error"]["code"], "practice_replay_diverged")

    def test_get_recovers_an_accepted_answer_if_next_presentation_was_interrupted(self) -> None:
        started = self.start()
        question = started["question"]
        trusted = self.application.smart_practice.questions[question["question_id"]]
        coordinator = self.application.smart_practice.legacy
        with patch.object(
            coordinator,
            "_recommend_and_record",
            side_effect=RuntimeError("simulated interruption after durable answer"),
        ):
            status, interrupted = self.request(
                "POST",
                started["links"]["answer"],
                {
                    "question_id": question["question_id"],
                    "question_version_id": question["question_version_id"],
                    "answer": trusted["scoring"]["correct_option"],
                },
            )
        self.assertEqual(status, 500, interrupted)
        self.assertEqual(interrupted["error"]["code"], "internal_error")

        status, recovered = self.request("GET", started["links"]["self"])
        self.assertEqual(status, 200, recovered)
        self.assertEqual(recovered["session"]["answered_count"], 1)
        self.assertEqual(recovered["question"]["ordinal"], 2)
        self.assertTrue(recovered["audit"]["trace_verified"])

    def test_repeated_cross_family_signature_triggers_reviewed_tutorial(self) -> None:
        payload = self.start()
        first = self.submit(payload, "A")  # q01: ratio-without-minus-one
        self.assertEqual(first["result"]["feedback"]["level"], "B")
        self.assertNotIn("microtutorial", first["result"]["feedback"])

        second = self.submit(first)  # q02 correct, same family is not used as repetition
        third = self.submit(second, "D")  # q03: same signature, independent family/material
        feedback = third["result"]["feedback"]
        self.assertEqual(feedback["level"], "C")
        self.assertTrue(feedback["microtutorial"]["body"])
        self.assertTrue(feedback["microtutorial"]["points"])
        self.assertEqual(third["question"]["ordinal"], 4)

        _, trace = self.request("GET", third["links"]["trace"])
        operations = []
        for event in trace["events"]:
            command = event["payload"]["command"]
            operations.extend(
                item["operation"]
                for item in (
                    command["commands"]
                    if command["operation"] == "batch"
                    else [command]
                )
            )
        self.assertIn("tutorial_shown", operations)

    def test_optional_probe_answer_or_skip_consumes_one_of_eight_slots(self) -> None:
        payload = self.start()
        first = self.submit(payload, "C")  # ambiguous current-denominator mapping
        second = self.submit(first)
        third = self.submit(second, "A")
        feedback = third["result"]["feedback"]
        self.assertEqual(feedback["level"], "D")
        self.assertNotIn("question", third)
        probe = feedback["probe"]

        status, skipped = self.request(
            "POST",
            third["links"]["probe"],
            {"hypothesis_id": probe["hypothesis_id"], "answer": "__skip__"},
        )
        self.assertEqual(status, 200, skipped)
        self.assertTrue(skipped["probe_result"]["skipped"])
        self.assertEqual(skipped["session"]["answered_count"], 4)
        self.assertEqual(skipped["session"]["scored_count"], 3)
        self.assertEqual(skipped["question"]["ordinal"], 5)

        status, duplicate = self.request(
            "POST",
            third["links"]["probe"],
            {"hypothesis_id": probe["hypothesis_id"], "answer": "__skip__"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(duplicate["error"]["code"], "probe_not_pending")

    def test_probe_answer_and_immediate_tutorial_are_atomic_and_replayable(self) -> None:
        payload = self.start()
        first = self.submit(payload, "C")
        second = self.submit(first)
        third = self.submit(second, "A")
        probe = third["result"]["feedback"]["probe"]
        self.assertNotIn("cause", json.dumps(probe, ensure_ascii=False).lower())

        status, answered = self.request(
            "POST",
            third["links"]["probe"],
            {"hypothesis_id": probe["hypothesis_id"], "answer": "B"},
        )
        self.assertEqual(status, 200, answered)
        self.assertFalse(answered["probe_result"]["skipped"])
        self.assertTrue(answered["probe_result"]["microtutorial"]["body"])

        status, trace = self.request("GET", answered["links"]["trace"])
        self.assertEqual(status, 200, trace)
        self.assertTrue(trace["semantic_replay_verified"])
        command = next(
            event["payload"]["command"]
            for event in trace["events"]
            if event["kind"] == "practice_probe_processed"
        )
        self.assertEqual(command["operation"], "batch")
        self.assertEqual(
            [item["operation"] for item in command["commands"]],
            ["probe_submitted", "tutorial_shown"],
        )

    def test_service_presents_a_probe_carried_from_slot_eight_in_the_next_session(self) -> None:
        coordinator = self.application.smart_practice.legacy
        engine = PracticePolicyEngine()
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        engine.start_session("completed-before-probe", started_at=base)

        def candidate(index: int) -> QuestionCandidate:
            return QuestionCandidate(
                question_id=f"carried-probe-{index}",
                diagnostic_unit_id="xingce.data.growth.direct-rate",
                evidence_family_id=f"carried-family-{index}",
                material_group_id=f"carried-material-{index}",
                eligible_roles=frozenset({QuestionRole.PRACTICE}),
            )

        for index in range(1, 7):
            decision = engine.recommend_next(
                [candidate(index)],
                at=base + timedelta(minutes=index),
            )
            engine.submit_answer(
                decision.decision_id,
                answer="A",
                is_correct=True,
                at=base + timedelta(minutes=index, seconds=1),
            )
        for index in (7, 8):
            decision = engine.recommend_next(
                [candidate(index)],
                at=base + timedelta(minutes=index),
            )
            engine.submit_answer(
                decision.decision_id,
                answer="B",
                is_correct=False,
                error_signature_id="growth.current-as-denominator",
                cause_candidates=(
                    "cause.comparison-start-confusion",
                    "cause.ratio-growth-distinction",
                ),
                at=base + timedelta(minutes=index, seconds=1),
            )

        with (
            patch.object(coordinator, "_rehydrate", return_value=engine),
            patch.object(coordinator, "_append", return_value=None),
        ):
            next_session = coordinator.start()
            self.assertNotIn("question", next_session)
            probe = next_session["pending_probe"]
            skipped = coordinator.submit_probe(
                next_session["session"]["session_id"],
                probe["hypothesis_id"],
                "__skip__",
            )
        self.assertEqual(skipped["session"]["answered_count"], 1)
        self.assertEqual(skipped["question"]["ordinal"], 2)

    def test_session_completes_at_eight_and_accepts_early_exit(self) -> None:
        payload = self.start()
        for expected in range(1, 9):
            payload = self.submit(payload)
            self.assertEqual(payload["session"]["answered_count"], expected)
        self.assertEqual(payload["session"]["status"], "completed")
        self.assertNotIn("question", payload)
        self.assertEqual(payload["summary"]["facts"][0]["value"], "8 / 8")

        status, extra = self.request(
            "POST",
            payload["links"]["answer"],
            {"question_id": "anything", "question_version_id": "1.0.0", "answer": "A"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(extra["error"]["code"], "practice_session_closed")

        # A new fixed-eight session may be ended without fabricating completion.
        next_session = self.start()
        status, ended = self.request(
            "POST",
            next_session["links"]["end"],
            {"reason": "learner_ended_early"},
        )
        self.assertEqual(status, 200, ended)
        self.assertEqual(ended["session"]["status"], "ended_early")
        self.assertEqual(ended["session"]["answered_count"], 0)

    def test_practice_routes_fail_closed_for_unknown_fields_and_versions(self) -> None:
        status, invalid = self.request("POST", "/v1/practice-sessions", {"target_count": 10})
        self.assertEqual(status, 400)
        self.assertEqual(invalid["error"]["code"], "invalid_body")

        started = self.start()
        question = started["question"]
        status, mismatch = self.request(
            "POST",
            started["links"]["answer"],
            {
                "question_id": question["question_id"],
                "question_version_id": "9.9.9",
                "answer": "A",
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(mismatch["error"]["code"], "question_version_mismatch")

        status, blank_scope = self.request(
            "POST",
            "/v1/practice-sessions",
            {"scope_id": "   "},
        )
        self.assertEqual(status, 400, blank_scope)
        self.assertEqual(blank_scope["error"]["code"], "invalid_scope_id")

        status, wrong_type = self.request(
            "POST",
            started["links"]["answer"],
            {
                "question_id": 123,
                "question_version_id": question["question_version_id"],
                "answer": "A",
            },
        )
        self.assertEqual(status, 400, wrong_type)
        self.assertEqual(wrong_type["error"]["code"], "invalid_question_id")


if __name__ == "__main__":
    unittest.main()
