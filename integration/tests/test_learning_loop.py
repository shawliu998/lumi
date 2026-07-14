from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_domains import load_fixture_document
from hermes_integration.loop import (
    ContinuationError,
    IntegrationSession,
    SCENARIOS,
    Scenario,
    _select_teaching_variant,
    attempt_state_name,
    continue_attempt,
    load_fixture,
    run_attempt,
    run_scenario,
)
from hermes_integration.learning_support import assess_probe_response
from hermes_runtime.state import RunStatus
from hermes_runtime.store import EventStore


class IntegrationLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = load_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_case(self, name: str) -> tuple[IntegrationSession, object]:
        store = EventStore(Path(self.temporary.name) / f"{name}.sqlite3")
        session = IntegrationSession(self.fixture, SCENARIOS[name], store)
        return session, session.run(f"integration-{name}")

    def test_success_runs_domain_engine_runtime_and_verifies_transfer(self) -> None:
        session, result = self.run_case("success")
        self.assertEqual(result.state.status, RunStatus.COMPLETED)
        self.assertEqual(result.state.step_count, 7)
        artifacts = result.state.artifacts
        self.assertEqual(artifacts["observe"][-1]["adapter_version"], "deterministic-domain-adapters-v1")
        self.assertEqual(
            artifacts["diagnose"][-1]["engine_tool"],
            {"name": "hermes_explainable_learning_model", "version": "0.2.0"},
        )
        self.assertTrue(artifacts["verify"][-1]["verification"]["effective"])
        self.assertEqual(artifacts["reflect"][-1]["outcome"], "verified_transfer")
        self.assertTrue(session.store.verify(result.state.run_id))
        session.store.close()

    def test_ambiguous_case_selects_disambiguating_probe(self) -> None:
        session, result = self.run_case("ambiguous")
        diagnosis = result.state.artifacts["diagnose"][-1]
        self.assertGreaterEqual(diagnosis["diagnosis"]["uncertainty"], 0.80)
        self.assertEqual(diagnosis["decision"], "disambiguate_hypotheses")
        self.assertFalse(result.state.artifacts["verify"][-1]["verification"]["effective"])
        self.assertEqual(result.state.artifacts["reflect"][-1]["outcome"], "not_yet_mastered")
        session.store.close()

    def test_offline_case_has_no_fabricated_model_calls_and_replays(self) -> None:
        session, result = self.run_case("offline")
        events_before = session.store.events(result.state.run_id)
        calls = [call for event in events_before for call in event.payload.get("model_calls", [])]
        self.assertEqual(calls, [])
        self.assertEqual(result.state.context["execution_mode"], "offline")
        frames = session.runtime.replay(result.state.run_id)
        self.assertEqual(len(session.store.events(result.state.run_id)), len(events_before))
        self.assertEqual(frames[-1]["state"]["status"], "completed")
        self.assertTrue(session.store.verify(result.state.run_id))
        session.store.close()

    def test_every_mastery_delta_has_evidence_and_versions(self) -> None:
        for name in SCENARIOS:
            session, result = self.run_case(name)
            update = result.state.artifacts["update"][-1]
            self.assertIsInstance(update["mastery_delta"], float)
            self.assertTrue(update["evidence"]["initial_attempt_id"])
            self.assertTrue(update["evidence"]["verification_attempt_id"])
            self.assertEqual(update["model_version"]["mastery"], "bkt-pfa-rasch-ensemble-v1")
            self.assertEqual(update["model_version"]["verification"], "independent-transfer-check-v1")
            self.assertEqual(update["policy_version"], "integration-learning-policy-v2")
            session.store.close()

    def test_failed_independent_transfer_withholds_mastery_update(self) -> None:
        scenario = Scenario(
            name="failed-independent-transfer",
            initial_response="A",
            probe_response="增长率的分母应是基期量。",
            verification_response="A",
            independently_answered=True,
            verification_hints=0,
        )
        store = EventStore(Path(self.temporary.name) / "failed-independent.sqlite3")
        session = IntegrationSession(self.fixture, scenario, store)
        result = session.run("failed-independent")

        verify = result.state.artifacts["verify"][-1]
        update = result.state.artifacts["update"][-1]
        reflect = result.state.artifacts["reflect"][-1]
        self.assertTrue(verify["verification"]["independently_verified"])
        self.assertFalse(verify["verification"]["effective"])
        self.assertEqual(update["commit_status"], "withheld_failed_verification")
        self.assertEqual(update["previous_mastery"], update["new_mastery"])
        self.assertEqual(update["mastery_delta"], 0.0)
        self.assertEqual(reflect["outcome"], "not_yet_mastered")
        self.assertEqual(reflect["next_action"], "schedule_targeted_retry")
        session.store.close()

    def test_assisted_correct_transfer_withholds_mastery_update(self) -> None:
        scenario = Scenario(
            name="assisted-correct-transfer",
            initial_response="A",
            probe_response="增长率的分母应是基期量。",
            verification_response="C",
            independently_answered=False,
            verification_hints=1,
            verification_evidence_weight=0.0,
        )
        store = EventStore(Path(self.temporary.name) / "assisted-correct.sqlite3")
        session = IntegrationSession(self.fixture, scenario, store)
        result = session.run("assisted-correct")

        verify = result.state.artifacts["verify"][-1]
        update = result.state.artifacts["update"][-1]
        reflect = result.state.artifacts["reflect"][-1]
        self.assertTrue(verify["verification_attempt"]["correct"])
        self.assertFalse(verify["verification"]["independently_verified"])
        self.assertIsNone(verify["verification"]["effective"])
        self.assertEqual(update["commit_status"], "withheld_assisted_verification")
        self.assertEqual(update["previous_mastery"], update["new_mastery"])
        self.assertEqual(update["mastery_delta"], 0.0)
        self.assertEqual(reflect["outcome"], "not_yet_mastered")
        self.assertEqual(reflect["next_action"], "schedule_targeted_retry")
        session.store.close()

    def test_successful_independent_transfer_commits_mastery_update(self) -> None:
        store = EventStore(Path(self.temporary.name) / "successful-independent.sqlite3")
        session = IntegrationSession(self.fixture, SCENARIOS["success"], store)
        result = session.run("successful-independent")

        verify = result.state.artifacts["verify"][-1]
        update = result.state.artifacts["update"][-1]
        reflect = result.state.artifacts["reflect"][-1]
        self.assertTrue(verify["verification_attempt"]["correct"])
        self.assertTrue(verify["verification"]["independently_verified"])
        self.assertTrue(verify["verification"]["effective"])
        self.assertEqual(update["commit_status"], "committed")
        self.assertGreater(update["new_mastery"], update["previous_mastery"])
        self.assertGreater(update["mastery_delta"], 0.0)
        self.assertEqual(reflect["outcome"], "verified_transfer")
        self.assertEqual(reflect["next_action"], "schedule_delayed_retention")
        session.store.close()

    def test_trace_contains_all_seven_real_phase_artifacts(self) -> None:
        session, result = self.run_case("success")
        phase_events = [event for event in session.store.events(result.state.run_id) if event.kind == "phase_completed"]
        self.assertEqual(
            [event.payload["phase"] for event in phase_events],
            ["observe", "diagnose", "probe", "teach", "verify", "update", "reflect"],
        )
        self.assertEqual(phase_events[0].payload["output"]["score"]["fixture_id"], self.fixture["fixture_id"])
        self.assertIn("provenance", phase_events[4].payload["output"]["post_state"])
        session.store.close()

    def test_product_metadata_binds_real_distinct_transfer_item_and_target_skill(self) -> None:
        fixture = deepcopy(self.fixture)
        fixture["task"]["item_id"] = "real-first-item"
        fixture["task"]["content_signature"] = "first-content-hash"
        fixture["independent_verify"]["item_id"] = "real-transfer-item"
        fixture["independent_verify"]["content_signature"] = "transfer-content-hash"
        fixture["independent_verify"]["novelty_status"] = "unseen_parallel_item"
        fixture["kt_target_skill_id"] = fixture["skills"][1]["skill_id"]
        store = EventStore(Path(self.temporary.name) / "real-item-metadata.sqlite3")
        session = IntegrationSession(fixture, SCENARIOS["success"], store)
        result = session.run("real-item-metadata")

        observe = result.state.artifacts["observe"][-1]
        teach = result.state.artifacts["teach"][-1]
        verify = result.state.artifacts["verify"][-1]
        update = result.state.artifacts["update"][-1]
        self.assertEqual(observe["attempt"]["item_id"], "real-first-item")
        self.assertEqual(
            observe["attempt"]["evidence_features"]["content_signature"],
            "first-content-hash",
        )
        self.assertEqual(
            teach["independent_verification_item"],
            {
                "item_id": "real-transfer-item",
                "content_signature": "transfer-content-hash",
                "novelty_status": "unseen_parallel_item",
                "options": fixture["independent_verify"]["pass_condition"]["options"],
            },
        )
        self.assertNotIn(
            "correct_option", teach["independent_verification_item"]
        )
        self.assertEqual(verify["verification_attempt"]["item_id"], "real-transfer-item")
        self.assertEqual(
            verify["verification_attempt"]["evidence_features"]["novelty_status"],
            "unseen_parallel_item",
        )
        self.assertEqual(update["skill_id"], fixture["skills"][1]["skill_id"])
        session.store.close()

    def test_real_responses_drive_distinct_score_and_diagnosis_paths(self) -> None:
        correct_session, correct = run_attempt(
            self.fixture, "B", 0.9, 18.0, Path(self.temporary.name) / "correct.sqlite3", run_id="real-correct"
        )
        wrong_session, wrong = run_attempt(
            self.fixture, "A", 0.8, 31.0, Path(self.temporary.name) / "wrong.sqlite3", run_id="real-wrong"
        )
        correct_observe = correct.state.artifacts["observe"][-1]
        wrong_observe = wrong.state.artifacts["observe"][-1]
        self.assertTrue(correct_observe["score"]["passed"])
        self.assertFalse(wrong_observe["score"]["passed"])
        self.assertEqual(correct.state.artifacts["diagnose"][-1]["diagnosis"]["hypotheses"], [])
        wrong_hypotheses = wrong.state.artifacts["diagnose"][-1]["diagnosis"]["hypotheses"]
        self.assertGreater(len(wrong_hypotheses), 0)
        self.assertEqual(wrong_hypotheses[0]["cause_id"], "denominator-current-base-confusion")
        self.assertEqual(attempt_state_name(wrong.state), "awaiting_probe")
        self.assertEqual(wrong.state.step_count, 3)
        self.assertNotIn("teach", wrong.state.artifacts)
        self.assertNotIn("update", wrong.state.artifacts)
        correct_session.store.close()
        wrong_session.store.close()

    def test_real_session_requires_probe_then_verification_before_mastery_update(self) -> None:
        database = Path(self.temporary.name) / "staged.sqlite3"
        initial_session, initial = run_attempt(
            self.fixture, "A", 0.8, 31.0, database, run_id="staged-real"
        )
        initial_version = initial_session.store.events(initial.state.run_id)[-1].seq
        self.assertEqual(attempt_state_name(initial.state), "awaiting_probe")
        self.assertNotIn("teach", initial.state.artifacts)
        initial_session.store.close()

        probe_session, after_probe = continue_attempt(
            self.fixture,
            database,
            "staged-real",
            phase="probe",
            expected_version=initial_version,
            expected_state="awaiting_probe",
            prompt_instance="staged-real:probe:1",
            response="增长率分母使用基期量。",
            confidence=0.75,
            response_time_seconds=24,
        )
        probe_version = probe_session.store.events("staged-real")[-1].seq
        self.assertEqual(attempt_state_name(after_probe.state), "awaiting_verification")
        self.assertIn("teach", after_probe.state.artifacts)
        self.assertNotIn("verify", after_probe.state.artifacts)
        self.assertNotIn("update", after_probe.state.artifacts)
        self.assertTrue(after_probe.state.artifacts["teach"][-1]["independent_verification_prompt"])
        probe_session.store.close()

        verification_session, completed = continue_attempt(
            self.fixture,
            database,
            "staged-real",
            phase="verification",
            expected_version=probe_version,
            expected_state="awaiting_verification",
            prompt_instance="staged-real:verification:1",
            response="C",
            confidence=0.9,
            response_time_seconds=20,
        )
        self.assertEqual(attempt_state_name(completed.state), "completed")
        self.assertTrue(completed.state.artifacts["verify"][-1]["verification"]["effective"])
        self.assertIn("update", completed.state.artifacts)
        self.assertIn("reflect", completed.state.artifacts)
        response_events = [
            event.payload["phase"]
            for event in verification_session.store.events("staged-real")
            if event.kind == "learner_response_recorded"
        ]
        self.assertEqual(response_events, ["probe", "verification"])
        verification_session.store.close()

    def test_continuation_rejects_out_of_order_and_stale_versions(self) -> None:
        database = Path(self.temporary.name) / "ordering.sqlite3"
        session, initial = run_attempt(self.fixture, "A", 0.8, 31, database, run_id="ordering-real")
        version = session.store.events("ordering-real")[-1].seq
        session.store.close()
        with self.assertRaisesRegex(ContinuationError, "not accepted"):
            continue_attempt(
                self.fixture,
                database,
                "ordering-real",
                phase="verification",
                expected_version=version,
                expected_state="awaiting_probe",
                prompt_instance="ordering-real:verification:1",
                response="C",
                confidence=0.9,
                response_time_seconds=20,
            )
        probe_session, _ = continue_attempt(
            self.fixture,
            database,
            "ordering-real",
            phase="probe",
            expected_version=version,
            expected_state="awaiting_probe",
            prompt_instance="ordering-real:probe:1",
            response="基期量作分母",
            confidence=0.8,
            response_time_seconds=10,
        )
        probe_session.store.close()
        with self.assertRaisesRegex(ContinuationError, "expected_version"):
            continue_attempt(
                self.fixture,
                database,
                "ordering-real",
                phase="probe",
                expected_version=version,
                expected_state="awaiting_probe",
                prompt_instance="ordering-real:probe:1",
                response="重复回答",
                confidence=0.8,
                response_time_seconds=10,
            )

    def test_continuation_rejects_fixture_drift_without_writing(self) -> None:
        database = Path(self.temporary.name) / "fixture-drift.sqlite3"
        session, initial = run_attempt(
            self.fixture,
            "A",
            0.8,
            31,
            database,
            run_id="fixture-drift",
        )
        version = session.store.events("fixture-drift")[-1].seq
        session.store.close()

        changed_fixture = deepcopy(self.fixture)
        changed_fixture["teach"]["prompt"] = "changed teaching content"
        with self.assertRaises(ContinuationError) as rejected:
            continue_attempt(
                changed_fixture,
                database,
                "fixture-drift",
                phase="probe",
                expected_version=version,
                expected_state="awaiting_probe",
                prompt_instance="fixture-drift:probe:1",
                response="基期量作分母",
                confidence=0.8,
                response_time_seconds=10,
            )
        self.assertEqual(rejected.exception.code, "fixture_version_mismatch")

        reopened = EventStore(database)
        try:
            self.assertEqual(reopened.events("fixture-drift")[-1].seq, version)
            self.assertTrue(reopened.verify("fixture-drift"))
        finally:
            reopened.close()

    def test_store_is_closed_when_continuation_fails_after_response_append(self) -> None:
        database = Path(self.temporary.name) / "continuation-close.sqlite3"
        session, initial = run_attempt(
            self.fixture,
            "A",
            0.8,
            31,
            database,
            run_id="continuation-close",
        )
        version = session.store.events("continuation-close")[-1].seq
        session.store.close()

        opened = []

        class TrackingEventStore(EventStore):
            def __init__(self, path: str | Path = ":memory:") -> None:
                self.was_closed = False
                super().__init__(path)
                opened.append(self)

            def close(self) -> None:
                self.was_closed = True
                super().close()

        with (
            patch("hermes_integration.loop.EventStore", TrackingEventStore),
            patch(
                "hermes_integration.loop.assess_probe_response",
                side_effect=RuntimeError("simulated assessment failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated assessment failure"):
                continue_attempt(
                    self.fixture,
                    database,
                    "continuation-close",
                    phase="probe",
                    expected_version=version,
                    expected_state="awaiting_probe",
                    prompt_instance="continuation-close:probe:1",
                    response="基期量作分母",
                    confidence=0.8,
                    response_time_seconds=10,
                )
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].was_closed)

    def test_store_is_closed_when_session_construction_fails(self) -> None:
        opened = []

        class TrackingEventStore(EventStore):
            def __init__(self, path: str | Path = ":memory:") -> None:
                self.was_closed = False
                super().__init__(path)
                opened.append(self)

            def close(self) -> None:
                self.was_closed = True
                super().close()

        starters = (
            lambda: run_scenario(
                "success",
                Path(self.temporary.name) / "scenario-construction-failure.sqlite3",
            ),
            lambda: run_attempt(
                self.fixture,
                "A",
                0.8,
                31,
                Path(self.temporary.name) / "attempt-construction-failure.sqlite3",
                run_id="attempt-construction-failure",
            ),
        )
        for starter in starters:
            opened.clear()
            with (
                patch("hermes_integration.loop.EventStore", TrackingEventStore),
                patch(
                    "hermes_integration.loop.IntegrationSession",
                    side_effect=RuntimeError("simulated construction failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated construction failure"):
                    starter()
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].was_closed)

    def test_real_response_is_scored_raw_but_only_redacted_evidence_is_traced(self) -> None:
        raw = "A learner@example.com 13800138000"
        session, result = run_attempt(
            self.fixture,
            raw,
            0.5,
            22.0,
            Path(self.temporary.name) / "redacted.sqlite3",
            run_id="real-redacted",
        )
        observe = result.state.artifacts["observe"][-1]
        self.assertFalse(observe["score"]["passed"])
        self.assertEqual(observe["response_evidence"]["redacted_text"], "A [EMAIL] [PHONE]")
        self.assertEqual(observe["response_evidence"]["redactions"], ["email", "phone"])
        serialized = repr([event.payload for event in session.store.events(result.state.run_id)])
        self.assertNotIn("learner@example.com", serialized)
        self.assertNotIn("13800138000", serialized)
        self.assertIn("[EMAIL]", serialized)
        session.store.close()

    def test_growth_formula_probe_uses_authored_semantic_classifier(self) -> None:
        expected = {
            "（120-100）÷100": ("refutes", "refutes", "refutes"),
            "（现期量减基期量）除以基期量": ("refutes", "refutes", "refutes"),
            "增长量除以基期量": ("refutes", "refutes", "refutes"),
            "增长量占基期量的百分比": ("refutes", "refutes", "refutes"),
            "现期量除以基期量后减1": ("refutes", "refutes", "refutes"),
            "120/100=1.2，同比增长20%": ("refutes", "refutes", "refutes"),
            "120/100": ("refutes", "refutes", "supports"),
            "（120-100）÷120": ("supports", "refutes", "refutes"),
            "增长量除以现期量": ("supports", "refutes", "refutes"),
            "增长量占现期量的比例": ("supports", "refutes", "refutes"),
            "20": ("insufficient_or_mixed", "supports", "insufficient_or_mixed"),
            "增长量为20": ("insufficient_or_mixed", "supports", "insufficient_or_mixed"),
            "现期和基期": (
                "insufficient_or_mixed",
                "insufficient_or_mixed",
                "insufficient_or_mixed",
            ),
        }
        cause_order = [
            "denominator-current-base-confusion",
            "increment-rate-confusion",
            "ratio-growth-confusion",
        ]
        for response, directions in expected.items():
            with self.subTest(response=response):
                result = assess_probe_response(
                    self.fixture,
                    response,
                    response_event_seq=7,
                    response_event_hash="event-hash",
                    diagnostic_evidence_weight=1.0,
                )
                by_cause = {item["cause_id"]: item for item in result["assessments"]}
                self.assertEqual(result["evaluator_version"], "growth_formula_v1")
                self.assertEqual(
                    tuple(by_cause[cause]["evidence_direction"] for cause in cause_order),
                    directions,
                )

    def test_zero_weight_probe_cannot_support_or_refute_growth_causes(self) -> None:
        result = assess_probe_response(
            self.fixture,
            "（120-100）÷100",
            response_event_seq=7,
            response_event_hash="event-hash",
            diagnostic_evidence_weight=0.0,
        )
        self.assertTrue(
            all(
                item["claim_status"] == "unconfirmed_hypothesis"
                and item["evidence_direction"] == "insufficient_or_mixed"
                for item in result["assessments"]
            )
        )

    def test_all_resolved_probe_polarity_samples_are_executable(self) -> None:
        fixture_root = Path(__file__).resolve().parents[2] / "domains" / "fixtures"
        expected = {
            "supporting_response": ("supports", "supported_hypothesis"),
            "refuting_response": ("refutes", "refuted_hypothesis"),
            "ambiguous_response": ("insufficient_or_mixed", "unconfirmed_hypothesis"),
        }
        fixtures = [
            load_fixture_document(path, fixture_root=fixture_root)
            for path in sorted(fixture_root.rglob("*.json"))
        ]
        self.assertEqual(len(fixtures), 42)
        self.assertTrue(all(fixture["probe"].get("assessment") for fixture in fixtures))
        for fixture in fixtures:
            for sample in fixture["probe"]["assessment"]["cause_samples"]:
                for response_key, (expected_direction, expected_status) in expected.items():
                    with self.subTest(
                        fixture=fixture["fixture_id"],
                        cause=sample["cause_id"],
                        polarity=response_key,
                    ):
                        result = assess_probe_response(
                            fixture,
                            sample[response_key],
                            response_event_seq=7,
                            response_event_hash="event-hash",
                            diagnostic_evidence_weight=1.0,
                        )
                        by_cause = {
                            item["cause_id"]: item for item in result["assessments"]
                        }
                        self.assertTrue(result["authored_rubric_available"])
                        self.assertEqual(
                            by_cause[sample["cause_id"]]["evidence_direction"],
                            expected_direction,
                        )
                        self.assertEqual(
                            by_cause[sample["cause_id"]]["claim_status"],
                            expected_status,
                        )
                        if response_key == "ambiguous_response":
                            self.assertTrue(
                                all(
                                    item["evidence_direction"] == "insufficient_or_mixed"
                                    and item["claim_status"] == "unconfirmed_hypothesis"
                                    for item in result["assessments"]
                                )
                            )

                        zero_weight = assess_probe_response(
                            fixture,
                            sample[response_key],
                            response_event_seq=7,
                            response_event_hash="event-hash",
                            diagnostic_evidence_weight=0.0,
                        )
                        zero_by_cause = {
                            item["cause_id"]: item for item in zero_weight["assessments"]
                        }
                        self.assertEqual(
                            zero_by_cause[sample["cause_id"]]["claim_status"],
                            "unconfirmed_hypothesis",
                        )

    def test_negated_probe_evidence_never_preserves_its_original_polarity(self) -> None:
        fixture_root = Path(__file__).resolve().parents[2] / "domains" / "fixtures"
        fixtures = [
            load_fixture_document(path, fixture_root=fixture_root)
            for path in sorted(fixture_root.rglob("*.json"))
            if path.name.endswith(".json")
        ]
        for fixture in fixtures:
            assessment = fixture["probe"]["assessment"]
            if assessment["evaluator"] != "authored_terms_v1":
                continue
            for rule in assessment["rules"]:
                cause_id = rule["cause_id"]
                for condition_key, forbidden_direction in (
                    ("support_if", "supports"),
                    ("refute_if", "refutes"),
                ):
                    terms = rule[condition_key]["all_terms"]
                    response = f"不能{terms[0]}，也反对{terms[1]}。"
                    with self.subTest(
                        fixture=fixture["fixture_id"],
                        cause=cause_id,
                        condition=condition_key,
                    ):
                        result = assess_probe_response(
                            fixture,
                            response,
                            response_event_seq=7,
                            response_event_hash="event-hash",
                            diagnostic_evidence_weight=1.0,
                        )
                        by_cause = {
                            item["cause_id"]: item for item in result["assessments"]
                        }
                        self.assertNotEqual(
                            by_cause[cause_id]["evidence_direction"], forbidden_direction
                        )

    def test_growth_formula_rejections_fail_closed_or_refute_only_explicit_claim(self) -> None:
        expected = {
            "不能用增长量除以基期量，这个公式是错的": (
                "insufficient_or_mixed",
                "insufficient_or_mixed",
                "insufficient_or_mixed",
            ),
            "不能用现期量作分母": (
                "refutes",
                "insufficient_or_mixed",
                "insufficient_or_mixed",
            ),
            "增长量除以现期量是不对的": (
                "refutes",
                "insufficient_or_mixed",
                "insufficient_or_mixed",
            ),
            "不能直接用120/100": (
                "insufficient_or_mixed",
                "insufficient_or_mixed",
                "refutes",
            ),
        }
        cause_order = [
            "denominator-current-base-confusion",
            "increment-rate-confusion",
            "ratio-growth-confusion",
        ]
        for response, directions in expected.items():
            with self.subTest(response=response):
                result = assess_probe_response(
                    self.fixture,
                    response,
                    response_event_seq=7,
                    response_event_hash="event-hash",
                    diagnostic_evidence_weight=1.0,
                )
                by_cause = {item["cause_id"]: item for item in result["assessments"]}
                self.assertEqual(
                    tuple(by_cause[cause]["evidence_direction"] for cause in cause_order),
                    directions,
                )

    def test_supported_and_refuted_probe_statuses_route_every_authored_variant(self) -> None:
        fixture_root = Path(__file__).resolve().parents[2] / "domains" / "fixtures"
        fixtures = [
            load_fixture_document(path, fixture_root=fixture_root)
            for path in sorted(fixture_root.rglob("*.json"))
        ]
        for fixture in fixtures:
            causes = [item["cause_id"] for item in fixture["diagnosis"]["candidate_causes"]]
            hypotheses = [
                {"cause_id": cause_id, "probability": 1.0 / len(causes)}
                for cause_id in causes
            ]
            variants = {item["cause_id"]: item for item in fixture["teach"]["variants"]}
            for cause_id in causes:
                with self.subTest(fixture=fixture["fixture_id"], supported=cause_id):
                    assessment = {
                        "assessments": [
                            {
                                "cause_id": item,
                                "claim_status": (
                                    "supported_hypothesis"
                                    if item == cause_id
                                    else "unconfirmed_hypothesis"
                                ),
                            }
                            for item in causes
                        ]
                    }
                    selection = _select_teaching_variant(
                        fixture, hypotheses, assessment
                    )
                    self.assertEqual(selection["instructional_focus"], cause_id)
                    self.assertEqual(selection["prompt"], variants[cause_id]["prompt"])
                    self.assertEqual(selection["strategy"], variants[cause_id]["strategy"])

            if len(causes) > 1:
                assessment = {
                    "assessments": [
                        {
                            "cause_id": item,
                            "claim_status": (
                                "refuted_hypothesis"
                                if index == 0
                                else "unconfirmed_hypothesis"
                            ),
                        }
                        for index, item in enumerate(causes)
                    ]
                }
                selection = _select_teaching_variant(fixture, hypotheses, assessment)
                self.assertEqual(selection["instructional_focus"], causes[1])
                self.assertNotEqual(selection["instructional_focus"], causes[0])

    def test_probe_evidence_changes_authored_teaching_focus_without_confirming_cause(self) -> None:
        database = Path(self.temporary.name) / "probe-driven-teaching.sqlite3"
        session, initial = run_attempt(
            self.fixture,
            "A",
            0.8,
            20,
            database,
            run_id="probe-driven-teaching",
        )
        version = session.store.events("probe-driven-teaching")[-1].seq
        original_top = initial.state.artifacts["probe"][-1]["top_hypothesis"]
        session.store.close()
        continued_session, after_probe = continue_attempt(
            self.fixture,
            database,
            "probe-driven-teaching",
            phase="probe",
            expected_version=version,
            expected_state="awaiting_probe",
            prompt_instance="probe-driven-teaching:probe:1",
            response="120/100",
            confidence=0.7,
            response_time_seconds=10,
        )
        teaching = after_probe.state.artifacts["teach"][-1]
        based_on = teaching["based_on"]
        ratio_variant = next(
            item
            for item in self.fixture["teach"]["variants"]
            if item["cause_id"] == "ratio-growth-confusion"
        )
        self.assertEqual(original_top, "denominator-current-base-confusion")
        self.assertEqual(based_on["original_top_hypothesis"], original_top)
        self.assertEqual(based_on["instructional_focus"], "ratio-growth-confusion")
        self.assertEqual(based_on["focus_claim_status"], "supported_hypothesis")
        self.assertIn("denominator-current-base-confusion", based_on["refuted_hypotheses"])
        self.assertEqual(teaching["prompt"], ratio_variant["prompt"])
        self.assertEqual(
            based_on["semantics"],
            "hypothesis_guided_instruction_not_causal_confirmation",
        )
        continued_session.store.close()


if __name__ == "__main__":
    unittest.main()
