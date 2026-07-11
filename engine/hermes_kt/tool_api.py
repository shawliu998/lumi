from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from .diagnosis import diagnose_causes
from .guardrails import ModelTier, RoutingContext, can_accept_generated_diagnosis, route_model
from .mastery import update_skill_state
from .models import (
    AttemptEvidence,
    CausePrior,
    LearnerCauseHistory,
    SkillParameters,
    SkillState,
)
from .verification import evaluate_intervention


class HermesKTTool:
    """Stateless, JSON-friendly adapter suitable for registration as an Agent tool."""

    name = "hermes_explainable_learning_model"
    version = "0.2.0"

    def route_diagnosis(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        context_payload = dict(payload)
        if context_payload.get("requested_tier") is not None:
            context_payload["requested_tier"] = ModelTier(context_payload["requested_tier"])
        return asdict(route_model(RoutingContext(**context_payload)))

    def guard_generated_diagnosis(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        decision_payload = dict(payload["routing_decision"])
        decision_payload["tier"] = ModelTier(decision_payload["tier"])
        from .guardrails import RoutingDecision

        accepted, errors = can_accept_generated_diagnosis(
            RoutingDecision(**decision_payload),
            payload["generated_diagnosis"],
            independently_verified=payload.get("independently_verified", False),
        )
        return {"accepted": accepted, "errors": list(errors)}

    def diagnose(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        attempt = AttemptEvidence(**payload["attempt"])
        priors = [CausePrior(**entry) for entry in payload["priors"]]
        history = LearnerCauseHistory(**payload.get("history", {}))
        return diagnose_causes(attempt, priors, history).to_dict()

    def update_mastery(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        state = SkillState(**payload["state"])
        attempt = AttemptEvidence(**payload["attempt"])
        params = SkillParameters(**payload["parameters"])
        return update_skill_state(
            state,
            attempt,
            params,
            item_difficulty=payload.get("item_difficulty", 0.0),
            skill_weight=payload.get("skill_weight", 1.0),
        ).to_dict()

    def verify_intervention(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        state = SkillState(**payload["pre_state"])
        attempt = AttemptEvidence(**payload["verification_attempt"])
        params = SkillParameters(**payload["parameters"])
        post_state, result = evaluate_intervention(
            payload["intervention_id"],
            state,
            attempt,
            params,
            item_difficulty=payload.get("item_difficulty", 0.0),
            minimum_gain=payload.get("minimum_gain", 0.02),
            evidence_weight=payload.get("evidence_weight", 1.0),
        )
        return {"post_state": post_state.to_dict(), "verification": asdict(result)}
