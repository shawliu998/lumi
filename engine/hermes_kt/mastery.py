from __future__ import annotations

import math
from dataclasses import replace

from .models import AttemptEvidence, SkillParameters, SkillState, clamp, utc_now


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def _bkt_update(prior: float, correct: bool, params: SkillParameters) -> float:
    prior = clamp(prior)
    if correct:
        numerator = prior * (1 - params.bkt_slip)
        denominator = numerator + (1 - prior) * params.bkt_guess
    else:
        numerator = prior * params.bkt_slip
        denominator = numerator + (1 - prior) * (1 - params.bkt_guess)
    posterior = numerator / max(denominator, 1e-12)
    return clamp(posterior + (1 - posterior) * params.bkt_learn)


def update_skill_state(
    state: SkillState,
    attempt: AttemptEvidence,
    params: SkillParameters,
    *,
    item_difficulty: float = 0.0,
    skill_weight: float = 1.0,
) -> SkillState:
    """Update mastery using BKT, PFA, and online Rasch/1PL IRT signals."""

    if state.skill_id != params.skill_id:
        raise ValueError("state and parameters refer to different skills")
    if not 0 <= skill_weight <= 1:
        raise ValueError("skill_weight must be in [0, 1]")
    # Zero-credit observations are recorded outside the authoritative skill
    # state. Returning the original immutable value avoids false precision from
    # changing mastery, effective counts, or uncertainty after a full solution.
    if skill_weight == 0:
        return state

    bkt_observed = _bkt_update(state.bkt_mastery, attempt.correct, params)
    bkt = state.bkt_mastery + skill_weight * (bkt_observed - state.bkt_mastery)
    successes = state.successes + (skill_weight if attempt.correct else 0)
    failures = state.failures + (skill_weight if not attempt.correct else 0)
    pfa = sigmoid(
        params.pfa_intercept
        + params.pfa_success_weight * successes
        + params.pfa_failure_weight * failures
    )

    predicted = sigmoid(state.irt_theta - item_difficulty)
    # Bounded stochastic-gradient step for the Rasch ability parameter.
    observation = 1.0 if attempt.correct else 0.0
    irt_theta = state.irt_theta + 0.25 * skill_weight * (observation - predicted)
    irt = sigmoid(irt_theta - item_difficulty)

    raw_weights = params.ensemble_weights
    total_weight = sum(raw_weights)
    weights = tuple(value / total_weight for value in raw_weights)
    components = (bkt, pfa, irt)
    mastery = sum(w * value for w, value in zip(weights, components))
    disagreement = math.sqrt(sum(w * (value - mastery) ** 2 for w, value in zip(weights, components)))
    scarcity = 1 / math.sqrt(state.evidence_count + 2)
    uncertainty = clamp(0.65 * scarcity + 0.35 * min(1.0, disagreement * 2), 0.0, 1.0)

    event = {
        "attempt": attempt.provenance(),
        "skill_weight": skill_weight,
        "item_difficulty": item_difficulty,
        "components": {"bkt": bkt, "pfa": pfa, "irt_1pl": irt},
        "ensemble_weights": {"bkt": weights[0], "pfa": weights[1], "irt_1pl": weights[2]},
        "formula_version": "bkt-pfa-rasch-ensemble-v1",
    }
    return replace(
        state,
        bkt_mastery=clamp(bkt),
        successes=successes,
        failures=failures,
        irt_theta=irt_theta,
        evidence_count=state.evidence_count + 1,
        mastery=clamp(mastery),
        uncertainty=uncertainty,
        last_updated_at=utc_now(),
        provenance=state.provenance + (event,),
    )
