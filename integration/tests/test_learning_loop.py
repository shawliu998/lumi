from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_integration.loop import (
    ContinuationError,
    IntegrationSession,
    SCENARIOS,
    attempt_state_name,
    continue_attempt,
    load_fixture,
    run_attempt,
)
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
            {"name": "hermes_explainable_learning_model", "version": "0.1.0"},
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
            self.assertEqual(update["policy_version"], "integration-learning-policy-v1")
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
                response="重复回答",
                confidence=0.8,
                response_time_seconds=10,
            )

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


if __name__ == "__main__":
    unittest.main()
