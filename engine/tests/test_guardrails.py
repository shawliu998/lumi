import unittest

from hermes_kt.guardrails import (
    ModelTier,
    RoutingContext,
    can_accept_generated_diagnosis,
    route_model,
    validate_generated_diagnosis,
)


VALID = {
    "hypotheses": [
        {"cause_id": "formula_reversal", "probability": 0.7, "evidence_ids": ["option:B"]},
        {"cause_id": "calculation", "probability": 0.3, "evidence_ids": ["time:91"]},
    ],
    "next_probe": "same structure with trivial arithmetic",
    "evidence_summary": "B matches the inverted-formula distractor",
}


class RoutingAndGuardrailTests(unittest.TestCase):
    def test_complex_diagnosis_routes_to_strong_model(self):
        decision = route_model(
            RoutingContext(diagnosis_uncertainty=0.8, candidate_cause_count=3)
        )
        self.assertEqual(decision.tier, ModelTier.STRONG)
        self.assertFalse(decision.may_directly_update_mastery)

    def test_routine_generation_routes_to_balanced_model(self):
        decision = route_model(
            RoutingContext(diagnosis_uncertainty=0.25, candidate_cause_count=2)
        )
        self.assertEqual(decision.tier, ModelTier.BALANCED)

    def test_low_cost_output_requires_independent_probe(self):
        decision = route_model(
            RoutingContext(
                diagnosis_uncertainty=0.2,
                candidate_cause_count=2,
                requested_tier=ModelTier.LOW_COST,
            )
        )
        accepted, errors = can_accept_generated_diagnosis(decision, VALID)
        self.assertFalse(accepted)
        self.assertIn("independent verification", errors[0])
        accepted, errors = can_accept_generated_diagnosis(
            decision, VALID, independently_verified=True
        )
        self.assertTrue(accepted)
        self.assertEqual(errors, ())

    def test_schema_guard_rejects_unnormalized_or_unproven_claims(self):
        invalid = {
            "hypotheses": [
                {"cause_id": "formula_reversal", "probability": 0.8, "evidence_ids": []}
            ],
            "next_probe": "",
        }
        valid, errors = validate_generated_diagnosis(invalid)
        self.assertFalse(valid)
        self.assertGreaterEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()
