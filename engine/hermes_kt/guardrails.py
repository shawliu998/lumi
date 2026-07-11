from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ModelTier(str, Enum):
    STRONG = "strong"
    BALANCED = "balanced"
    LOW_COST = "low_cost"


@dataclass(frozen=True)
class RoutingContext:
    diagnosis_uncertainty: float
    candidate_cause_count: int
    skill_count: int = 1
    has_free_text_reasoning: bool = False
    multimodal: bool = False
    requested_tier: ModelTier | None = None


@dataclass(frozen=True)
class RoutingDecision:
    tier: ModelTier
    reason: str
    schema_required: bool = True
    independent_verification_required: bool = False
    may_directly_update_mastery: bool = False


def route_model(context: RoutingContext) -> RoutingDecision:
    """Choose capability by diagnosis complexity, never by opaque model whim."""

    complex_case = (
        context.diagnosis_uncertainty >= 0.70
        or context.candidate_cause_count >= 4
        or context.skill_count >= 3
        or context.has_free_text_reasoning
        or context.multimodal
    )
    if complex_case:
        return RoutingDecision(
            tier=ModelTier.STRONG,
            reason="complex or ambiguous diagnosis requires stronger reasoning",
        )
    if context.requested_tier == ModelTier.LOW_COST:
        return RoutingDecision(
            tier=ModelTier.LOW_COST,
            reason="low-cost tier accepted only for a simple case with verification",
            independent_verification_required=True,
        )
    return RoutingDecision(
        tier=ModelTier.BALANCED,
        reason="routine structured tutoring or explanation",
    )


def validate_generated_diagnosis(payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Deterministic schema/semantic guardrail for model-produced hypotheses."""

    errors: list[str] = []
    allowed_top_level = {"hypotheses", "next_probe", "evidence_summary"}
    unknown = set(payload) - allowed_top_level
    if unknown:
        errors.append(f"unknown top-level fields: {sorted(unknown)}")
    hypotheses = payload.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        errors.append("hypotheses must be a non-empty list")
        return False, tuple(errors)
    total = 0.0
    for index, item in enumerate(hypotheses):
        if not isinstance(item, Mapping):
            errors.append(f"hypotheses[{index}] must be an object")
            continue
        if set(item) != {"cause_id", "probability", "evidence_ids"}:
            errors.append(f"hypotheses[{index}] has invalid fields")
            continue
        if not isinstance(item["cause_id"], str) or not item["cause_id"]:
            errors.append(f"hypotheses[{index}].cause_id must be non-empty")
        probability = item["probability"]
        if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
            errors.append(f"hypotheses[{index}].probability must be in [0, 1]")
        else:
            total += float(probability)
        if not isinstance(item["evidence_ids"], list) or not item["evidence_ids"]:
            errors.append(f"hypotheses[{index}].evidence_ids must be non-empty")
    if abs(total - 1.0) > 1e-6:
        errors.append("hypothesis probabilities must sum to 1")
    if not isinstance(payload.get("next_probe"), str) or not payload.get("next_probe"):
        errors.append("next_probe must be non-empty")
    return not errors, tuple(errors)


def can_accept_generated_diagnosis(
    decision: RoutingDecision,
    payload: Mapping[str, Any],
    *,
    independently_verified: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    valid, errors = validate_generated_diagnosis(payload)
    if not valid:
        return False, errors
    if decision.independent_verification_required and not independently_verified:
        return False, ("independent verification item is required for low-cost output",)
    return True, ()
