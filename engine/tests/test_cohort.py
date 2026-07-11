import unittest

from hermes_kt.cohort import (
    CohortAggregate,
    CohortPriorPolicy,
    build_cohort_priors,
)
from hermes_kt.diagnosis import diagnose_causes
from hermes_kt.models import AttemptEvidence, CausePrior


FALLBACKS = (
    CausePrior("ratio_only", 0.40, "engineering", 0, "expert-taxonomy-v1"),
    CausePrior("wrong_denominator", 0.35, "engineering", 0, "expert-taxonomy-v1"),
    CausePrior("increment_as_rate", 0.25, "engineering", 0, "expert-taxonomy-v1"),
)


class CohortPriorTests(unittest.TestCase):
    def test_eligible_aggregate_is_shrunk_and_provenance_carries_sample_size(self):
        build = build_cohort_priors(
            CohortAggregate(
                cohort_id="reviewed-2026-growth",
                item_type="资料分析/增长率",
                total_attempts=200,
                cause_counts={
                    "ratio_only": 20,
                    "wrong_denominator": 70,
                    "increment_as_rate": 10,
                },
                source_version="aggregate-v3",
                privacy_reviewed=True,
            ),
            FALLBACKS,
        )
        self.assertTrue(build.cohort_eligible)
        self.assertEqual(build.reason, "eligible_privacy_reviewed_aggregate")
        priors = {prior.cause_id: prior for prior in build.priors}
        self.assertGreater(priors["wrong_denominator"].probability, 0.60)
        self.assertEqual(priors["wrong_denominator"].sample_size, 200)

        result = diagnose_causes(
            AttemptEvidence(
                attempt_id="a1",
                learner_id="l1",
                item_id="q1",
                item_type="资料分析/增长率",
                correct=False,
                response_time_seconds=30,
            ),
            build.priors,
        )
        self.assertIn("cohort_prior", result.hypotheses[0].evidence)
        self.assertEqual(result.provenance["cohort_sources"][0]["sample_size"], 200)

    def test_small_cohort_fails_closed_without_exposing_counts(self):
        build = build_cohort_priors(
            CohortAggregate(
                cohort_id="too-small",
                item_type="资料分析/增长率",
                total_attempts=12,
                cause_counts={"wrong_denominator": 12},
                source_version="aggregate-v1",
                privacy_reviewed=True,
            ),
            FALLBACKS,
            CohortPriorPolicy(min_attempts=50),
        )
        self.assertFalse(build.cohort_eligible)
        self.assertEqual(build.reason, "below_minimum_attempt_threshold")
        self.assertTrue(all(prior.sample_size == 0 for prior in build.priors))
        self.assertNotIn("cause_counts", build.to_dict()["aggregate_summary"])

        result = diagnose_causes(
            AttemptEvidence(
                attempt_id="a2",
                learner_id="l1",
                item_id="q1",
                item_type="资料分析/增长率",
                correct=False,
                response_time_seconds=30,
            ),
            build.priors,
        )
        self.assertIn("engineering_prior", result.hypotheses[0].evidence)
        self.assertNotIn("cohort_prior", result.hypotheses[0].evidence)

    def test_unreviewed_aggregate_never_influences_prior(self):
        build = build_cohort_priors(
            CohortAggregate(
                cohort_id="unreviewed",
                item_type="资料分析/增长率",
                total_attempts=1000,
                cause_counts={"wrong_denominator": 1000},
                source_version="raw-export-v1",
                privacy_reviewed=False,
            ),
            FALLBACKS,
        )
        self.assertFalse(build.cohort_eligible)
        self.assertEqual(build.reason, "aggregate_not_privacy_reviewed")
        probabilities = [prior.probability for prior in build.priors]
        self.assertEqual(probabilities, [0.40, 0.35, 0.25])

    def test_unknown_taxonomy_cause_is_rejected(self):
        with self.assertRaises(ValueError):
            build_cohort_priors(
                CohortAggregate(
                    cohort_id="bad",
                    item_type="资料分析/增长率",
                    total_attempts=100,
                    cause_counts={"invented_cause": 10},
                    source_version="bad-v1",
                    privacy_reviewed=True,
                ),
                FALLBACKS,
            )

    def test_counts_cannot_exceed_attempts(self):
        with self.assertRaises(ValueError):
            CohortAggregate(
                cohort_id="invalid-counts",
                item_type="资料分析/增长率",
                total_attempts=10,
                cause_counts={"ratio_only": 6, "wrong_denominator": 5},
                source_version="invalid-v1",
                privacy_reviewed=True,
            )


if __name__ == "__main__":
    unittest.main()
