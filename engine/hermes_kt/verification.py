from __future__ import annotations

from .mastery import update_skill_state
from .models import (
    AttemptEvidence,
    SkillParameters,
    SkillState,
    VerificationResult,
)


def evaluate_intervention(
    intervention_id: str,
    pre_state: SkillState,
    verification_attempt: AttemptEvidence,
    params: SkillParameters,
    *,
    item_difficulty: float = 0.0,
    minimum_gain: float = 0.02,
) -> tuple[SkillState, VerificationResult]:
    """Update state and evaluate teaching only on an independent verification.

    A hinted or non-independent answer still becomes evidence, but it cannot prove
    that the intervention worked. This prevents tutor assistance from being
    mistaken for learner mastery.
    """

    post_state = update_skill_state(
        pre_state,
        verification_attempt,
        params,
        item_difficulty=item_difficulty,
    )
    independent = verification_attempt.independently_answered and verification_attempt.hints_used == 0
    gain = post_state.mastery - pre_state.mastery
    if not independent:
        effective = None
        reason = "inconclusive: verification used help or was not independent"
    elif verification_attempt.correct and gain >= minimum_gain:
        effective = True
        reason = "effective: independent correct transfer with mastery gain"
    else:
        effective = False
        reason = "not yet effective: independent transfer criterion was not met"

    result = VerificationResult(
        intervention_id=intervention_id,
        pre_mastery=pre_state.mastery,
        post_mastery=post_state.mastery,
        mastery_gain=gain,
        independently_verified=independent,
        effective=effective,
        reason=reason,
        provenance={
            "verification_attempt": verification_attempt.provenance(),
            "minimum_gain": minimum_gain,
            "model_version": "independent-transfer-check-v1",
        },
    )
    return post_state, result
