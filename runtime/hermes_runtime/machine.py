from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .diff import state_diff
from .guardrails import BoundaryGuardrail, CompositeGuardrail, GuardAction, Guardrail
from .models import ModelRouter
from .state import AgentState, PHASE_ORDER, Phase, RunStatus
from .store import EventStore
from .tools import ToolContext, ToolRegistry


PHASE_TO_TOOL = {phase: f"learning.{phase.value}" for phase in PHASE_ORDER}


@dataclass(frozen=True, slots=True)
class RunResult:
    state: AgentState
    steps_executed: int


class AgentRuntime:
    """Bounded observe→diagnose→probe→teach→verify→update→reflect loop."""

    def __init__(
        self,
        registry: ToolRegistry,
        store: EventStore,
        router: ModelRouter,
        guardrail: Guardrail | None = None,
        phase_tools: Mapping[Phase, str] | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.router = router
        self.guardrail = guardrail or CompositeGuardrail(BoundaryGuardrail())
        self.phase_tools = dict(PHASE_TO_TOOL if phase_tools is None else phase_tools)

    def start(self, state: AgentState) -> AgentState:
        if self.store.events(state.run_id):
            raise ValueError(f"run already exists: {state.run_id}")
        state.status = RunStatus.RUNNING
        self.store.append(
            state.run_id,
            "run_started",
            {"state_after": state.to_dict(), "tool_manifest": self.registry.manifest()},
        )
        return state

    def run(
        self,
        state: AgentState,
        *,
        interrupt_after: int | None = None,
        payload_factory: Callable[[AgentState], Mapping[str, Any]] | None = None,
    ) -> RunResult:
        if not self.store.events(state.run_id):
            self.start(state)
        elif state.status in {RunStatus.INTERRUPTED, RunStatus.PAUSED}:
            state = self.resume(state.run_id)
        elif state.status is RunStatus.READY:
            state.status = RunStatus.RUNNING

        executed = 0
        while state.status is RunStatus.RUNNING:
            if interrupt_after is not None and executed >= interrupt_after:
                state = self.interrupt(state.run_id, "requested interrupt boundary")
                break
            state = self.step(state, payload_factory=payload_factory)
            executed += 1
        return RunResult(state=state, steps_executed=executed)

    def step(
        self,
        state: AgentState,
        *,
        payload_factory: Callable[[AgentState], Mapping[str, Any]] | None = None,
    ) -> AgentState:
        if state.status is not RunStatus.RUNNING:
            raise RuntimeError(f"cannot step run in {state.status.value} status")
        if state.step_count >= state.max_steps:
            return self._stop(state, RunStatus.FAILED, "max_steps exceeded", "run_failed")
        if state.phase is Phase.COMPLETE:
            return self._stop(state, RunStatus.COMPLETED, None, "run_completed")

        tool_name = self.phase_tools[state.phase]
        payload = dict(payload_factory(state) if payload_factory else self._default_payload(state))
        decision = self.guardrail.check(state, tool_name, payload)
        if decision.action is GuardAction.BLOCK:
            return self._stop(state, RunStatus.FAILED, decision.reason, "guardrail_blocked")
        if decision.action is GuardAction.PAUSE:
            return self._stop(state, RunStatus.PAUSED, decision.reason, "guardrail_paused")

        before = deepcopy(state.to_dict())
        context = ToolContext(state=state, router=self.router)
        try:
            output = self.registry.invoke(tool_name, payload, context)
        except Exception as exc:
            return self._stop(state, RunStatus.FAILED, f"{type(exc).__name__}: {exc}", "tool_failed")

        completed_phase = state.phase
        state.append_artifact(completed_phase, output)
        state.step_count += 1
        self._advance(state, output)
        after = state.to_dict()
        self.store.append(
            state.run_id,
            "phase_completed",
            {
                "phase": completed_phase.value,
                "tool": tool_name,
                "tool_version": self.registry.get(tool_name).version,
                "input": payload,
                "output": output,
                "model_calls": context.model_calls,
                "state_diff": state_diff(before, after),
                "state_after": after,
            },
        )
        return state

    def interrupt(self, run_id: str, reason: str = "user requested") -> AgentState:
        state = self.store.load_state(run_id)
        if state.status not in {RunStatus.RUNNING, RunStatus.READY}:
            return state
        return self._stop(state, RunStatus.INTERRUPTED, reason, "run_interrupted")

    def resume(self, run_id: str) -> AgentState:
        state = self.store.load_state(run_id)
        if state.status not in {RunStatus.INTERRUPTED, RunStatus.PAUSED}:
            raise RuntimeError(f"run {run_id} cannot resume from {state.status.value}")
        before = deepcopy(state.to_dict())
        state.status = RunStatus.RUNNING
        state.last_error = None
        after = state.to_dict()
        self.store.append(
            run_id,
            "run_resumed",
            {"state_diff": state_diff(before, after), "state_after": after},
        )
        return state

    def replay(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.store.replay(run_id))

    def _advance(self, state: AgentState, output: Mapping[str, Any]) -> None:
        if state.phase is Phase.REFLECT:
            should_continue = bool(output.get("continue", False))
            if should_continue and state.cycle < state.max_cycles:
                state.cycle += 1
                state.phase = Phase.OBSERVE
            else:
                state.phase = Phase.COMPLETE
                state.status = RunStatus.COMPLETED
            return
        index = PHASE_ORDER.index(state.phase)
        state.phase = PHASE_ORDER[index + 1]

    def _stop(self, state: AgentState, status: RunStatus, error: str | None, kind: str) -> AgentState:
        before = deepcopy(state.to_dict())
        state.status = status
        state.last_error = error
        if status is RunStatus.COMPLETED:
            state.phase = Phase.COMPLETE
        after = state.to_dict()
        self.store.append(
            state.run_id,
            kind,
            {"reason": error, "state_diff": state_diff(before, after), "state_after": after},
        )
        return state

    @staticmethod
    def _default_payload(state: AgentState) -> dict[str, Any]:
        latest = {
            phase: artifacts[-1]
            for phase, artifacts in state.artifacts.items()
            if artifacts
        }
        # This JSON-safe boundary is the only contract expected from domain/KT engines.
        return {
            "run_id": state.run_id,
            "learner_id": state.learner_id,
            "domain": state.domain,
            "goal": state.goal,
            "phase": state.phase.value,
            "cycle": state.cycle,
            "context": state.context,
            "latest_artifacts": latest,
        }
