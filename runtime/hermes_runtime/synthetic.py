from __future__ import annotations

from typing import Any, Mapping

from .models import ModelRequest
from .state import Phase
from .tools import ToolContext, ToolRegistry, ToolSpec


OBJECT_SCHEMA = {"type": "object", "properties": {}}


def synthetic_registry() -> ToolRegistry:
    """Representative, deterministic learning tools for local smoke tests."""
    registry = ToolRegistry()

    def add(phase: Phase, handler: Any, output_schema: Mapping[str, Any]) -> None:
        registry.register(
            ToolSpec(
                name=f"learning.{phase.value}",
                description=f"Synthetic {phase.value} adapter across the JSON engine boundary",
                input_schema={"type": "object", "required": ["run_id", "phase", "context"]},
                output_schema=output_schema,
                handler=handler,
                phases=frozenset({phase}),
            )
        )

    add(Phase.OBSERVE, _observe, _required("answer", "correct"))
    add(Phase.DIAGNOSE, _diagnose, _required("hypotheses", "selected"))
    add(Phase.PROBE, _probe, _required("probe_id", "targets"))
    add(Phase.TEACH, _teach, _required("intervention", "principle"))
    add(Phase.VERIFY, _verify, _required("passed", "independent_transfer"))
    add(Phase.UPDATE, _update, _required("skill_id", "mastery_delta"))
    add(Phase.REFLECT, _reflect, _required("continue", "lesson"))
    return registry


def _required(*fields: str) -> dict[str, Any]:
    return {"type": "object", "required": list(fields), "properties": {}}


def _observe(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    answer = payload["context"].get("answer", "B")
    return {"answer": answer, "correct": False, "latency_ms": 42000, "confidence": 0.78}


def _diagnose(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    response = context.complete(
        ModelRequest(
            task="rank-misconceptions",
            prompt="Infer a specific cause for a data-analysis base-period distractor.",
            complexity=0.91,
            risk=0.72,
        )
    )
    return {
        "hypotheses": [
            {"cause": "base/current-period formula inversion", "probability": 0.67},
            {"cause": "arithmetic slip", "probability": 0.21},
        ],
        "selected": "base/current-period formula inversion",
        "rationale": response.content,
    }


def _probe(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    return {"probe_id": "growth-base-direction-01", "targets": ["formula-direction"], "answer": "A"}


def _teach(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    response = context.complete(
        ModelRequest(
            task="micro-teaching",
            prompt="Give one Socratic hint without revealing the answer.",
            complexity=0.55,
            risk=0.2,
        )
    )
    return {"intervention": response.content, "principle": "current = base × (1 + growth)"}


def _verify(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    passed = context.state.cycle >= 2
    return {"passed": passed, "independent_transfer": passed, "item_id": f"transfer-{context.state.cycle}"}


def _update(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    passed = bool(payload["latest_artifacts"].get("verify", {}).get("passed", False))
    return {
        "skill_id": "xingce.data-analysis.growth.base-period",
        "mastery_delta": 0.12 if passed else -0.03,
        "evidence": "independent transfer" if passed else "failed targeted transfer",
    }


def _reflect(payload: Mapping[str, Any], context: ToolContext) -> Mapping[str, Any]:
    should_continue = context.state.cycle < context.state.max_cycles
    context.complete(
        ModelRequest(
            task="record-reflection",
            prompt="Record deterministic next-step decision.",
            complexity=0.1,
            deterministic=True,
        )
    )
    return {
        "continue": should_continue,
        "lesson": "Probe before teaching; verify with an independent isomorphic item.",
    }
