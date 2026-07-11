from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from .models import CausePrior


@dataclass(frozen=True)
class CohortAggregate:
    """Privacy-reviewed aggregate counts, never learner-level attempt rows."""

    cohort_id: str
    item_type: str
    total_attempts: int
    cause_counts: Mapping[str, int]
    source_version: str
    privacy_reviewed: bool = False

    def __post_init__(self) -> None:
        if not self.cohort_id or not self.item_type or not self.source_version:
            raise ValueError("cohort_id, item_type, and source_version are required")
        if self.total_attempts < 0:
            raise ValueError("total_attempts cannot be negative")
        if any(not cause_id or count < 0 for cause_id, count in self.cause_counts.items()):
            raise ValueError("cause counts require non-empty ids and non-negative values")
        if sum(self.cause_counts.values()) > self.total_attempts:
            raise ValueError("cause counts cannot exceed total_attempts")


@dataclass(frozen=True)
class CohortPriorPolicy:
    min_attempts: int = 50
    shrinkage_strength: float = 20.0

    def __post_init__(self) -> None:
        if self.min_attempts < 1:
            raise ValueError("min_attempts must be positive")
        if self.shrinkage_strength <= 0:
            raise ValueError("shrinkage_strength must be positive")


@dataclass(frozen=True)
class CohortPriorBuild:
    priors: tuple[CausePrior, ...]
    cohort_eligible: bool
    reason: str
    policy: CohortPriorPolicy
    aggregate_summary: Mapping[str, object]
    formula: str

    def to_dict(self) -> dict[str, object]:
        return {
            "priors": [asdict(prior) for prior in self.priors],
            "cohort_eligible": self.cohort_eligible,
            "reason": self.reason,
            "policy": asdict(self.policy),
            "aggregate_summary": dict(self.aggregate_summary),
            "formula": self.formula,
        }


def build_cohort_priors(
    aggregate: CohortAggregate,
    fallback_priors: Sequence[CausePrior],
    policy: CohortPriorPolicy | None = None,
) -> CohortPriorBuild:
    """Build shrunk misconception priors or fail closed to engineering priors.

    The input contains aggregate counts only. Counts below the privacy/evidence
    threshold are not exposed in the result and cannot influence diagnosis.
    """

    policy = policy or CohortPriorPolicy()
    fallbacks = tuple(fallback_priors)
    if not fallbacks:
        raise ValueError("at least one fallback prior is required")
    cause_ids = [prior.cause_id for prior in fallbacks]
    if len(set(cause_ids)) != len(cause_ids):
        raise ValueError("fallback cause ids must be unique")
    fallback_total = sum(prior.probability for prior in fallbacks)
    if fallback_total <= 0:
        raise ValueError("fallback probabilities must have positive total")
    unknown = set(aggregate.cause_counts) - set(cause_ids)
    if unknown:
        raise ValueError(f"aggregate contains unknown cause ids: {sorted(unknown)}")

    fallback_probabilities = {
        prior.cause_id: prior.probability / fallback_total for prior in fallbacks
    }
    aggregate_summary = {
        "cohort_id": aggregate.cohort_id,
        "item_type": aggregate.item_type,
        "source_version": aggregate.source_version,
        "total_attempts": aggregate.total_attempts,
        "privacy_reviewed": aggregate.privacy_reviewed,
        "cause_count_fields": len(aggregate.cause_counts),
    }

    if not aggregate.privacy_reviewed:
        return _fallback_build(
            fallbacks,
            policy,
            aggregate_summary,
            "aggregate_not_privacy_reviewed",
        )
    if aggregate.total_attempts < policy.min_attempts:
        return _fallback_build(
            fallbacks,
            policy,
            aggregate_summary,
            "below_minimum_attempt_threshold",
        )

    observed_total = sum(aggregate.cause_counts.values())
    if observed_total <= 0:
        return _fallback_build(
            fallbacks,
            policy,
            aggregate_summary,
            "no_observed_cause_counts",
        )

    denominator = observed_total + policy.shrinkage_strength
    priors = tuple(
        CausePrior(
            cause_id=cause_id,
            probability=(
                aggregate.cause_counts.get(cause_id, 0)
                + policy.shrinkage_strength * fallback_probabilities[cause_id]
            )
            / denominator,
            cohort_id=aggregate.cohort_id,
            sample_size=aggregate.total_attempts,
            source_version=aggregate.source_version,
        )
        for cause_id in cause_ids
    )
    return CohortPriorBuild(
        priors=priors,
        cohort_eligible=True,
        reason="eligible_privacy_reviewed_aggregate",
        policy=policy,
        aggregate_summary=aggregate_summary,
        formula="(aggregate_cause_count + shrinkage_strength * engineering_prior) / "
        "(aggregate_cause_count_total + shrinkage_strength)",
    )


def _fallback_build(
    fallbacks: tuple[CausePrior, ...],
    policy: CohortPriorPolicy,
    aggregate_summary: Mapping[str, object],
    reason: str,
) -> CohortPriorBuild:
    total = sum(prior.probability for prior in fallbacks)
    priors = tuple(
        CausePrior(
            cause_id=prior.cause_id,
            probability=prior.probability / total,
            cohort_id="engineering-fallback",
            sample_size=0,
            source_version=prior.source_version,
        )
        for prior in fallbacks
    )
    return CohortPriorBuild(
        priors=priors,
        cohort_eligible=False,
        reason=reason,
        policy=policy,
        aggregate_summary=aggregate_summary,
        formula="normalized_engineering_prior_only",
    )
