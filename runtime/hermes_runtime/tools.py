from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .models import ModelRequest, ModelResponse, ModelRouter
from .state import AgentState, Phase


JsonSchema = Mapping[str, Any]
ToolHandler = Callable[[Mapping[str, Any], "ToolContext"], Mapping[str, Any]]


class ToolError(RuntimeError):
    pass


@dataclass(slots=True)
class ToolContext:
    state: AgentState
    router: ModelRouter
    model_calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, request: ModelRequest) -> ModelResponse:
        response, route_reason = self.router.complete(request)
        self.model_calls.append(
            {
                "task": request.task,
                "complexity": request.complexity,
                "risk": request.risk,
                "tier": response.tier.value,
                "model": response.model,
                "settings": dict(response.settings),
                "usage": dict(response.usage),
                "latency_ms": response.latency_ms,
                "cost": response.cost,
                "route_reason": route_reason,
            }
        )
        return response


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    handler: ToolHandler
    phases: frozenset[Phase] = field(default_factory=frozenset)
    version: str = "1"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"unknown tool: {name}") from exc

    def invoke(self, name: str, payload: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
        spec = self.get(name)
        if spec.phases and context.state.phase not in spec.phases:
            raise ToolError(f"tool {name} cannot run during {context.state.phase.value}")
        _validate(payload, spec.input_schema, f"{name} input")
        result = dict(spec.handler(dict(payload), context))
        _validate(result, spec.output_schema, f"{name} output")
        return result

    def manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "output_schema": spec.output_schema,
                "phases": sorted(p.value for p in spec.phases),
                "version": spec.version,
            }
            for spec in sorted(self._tools.values(), key=lambda item: item.name)
        ]


def _validate(value: Mapping[str, Any], schema: JsonSchema, label: str) -> None:
    """Small JSON-schema subset: object, required, properties and scalar types."""

    required = schema.get("required", [])
    for key in required:
        if key not in value:
            raise ToolError(f"{label} missing required field: {key}")
    properties = schema.get("properties", {})
    type_map = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict, "array": list}
    for key, definition in properties.items():
        if key not in value or "type" not in definition:
            continue
        expected = type_map.get(definition["type"])
        if expected is not None and not isinstance(value[key], expected):
            raise ToolError(f"{label}.{key} expected {definition['type']}")
