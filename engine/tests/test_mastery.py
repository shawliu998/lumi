import json
import unittest

from hermes_kt.mastery import update_skill_state
from hermes_kt.models import AttemptEvidence, SkillParameters, SkillState
from hermes_kt.tool_api import HermesKTTool
from hermes_kt.verification import evaluate_intervention


def attempt(identifier, correct, *, independent=True, hints=0):
    return AttemptEvidence(
        attempt_id=identifier,
        learner_id="learner-1",
        item_id=f"item-{identifier}",
        item_type="资料分析/增长率",
        correct=correct,
        response_time_seconds=60,
        independently_answered=independent,
        hints_used=hints,
    )


class MasteryTests(unittest.TestCase):
    def setUp(self):
        self.params = SkillParameters(skill_id="growth_rate")
        self.state = SkillState(learner_id="learner-1", skill_id="growth_rate")

    def test_correct_attempt_increases_mastery_and_records_components(self):
        updated = update_skill_state(self.state, attempt("1", True), self.params)
        self.assertGreater(updated.mastery, self.state.mastery)
        self.assertEqual(updated.evidence_count, 1)
        self.assertLess(updated.uncertainty, self.state.uncertainty)
        self.assertEqual(
            set(updated.provenance[-1]["components"]), {"bkt", "pfa", "irt_1pl"}
        )

    def test_incorrect_attempt_reduces_mastery(self):
        strong = SkillState(
            learner_id="learner-1",
            skill_id="growth_rate",
            bkt_mastery=0.8,
            successes=5,
            mastery=0.8,
            evidence_count=5,
            uncertainty=0.3,
        )
        updated = update_skill_state(strong, attempt("2", False), self.params)
        self.assertLess(updated.mastery, strong.mastery)
        self.assertEqual(updated.failures, 1)

    def test_independent_verification_can_mark_teaching_effective(self):
        post, result = evaluate_intervention(
            "lesson-1", self.state, attempt("3", True), self.params
        )
        self.assertGreater(post.mastery, self.state.mastery)
        self.assertTrue(result.independently_verified)
        self.assertTrue(result.effective)

    def test_hinted_verification_is_inconclusive(self):
        _, result = evaluate_intervention(
            "lesson-2",
            self.state,
            attempt("4", True, independent=False, hints=1),
            self.params,
        )
        self.assertFalse(result.independently_verified)
        self.assertIsNone(result.effective)

    def test_tool_update_is_serializable(self):
        payload = {
            "state": self.state.to_dict(),
            "attempt": {
                "attempt_id": "5",
                "learner_id": "learner-1",
                "item_id": "item-5",
                "item_type": "资料分析/增长率",
                "correct": True,
                "response_time_seconds": 42,
            },
            "parameters": {"skill_id": "growth_rate"},
        }
        output = HermesKTTool().update_mastery(payload)
        json.dumps(output)
        self.assertEqual(output["evidence_count"], 1)


if __name__ == "__main__":
    unittest.main()
