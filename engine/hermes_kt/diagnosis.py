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

    A versioned engineering prior or privacy-reviewed cohort prior supplies the
    cold-start distribution. Learner history contributes a separate
    Dirichlet-style factor. Attempt evidence supplies likelihood ratios. This is
    a ranking model, not a causal claim; verification should follow.
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
    base_prior = {p.cause_id: p.probability / total_prior for p in prior_list}
    history_total = sum(max(0.0, history.counts.get(cause, 0.0)) for cause in cause_ids)

    # A small prior-seeded base prevents sparse learner history from dominating.
    learner_denominator = history_total + learner_strength
    scores: dict[str, float] = {}
    learner_components: dict[str, float] = {}
    likelihoods: dict[str, float] = {}
    for cause in cause_ids:
        learner_posterior = (
            max(0.0, history.counts.get(cause, 0.0))
            + learner_strength * base_prior[cause]
        ) / learner_denominator
        # Use history as a likelihood ratio over the prior already present in
        # the score. With no history this is exactly 1.0, so cold-start priors
        # are not accidentally squared.
        learner_component = learner_posterior / max(base_prior[cause], 1e-12)
        likelihood = max(1e-6, attempt.cause_likelihoods.get(cause, 1.0))
        learner_components[cause] = learner_component
        likelihoods[cause] = likelihood
        scores[cause] = base_prior[cause] * learner_component * likelihood

    normalizer = sum(scores.values())
    if normalizer <= 0:
        raise ValueError("diagnosis produced no positive probability mass")

    hypotheses = []
    for cause in cause_ids:
        evidence = [
            "cohort_prior"
            if priors_by_cause[cause].sample_size > 0
            else "engineering_prior",
            "learner_history" if history_total > 0 else "learner_history_absent",
        ]
        if cause in attempt.cause_likelihoods:
            evidence.append("attempt_feature_likelihood")
        hypotheses.append(
            CauseHypothesis(
                cause_id=cause,
                probability=scores[cause] / normalizer,
                prior_component=base_prior[cause],
                prior_kind=(
                    "cohort_prior"
                    if priors_by_cause[cause].sample_size > 0
                    else "engineering_prior"
                ),
                learner_component=learner_components[cause],
                evidence_likelihood=likelihoods[cause],
                evidence=tuple(evidence),
            )
        )
    hypotheses.sort(key=lambda item: item.probability, reverse=True)

    provenance = {
        "attempt": attempt.provenance(),
        "prior_sources": [
            {
                "cause_id": p.cause_id,
                "source_id": p.cohort_id,
                "kind": "cohort_prior" if p.sample_size > 0 else "engineering_prior",
                "sample_size": p.sample_size,
                "source_version": p.source_version,
            }
            for p in prior_list
        ],
        "learner_history_version": history.source_version,
        "learner_history_exposure_count": history.exposure_count,
        "formula": "normalize(prior * learner_history_likelihood_ratio * evidence_likelihood)",
    }
    return DiagnosisResult(
        attempt_id=attempt.attempt_id,
        hypotheses=tuple(hypotheses),
        uncertainty=clamp(_entropy(h.probability for h in hypotheses), 0.0, 1.0),
        provenance=provenance,
        model_version="hierarchical-cause-baseline-v3",
    )
