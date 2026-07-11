from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from hermes_service.api import create_server
from hermes_service.application import SidecarApplication


def opaque_public_id(prefix: str, label: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOP"
    digest = hashlib.sha256(label.encode("utf-8")).digest()[:20]
    encoded = "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}" for byte in digest
    )
    return f"{prefix}_{encoded}"


def test_command_id(label: str) -> str:
    if (
        label.startswith("c_")
        and len(label) == 42
        and all(character in "ABCDEFGHIJKLMNOP" for character in label[2:])
    ):
        return label
    return opaque_public_id("c", label)


class MutableDate:
    def __init__(self, value: date) -> None:
        self.value = value

    def __call__(self) -> date:
        return self.value


class ScheduleApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sidecar.sqlite3"
        self.clock = MutableDate(date(2026, 7, 11))
        self.application = SidecarApplication(
            self.database, today_provider=self.clock
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

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        base: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(
            (base or self.base) + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        try:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
        finally:
            response.close()

    def create_plan(
        self,
        command_id: str,
        *,
        budget: int = 60,
        raw_command_id: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        return self.request(
            "POST",
            "/v1/today-plans",
            {
                "plan_date": self.clock.value.isoformat(),
                "exam_date": (self.clock.value + timedelta(days=30)).isoformat(),
                "daily_budget_minutes": budget,
                "expected_version": 0,
                "command_id": (
                    command_id if raw_command_id else test_command_id(command_id)
                ),
            },
        )

    def start_attempt(
        self, suffix: str, *, initial_response: str = "A"
    ) -> dict[str, Any]:
        status, attempt = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": initial_response,
                "confidence": 0.6,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", f"schedule-attempt-{suffix}"),
            },
        )
        self.assertEqual(status, 201)
        return attempt

    def seed_attempt(
        self,
        suffix: str,
        *,
        initial_response: str = "A",
        verification_response: str = "A",
    ) -> dict[str, Any]:
        attempt = self.start_attempt(suffix, initial_response=initial_response)
        status, after_probe = self.request(
            "POST",
            attempt["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": attempt["state_version"],
                "expected_state": "awaiting_probe",
                "prompt_instance_id": attempt["probe"]["prompt_instance_id"],
                "response": "120÷100",
                "confidence": 0.8,
                "response_time_seconds": 15,
            },
        )
        self.assertEqual(status, 200)
        status, completed = self.request(
            "POST",
            after_probe["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": after_probe["state_version"],
                "expected_state": "awaiting_verification",
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
                "response": verification_response,
                "confidence": 0.9,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["state"], "completed")
        return completed

    def seed_due_plan(self, count: int = 1) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        attempts = [self.seed_attempt(str(index)) for index in range(count)]
        status, today = self.create_plan("create-seed-day")
        self.assertEqual(status, 201)
        self.assertEqual(today["empty_reason"], "no_task_due_today")
        self.clock.value += timedelta(days=1)
        status, due = self.create_plan("create-due-day")
        self.assertEqual(status, 201)
        self.assertEqual(len(due["tasks"]), count)
        return attempts, due

    def task_command(
        self,
        plan: dict[str, Any],
        task_id: str,
        action: str,
        expected_version: int,
        command_id: str,
        *,
        expected_task_version: int | None = None,
        postpone_until: str | None = None,
        base: str | None = None,
        raw_command_id: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        body: dict[str, Any] = {
            "action": action,
            "expected_version": expected_version,
            "expected_task_version": (
                expected_task_version
                if expected_task_version is not None
                else next(
                    item["version"]
                    for item in plan["tasks"]
                    if item["task_id"] == task_id
                )
            ),
            "command_id": (
                command_id if raw_command_id else test_command_id(command_id)
            ),
        }
        if postpone_until is not None:
            body["postpone_until"] = postpone_until
        return self.request(
            "POST",
            f"/v1/today-plans/{plan['plan_id']}/tasks/{task_id}/commands",
            body,
            base=base,
        )

    def test_no_evidence_is_empty_and_client_cannot_forge_dates(self) -> None:
        status, plan = self.create_plan("create-empty")
        self.assertEqual(status, 201)
        self.assertEqual(plan["status"], "empty")
        self.assertEqual(plan["empty_reason"], "no_recorded_evidence")
        self.assertEqual(plan["tasks"], [])
        self.assertFalse(plan["mastery_write_capability"])
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["count"], 0)
        _, replay = self.request("GET", f"/v1/today-plans/{plan['plan_id']}/replay")
        self.assertTrue(replay["trace_verified"])

        original_day = self.clock.value
        self.clock.value += timedelta(days=1)
        replay_status, replayed_receipt = self.request(
            "POST",
            "/v1/today-plans",
            {
                "plan_date": original_day.isoformat(),
                "exam_date": (original_day + timedelta(days=30)).isoformat(),
                "daily_budget_minutes": 60,
                "expected_version": 0,
                "command_id": test_command_id("create-empty"),
            },
        )
        self.assertEqual(replay_status, 201)
        self.assertEqual(replayed_receipt, plan)

        future = self.clock.value + timedelta(days=1)
        status, error = self.request(
            "POST",
            "/v1/today-plans",
            {
                "plan_date": future.isoformat(),
                "daily_budget_minutes": 30,
                "expected_version": 0,
                "command_id": test_command_id("future-plan"),
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "plan_date_mismatch")

        for index, invalid_date in enumerate(
            ("2026-7-12", "not-a-date", "2026-02-30")
        ):
            invalid_status, invalid = self.request(
                "POST",
                "/v1/today-plans",
                {
                    "plan_date": invalid_date,
                    "daily_budget_minutes": 30,
                    "expected_version": 0,
                    "command_id": test_command_id(f"invalid-plan-date-{index}"),
                },
            )
            self.assertEqual(invalid_status, 400)
            self.assertEqual(invalid["error"]["code"], "invalid_plan_date")

        phone_like_server_id = "review-13800138000abcdefabcdefa"
        self.assertEqual(len(phone_like_server_id.removeprefix("review-")), 24)
        missing_status, missing = self.request(
            "GET", f"/v1/review-schedule/{phone_like_server_id}/replay"
        )
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing["error"]["code"], "schedule_not_found")

    def test_incomplete_attempt_cannot_seed_a_review_task(self) -> None:
        self.start_attempt("incomplete")
        status, plan = self.create_plan("create-incomplete")
        self.assertEqual(status, 201)
        self.assertEqual(plan["status"], "empty")
        self.assertEqual(plan["empty_reason"], "no_recorded_evidence")
        self.assertEqual(plan["tasks"], [])
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["count"], 0)

    def test_new_writes_use_opaque_ids_and_legacy_32hex_trace_remains_readable(self) -> None:
        status, attempt = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.6,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(status, 201)
        self.assertRegex(attempt["run_id"], r"^r_[A-P]{40}$")
        status, after_probe = self.request(
            "POST",
            attempt["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": attempt["state_version"],
                "expected_state": "awaiting_probe",
                "prompt_instance_id": attempt["probe"]["prompt_instance_id"],
                "response": "120÷100",
                "confidence": 0.8,
                "response_time_seconds": 15,
            },
        )
        self.assertEqual(status, 200)
        status, completed = self.request(
            "POST",
            after_probe["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": after_probe["state_version"],
                "expected_state": "awaiting_verification",
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 15,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["state"], "completed")
        trace_status, trace = self.request("GET", attempt["links"]["trace"])
        self.assertEqual(trace_status, 200)
        self.assertTrue(trace["trace_verified"])
        dossier_status, dossier = self.request(
            "GET", attempt["links"]["misconception"]
        )
        self.assertEqual(dossier_status, 200)
        self.assertTrue(dossier["provenance"]["trace_verified"])

        for legacy_run_id in (
            "86e50149658661312a9e0b35abcdef12",
            "legacy-safe-run",
        ):
            with self.subTest(legacy_read_id=legacy_run_id):
                self.application.run_learning_loop("success", legacy_run_id)
                legacy_trace_status, legacy_trace = self.request(
                    "GET", f"/v1/runs/{legacy_run_id}/trace"
                )
                self.assertEqual(legacy_trace_status, 200)
                self.assertEqual(legacy_trace["run_id"], legacy_run_id)
                self.assertTrue(legacy_trace["trace_verified"])

        status, seed = self.create_plan("create-generated-run-seed")
        self.assertEqual(status, 201)
        self.assertEqual(seed["empty_reason"], "no_task_due_today")
        self.clock.value += timedelta(days=1)
        status, due = self.create_plan("create-generated-run-due")
        self.assertEqual(status, 201)
        self.assertEqual(len(due["tasks"]), 1)

    def test_task_contract_is_executable_authored_and_unconfirmed(self) -> None:
        completed_attempt = self.seed_attempt("contract")
        self.create_plan("create-contract-seed")
        self.clock.value += timedelta(days=1)
        status, plan = self.create_plan("create-contract-due")
        self.assertEqual(status, 201)
        task = plan["tasks"][0]
        self.assertEqual(task["state"], "scheduled")
        self.assertEqual(task["cause_confirmation_status"], "unconfirmed")
        self.assertIn(task["cause_label"], task["reason"])
        self.assertNotIn(task["cause_id"], task["reason"])
        self.assertEqual(task["definition_status"], "authored_engineering_estimate_unvalidated")
        self.assertEqual(
            task["activity_ref"]["fixture_id"],
            "xingce.data-analysis.growth-rate.synthetic-01",
        )
        self.assertEqual(task["activity_ref"]["launch_endpoint"], "/v1/attempts")
        self.assertEqual(
            task["activity_ref"]["novelty_status"],
            "same_fixture_retest_not_novel_item",
        )
        self.assertEqual(len(task["activity_ref"]["fixture_content_sha256"]), 64)
        self.assertTrue(
            task["evidence_refs"][0]["ref"].startswith(
                f"trace:{completed_attempt['run_id']}:event:"
            )
        )

        status, invalid = self.request(
            "POST",
            f"/v1/today-plans/{plan['plan_id']}/tasks/{task['task_id']}/commands",
            {
                "action": "accept",
                "action_date": self.clock.value.isoformat(),
                "expected_version": 1,
                "expected_task_version": task["version"],
                "command_id": test_command_id("forged-action-date"),
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid["error"]["code"], "invalid_body")

        status, stale = self.task_command(
            plan,
            task["task_id"],
            "accept",
            plan["version"],
            "wrong-task-version",
            expected_task_version=task["version"] + 99,
        )
        self.assertEqual(status, 409)
        self.assertEqual(stale["error"]["code"], "stale_task_version")
        _, unchanged = self.request("GET", plan["links"]["self"])
        self.assertEqual(unchanged["version"], plan["version"])
        self.assertEqual(unchanged["tasks"][0]["state"], "scheduled")

    def test_successful_transfer_prioritizes_delayed_retention_with_unconfirmed_context(self) -> None:
        self.seed_attempt("retention", verification_response="C")
        status, today = self.create_plan("create-retention-seed")
        self.assertEqual(status, 201)
        self.assertEqual(today["empty_reason"], "no_task_due_today")
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["count"], 1)
        task = schedule["items"][0]
        self.assertEqual(task["task_kind"], "delayed_retention")
        self.assertEqual(
            task["due_on"], (self.clock.value + timedelta(days=3)).isoformat()
        )
        self.assertEqual(task["schedule_window"]["policy_offset_days"], 3)
        self.assertNotIn("applied_offset_days", task["schedule_window"])
        self.assertIn("仍未确认", task["reason"])
        self.assertIsNone(task["cause_confirmation_status"])
        candidate_refs = [
            ref for ref in task["evidence_refs"] if ref["kind"] == "candidate_cause"
        ]
        self.assertGreaterEqual(len(candidate_refs), 2)
        self.assertTrue(
            all(ref["confirmation_status"] == "unconfirmed" for ref in candidate_refs)
        )
        self.assertIn(
            "verification_effective",
            {ref["semantic"] for ref in task["evidence_refs"]},
        )

        self.clock.value += timedelta(days=3)
        status, due = self.create_plan("create-retention-due")
        self.assertEqual(status, 201)
        self.assertEqual(due["tasks"][0]["task_id"], task["task_id"])

    def test_correct_first_failed_transfer_creates_generic_retry(self) -> None:
        self.seed_attempt(
            "correct-first-failed-transfer",
            initial_response="B",
            verification_response="A",
        )
        status, seed = self.create_plan("create-correct-first-seed")
        self.assertEqual(status, 201)
        self.assertEqual(seed["empty_reason"], "no_task_due_today")
        self.clock.value += timedelta(days=1)
        status, due = self.create_plan("create-correct-first-due")
        self.assertEqual(status, 201)
        task = due["tasks"][0]
        self.assertEqual(task["task_kind"], "independent_retry")
        self.assertIsNone(task["cause_id"])
        self.assertIsNone(task["cause_confirmation_status"])
        self.assertEqual(task["schedule_window"]["policy_offset_days"], 1)
        self.assertNotIn("applied_offset_days", task["schedule_window"])
        self.assertNotIn("候选错因", task["reason"])

    def test_cross_instance_idempotency_conflict_and_cas(self) -> None:
        _, plan = self.seed_due_plan(2)
        second_application = SidecarApplication(
            self.database, today_provider=self.clock
        )
        second_server = create_server(second_application, port=0)
        second_thread = threading.Thread(
            target=second_server.serve_forever, daemon=True
        )
        second_thread.start()
        second_base = f"http://127.0.0.1:{second_server.server_address[1]}"
        first_task, second_task = [item["task_id"] for item in plan["tasks"]]
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        self.task_command,
                        plan,
                        first_task,
                        "accept",
                        1,
                        "shared-accept-command",
                        base=base,
                    )
                    for base in (self.base, second_base)
                ]
                duplicate_results = [future.result(timeout=5) for future in futures]
            self.assertEqual([status for status, _ in duplicate_results], [200, 200])
            self.assertEqual(duplicate_results[0][1], duplicate_results[1][1])
            self.assertEqual(duplicate_results[0][1]["version"], 2)

            conflict_status, conflict = self.task_command(
                plan,
                first_task,
                "skip",
                1,
                "shared-accept-command",
            )
            self.assertEqual(conflict_status, 409)
            self.assertEqual(conflict["error"]["code"], "command_conflict")

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        self.task_command,
                        plan,
                        second_task,
                        "accept",
                        2,
                        command_id,
                        base=base,
                    )
                    for base, command_id in (
                        (self.base, "cas-command-one"),
                        (second_base, "cas-command-two"),
                    )
                ]
                cas_results = [future.result(timeout=5) for future in futures]
            self.assertEqual(sorted(status for status, _ in cas_results), [200, 409])
            rejected = next(payload for status, payload in cas_results if status == 409)
            self.assertEqual(rejected["error"]["code"], "stale_schedule_version")
        finally:
            second_server.shutdown()
            second_server.server_close()
            second_thread.join(timeout=2)

    def test_fresh_sidecars_create_one_exact_plan_receipt_under_concurrency(self) -> None:
        second_application = SidecarApplication(
            self.database, today_provider=self.clock
        )
        second_server = create_server(second_application, port=0)
        second_thread = threading.Thread(
            target=second_server.serve_forever, daemon=True
        )
        second_thread.start()
        second_base = f"http://127.0.0.1:{second_server.server_address[1]}"
        body = {
            "plan_date": self.clock.value.isoformat(),
            "exam_date": (self.clock.value + timedelta(days=30)).isoformat(),
            "daily_budget_minutes": 60,
            "expected_version": 0,
            "command_id": test_command_id("fresh-shared-create"),
        }
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        self.request,
                        "POST",
                        "/v1/today-plans",
                        body,
                        base=base,
                    )
                    for base in (self.base, second_base)
                ]
                results = [future.result(timeout=10) for future in futures]
            self.assertEqual([status for status, _ in results], [201, 201])
            self.assertEqual(results[0][1], results[1][1])
            self.assertEqual(results[0][1]["empty_reason"], "no_recorded_evidence")
        finally:
            second_server.shutdown()
            second_server.server_close()
            second_thread.join(timeout=2)

    def test_newer_plan_freezes_old_plan_under_sidecar_clock_skew(self) -> None:
        _, old_plan = self.seed_due_plan()
        old_task = old_plan["tasks"][0]
        newer_clock = MutableDate(self.clock.value + timedelta(days=1))
        newer_application = SidecarApplication(
            self.database, today_provider=newer_clock
        )
        newer_server = create_server(newer_application, port=0)
        newer_thread = threading.Thread(
            target=newer_server.serve_forever, daemon=True
        )
        newer_thread.start()
        newer_base = f"http://127.0.0.1:{newer_server.server_address[1]}"
        try:
            status, newer_plan = self.request(
                "POST",
                "/v1/today-plans",
                {
                    "plan_date": newer_clock.value.isoformat(),
                    "exam_date": (newer_clock.value + timedelta(days=30)).isoformat(),
                    "daily_budget_minutes": 60,
                    "expected_version": 0,
                    "command_id": test_command_id("create-newer-clock-plan"),
                },
                base=newer_base,
            )
            self.assertEqual(status, 201)
            self.assertEqual(newer_plan["tasks"][0]["task_id"], old_task["task_id"])

            status, rejected = self.task_command(
                old_plan,
                old_task["task_id"],
                "accept",
                old_plan["version"],
                "late-old-clock-accept",
            )
            self.assertEqual(status, 409)
            self.assertEqual(
                rejected["error"]["code"], "historical_plan_read_only"
            )

            current_task = newer_plan["tasks"][0]
            status, accepted = self.task_command(
                newer_plan,
                current_task["task_id"],
                "accept",
                newer_plan["version"],
                "current-clock-accept",
                base=newer_base,
            )
            self.assertEqual(status, 200)
            self.assertEqual(accepted["tasks"][0]["state"], "accepted")
        finally:
            newer_server.shutdown()
            newer_server.server_close()
            newer_thread.join(timeout=2)

    def test_newer_plan_prevents_stale_sidecar_from_creating_an_older_plan(self) -> None:
        newer_clock = MutableDate(self.clock.value + timedelta(days=1))
        newer_application = SidecarApplication(
            self.database, today_provider=newer_clock
        )
        newer_server = create_server(newer_application, port=0)
        newer_thread = threading.Thread(
            target=newer_server.serve_forever, daemon=True
        )
        newer_thread.start()
        newer_base = f"http://127.0.0.1:{newer_server.server_address[1]}"
        try:
            newer_body = {
                "plan_date": newer_clock.value.isoformat(),
                "exam_date": (newer_clock.value + timedelta(days=30)).isoformat(),
                "daily_budget_minutes": 60,
                "expected_version": 0,
                "command_id": test_command_id("newer-plan-first"),
            }
            status, newer_plan = self.request(
                "POST", "/v1/today-plans", newer_body, base=newer_base
            )
            self.assertEqual(status, 201)

            status, rejected = self.create_plan("stale-plan-after-newer")
            self.assertEqual(status, 409)
            self.assertEqual(
                rejected["error"]["code"], "historical_plan_read_only"
            )

            status, replayed = self.request(
                "POST", "/v1/today-plans", newer_body, base=newer_base
            )
            self.assertEqual(status, 201)
            self.assertEqual(replayed, newer_plan)
        finally:
            newer_server.shutdown()
            newer_server.server_close()
            newer_thread.join(timeout=2)

    def test_public_resurface_action_is_rejected_and_remains_automatic(self) -> None:
        _, plan = self.seed_due_plan()
        task = plan["tasks"][0]
        status, payload = self.task_command(
            plan,
            task["task_id"],
            "resurface",
            plan["version"],
            "public-resurface",
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_action")

    def test_overdue_count_is_after_one_task_per_run_deduplication(self) -> None:
        self.seed_attempt("overdue-dedup")
        self.clock.value += timedelta(days=5)
        status, plan = self.create_plan("create-overdue-dedup")
        self.assertEqual(status, 201)
        self.assertEqual(len(plan["tasks"]), 1)
        self.assertEqual(
            plan["basis"]["workload_guardrail"]["overdue_catch_up_count"],
            1,
        )
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["count"], 1)

    def test_repeated_skip_rotates_three_recovery_tasks_over_http(self) -> None:
        for index in range(3):
            self.seed_attempt(f"http-skip-rotation-{index}")
        status, seed = self.create_plan("http-skip-rotation-seed")
        self.assertEqual(status, 201)
        self.assertEqual(seed["empty_reason"], "no_task_due_today")
        self.clock.value += timedelta(days=1)
        status, plan = self.create_plan("http-skip-rotation-day-0")
        self.assertEqual(status, 201)
        surfaced: list[str] = []
        for index in range(3):
            self.assertEqual(len(plan["tasks"]), 1)
            task = plan["tasks"][0]
            surfaced.append(task["task_id"])
            status, _ = self.task_command(
                plan,
                task["task_id"],
                "skip",
                plan["version"],
                f"http-skip-rotation-command-{index}",
            )
            self.assertEqual(status, 200)
            if index < 2:
                self.clock.value += timedelta(days=1)
                status, plan = self.create_plan(
                    f"http-skip-rotation-day-{index + 1}"
                )
                self.assertEqual(status, 201)
        self.assertEqual(len(set(surfaced)), 3)

    def test_accepted_recovery_task_carries_into_next_day_http_plan(self) -> None:
        for index in range(3):
            self.seed_attempt(f"http-accepted-carry-{index}")
        status, seed = self.create_plan("http-accepted-carry-seed")
        self.assertEqual(status, 201)
        self.assertEqual(seed["empty_reason"], "no_task_due_today")
        self.clock.value += timedelta(days=1)
        status, plan = self.create_plan("http-accepted-carry-day-0")
        self.assertEqual(status, 201)
        task = plan["tasks"][0]
        status, accepted = self.task_command(
            plan,
            task["task_id"],
            "accept",
            plan["version"],
            "http-accepted-carry-command",
        )
        self.assertEqual(status, 200)
        self.clock.value += timedelta(days=1)
        status, tomorrow = self.create_plan("http-accepted-carry-day-1")
        self.assertEqual(status, 201)
        self.assertEqual(tomorrow["tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(tomorrow["tasks"][0]["state"], "accepted")
        status, completed = self.task_command(
            tomorrow,
            task["task_id"],
            "complete",
            tomorrow["version"],
            "http-complete-carried-command",
            expected_task_version=accepted["tasks"][0]["version"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            next(
                item["state"]
                for item in completed["tasks"]
                if item["task_id"] == task["task_id"]
            ),
            "completed",
        )
        self.assertEqual(completed["status"], "active")

    def test_low_budget_for_accepted_task_is_retryable_without_empty_plan_write(self) -> None:
        _, plan = self.seed_due_plan()
        task = plan["tasks"][0]
        status, accepted = self.task_command(
            plan,
            task["task_id"],
            "accept",
            plan["version"],
            "http-accept-before-budget-check",
        )
        self.assertEqual(status, 200)
        self.clock.value += timedelta(days=1)
        status, rejected = self.create_plan(
            "http-create-too-small-budget", budget=5
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            rejected["error"]["code"], "budget_below_accepted_commitment"
        )
        status, missing = self.request(
            "GET", f"/v1/today-plans/today-{self.clock.value.isoformat()}"
        )
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"]["code"], "schedule_not_found")

        status, retried = self.create_plan(
            "http-create-large-enough-budget", budget=60
        )
        self.assertEqual(status, 201)
        self.assertEqual(retried["tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(retried["tasks"][0]["state"], "accepted")
        status, completed = self.task_command(
            retried,
            task["task_id"],
            "complete",
            retried["version"],
            "http-complete-after-budget-retry",
            expected_task_version=accepted["tasks"][0]["version"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "completed")

    def test_skip_and_postpone_resurface_in_the_next_due_plan(self) -> None:
        _, plan = self.seed_due_plan(2)
        first_task, second_task = [item["task_id"] for item in plan["tasks"]]
        status, skipped = self.task_command(
            plan, first_task, "skip", 1, "http-skip"
        )
        self.assertEqual(status, 200)
        next_day = self.clock.value + timedelta(days=1)
        status, postponed = self.task_command(
            plan,
            second_task,
            "postpone",
            skipped["version"],
            "http-postpone",
            postpone_until=next_day.isoformat(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(postponed["status"], "handled")

        self.clock.value = next_day
        status, resurfaced = self.create_plan("create-resurfaced")
        self.assertEqual(status, 201)
        self.assertEqual(
            {item["task_id"] for item in resurfaced["tasks"]},
            {first_task, second_task},
        )
        self.assertTrue(all(item["state"] == "scheduled" for item in resurfaced["tasks"]))
        for task_id in (first_task, second_task):
            _, replay = self.request("GET", f"/v1/review-schedule/{task_id}/replay")
            self.assertEqual(replay["frames"][-1]["kind"], "task_resurfaced")

        stale_status, stale = self.task_command(
            plan,
            first_task,
            "accept",
            postponed["version"],
            "stale-old-plan-command",
            expected_task_version=3,
        )
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"]["code"], "historical_plan_read_only")
        _, current_schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(
            next(
                item["state"]
                for item in current_schedule["items"]
                if item["task_id"] == first_task
            ),
            "scheduled",
        )

    def test_historical_plan_is_read_only_even_when_task_version_is_unchanged(self) -> None:
        _, old_plan = self.seed_due_plan(1)
        task = old_plan["tasks"][0]
        self.clock.value += timedelta(days=1)
        status, current_plan = self.create_plan("create-current-overdue-plan")
        self.assertEqual(status, 201)
        self.assertEqual(current_plan["tasks"][0]["version"], task["version"])

        status, error = self.task_command(
            old_plan,
            task["task_id"],
            "accept",
            old_plan["version"],
            "historical-plan-command",
        )
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "historical_plan_read_only")
        _, schedule = self.request("GET", "/v1/review-schedule")
        self.assertEqual(schedule["items"][0]["state"], "scheduled")
        _, current = self.request("GET", current_plan["links"]["self"])
        self.assertEqual(current["tasks"][0]["state"], "scheduled")

    def test_user_marked_completion_never_changes_learning_trace_or_kt(self) -> None:
        attempts, plan = self.seed_due_plan(1)
        run_id = attempts[0]["run_id"]
        _, trace_before = self.request("GET", f"/v1/runs/{run_id}/trace")
        _, skills_before = self.request("GET", "/v1/skills/report")
        task_id = plan["tasks"][0]["task_id"]
        status, accepted = self.task_command(
            plan, task_id, "accept", 1, "http-accept-complete"
        )
        self.assertEqual(status, 200)
        status, completed = self.task_command(
            plan,
            task_id,
            "complete",
            accepted["version"],
            "http-mark-complete",
            expected_task_version=2,
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            completed["tasks"][0]["completion_semantics"],
            "user_marked_not_learning_evidence",
        )
        self.assertFalse(completed["mastery_write_capability"])
        _, trace_after = self.request("GET", f"/v1/runs/{run_id}/trace")
        _, skills_after = self.request("GET", "/v1/skills/report")
        self.assertEqual(trace_after, trace_before)
        self.assertEqual(skills_after, skills_before)
        _, replay = self.request("GET", f"/v1/today-plans/{plan['plan_id']}/replay")
        self.assertTrue(replay["trace_verified"])
        self.assertEqual(replay["frames"][-1]["state"]["status"], "completed")

    def test_schedule_commands_reject_claim_fields_and_sensitive_ids_without_writes(self) -> None:
        _, plan = self.seed_due_plan(1)
        task = plan["tasks"][0]
        _, before = self.request("GET", plan["links"]["self"])
        forbidden_fields = {
            "completion_evidence_ref": "forged",
            "mastery": 0.9,
            "peer_rate": 0.75,
            "forgetting_probability": 0.42,
        }
        for index, (field, value) in enumerate(forbidden_fields.items()):
            body = {
                "action": "accept",
                "expected_version": plan["version"],
                "expected_task_version": task["version"],
                "command_id": test_command_id(f"forbidden-field-{index}"),
                field: value,
            }
            status, error = self.request(
                "POST",
                f"/v1/today-plans/{plan['plan_id']}/tasks/{task['task_id']}/commands",
                body,
            )
            self.assertEqual(status, 400)
            self.assertEqual(error["error"]["code"], "invalid_body")

        sensitive_ids = [
            "cmd-13800138000",
            "cmd-138-0013-8000",
            "cmd-11010519491231002X",
            "cmd-110105-19491231-002X",
            "cmd-s" + "k-abcdefghijklmnopqrstuvwxyz",
            "cmd-s" + "k_live_abcdefghijklmnopqrstuvwxyz",
            "cmd-gh" + "p_abcdefghijklmnopqrstuvwxyz",
            "cmd-AKI" + "AIOSFODNN7EXAMPLE",
        ]
        for command_id in sensitive_ids:
            status, error = self.task_command(
                plan,
                task["task_id"],
                "accept",
                plan["version"],
                command_id,
                raw_command_id=True,
            )
            self.assertEqual(status, 400)
            self.assertEqual(error["error"]["code"], "invalid_command_id")
            self.assertNotIn(command_id, json.dumps(error, ensure_ascii=False))
        _, after = self.request("GET", plan["links"]["self"])
        self.assertEqual(after, before)

    def test_create_plan_rejects_nonopaque_command_ids_with_zero_writes(self) -> None:
        invalid_ids = (
            "legacy-command",
            "13800138000",
            "sk-" + "a" * 24,
            "ghp_" + "a" * 24,
            "github_pat_" + "A" * 82,
            "AIzaSy" + "A" * 33,
            "npm_" + "A" * 36,
            "xoxb-" + "A" * 24 + "-" + "B" * 24,
        )
        for command_id in invalid_ids:
            with self.subTest(command_id=command_id):
                status, error = self.create_plan(
                    command_id, raw_command_id=True
                )
                self.assertEqual(status, 400)
                self.assertEqual(error["error"]["code"], "invalid_command_id")
                self.assertNotIn(command_id, json.dumps(error, ensure_ascii=False))
                plan_status, missing = self.request(
                    "GET", f"/v1/today-plans/today-{self.clock.value.isoformat()}"
                )
                self.assertEqual(plan_status, 404)
                self.assertEqual(missing["error"]["code"], "schedule_not_found")
                _, schedule = self.request("GET", "/v1/review-schedule")
                self.assertEqual(schedule["count"], 0)

        status, plan = self.create_plan(
            opaque_public_id("c", "valid create plan command")
        )
        self.assertEqual(status, 201)
        self.assertEqual(plan["empty_reason"], "no_recorded_evidence")


if __name__ == "__main__":
    unittest.main()
