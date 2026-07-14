import unittest

from hermes_kt.assistance import (
    ASSISTANCE_CALIBRATION_STATUS,
    ASSISTANCE_LEVELS,
    ASSISTANCE_POLICY_VERSION,
    assistance_policy_manifest,
    next_assistance_level,
)


class AssistancePolicyTests(unittest.TestCase):
    def test_six_levels_are_ordered_and_full_explanation_has_zero_credit(self):
        self.assertEqual(
            [level.action for level in ASSISTANCE_LEVELS],
            [
                "retry",
                "locate_evidence",
                "rule_hint",
                "analogous_example",
                "worked_step",
                "full_explanation",
            ],
        )
        weights = [level.diagnostic_evidence_weight for level in ASSISTANCE_LEVELS]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(weights[-1], 0.0)
        self.assertTrue(all(0 <= weight <= 1 for weight in weights))

    def test_policy_is_explicitly_uncalibrated_engineering_policy(self):
        manifest = assistance_policy_manifest()
        self.assertEqual(manifest["policy_version"], ASSISTANCE_POLICY_VERSION)
        self.assertEqual(manifest["calibration_status"], ASSISTANCE_CALIBRATION_STATUS)
        self.assertEqual(manifest["assisted_verification_mastery_credit"], 0.0)

    def test_server_side_next_level_fails_closed_after_six(self):
        self.assertEqual(next_assistance_level(0).action, "retry")
        self.assertEqual(next_assistance_level(5).action, "full_explanation")
        with self.assertRaises(LookupError):
            next_assistance_level(6)


if __name__ == "__main__":
    unittest.main()
