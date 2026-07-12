from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from hermes_service.api import create_server
from hermes_service.application import ServiceError, SidecarApplication, public_safe
from hermes_runtime.store import EventStore


def opaque_public_id(prefix: str, label: str) -> str:
    alphabet = "ABCDEFGHIJKLMNOP"
    digest = hashlib.sha256(label.encode("utf-8")).digest()[:20]
    encoded = "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}" for byte in digest
    )
    return f"{prefix}_{encoded}"


class SidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "sidecar.sqlite3"
        # ScenarioCatalog exercises are deterministic evaluation fixtures, not
        # production human learner activity.
        self.application = SidecarApplication(
            self.database,
            attempt_evidence_origin="evaluation_fixture",
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

    def evaluation_application(self) -> SidecarApplication:
        return SidecarApplication(
            self.database,
            attempt_evidence_origin="evaluation_fixture",
            review_commit_evidence_origins=frozenset({"evaluation_fixture"}),
        )

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

    def test_public_run_route_is_disabled_and_internal_evaluation_is_invisible(self) -> None:
        evaluation = self.application.run_learning_loop(
            "success", "internal-evaluation-fixture"
        )
        self.assertEqual(evaluation["status"], "completed")

        status, error, headers = self.request(
            "POST",
            "/v1/runs",
            {"mode": "success", "run_id": "http-evaluation-must-be-disabled"},
            {"Origin": "http://127.0.0.1:1420", "X-Request-ID": "client-request-1"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"]["code"], "route_not_found")
        self.assertEqual(headers["X-Request-ID"], "client-request-1")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:1420")

        _, capabilities, _ = self.request("GET", "/v1/capabilities")
        self.assertNotIn("run", capabilities["endpoints"])
        self.assertNotIn("learning_modes", capabilities)
        _, health, _ = self.request("GET", "/v1/health")
        _, skills, _ = self.request("GET", "/v1/skills/report")
        _, misconceptions, _ = self.request("GET", "/v1/misconceptions")
        self.assertEqual(health["run_count"], 0)
        self.assertEqual(skills["skill_count"], 0)
        self.assertEqual(misconceptions["count"], 0)
        dossier_status, dossier, _ = self.request(
            "GET", "/v1/misconceptions/internal-evaluation-fixture"
        )
        self.assertEqual(dossier_status, 404)
        self.assertEqual(dossier["error"]["code"], "run_not_found")

        today = date.today().isoformat()
        plan_status, plan, _ = self.request(
            "POST",
            "/v1/today-plans",
            {
                "plan_date": today,
                "daily_budget_minutes": 60,
                "expected_version": 0,
                "command_id": opaque_public_id("c", "synthetic invisible plan"),
            },
        )
        self.assertEqual(plan_status, 201)
        self.assertEqual(plan["empty_reason"], "no_recorded_evidence")
        self.assertEqual(plan["tasks"], [])

    def test_all_three_learning_modes_complete(self) -> None:
        expected = {"success": True, "ambiguous": False, "offline": True}
        for mode, effective in expected.items():
            result = self.application.run_learning_loop(mode, f"direct-{mode}")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["summary"]["verification_effective"], effective)
            self.assertTrue(result["trace_verified"])

    def test_real_continuation_commits_authored_transfer_across_all_domains(self) -> None:
        fixture_ids = (
            "xingce.data-analysis.growth-rate.synthetic-01",
            "shenlun.countermeasure.rural-bus.synthetic-01",
            "interview.emergency.power-outage.synthetic-01",
        )
        for index, fixture_id in enumerate(fixture_ids, start=1):
            with self.subTest(fixture_id=fixture_id):
                fixture = self.application.catalog.resolve(fixture_id)
                samples = fixture["independent_verify"]["samples"]
                run_id = opaque_public_id("r", f"cross-domain-transfer-{index}")
                initial = self.application.submit_attempt(
                    fixture_id,
                    samples["failing_response"],
                    0.5,
                    20,
                    run_id,
                )
                self.assertFalse(initial["score"]["passed"])
                after_probe = self.application.continue_attempt_session(
                    run_id,
                    "probe",
                    initial["state_version"],
                    "awaiting_probe",
                    initial["probe"]["prompt_instance_id"],
                    "我会按题干和材料逐项核对判断依据。",
                    0.6,
                    12,
                )
                completed = self.application.continue_attempt_session(
                    run_id,
                    "verification",
                    after_probe["state_version"],
                    "awaiting_verification",
                    after_probe["verification"]["prompt_instance_id"],
                    samples["passing_response"],
                    0.8,
                    25,
                )
                self.assertEqual(completed["state"], "completed")
                self.assertTrue(completed["verification"]["independently_verified"])
                self.assertTrue(completed["verification"]["effective"])
                self.assertIsNotNone(completed["mastery_update"])
                self.assertTrue(completed["trace_verified"])

    def test_negated_keyword_stuffing_never_passes_text_scoring_or_transfer(self) -> None:
        fixture_ids = [
            item["fixture_id"]
            for item in self.application.catalog.list(mode="success")
            if item["response_mode"] != "single_choice"
        ]
        self.assertEqual(len(fixture_ids), 9)
        for index, fixture_id in enumerate(fixture_ids, start=1):
            for attack_index, attack_prefix in enumerate(("不要", "必须取消", "应当避免"), start=1):
                with self.subTest(fixture_id=fixture_id, attack_prefix=attack_prefix):
                    fixture = self.application.catalog.resolve(fixture_id)
                    initial_attack = "；".join(
                        f"{attack_prefix}{criterion['keywords'][0]}"
                        for criterion in fixture["scoring"]["criteria"]
                    ) + "；以上全部不应做。"
                    condition = fixture["independent_verify"]["pass_condition"]
                    group_key = (
                        "required_dimensions"
                        if condition["scorer"] == "authored_dimensions_v1"
                        else "required_slots"
                    )
                    verification_attack = "；".join(
                        f"{attack_prefix}{group['aliases'][0]}" for group in condition[group_key]
                    ) + "；以上全部不应做。"
                    run_id = opaque_public_id(
                        "r", f"negation-guard-{index}-{attack_index}"
                    )
                    initial = self.application.submit_attempt(
                        fixture_id,
                        initial_attack,
                        0.8,
                        20,
                        run_id,
                    )
                    self.assertFalse(initial["score"]["passed"])
                    after_probe = self.application.continue_attempt_session(
                        run_id,
                        "probe",
                        initial["state_version"],
                        "awaiting_probe",
                        initial["probe"]["prompt_instance_id"],
                        "我还不能确定，需要回到题干逐项核对。",
                        0.4,
                        12,
                    )
                    completed = self.application.continue_attempt_session(
                        run_id,
                        "verification",
                        after_probe["state_version"],
                        "awaiting_verification",
                        after_probe["verification"]["prompt_instance_id"],
                        verification_attack,
                        0.8,
                        20,
                    )
                    self.assertFalse(completed["verification"]["effective"])
                    self.assertIsNone(completed["mastery_update"])
                    self.assertEqual(
                        completed["mastery_commit"]["status"], "withheld"
                    )
                    self.assertEqual(
                        completed["mastery_commit"]["reason_code"],
                        "failed_verification",
                    )
                    self.assertEqual(
                        completed["mastery_commit"]["mastery_delta"], 0
                    )

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
                "run_id": opaque_public_id("r", "http-attempt-correct"),
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
                "run_id": opaque_public_id("r", "http-attempt-wrong"),
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
                "run_id": opaque_public_id("r", "http-staged-attempt"),
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
                "prompt_instance_id": "http-staged-attempt:verification:1",
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
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
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
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
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
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
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
        # The deterministic ScenarioCatalog runs in an explicit evaluation
        # namespace, so it cannot project into the human learner report.
        self.assertEqual(skills["skill_count"], 0)
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
                "run_id": opaque_public_id("r", "http-concurrent-attempt"),
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
                    "prompt_instance_id": initial["probe"]["prompt_instance_id"],
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

    def test_two_sidecar_instances_share_database_level_continuation_cas(self) -> None:
        first = self.evaluation_application()
        second = self.evaluation_application()
        run_id = opaque_public_id("r", "two-sidecar-cas")
        initial = first.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "A",
            0.8,
            20,
            run_id,
        )
        barrier = threading.Barrier(3)

        def submit(application: SidecarApplication, label: str) -> tuple[str, Any]:
            barrier.wait(timeout=3)
            try:
                return (
                    "accepted",
                    application.continue_attempt_session(
                        run_id,
                        "probe",
                        initial["state_version"],
                        "awaiting_probe",
                        initial["probe"]["prompt_instance_id"],
                        f"基期作分母 {label}",
                        0.8,
                        10,
                    ),
                )
            except ServiceError as error:
                return "rejected", error.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit, application, label)
                for application, label in ((first, "one"), (second, "two"))
            ]
            barrier.wait(timeout=3)
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(status for status, _ in results), ["accepted", "rejected"])
        rejected_code = next(value for status, value in results if status == "rejected")
        self.assertEqual(rejected_code, "stale_version")
        accepted = next(value for status, value in results if status == "accepted")
        self.assertEqual(accepted["state"], "awaiting_verification")
        store = EventStore(self.database)
        self.assertTrue(store.verify(run_id))
        self.assertEqual(
            sum(
                event.kind == "learner_response_recorded"
                for event in store.events(run_id)
            ),
            1,
        )
        store.close()

    def test_two_sidecars_replay_the_same_assistance_command_idempotently(self) -> None:
        first = self.evaluation_application()
        second = self.evaluation_application()
        run_id = opaque_public_id("r", "two-sidecar-idempotency")
        command_id = opaque_public_id("c", "shared-assistance-command")
        initial = first.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "A",
            0.8,
            20,
            run_id,
        )
        barrier = threading.Barrier(3)

        def request_help(application: SidecarApplication) -> dict[str, Any]:
            barrier.wait(timeout=3)
            return application.deliver_assistance(
                run_id,
                "probe",
                initial["state_version"],
                "awaiting_probe",
                initial["probe"]["prompt_instance_id"],
                "next",
                4,
                command_id,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(request_help, app) for app in (first, second)]
            barrier.wait(timeout=3)
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(item["idempotent_replay"] for item in results), [False, True])
        self.assertEqual({item["state_version"] for item in results}, {initial["state_version"] + 1})
        store = EventStore(self.database)
        self.assertEqual(
            sum(
                event.kind == "assistance_delivered"
                for event in store.events(run_id)
            ),
            1,
        )
        self.assertTrue(store.verify(run_id))
        store.close()

    def test_progressive_assistance_is_persistent_ordered_and_idempotent(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 31,
                "run_id": opaque_public_id("r", "http-assistance-ladder"),
            },
        )
        dossier_status, initial_dossier, _ = self.request(
            "GET", initial["links"]["misconception"]
        )
        self.assertEqual(dossier_status, 404)
        self.assertEqual(initial_dossier["error"]["code"], "run_not_found")

        expected_actions = [
            "retry",
            "locate_evidence",
            "rule_hint",
            "analogous_example",
            "worked_step",
            "full_explanation",
        ]
        expected_weights = [1.0, 0.8, 0.65, 0.5, 0.3, 0.0]
        version = initial["state_version"]
        first_body = None
        for index, (expected_action, expected_weight) in enumerate(
            zip(expected_actions, expected_weights), start=1
        ):
            body = {
                "phase": "probe",
                "expected_version": version,
                "expected_state": "awaiting_probe",
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                "action": "next",
                "elapsed_time_seconds": index * 3,
                "command_id": opaque_public_id("c", f"assist-{index}"),
            }
            status, delivered, _ = self.request("POST", initial["links"]["assist"], body)
            self.assertEqual(status, 200)
            self.assertEqual(delivered["assistance"]["action"], expected_action)
            self.assertEqual(delivered["assistance"]["ordinal"], index)
            self.assertEqual(
                delivered["assistance"]["diagnostic_evidence_weight"], expected_weight
            )
            self.assertEqual(
                delivered["assistance"]["calibration_status"],
                "engineering_policy_unvalidated",
            )
            self.assertEqual(delivered["state"], "awaiting_probe")
            self.assertTrue(delivered["trace_verified"])
            version = delivered["state_version"]
            if index == 1:
                first_body = body

        assert first_body is not None
        replay_status, replayed, _ = self.request(
            "POST", initial["links"]["assist"], first_body
        )
        self.assertEqual(replay_status, 200)
        self.assertTrue(replayed["idempotent_replay"])
        self.assertEqual(replayed["state_version"], initial["state_version"] + 1)
        conflict_status, conflict, _ = self.request(
            "POST",
            initial["links"]["assist"],
            {**first_body, "elapsed_time_seconds": 99},
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict["error"]["code"], "command_conflict")

        exhausted_body = {
            "phase": "probe",
            "expected_version": version,
            "expected_state": "awaiting_probe",
            "prompt_instance_id": initial["probe"]["prompt_instance_id"],
            "action": "next",
            "elapsed_time_seconds": 30,
            "command_id": opaque_public_id("c", "assist-7"),
        }
        status, exhausted, _ = self.request(
            "POST", initial["links"]["assist"], exhausted_body
        )
        self.assertEqual(status, 409)
        self.assertEqual(exhausted["error"]["code"], "assistance_exhausted")

        _, after_probe, _ = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": version,
                "expected_state": "awaiting_probe",
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                "response": "120÷100",
                "confidence": 0.7,
                "response_time_seconds": 20,
            },
        )
        dossier_status, dossier, _ = self.request(
            "GET", initial["links"]["misconception"]
        )
        self.assertEqual(dossier_status, 404)
        self.assertEqual(dossier["error"]["code"], "run_not_found")
        _, empty_skills, _ = self.request("GET", "/v1/skills/report")
        self.assertEqual(empty_skills["skill_count"], 0)

        status, completed, _ = self.request(
            "POST",
            after_probe["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": after_probe["state_version"],
                "expected_state": "awaiting_verification",
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
                "response": "C",
                "confidence": 0.9,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(completed["verification"]["independently_verified"])
        self.assertTrue(completed["verification"]["effective"])
        self.assertIsNotNone(completed["mastery_update"])
        dossier_status, completed_dossier, _ = self.request(
            "GET", initial["links"]["misconception"]
        )
        self.assertEqual(dossier_status, 404)
        self.assertEqual(completed_dossier["error"]["code"], "run_not_found")

    def test_authored_probe_assessment_supports_and_refutes_without_confirming(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", "http-probe-assessment"),
            },
        )
        _, after_probe, _ = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": initial["state_version"],
                "expected_state": "awaiting_probe",
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                "response": "120÷100",
                "confidence": 0.6,
                "response_time_seconds": 12,
            },
        )
        self.assertEqual(after_probe["state"], "awaiting_verification")
        self.assertEqual(
            after_probe["teaching"]["based_on"]["original_top_hypothesis"],
            "denominator-current-base-confusion",
        )
        self.assertEqual(
            after_probe["teaching"]["based_on"]["instructional_focus"],
            "ratio-growth-confusion",
        )
        self.assertEqual(
            after_probe["teaching"]["based_on"]["focus_claim_status"],
            "supported_hypothesis",
        )
        store = EventStore(self.database)
        try:
            assessment = next(
                event.payload
                for event in reversed(store.events(initial["run_id"]))
                if event.kind == "probe_assessed"
            )
        finally:
            store.close()
        by_cause = {item["cause_id"]: item for item in assessment["assessments"]}
        self.assertEqual(
            by_cause["denominator-current-base-confusion"]["claim_status"],
            "refuted_hypothesis",
        )
        self.assertEqual(
            by_cause["ratio-growth-confusion"]["claim_status"],
            "supported_hypothesis",
        )
        serialized = json.dumps(assessment, ensure_ascii=False)
        self.assertNotIn("confirmed_cause", serialized)

    def test_assisted_verification_is_withheld_even_if_trace_contains_help(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", "http-assisted-verification"),
            },
        )
        _, after_probe, _ = self.request(
            "POST",
            initial["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": initial["state_version"],
                "expected_state": "awaiting_probe",
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                "response": "（120-100）÷100",
                "confidence": 0.8,
                "response_time_seconds": 14,
            },
        )
        forbidden_status, forbidden, _ = self.request(
            "POST",
            after_probe["links"]["assist"],
            {
                "phase": "verification",
                "expected_version": after_probe["state_version"],
                "expected_state": "awaiting_verification",
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
                "action": "next",
                "elapsed_time_seconds": 3,
                "command_id": opaque_public_id("c", "forbidden-verification-help"),
            },
        )
        self.assertEqual(forbidden_status, 409)
        self.assertEqual(
            forbidden["error"]["code"], "independent_verification_help_forbidden"
        )

        store = EventStore(self.database)
        state = store.load_state(initial["run_id"])
        current = store.events(initial["run_id"])[-1].seq
        injected = store.append_if_version(
            initial["run_id"],
            current,
            "assistance_delivered",
            {
                "schema_version": "hermes.assistance-event.v1",
                "phase": "verification",
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
                "ordinal": 1,
                "action": "retry",
                "diagnostic_evidence_weight": 1.0,
                "policy_version": "assistance-evidence-policy.v1",
                "state_after": state.to_dict(),
            },
        )
        store.close()
        status, completed, _ = self.request(
            "POST",
            after_probe["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": injected.seq,
                "expected_state": "awaiting_verification",
                "prompt_instance_id": after_probe["verification"]["prompt_instance_id"],
                "response": "C",
                "confidence": 0.9,
                "response_time_seconds": 20,
            },
        )
        self.assertEqual(status, 200)
        self.assertFalse(completed["verification"]["independently_verified"])
        self.assertIsNone(completed["verification"]["effective"])
        self.assertIsNone(completed["mastery_update"])
        self.assertEqual(
            completed["reflection"]["outcome"], "not_yet_mastered"
        )
        self.assertEqual(completed["mastery_commit"]["status"], "withheld")
        self.assertEqual(
            completed["mastery_commit"]["reason_code"],
            "assisted_verification",
        )
        _, skills, _ = self.request("GET", "/v1/skills/report")
        self.assertEqual(skills["skill_count"], 0)
        dossier_status, dossier, _ = self.request(
            "GET", after_probe["links"]["misconception"]
        )
        self.assertEqual(dossier_status, 404)
        self.assertEqual(dossier["error"]["code"], "run_not_found")

    def test_concurrent_assistance_requests_accept_exactly_one(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", "http-concurrent-assistance"),
            },
        )
        barrier = threading.Barrier(3)

        def request_help(command_id: str) -> tuple[int, dict[str, Any]]:
            barrier.wait(timeout=3)
            status, payload, _ = self.request(
                "POST",
                initial["links"]["assist"],
                {
                    "phase": "probe",
                    "expected_version": initial["state_version"],
                    "expected_state": "awaiting_probe",
                    "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                    "action": "next",
                    "elapsed_time_seconds": 4,
                    "command_id": opaque_public_id("c", command_id),
                },
            )
            return status, payload

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(request_help, value) for value in ("help-one", "help-two")]
            barrier.wait(timeout=3)
            results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        rejected = next(payload for status, payload in results if status == 409)
        self.assertEqual(rejected["error"]["code"], "stale_version")
        _, trace, _ = self.request("GET", initial["links"]["trace"])
        self.assertEqual(
            sum(event["kind"] == "assistance_delivered" for event in trace["events"]),
            1,
        )

    def test_assistance_contract_rejects_client_claims_without_writing(self) -> None:
        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.8,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", "http-assistance-invalid"),
            },
        )
        _, before, _ = self.request("GET", initial["links"]["trace"])
        base = {
            "phase": "probe",
            "expected_version": initial["state_version"],
            "expected_state": "awaiting_probe",
            "prompt_instance_id": initial["probe"]["prompt_instance_id"],
            "action": "next",
            "elapsed_time_seconds": 4,
            "command_id": opaque_public_id("c", "invalid-help"),
        }
        cases = (
            ({**base, "level": "full_explanation"}, 400, "invalid_body"),
            ({**base, "action": "full_explanation"}, 400, "invalid_action"),
            ({**base, "elapsed_time_seconds": True}, 400, "invalid_elapsed_time"),
            ({**base, "prompt_instance_id": "wrong:probe:1"}, 409, "prompt_mismatch"),
        )
        for body, expected_status, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                status, payload, _ = self.request(
                    "POST", initial["links"]["assist"], body
                )
                self.assertEqual(status, expected_status)
                self.assertEqual(payload["error"]["code"], expected_code)
        unknown_status, unknown, _ = self.request(
            "POST",
            "/v1/attempts/missing-run/assistance",
            {
                **base,
                "command_id": opaque_public_id("c", "unknown-run-help"),
            },
        )
        self.assertEqual(unknown_status, 404)
        self.assertEqual(unknown["error"]["code"], "run_not_found")
        _, after, _ = self.request("GET", initial["links"]["trace"])
        self.assertEqual(after["event_count"], before["event_count"])
        self.assertTrue(after["trace_verified"])

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
                "run_id": opaque_public_id("r", "http-attempt-redacted"),
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(attempt["response_evidence"]["redacted_text"], "A [EMAIL] [PHONE]")
        _, trace, _ = self.request("GET", attempt["links"]["trace"])
        serialized = json.dumps(trace, ensure_ascii=False)
        self.assertNotIn("learner@example.com", serialized)
        self.assertNotIn("13800138000", serialized)
        self.assertIn("[EMAIL]", serialized)

    def test_attempt_trace_redacts_secret_like_learner_text(self) -> None:
        raw_secret = "sk-" + "abcdefghijklmnopqrstuvwxyz" + "123456"
        status, attempt, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": f"A {raw_secret}",
                "confidence": 0.4,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", "secret-redaction"),
            },
        )
        self.assertEqual(status, 201)
        self.assertIn("[SECRET]", attempt["response_evidence"]["redacted_text"])
        self.assertIn("openai_key", attempt["response_evidence"]["redactions"])
        _, trace, _ = self.request("GET", attempt["links"]["trace"])
        _, replay, _ = self.request("GET", attempt["links"]["replay"])
        serialized = json.dumps([trace, replay], ensure_ascii=False)
        self.assertNotIn(raw_secret, serialized)
        self.assertIn("[SECRET]", serialized)

    def test_public_identifiers_reject_pii_secrets_and_unicode(self) -> None:
        base = {
            "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
            "response": "A",
            "confidence": 0.5,
            "response_time_seconds": 20,
        }
        for run_id in (
            "legacy-safe-run",
            "13800138000",
            "run-13800138000",
            "run-013800138000",
            "run-11010519491231002X",
            "run-" + "sk-" + "abcdefghijklmnopqrstuvwxyz" + "123456",
            "run-" + "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "123456",
            "github_pat_" + "A" * 82,
            "AIzaSy" + "A" * 33,
            "npm_" + "A" * 36,
            "xoxb-" + "A" * 24 + "-" + "B" * 24,
            "学习者一号",
            "run" + "x" * 94,
        ):
            with self.subTest(run_id=run_id):
                status, payload, _ = self.request(
                    "POST", "/v1/attempts", {**base, "run_id": run_id}
                )
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_run_id")

        store = EventStore(self.database)
        try:
            self.assertEqual(store.run_ids(), [])
        finally:
            store.close()

        valid_run_id = opaque_public_id("r", "safe command run")
        _, initial, _ = self.request(
            "POST", "/v1/attempts", {**base, "run_id": valid_run_id}
        )
        _, trace_before, _ = self.request("GET", initial["links"]["trace"])
        for command_id in (
            "legacy-command",
            "cmd-13800138000",
            "cmd-013800138000",
            "cmd-" + "sk-" + "abcdefghijklmnopqrstuvwxyz" + "123456",
            "cmd-" + "ghp_" + "abcdefghijklmnopqrstuvwxyz" + "123456",
            "github_pat_" + "A" * 82,
            "AIzaSy" + "A" * 33,
            "npm_" + "A" * 36,
            "xoxb-" + "A" * 24 + "-" + "B" * 24,
        ):
            with self.subTest(command_id=command_id):
                status, payload, _ = self.request(
                    "POST",
                    initial["links"]["assist"],
                    {
                        "phase": "probe",
                        "expected_version": initial["state_version"],
                        "expected_state": "awaiting_probe",
                        "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                        "action": "next",
                        "elapsed_time_seconds": 1,
                        "command_id": command_id,
                    },
                )
                self.assertEqual(status, 400)
                self.assertEqual(payload["error"]["code"], "invalid_command_id")

        _, trace_after, _ = self.request("GET", initial["links"]["trace"])
        self.assertEqual(trace_after, trace_before)

        status, generated, _ = self.request("POST", "/v1/attempts", base)
        self.assertEqual(status, 201)
        self.assertRegex(generated["run_id"], r"^r_[A-P]{40}$")

    def test_real_attempt_and_verification_use_service_utc_timestamps(self) -> None:
        before = datetime.now(timezone.utc)
        run_id = opaque_public_id("r", "real-observed-at")
        initial = self.application.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "A",
            0.7,
            20,
            run_id,
        )
        after_initial = datetime.now(timezone.utc)
        after_probe = self.application.continue_attempt_session(
            run_id,
            "probe",
            initial["state_version"],
            "awaiting_probe",
            initial["probe"]["prompt_instance_id"],
            "增长量除以基期量",
            0.7,
            10,
        )
        before_verification = datetime.now(timezone.utc)
        self.application.continue_attempt_session(
            run_id,
            "verification",
            after_probe["state_version"],
            "awaiting_verification",
            after_probe["verification"]["prompt_instance_id"],
            "C",
            0.8,
            12,
        )
        after_verification = datetime.now(timezone.utc)
        store = EventStore(self.database)
        state = store.load_state(run_id)
        store.close()
        initial_at = datetime.fromisoformat(
            state.artifacts["observe"][-1]["attempt"]["observed_at"]
        )
        verification_at = datetime.fromisoformat(
            state.artifacts["verify"][-1]["verification_attempt"]["observed_at"]
        )
        self.assertLessEqual(before, initial_at)
        self.assertLessEqual(initial_at, after_initial)
        self.assertLessEqual(before_verification, verification_at)
        self.assertLessEqual(verification_at, after_verification)
        self.assertNotEqual(initial_at.isoformat(), "2026-07-11T00:00:00+00:00")
        self.assertNotEqual(verification_at.isoformat(), "2026-07-11T00:05:00+00:00")

    def test_correct_initial_answer_does_not_hide_failed_transfer(self) -> None:
        initial = self.application.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "B",
            0.8,
            18,
            opaque_public_id("r", "correct-then-failed-transfer"),
        )
        after_probe = self.application.continue_attempt_session(
            initial["run_id"],
            "probe",
            initial["state_version"],
            "awaiting_probe",
            initial["probe"]["prompt_instance_id"],
            "增长量除以基期量",
            0.8,
            10,
        )
        completed = self.application.continue_attempt_session(
            initial["run_id"],
            "verification",
            after_probe["state_version"],
            "awaiting_verification",
            after_probe["verification"]["prompt_instance_id"],
            "D",
            0.7,
            15,
        )
        self.assertFalse(completed["verification"]["effective"])
        self.assertEqual(completed["mastery_commit"]["status"], "withheld")
        self.assertEqual(completed["mastery_commit"]["reason_code"], "failed_verification")
        self.assertEqual(completed["reflection"]["outcome"], "not_yet_mastered")
        self.assertEqual(completed["reflection"]["next_action"], "schedule_targeted_retry")

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

    def test_json_field_types_fail_closed_without_http_500(self) -> None:
        status, invalid_run, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.5,
                "response_time_seconds": 20,
                "run_id": 7,
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid_run["error"]["code"], "invalid_run_id")

        _, initial, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": "A",
                "confidence": 0.5,
                "response_time_seconds": 20,
                "run_id": opaque_public_id("r", "typed-continuation"),
            },
        )
        base = {
            "phase": "probe",
            "expected_version": initial["state_version"],
            "expected_state": "awaiting_probe",
            "prompt_instance_id": initial["probe"]["prompt_instance_id"],
            "response": "基期量作分母",
            "confidence": 0.6,
            "response_time_seconds": 10,
        }
        for mutation, expected_code in (
            ({"phase": []}, "invalid_phase"),
            ({"expected_state": []}, "invalid_state"),
        ):
            with self.subTest(expected_code=expected_code):
                case_status, payload, _ = self.request(
                    "POST", initial["links"]["respond"], {**base, **mutation}
                )
                self.assertEqual(case_status, 400)
                self.assertEqual(payload["error"]["code"], expected_code)

    def test_session_uses_immutable_fixture_snapshot_after_catalog_drift(self) -> None:
        first = self.evaluation_application()
        run_id = opaque_public_id("r", "immutable-fixture-session")
        initial = first.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "A",
            0.7,
            20,
            run_id,
        )
        second = self.evaluation_application()
        fixture = second.catalog._fixtures[
            "xingce.data-analysis.growth-rate.synthetic-01"
        ]
        original_prompt = fixture["teach"]["prompt"]
        fixture["teach"]["prompt"] = "DRIFT MUST NOT BE USED"
        result = second.continue_attempt_session(
            run_id,
            "probe",
            initial["state_version"],
            "awaiting_probe",
            initial["probe"]["prompt_instance_id"],
            "增长量除以基期量",
            0.8,
            12,
        )
        self.assertEqual(result["teaching"]["prompt"], original_prompt)
        self.assertNotEqual(result["teaching"]["prompt"], "DRIFT MUST NOT BE USED")

    def test_legacy_run_without_fixture_snapshot_is_skipped_by_report(self) -> None:
        source_run_id = opaque_public_id("r", "snapshot-source")
        initial = self.application.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "A",
            0.7,
            20,
            source_run_id,
        )
        store = EventStore(self.database)
        state = store.load_state(initial["run_id"])
        legacy_state = state.to_dict()
        legacy_state["run_id"] = "legacy-no-snapshot"
        legacy_state["context"].pop("fixture_content_sha256", None)
        # Simulate a pre-boundary historical human trace without replaying a
        # learner answer through the production endpoint.
        legacy_state["context"]["evidence_origin"] = "human_local_interactive"
        store.append(
            "legacy-no-snapshot",
            "legacy_state_imported",
            {"state_after": legacy_state},
        )
        store.close()

        with self.assertRaises(ServiceError) as raised:
            self.application.misconception_dossier("legacy-no-snapshot")
        self.assertEqual(raised.exception.code, "fixture_snapshot_unavailable")
        report = self.application.misconception_report()
        self.assertEqual(report["count"], 0)

    def test_processing_dossier_never_offers_an_unexecutable_prompt_write(self) -> None:
        run_id = opaque_public_id("r", "processing-dossier")
        initial = self.application.submit_attempt(
            "xingce.data-analysis.growth-rate.synthetic-01",
            "A",
            0.7,
            20,
            run_id,
        )
        store = EventStore(self.database)
        state = store.load_state(run_id)
        state.context["consumed_prompt_instances"] = [
            initial["probe"]["prompt_instance_id"]
        ]
        store.append_if_version(
            run_id,
            initial["state_version"],
            "learner_response_recorded",
            {
                "phase": "probe",
                "prompt_instance_id": initial["probe"]["prompt_instance_id"],
                "state_after": state.to_dict(),
            },
        )
        store.close()
        status, payload, _ = self.request("GET", initial["links"]["misconception"])
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "run_not_found")

    def test_offline_attempt_records_zero_cloud_calls(self) -> None:
        status, result, _ = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.offline-01",
                "response": "D",
                "confidence": 0.7,
                "response_time_seconds": 42,
                "run_id": opaque_public_id("r", "http-attempt-offline"),
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

    def test_cors_allows_the_loopback_vite_quality_assurance_origin(self) -> None:
        status, payload, headers = self.request(
            "GET", "/v1/health", headers={"Origin": "http://127.0.0.1:5173"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5173")

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
