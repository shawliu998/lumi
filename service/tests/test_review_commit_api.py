from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timezone
from pathlib import Path

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication, _is_valid_mastery_commit


class ReviewCommitApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.application = SidecarApplication(
            Path(self.temporary.name) / "sidecar.sqlite3",
            today_provider=date.today,
            planning_timezone=timezone.utc,
            attempt_evidence_origin="evaluation_fixture",
            # Explicit test-only injection: automated answers never masquerade
            # as human_local_interactive evidence.
            review_commit_evidence_origins=frozenset({"evaluation_fixture"}),
        )
        self.server = create_server(self.application, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            return response.status, json.loads(response.read())
        finally:
            response.close()

    def complete(self, transfer_response: str):
        status, catalog = self.request("GET", "/v1/product-activities")
        self.assertEqual(status, 200)
        activity = next(
            item for item in catalog["items"]
            if item["diagnostic_role"] == "first_answer"
        )
        status, attempt = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": activity["activity_id"],
                "response": "C",
                "confidence": 0.7,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(status, 201)
        status, probed = self.request(
            "POST",
            attempt["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": attempt["state_version"],
                "expected_state": "awaiting_probe",
                "prompt_instance_id": attempt["probe"]["prompt_instance_id"],
                "response": "先用现期量除以 1 加增长率",
                "confidence": 0.8,
                "response_time_seconds": 12,
            },
        )
        self.assertEqual(status, 200)
        status, completed = self.request(
            "POST",
            probed["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": probed["state_version"],
                "expected_state": "awaiting_verification",
                "prompt_instance_id": probed["verification"]["prompt_instance_id"],
                "response": transfer_response,
                "confidence": 0.8,
                "response_time_seconds": 15,
            },
        )
        self.assertEqual(status, 200)
        return completed

    def test_failed_transfer_withholds_mastery_and_commits_retry_once(self) -> None:
        completed = self.complete("A")
        self.assertEqual(completed["mastery_commit"]["status"], "withheld")
        self.assertEqual(
            completed["mastery_commit"]["reason_code"], "failed_verification"
        )
        self.assertEqual(completed["mastery_commit"]["mastery_delta"], 0)
        self.assertEqual(
            completed["mastery_commit"]["previous_mastery"],
            completed["mastery_commit"]["new_mastery"],
        )
        task = completed["review_schedule_commit"]["task"]
        self.assertEqual(task["task_kind"], "independent_retry")
        self.assertEqual(task["policy_offset_days"], 1)
        self.assertTrue(task["evidence_refs"])
        self.assertGreater(task["expected_duration_minutes"], 0)
        self.assertTrue(task["success_criterion"])
        self.assertTrue(task["skip_consequence"])

        status, replay = self.request(
            "POST", f"/v1/runs/{completed['run_id']}/review-commit", {}
        )
        self.assertEqual(status, 200)
        self.assertEqual(replay["task"]["task_id"], task["task_id"])
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["count"], 1)

    def test_successful_transfer_commits_mastery_and_retention_plus_three(self) -> None:
        completed = self.complete("B")
        self.assertEqual(completed["mastery_commit"]["status"], "committed")
        self.assertEqual(
            completed["mastery_commit"]["reason_code"],
            "verified_independent_transfer",
        )
        task = completed["review_schedule_commit"]["task"]
        self.assertEqual(task["task_kind"], "delayed_retention")
        self.assertEqual(task["policy_offset_days"], 3)

    def test_incomplete_run_and_closed_retry_body_fail_without_writing(self) -> None:
        _, catalog = self.request("GET", "/v1/product-activities")
        activity = next(
            item for item in catalog["items"]
            if item["diagnostic_role"] == "first_answer"
        )
        _, attempt = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": activity["activity_id"],
                "response": "C",
                "confidence": 0.7,
                "response_time_seconds": 20,
            },
        )
        status, error = self.request(
            "POST", f"/v1/runs/{attempt['run_id']}/review-commit", {}
        )
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "run_incomplete")
        status, error = self.request(
            "POST", f"/v1/runs/{attempt['run_id']}/review-commit", {"force": True}
        )
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "invalid_body")
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["count"], 0)

    def test_legacy_failed_commit_is_not_current_kt_evidence(self) -> None:
        self.assertFalse(
            _is_valid_mastery_commit(
                {
                    "commit_status": "committed",
                    "policy_version": "integration-learning-policy-v1",
                    "evidence": {
                        "verification_effective": False,
                        "independently_verified": True,
                    },
                }
            )
        )
        self.assertTrue(
            _is_valid_mastery_commit(
                {
                    "commit_status": "committed",
                    "policy_version": "integration-learning-policy-v1",
                    "evidence": {
                        "verification_effective": True,
                        "independently_verified": True,
                    },
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
