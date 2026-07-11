from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication, public_safe


class SidecarTests(unittest.TestCase):
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
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        merged = dict(headers or {})
        if data is not None:
            merged["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=merged, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            raw = response.read()
            payload = json.loads(raw) if raw else {}
            return response.status, payload, response.headers
        finally:
            response.close()

    def test_health_capabilities_and_42_safe_scenarios(self) -> None:
        status, health, _ = self.request("GET", "/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["local_only"])
        _, capabilities, _ = self.request("GET", "/v1/capabilities")
        self.assertEqual(capabilities["scenario_count"], 42)
        _, scenarios, _ = self.request("GET", "/v1/scenarios")
        self.assertEqual(scenarios["count"], 42)
        serialized = json.dumps(scenarios, ensure_ascii=False).lower()
        self.assertNotIn("/users/", serialized)
        self.assertNotIn("shenlun-agent-platform", serialized)
        self.assertNotIn("xingcetiku", serialized)

    def test_scenario_filters_cover_domain_and_mode(self) -> None:
        _, xingce, _ = self.request("GET", "/v1/scenarios?domain=xingce")
        _, offline, _ = self.request("GET", "/v1/scenarios?mode=offline")
        self.assertEqual(xingce["count"], 15)
        self.assertEqual(offline["count"], 14)

    def test_http_run_trace_replay_and_skill_report(self) -> None:
        status, run, headers = self.request(
            "POST",
            "/v1/runs",
            {"mode": "success", "run_id": "http-success"},
            {"Origin": "http://127.0.0.1:1420", "X-Request-ID": "client-request-1"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(headers["X-Request-ID"], "client-request-1")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:1420")
        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["trace_verified"])

        _, trace, _ = self.request("GET", run["links"]["trace"])
        _, replay, _ = self.request("GET", run["links"]["replay"])
        _, skills, _ = self.request("GET", "/v1/skills/report")
        self.assertEqual(trace["event_count"], 8)
        self.assertTrue(trace["trace_verified"])
        self.assertEqual(replay["frame_count"], 8)
        self.assertEqual(replay["frames"][-1]["state"]["status"], "completed")
        self.assertEqual(skills["skill_count"], 1)
        self.assertEqual(skills["items"][0]["verified_transfers"], 1)

    def test_all_three_learning_modes_complete(self) -> None:
        expected = {"success": True, "ambiguous": False, "offline": True}
        for mode, effective in expected.items():
            result = self.application.run_learning_loop(mode, f"direct-{mode}")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["verification_effective"], effective)
            self.assertTrue(result["trace_verified"])

    def test_real_attempt_responses_change_score_and_diagnosis(self) -> None:
        fixture_id = "xingce.data-analysis.growth-rate.synthetic-01"
        _, correct, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": fixture_id,
                "response": "B",
                "confidence": 0.9,
                "response_time_seconds": 18,
                "run_id": "http-attempt-correct",
            },
        )
        _, wrong, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": fixture_id,
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 31,
                "run_id": "http-attempt-wrong",
            },
        )
        self.assertTrue(correct["score"]["passed"])
        self.assertEqual(correct["diagnosis"]["hypotheses"], [])
        self.assertFalse(wrong["score"]["passed"])
        self.assertEqual(
            wrong["diagnosis"]["hypotheses"][0]["cause_id"],
            "denominator-current-base-confusion",
        )
        self.assertTrue(
            all(item["status"] == "unconfirmed_hypothesis" for item in wrong["diagnosis"]["hypotheses"])
        )
        self.assertEqual(wrong["diagnosis"]["semantics"], "ranked_unconfirmed_hypotheses")
        self.assertEqual(wrong["state"], "awaiting_probe")
        self.assertIsNone(wrong["teaching"])
        self.assertIsNone(wrong["verification"])
        self.assertIsNone(wrong["mastery_update"])
        self.assertEqual(wrong["steps"], 3)
        self.assertTrue(wrong["trace_verified"])
        self.assertIn("skill_report", wrong["links"])

    def test_staged_http_continuation_requires_probe_then_verification(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 31,
                "run_id": "http-staged-attempt",
            },
        )
        _, empty_skills, _ = self.request("GET", "/v1/skills/report")
        self.assertEqual(empty_skills["skill_count"], 0)

        out_of_order_status, out_of_order, _ = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": initial["state_version"],
                "expected_state": "awaiting_probe",
                "response": "C",
                "confidence": 0.9,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(out_of_order_status, 409)
        self.assertEqual(out_of_order["error"]["code"], "out_of_order")

        status, after_probe, _ = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": initial["state_version"],
                "expected_state": "awaiting_probe",
                "response": "分母应使用基期量 learner@example.com",
                "confidence": 0.75,
                "response_time_seconds": 24,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(after_probe["state"], "awaiting_verification")
        self.assertIsNotNone(after_probe["teaching"])
        self.assertEqual(after_probe["verification"]["status"], "awaiting_learner_response")
        self.assertIsNone(after_probe["mastery_update"])
        self.assertIsNone(after_probe["reflection"])
        _, still_empty_skills, _ = self.request("GET", "/v1/skills/report")
        self.assertEqual(still_empty_skills["skill_count"], 0)

        stale_status, stale, _ = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": initial["state_version"],
                "expected_state": "awaiting_probe",
                "response": "重复回答",
                "confidence": 0.7,
                "response_time_seconds": 10,
            },
        )
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"]["code"], "stale_version")

        status, completed, _ = self.request(
            "POST",
            after_probe["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": after_probe["state_version"],
                "expected_state": "awaiting_verification",
                "response": "C",
                "confidence": 0.9,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["state"], "completed")
        self.assertTrue(completed["verification"]["effective"])
        self.assertIsNotNone(completed["mastery_update"])
        self.assertEqual(completed["reflection"]["outcome"], "verified_transfer")
        _, skills, _ = self.request("GET", "/v1/skills/report")
        self.assertEqual(skills["skill_count"], 1)
        _, trace, _ = self.request("GET", completed["links"]["trace"])
        serialized = json.dumps(trace, ensure_ascii=False)
        self.assertNotIn("learner@example.com", serialized)
        self.assertIn("[EMAIL]", serialized)
        response_phases = [
            event["payload"]["phase"]
            for event in trace["events"]
            if event["kind"] == "learner_response_recorded"
        ]
        self.assertEqual(response_phases, ["probe", "verification"])

    def test_concurrent_same_version_continuations_accept_exactly_one(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 31,
                "run_id": "http-concurrent-attempt",
            },
        )
        barrier = threading.Barrier(3)

        def submit_probe(label: str) -> tuple[int, dict[str, Any]]:
            barrier.wait(timeout=3)
            status, payload, _ = self.request(
                "POST",
                initial["links"]["respond"],
                {
                    "phase": "probe",
                    "expected_version": initial["state_version"],
                    "expected_state": "awaiting_probe",
                    "response": f"基期量作分母 {label}",
                    "confidence": 0.8,
                    "response_time_seconds": 12,
                },
            )
            return status, payload

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit_probe, label) for label in ("one", "two")]
            barrier.wait(timeout=3)
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        rejected = next(payload for status, payload in results if status == 409)
        accepted = next(payload for status, payload in results if status == 200)
        self.assertEqual(rejected["error"]["code"], "stale_version")
        self.assertEqual(accepted["state"], "awaiting_verification")

    def test_attempt_trace_contains_redacted_response_evidence(self) -> None:
        raw = "A learner@example.com 13800138000"
        status, attempt, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": raw,
                "confidence": 0.4,
                "response_time_seconds": 50,
                "run_id": "http-attempt-redacted",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(attempt["response_evidence"]["redacted_text"], "A [EMAIL] [PHONE]")
        _, trace, _ = self.request("GET", attempt["links"]["trace"])
        serialized = json.dumps(trace, ensure_ascii=False)
        self.assertNotIn("learner@example.com", serialized)
        self.assertNotIn("13800138000", serialized)
        self.assertIn("[EMAIL]", serialized)

    def test_attempt_is_fail_closed_for_unknown_fields_fixture_and_values(self) -> None:
        base = {
            "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
            "response": "A",
            "confidence": 0.5,
            "response_time_seconds": 20,
        }
        for mutation, expected in (
            ({"mastery": 1.0}, "invalid_body"),
            ({"cause_ground_truth": "arithmetic"}, "invalid_body"),
            ({"confidence": 1.5}, "invalid_confidence"),
            ({"response_time_seconds": -1}, "invalid_response_time"),
            ({"fixture_id": "not-in-catalog"}, "fixture_not_found"),
        ):
            body = {**base, **mutation}
            status, payload, _ = self.request("POST", "/v1/attempts", body)
            self.assertGreaterEqual(status, 400)
            self.assertEqual(payload["error"]["code"], expected)

    def test_offline_attempt_records_zero_cloud_calls(self) -> None:
        status, result, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.offline-01",
                "response": "D",
                "confidence": 0.7,
                "response_time_seconds": 42,
                "run_id": "http-attempt-offline",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["execution"], {"connectivity": "offline", "cloud_calls": 0})

    def test_cors_rejects_non_allowlisted_origin(self) -> None:
        status, payload, headers = self.request(
            "GET", "/v1/health", headers={"Origin": "https://untrusted.example"}
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "origin_denied")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_structured_errors_carry_request_id_without_internal_paths(self) -> None:
        status, payload, headers = self.request(
            "GET", "/v1/runs/missing/trace", headers={"X-Request-ID": "missing-trace-1"}
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["request_id"], "missing-trace-1")
        self.assertEqual(headers["X-Request-ID"], "missing-trace-1")
        encoded = json.dumps(payload).lower()
        self.assertNotIn("/users/", encoded)
        self.assertNotIn("sqlite", encoded)

    def test_non_loopback_bind_is_impossible(self) -> None:
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            create_server(self.application, host="0.0.0.0", port=0)

    def test_public_safe_redacts_protected_paths(self) -> None:
        home = Path.home()
        value = public_safe(
            {
                "production": str(home / "Desktop" / "shenlun-agent-platform"),
                "bulk": str(home / "Documents" / "xingcetiku" / "data"),
                "normal": "xingce.data.growth",
            }
        )
        self.assertEqual(value["production"], "[REDACTED_LOCAL_PATH]")
        self.assertEqual(value["bulk"], "[REDACTED_LOCAL_PATH]")
        self.assertEqual(value["normal"], "xingce.data.growth")


if __name__ == "__main__":
    unittest.main()
