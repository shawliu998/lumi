import json
import unittest
from pathlib import Path

from hermes_kt.diagnosis import diagnose_causes
from hermes_kt.models import AttemptEvidence, CausePrior, LearnerCauseHistory
from hermes_kt.tool_api import HermesKTTool


FIXTURE = Path(__file__).parent / "fixtures" / "growth_rate_case.json"


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_distractor_and_history_raise_specific_cause(self):
        result = diagnose_causes(
            AttemptEvidence(**self.payload["attempt"]),
            [CausePrior(**row) for row in self.payload["priors"]],
            LearnerCauseHistory(**self.payload["history"]),
        )
        self.assertEqual(result.hypotheses[0].cause_id, "base_current_reversal")
        self.assertGreater(result.hypotheses[0].probability, 0.75)
        self.assertAlmostEqual(sum(x.probability for x in result.hypotheses), 1.0)
        self.assertGreaterEqual(result.uncertainty, 0.0)
        self.assertLessEqual(result.uncertainty, 1.0)
        self.assertEqual(result.provenance["attempt"]["selected_option"], "B")
        self.assertEqual(result.provenance["prior_sources"][0]["sample_size"], 0)
        self.assertEqual(result.provenance["prior_sources"][0]["kind"], "engineering_prior")

    def test_tool_boundary_is_json_friendly(self):
        output = HermesKTTool().diagnose(self.payload)
        json.dumps(output)
        self.assertEqual(output["model_version"], "hierarchical-cause-baseline-v3")
        serialized = json.dumps(output, ensure_ascii=False)
        self.assertNotIn("cohort_component", serialized)
        self.assertNotIn("cohort_sources", serialized)

    def test_invalid_empty_prior_is_rejected(self):
        with self.assertRaises(ValueError):
            diagnose_causes(AttemptEvidence(**self.payload["attempt"]), [])


if __name__ == "__main__":
    unittest.main()
