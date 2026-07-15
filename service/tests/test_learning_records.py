from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication
from hermes_runtime.store import EventStore


CORE_SCOPES = {
    "xingce.verbal.core",
    "xingce.judgment.core",
    "xingce.quantitative.core",
    "xingce.data-analysis.core",
    "xingce.mixed.core",
}
MODULE_IDS = CORE_SCOPES - {"xingce.mixed.core"}


class PracticeLearningRecordHttpTests(unittest.TestCase):
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
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        try:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
        finally:
            response.close()

    def start(self, scope_id: str) -> dict[str, Any]:
        status, payload = self.request(
            "POST",
            "/v1/practice-sessions",
            {"scope_id": scope_id},
        )
        self.assertEqual(status, 201, payload)
        return payload

    def answer(
        self,
        payload: dict[str, Any],
        *,
        correct: bool,
        response_time_seconds: float | None = None,
    ) -> dict[str, Any]:
        question_view = payload["question"]
        trusted = self.application.smart_practice.questions[
            question_view["question_id"]
        ]
        correct_option = trusted["scoring"]["correct_option"]
        answer = correct_option
        if not correct:
            answer = next(option for option in "ABCD" if option != correct_option)
        body: dict[str, Any] = {
            "question_id": question_view["question_id"],
            "question_version_id": question_view["question_version_id"],
            "answer": answer,
        }
        if response_time_seconds is not None:
            body["response_time_seconds"] = response_time_seconds
        status, result = self.request("POST", payload["links"]["answer"], body)
        self.assertEqual(status, 200, result)
        return result

    def complete_mixed_session(self) -> tuple[str, dict[str, Any]]:
        payload = self.start("xingce.mixed.core")
        session_id = payload["session"]["session_id"]
        for ordinal in range(8):
            payload = self.answer(
                payload,
                correct=ordinal != 0,
                response_time_seconds=10 + ordinal,
            )
        self.assertEqual(payload["session"]["status"], "completed")
        return session_id, payload

    def test_empty_views_are_explicit_and_capability_discoverable(self) -> None:
        status, capabilities = self.request("GET", "/v1/capabilities")
        self.assertEqual(status, 200, capabilities)
        for endpoint in (
            "practice_session_report",
            "practice_overview",
            "practice_history",
            "practice_wrong_questions",
            "practice_profile",
        ):
            self.assertIn(endpoint, capabilities["endpoints"])
        self.assertIn(
            "independent-evidence-practice-profile-v1",
            capabilities["features"],
        )
        record_capability = capabilities["practice_learning_records"]
        self.assertTrue(record_capability["read_only"])
        self.assertEqual(
            record_capability["schemas"],
            {
                "session_report": "lumi.practice-session-report.v1",
                "overview": "lumi.practice-overview.v1",
                "profile": "lumi.practice-profile.v1",
                "history": "lumi.practice-history.v1",
                "wrong_questions": "lumi.wrong-question-book.v1",
            },
        )

        status, overview = self.request("GET", "/v1/practice/overview")
        self.assertEqual(status, 200, overview)
        self.assertEqual(overview["schema_version"], "lumi.practice-overview.v1")
        self.assertEqual(overview["recent_sessions"], [])
        self.assertEqual(overview["wrong_question_preview"], [])
        self.assertEqual(overview["profile"]["overall"]["scored_attempt_count"], 0)
        self.assertIsNone(overview["profile"]["overall"]["accuracy"])
        self.assertEqual(
            {item["module_id"] for item in overview["profile"]["modules"]},
            MODULE_IDS,
        )
        self.assertIn(
            overview["recommendation"]["decision"]["recommended_scope_id"],
            CORE_SCOPES,
        )

        for path, schema in (
            ("/v1/practice/history", "lumi.practice-history.v1"),
            ("/v1/practice/wrong-questions", "lumi.wrong-question-book.v1"),
        ):
            status, payload = self.request("GET", path)
            self.assertEqual(status, 200, payload)
            self.assertEqual(payload["schema_version"], schema)
            self.assertEqual(payload["total"], 0)
            self.assertEqual(payload["count"], 0)
            self.assertEqual(payload["items"], [])

    def test_completed_session_rebuilds_report_wrong_book_history_and_profile(self) -> None:
        session_id, _ = self.complete_mixed_session()

        status, report = self.request(
            "GET", f"/v1/practice-sessions/{session_id}/report"
        )
        self.assertEqual(status, 200, report)
        self.assertEqual(report["schema_version"], "lumi.practice-session-report.v1")
        self.assertEqual(report["session"]["scope_id"], "xingce.mixed.core")
        self.assertEqual(report["metrics"]["scored_count"], 8)
        self.assertEqual(report["metrics"]["correct_count"], 7)
        self.assertEqual(report["metrics"]["incorrect_count"], 1)
        self.assertEqual(report["metrics"]["accuracy"], 0.875)
        self.assertEqual(report["metrics"]["recorded_response_time_count"], 8)
        self.assertEqual(report["metrics"]["average_response_time_seconds"], 13.5)
        self.assertEqual(
            {item["module_id"] for item in report["module_breakdown"]},
            MODULE_IDS,
        )
        self.assertTrue(report["audit"]["trace_verified"])
        self.assertTrue(report["audit"]["semantic_replay_verified"])

        status, wrong = self.request("GET", "/v1/practice/wrong-questions")
        self.assertEqual(status, 200, wrong)
        self.assertEqual(wrong["total"], 1)
        item = wrong["items"][0]
        self.assertEqual(item["review_state"], "needs_review")
        self.assertEqual(item["attempts"]["wrong_count"], 1)
        self.assertIn(item["answer_review"]["correct_option"], "ABCD")
        self.assertTrue(item["answer_review"]["explanation"])
        self.assertEqual(set(item["question"]["options"]), set("ABCD"))

        status, history = self.request(
            "GET", "/v1/practice/history?limit=1&offset=0&status=completed"
        )
        self.assertEqual(status, 200, history)
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["items"][0]["session_id"], session_id)
        self.assertEqual(history["items"][0]["accuracy"], 0.875)

        status, profile = self.request("GET", "/v1/practice/profile")
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["schema_version"], "lumi.practice-profile.v1")
        self.assertEqual(profile["overall"]["scored_attempt_count"], 8)
        self.assertEqual(profile["overall"]["correct_count"], 7)
        self.assertEqual(profile["overall"]["accuracy"], 0.875)
        self.assertEqual(profile["evidence_policy"]["mastery_claimed"], False)
        self.assertTrue(
            profile["evidence_policy"]["independent_attempts_only_for_evidence_status"]
        )

        status, overview = self.request("GET", "/v1/practice/overview")
        self.assertEqual(status, 200, overview)
        self.assertEqual(overview["recent_sessions"][0]["session_id"], session_id)
        self.assertEqual(len(overview["wrong_question_preview"]), 1)
        self.assertEqual(
            overview["recommendation"]["decision"]["recommended_scope_id"],
            "xingce.mixed.core",
        )
        self.assertIn(
            "no_cross_session_supported_weakness",
            overview["recommendation"]["decision"]["reason_codes"],
        )

    def test_read_models_survive_restart_without_creating_shadow_tables(self) -> None:
        session_id, _ = self.complete_mixed_session()
        before_report = self.application.practice_session_report(session_id)
        before_profile = self.application.practice_profile()

        restarted = SidecarApplication(self.database)
        self.assertEqual(restarted.practice_session_report(session_id), before_report)
        self.assertEqual(restarted.practice_profile(), before_profile)
        overview = restarted.practice_overview()
        self.assertTrue(overview["audit"]["semantic_replay_verified"])

        connection = sqlite3.connect(self.database)
        try:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            connection.close()
        self.assertEqual(tables, {"trace_events"})

    def test_optional_probe_is_scored_separately_but_not_profile_mastery_evidence(self) -> None:
        status, payload = self.request("POST", "/v1/practice-sessions", {})
        self.assertEqual(status, 201, payload)
        session_id = payload["session"]["session_id"]

        # The pinned legacy regression sequence creates an ambiguous repeated
        # signature on question three and therefore offers a skippable probe.
        first_question = payload["question"]
        status, payload = self.request(
            "POST",
            payload["links"]["answer"],
            {
                "question_id": first_question["question_id"],
                "question_version_id": first_question["question_version_id"],
                "answer": "C",
            },
        )
        self.assertEqual(status, 200, payload)
        payload = self.answer(payload, correct=True)
        third = payload["question"]
        status, payload = self.request(
            "POST",
            payload["links"]["answer"],
            {
                "question_id": third["question_id"],
                "question_version_id": third["question_version_id"],
                "answer": "A",
            },
        )
        self.assertEqual(status, 200, payload)
        probe = payload["result"]["feedback"]["probe"]
        status, payload = self.request(
            "POST",
            payload["links"]["probe"],
            {
                "hypothesis_id": probe["hypothesis_id"],
                "answer": next(iter(probe["options"])),
            },
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["session"]["answered_count"], 4)
        self.assertEqual(payload["session"]["scored_count"], 4)

        status, report = self.request(
            "GET", f"/v1/practice-sessions/{session_id}/report"
        )
        self.assertEqual(status, 200, report)
        self.assertEqual(report["metrics"]["probe_or_skip_count"], 1)
        self.assertEqual(report["metrics"]["scored_count"], 4)
        self.assertEqual(report["metrics"]["question_attempt_count"], 3)
        self.assertEqual(report["metrics"]["probe_scored_count"], 1)

        status, profile = self.request("GET", "/v1/practice/profile")
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["overall"]["scored_attempt_count"], 3)
        self.assertEqual(profile["evidence_policy"]["excluded_probe_count"], 1)
        self.assertFalse(profile["evidence_policy"]["mastery_claimed"])

    def test_invalid_filters_and_unknown_report_fail_closed(self) -> None:
        for path in (
            "/v1/practice/history?limit=0",
            "/v1/practice/history?offset=-1",
            "/v1/practice/history?status=created",
            "/v1/practice/history?scope_id=xingce.unknown.core",
            "/v1/practice/wrong-questions?state=pending",
            "/v1/practice/wrong-questions?module_id=xingce.mixed.core",
            "/v1/practice/overview?extra=1",
        ):
            with self.subTest(path=path):
                status, payload = self.request("GET", path)
                self.assertEqual(status, 400, payload)
                self.assertEqual(payload["error"]["code"], "invalid_query")

        status, payload = self.request(
            "GET", "/v1/practice-sessions/practice-does-not-exist/report"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["error"]["code"], "practice_session_not_found")

    def test_hash_valid_but_unreplayable_trace_cannot_feed_aggregates(self) -> None:
        started = self.start("xingce.verbal.core")
        coordinator = self.application.smart_practice.v3
        self.assertIsNotNone(coordinator)
        store = EventStore(self.database)
        try:
            store.append(
                coordinator.trace_run_id,
                "practice_forged_read_model_input",
                {
                    "schema_version": "lumi.practice-command.unsupported",
                    "policy_version": "lumi.smart-practice-policy.v2.1.0",
                    "content": coordinator.content_descriptor,
                    "command": {
                        "operation": "session_ended",
                        "session_id": started["session"]["session_id"],
                        "reason": "forged",
                        "at": started["session"]["started_at"],
                    },
                },
            )
            self.assertTrue(store.verify(coordinator.trace_run_id))
        finally:
            store.close()

        status, payload = self.request("GET", "/v1/practice/overview")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["error"]["code"], "practice_schema_unavailable")


if __name__ == "__main__":
    unittest.main()
