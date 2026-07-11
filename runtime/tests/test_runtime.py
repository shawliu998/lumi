from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_runtime.guardrails import BoundaryGuardrail
from hermes_runtime.machine import AgentRuntime
from hermes_runtime.models import DeterministicProvider, ModelRequest, ModelRouter, ModelTier
from hermes_runtime.state import AgentState, Phase, RunStatus
from hermes_runtime.store import EventStore, TraceVersionConflict
from hermes_runtime.synthetic import synthetic_registry
from hermes_runtime.tools import ToolContext, ToolError, ToolRegistry, ToolSpec


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EventStore(":memory:")
        self.router = ModelRouter(DeterministicProvider())
        self.runtime = AgentRuntime(synthetic_registry(), self.store, self.router)

    def tearDown(self) -> None:
        self.store.close()

    def make_state(self, **overrides: object) -> AgentState:
        values = {
            "learner_id": "learner-1",
            "domain": "xingce",
            "goal": "learn growth rates",
            "context": {"answer": "B"},
            "max_cycles": 2,
        }
        values.update(overrides)
        return AgentState(**values)  # type: ignore[arg-type]

    def test_two_cycle_demo_completes_with_typed_artifacts(self) -> None:
        result = self.runtime.run(self.make_state())
        self.assertEqual(result.state.status, RunStatus.COMPLETED)
        self.assertEqual(result.state.phase, Phase.COMPLETE)
        self.assertEqual(result.state.step_count, 14)
        self.assertEqual(len(result.state.artifacts["diagnose"]), 2)
        self.assertTrue(result.state.artifacts["verify"][-1]["independent_transfer"])
        self.assertTrue(self.store.verify(result.state.run_id))

    def test_interrupt_resume_reconstructs_from_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.sqlite3"
            store = EventStore(path)
            runtime = AgentRuntime(synthetic_registry(), store, self.router)
            first = runtime.run(self.make_state(), interrupt_after=4)
            self.assertEqual(first.state.status, RunStatus.INTERRUPTED)
            run_id = first.state.run_id
            store.close()

            reopened = EventStore(path)
            resumed_runtime = AgentRuntime(synthetic_registry(), reopened, self.router)
            state = resumed_runtime.resume(run_id)
            result = resumed_runtime.run(state)
            self.assertEqual(result.state.status, RunStatus.COMPLETED)
            self.assertEqual(result.state.step_count, 14)
            self.assertTrue(reopened.verify(run_id))
            reopened.close()

    def test_replay_does_not_invoke_tools(self) -> None:
        result = self.runtime.run(self.make_state(max_cycles=1))
        event_count = len(self.store.events(result.state.run_id))
        frames = self.runtime.replay(result.state.run_id)
        self.assertEqual(len(self.store.events(result.state.run_id)), event_count)
        self.assertEqual(frames[-1]["state"]["status"], "completed")

    def test_model_routing_quality_first(self) -> None:
        sol, _ = self.router.choose(ModelRequest("hard", "", complexity=0.9))
        terra, _ = self.router.choose(ModelRequest("normal", "", complexity=0.5))
        light, _ = self.router.choose(ModelRequest("fixed", "", complexity=0.9, deterministic=True))
        self.assertEqual((sol, terra, light), (ModelTier.SOL, ModelTier.TERRA, ModelTier.LIGHT))

    def test_model_calls_are_recorded(self) -> None:
        result = self.runtime.run(self.make_state(max_cycles=1))
        calls = [call for event in self.store.events(result.state.run_id) for call in event.payload.get("model_calls", [])]
        self.assertEqual([call["tier"] for call in calls], ["sol", "terra", "light"])
        self.assertTrue(all("route_reason" in call for call in calls))

    def test_guardrail_blocks_protected_path(self) -> None:
        protected = Path.home() / "Desktop" / "shenlun-agent-platform"
        state = self.make_state(context={"path": str(protected)})
        result = self.runtime.run(state)
        self.assertEqual(result.state.status, RunStatus.FAILED)
        self.assertIn("protected", result.state.last_error or "")

    def test_trace_is_append_only_and_redacts_secrets(self) -> None:
        state = self.make_state(context={"api_token": "do-not-store"}, max_cycles=1)
        result = self.runtime.run(state)
        encoded = repr([event.payload for event in self.store.events(result.state.run_id)])
        self.assertNotIn("do-not-store", encoded)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute("DELETE FROM trace_events")  # type: ignore[attr-defined]

    def test_append_if_version_is_database_level_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cas.sqlite3"
            first = EventStore(path)
            second = EventStore(path)
            first.append("cas-run", "started", {"value": 1})
            accepted = first.append_if_version("cas-run", 1, "accepted", {"value": 2})
            self.assertEqual(accepted.seq, 2)
            with self.assertRaises(TraceVersionConflict) as conflict:
                second.append_if_version("cas-run", 1, "rejected", {"value": 3})
            self.assertEqual(conflict.exception.actual_version, 2)
            self.assertEqual([event.kind for event in second.events("cas-run")], ["started", "accepted"])
            self.assertTrue(second.verify("cas-run"))
            first.close()
            second.close()

    def test_content_snapshot_is_private_immutable_and_hash_addressed(self) -> None:
        content_hash = self.store.put_content_snapshot(
            "domain_fixture", {"fixture_id": "fixture-1", "value": 2}
        )
        loaded = self.store.load_content_snapshot(content_hash, kind="domain_fixture")
        self.assertEqual(loaded["content"], {"fixture_id": "fixture-1", "value": 2})
        self.assertEqual(
            self.store.put_content_snapshot(
                "domain_fixture", {"fixture_id": "fixture-1", "value": 2}
            ),
            content_hash,
        )
        self.assertEqual(self.store.events("fixture-1"), [])
        with self.assertRaises(sqlite3.IntegrityError):
            self.store._connection.execute(  # type: ignore[attr-defined]
                "DELETE FROM content_snapshots WHERE content_hash = ?", (content_hash,)
            )

    def test_tool_schema_rejects_invalid_output(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "bad",
                "bad",
                {"type": "object"},
                {"type": "object", "required": ["ok"]},
                lambda payload, context: {},
            )
        )
        with self.assertRaises(ToolError):
            registry.invoke("bad", {}, ToolContext(self.make_state(), self.router))


if __name__ == "__main__":
    unittest.main()
