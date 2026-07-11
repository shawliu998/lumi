from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol


class ModelTier(StrEnum):
    SOL = "sol"
    TERRA = "terra"
    LIGHT = "light"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    task: str
    prompt: str
    complexity: float = 0.5
    risk: float = 0.0
    deterministic: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    tier: ModelTier
    model: str
    content: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    usage: Mapping[str, int] = field(default_factory=dict)
    latency_ms: int | None = None
    cost: float | None = None


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest, tier: ModelTier) -> ModelResponse: ...


class ModelRouter:
    """Routes hard/high-risk work to Sol and routine work to cheaper tiers."""

    def __init__(self, provider: ModelProvider, sol_threshold: float = 0.78, light_threshold: float = 0.28) -> None:
        self.provider = provider
        self.sol_threshold = sol_threshold
        self.light_threshold = light_threshold

    def choose(self, request: ModelRequest) -> tuple[ModelTier, str]:
        if request.deterministic:
            return ModelTier.LIGHT, "deterministic task"
        score = max(request.complexity, request.risk)
        if score >= self.sol_threshold:
            return ModelTier.SOL, f"complexity/risk score {score:.2f}"
        if score <= self.light_threshold:
            return ModelTier.LIGHT, f"complexity/risk score {score:.2f}"
        return ModelTier.TERRA, f"balanced complexity/risk score {score:.2f}"

    def complete(self, request: ModelRequest) -> tuple[ModelResponse, str]:
        tier, reason = self.choose(request)
        return self.provider.complete(request, tier), reason


class DeterministicProvider:
    """Offline provider used by tests and the synthetic demo."""

    names = {ModelTier.SOL: "offline-sol", ModelTier.TERRA: "offline-terra", ModelTier.LIGHT: "offline-light"}

    def complete(self, request: ModelRequest, tier: ModelTier) -> ModelResponse:
        content = f"[{tier.value}] {request.task}: {request.prompt[:120]}"
        return ModelResponse(tier=tier, model=self.names[tier], content=content, settings={"temperature": 0})
