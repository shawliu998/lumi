from __future__ import annotations

from collections import Counter
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hermes_service.api import create_server
from hermes_service.application import ServiceError, SidecarApplication


MODULE_SCOPES = {
    "xingce.verbal.core": "言语理解",
    "xingce.judgment.core": "判断推理",
    "xingce.quantitative.core": "数量关系",
    "xingce.data-analysis.core": "资料分析",
}
MIXED_SCOPE_ID = "xingce.mixed.core"


class PracticeScopeHttpTests(unittest.TestCase):
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

    def submit_correct(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = payload["question"]
        trusted = self.application.smart_practice.questions[question["question_id"]]
        status, result = self.request(
            "POST",
            payload["links"]["answer"],
            {
                "question_id": question["question_id"],
                "question_version_id": question["question_version_id"],
                "answer": trusted["scoring"]["correct_option"],
            },
        )
        self.assertEqual(status, 200, result)
        return result

    def test_capabilities_expose_pinned_core_320_bank_and_five_scopes(self) -> None:
        status, payload = self.request("GET", "/v1/capabilities")
        self.assertEqual(status, 200, payload)
        bank = payload["smart_practice_bank"]
        self.assertEqual(bank["bank_id"], "lumi.xingce.core-320.practice-v3")
        self.assertEqual(bank["counts"]["questions"], 320)
        self.assertEqual(bank["counts"]["questions_per_module"], 80)
        self.assertEqual(bank["counts"]["module_scopes"], 4)
        self.assertEqual(bank["counts"]["scopes"], 5)
        self.assertEqual(
            {item["scope_id"] for item in bank["scopes"]},
            {*MODULE_SCOPES, MIXED_SCOPE_ID},
        )
        self.assertIn("scope-bound-core-320-practice-v3", payload["features"])

    def test_each_module_scope_starts_fixed_eight_and_is_answer_safe(self) -> None:
        protected = {
            "correct_option",
            "canonical_answer",
            "error_option_mappings",
            "signature_id",
            "cause_candidate_ids",
            "diagnostic_unit_id",
            "material_group_id",
            "evidence_family_id",
            "verification",
        }
        for scope_id, label in MODULE_SCOPES.items():
            with self.subTest(scope_id=scope_id):
                payload = self.start(scope_id)
                self.assertEqual(payload["session"]["scope_id"], scope_id)
                self.assertEqual(payload["session"]["target_count"], 8)
                self.assertEqual(payload["module_label"], label)
                self.assertEqual(payload["question"]["user_facing_type"], label)
                self.assertEqual(set(payload["question"]["options"]), set("ABCD"))
                self.assertTrue(payload["audit"]["trace_verified"])
                self.assertEqual(
                    payload["audit"]["content"]["bank_id"],
                    "lumi.xingce.core-320.practice-v3",
                )
                self.assertTrue(payload["audit"]["content"]["generated_sha256"])
                serialized = json.dumps(payload["question"], ensure_ascii=False).lower()
                self.assertTrue(protected.isdisjoint(payload["question"]))
                for field in protected:
                    self.assertNotIn(field, serialized)
                status, ended = self.request(
                    "POST",
                    payload["links"]["end"],
                    {"reason": "scope_contract_test_complete"},
                )
                self.assertEqual(status, 200, ended)

    def test_mixed_first_eight_rotate_across_all_four_modules(self) -> None:
        payload = self.start(MIXED_SCOPE_ID)
        labels = []
        question_ids = []
        for ordinal in range(1, 9):
            self.assertEqual(payload["question"]["ordinal"], ordinal)
            labels.append(payload["question"]["user_facing_type"])
            question_ids.append(payload["question"]["question_id"])
            payload = self.submit_correct(payload)
        self.assertEqual(payload["session"]["status"], "completed")
        self.assertEqual(payload["session"]["answered_count"], 8)
        self.assertEqual(Counter(labels), Counter({label: 2 for label in MODULE_SCOPES.values()}))
        self.assertEqual(len(set(question_ids)), 8)

    def test_restart_preserves_original_bank_version_and_scope(self) -> None:
        started = self.start("xingce.judgment.core")
        answered = self.submit_correct(started)
        restarted = SidecarApplication(self.database)
        resumed = restarted.practice_session(started["session"]["session_id"])
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["session"]["scope_id"], "xingce.judgment.core")
        self.assertEqual(resumed["session"]["content"], answered["session"]["content"])
        self.assertEqual(resumed["question"]["question_id"], answered["question"]["question_id"])

        status, trace = self.request("GET", answered["links"]["trace"])
        self.assertEqual(status, 200, trace)
        self.assertTrue(trace["trace_verified"])
        expected_content = answered["session"]["content"]
        self.assertTrue(trace["events"])
        self.assertTrue(all(event["payload"]["content"] == expected_content for event in trace["events"]))

    def test_module_then_mixed_share_one_trace_and_keep_exposure_history(self) -> None:
        first = self.start("xingce.verbal.core")
        exposed_question_ids = {first["question"]["question_id"]}
        first = self.submit_correct(first)
        exposed_question_ids.add(first["question"]["question_id"])
        status, ended = self.request(
            "POST",
            first["links"]["end"],
            {"reason": "switch_to_mixed"},
        )
        self.assertEqual(status, 200, ended)

        mixed = self.start(MIXED_SCOPE_ID)
        self.assertNotEqual(mixed["session"]["session_id"], first["session"]["session_id"])
        self.assertEqual(mixed["links"]["trace"], first["links"]["trace"])
        self.assertNotIn(mixed["question"]["question_id"], exposed_question_ids)
        self.assertNotIn("repeated_question_allowed_for_practice_only", mixed["audit"]["reason_codes"])

        status, trace = self.request("GET", mixed["links"]["trace"])
        self.assertEqual(status, 200, trace)
        starts = [
            event["payload"]["command"]
            for event in trace["events"]
            if event["kind"] == "practice_session_started"
        ]
        self.assertEqual(
            [command["scope_id"] for command in starts],
            ["xingce.verbal.core", MIXED_SCOPE_ID],
        )

        restarted = SidecarApplication(self.database)
        resumed = restarted.practice_session(mixed["session"]["session_id"])
        self.assertEqual(resumed["session"]["scope_id"], MIXED_SCOPE_ID)
        self.assertEqual(resumed["question"]["question_id"], mixed["question"]["question_id"])

    def test_unknown_or_ambiguous_scope_fails_closed(self) -> None:
        status, unknown = self.request(
            "POST",
            "/v1/practice-sessions",
            {"scope_id": "xingce.unknown.core"},
        )
        self.assertEqual(status, 404, unknown)
        self.assertEqual(unknown["error"]["code"], "scope_not_found")

        status, ambiguous = self.request(
            "POST",
            "/v1/practice-sessions",
            {
                "scope_id": "xingce.data-analysis.core",
                "unit_id": "xingce.data-analysis.direct-growth-rate",
            },
        )
        self.assertEqual(status, 400, ambiguous)
        self.assertEqual(ambiguous["error"]["code"], "ambiguous_practice_scope")

    def test_active_scope_is_idempotently_resumed_but_different_scope_conflicts(self) -> None:
        started = self.start("xingce.verbal.core")
        resumed = self.start("xingce.verbal.core")
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["session"]["session_id"], started["session"]["session_id"])
        self.assertEqual(resumed["question"]["question_id"], started["question"]["question_id"])

        status, conflict = self.request(
            "POST",
            "/v1/practice-sessions",
            {"scope_id": "xingce.judgment.core"},
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["error"]["code"], "active_practice_scope_conflict")

        status, legacy_conflict = self.request(
            "POST",
            "/v1/practice-sessions",
            {},
        )
        self.assertEqual(status, 409, legacy_conflict)
        self.assertEqual(
            legacy_conflict["error"]["code"],
            "active_practice_mode_conflict",
        )

    def test_two_app_instances_serialize_the_same_answer_and_trace_remains_replayable(self) -> None:
        started = self.start("xingce.quantitative.core")
        question = started["question"]
        trusted = self.application.smart_practice.questions[question["question_id"]]
        second_application = SidecarApplication(self.database)
        barrier = threading.Barrier(2)
        outcomes: list[tuple[int, str]] = []

        def submit(application: SidecarApplication) -> None:
            barrier.wait(timeout=5)
            try:
                result = application.submit_practice_answer(
                    started["session"]["session_id"],
                    question["question_id"],
                    question["question_version_id"],
                    trusted["scoring"]["correct_option"],
                )
            except ServiceError as exc:
                outcomes.append((exc.status, exc.code))
            else:
                outcomes.append((200, result["session"]["status"]))

        threads = [
            threading.Thread(target=submit, args=(application,))
            for application in (self.application, second_application)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(sum(status == 200 for status, _ in outcomes), 1)
        self.assertEqual(sum(status == 409 for status, _ in outcomes), 1)

        restarted = SidecarApplication(self.database)
        resumed = restarted.practice_session(started["session"]["session_id"])
        self.assertEqual(resumed["session"]["answered_count"], 1)
        self.assertIn("question", resumed)


if __name__ == "__main__":
    unittest.main()
