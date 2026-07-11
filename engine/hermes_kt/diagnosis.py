from __future__ import annotations

import math
from collections.abc import Iterable

from .models import (
    AttemptEvidence,
    CauseHypothesis,
    CausePrior,
    DiagnosisResult,
    LearnerCauseHistory,
    clamp,
)


def _entropy(probabilities: Iterable[float]) -> float:
    values = [p for p in probabilities if p > 0]
    if len(values) <= 1:
        return 0.0
    raw = -sum(p * math.log(p) for p in values)
    return raw / math.log(len(values))


def diagnose_causes(
    attempt: AttemptEvidence,
    priors: Iterable[CausePrior],
    history: LearnerCauseHistory | None = None,
    *,
    learner_strength: float = 4.0,
) -> DiagnosisResult:
    """Infer misconception hypotheses with transparent Bayesian-style factors.

    The cohort prior supplies cold-start pseudo-counts. Learner history contributes
    a separate Dirichlet-style factor. Attempt evidence supplies likelihood ratios.
    This is a ranking model, not a causal claim; verification should follow.
    """

    prior_list = list(priors)
    if not prior_list:
        raise ValueError("at least one cause prior is required")
    total_prior = sum(p.probability for p in prior_list)
    if total_prior <= 0:
        raise ValueError("cause prior probabilities must have positive total")
    history = history or LearnerCauseHistory()
    cause_ids = {p.cause_id for p in prior_list}
    priors_by_cause = {p.cause_id: p for p in prior_list}
    cohort = {p.cause_id: p.probability / total_prior for p in prior_list}
    history_total = sum(max(0.0, history.counts.get(cause, 0.0)) for cause in cause_ids)

    # A small symmetric base prevents a new learner from overpowering the cohort.
    learner_denominator = history_total + learner_strength
    scores: dict[str, float] = {}
    learner_components: dict[str, float] = {}
    likelihoods: dict[str, float] = {}
    for cause in cause_ids:
        learner_component = (
            max(0.0, history.counts.get(cause, 0.0))
            + learner_strength * cohort[cause]
        ) / learner_denominator
        likelihood = max(1e-6, attempt.cause_likelihoods.get(cause, 1.0))
        learner_components[cause] = learner_component
        likelihoods[cause] = likelihood
        scores[cause] = cohort[cause] * learner_component * likelihood

    normalizer = sum(scores.values())
    if normalizer <= 0:
        raise ValueError("diagnosis produced no positive probability mass")

    hypotheses = []
    for cause in cause_ids:
        evidence = [
            "cohort_prior"
            if priors_by_cause[cause].sample_size > 0
            else "engineering_prior",
            "learner_history",
        ]
        if cause in attempt.cause_likelihoods:
            evidence.append("attempt_feature_likelihood")
        hypotheses.append(
            CauseHypothesis(
                cause_id=cause,
                probability=scores[cause] / normalizer,
                cohort_component=cohort[cause],
                learner_component=learner_components[cause],
                evidence_likelihood=likelihoods[cause],
                evidence=tuple(evidence),
            )
        )
    hypotheses.sort(key=lambda item: item.probability, reverse=True)

    provenance = {
        "attempt": attempt.provenance(),
        "cohort_sources": [
            {
                "cause_id": p.cause_id,
                "cohort_id": p.cohort_id,
                "sample_size": p.sample_size,
                "source_version": p.source_version,
            }
            for p in prior_list
        ],
        "learner_history_version": history.source_version,
        "learner_history_exposure_count": history.exposure_count,
        "formula": "normalize(cohort_prior * learner_dirichlet_posterior * evidence_likelihood)",
    }
    return DiagnosisResult(
        attempt_id=attempt.attempt_id,
        hypotheses=tuple(hypotheses),
        uncertainty=clamp(_entropy(h.probability for h in hypotheses), 0.0, 1.0),
        provenance=provenance,
    )
