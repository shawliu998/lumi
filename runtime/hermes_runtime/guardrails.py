from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol

from .state import AgentState, Phase


class GuardAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    PAUSE = "pause"


@dataclass(frozen=True, slots=True)
class GuardDecision:
    action: GuardAction
    reason: str = ""


class Guardrail(Protocol):
    def check(self, state: AgentState, tool_name: str, payload: Mapping[str, Any]) -> GuardDecision: ...


class BoundaryGuardrail:
    """Blocks unsafe paths and network intent at the local tool boundary."""

    forbidden_fragments = ("shenlun-agent-platform", "../", "file://")

    def check(self, state: AgentState, tool_name: str, payload: Mapping[str, Any]) -> GuardDecision:
        serialized = repr(dict(payload)).lower()
        if any(fragment in serialized for fragment in self.forbidden_fragments):
            return GuardDecision(GuardAction.BLOCK, "payload crosses a protected filesystem boundary")
        if payload.get("network") is True and not state.context.get("network_opt_in", False):
            return GuardDecision(GuardAction.PAUSE, "network access requires explicit opt-in")
        return GuardDecision(GuardAction.ALLOW)


class PhaseGuardrail:
    def __init__(self, allowed: Mapping[str, set[Phase]]) -> None:
        self.allowed = dict(allowed)

    def check(self, state: AgentState, tool_name: str, payload: Mapping[str, Any]) -> GuardDecision:
        phases = self.allowed.get(tool_name)
        if phases is not None and state.phase not in phases:
            return GuardDecision(GuardAction.BLOCK, f"{tool_name} is not allowed during {state.phase.value}")
        return GuardDecision(GuardAction.ALLOW)


class CompositeGuardrail:
    def __init__(self, *guards: Guardrail) -> None:
        self.guards = guards

    def check(self, state: AgentState, tool_name: str, payload: Mapping[str, Any]) -> GuardDecision:
        for guard in self.guards:
            decision = guard.check(state, tool_name, payload)
            if decision.action is not GuardAction.ALLOW:
                return decision
        return GuardDecision(GuardAction.ALLOW)
