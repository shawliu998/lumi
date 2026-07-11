from __future__ import annotations

import copy
import json
import unittest
from collections import Counter
from pathlib import Path

from hermes_domains import ContractError, load_fixture_document, score_attempt, validate_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "fixtures"


def load_fixtures() -> list[dict]:
    return [load_fixture_document(path, fixture_root=FIXTURE_ROOT) for path in sorted(FIXTURE_ROOT.rglob("*.json"))]


class DomainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures()

    def test_representative_coverage(self) -> None:
        self.assertEqual(Counter(f["domain"] for f in self.fixtures), {"xingce": 15, "shenlun": 15, "interview": 12})
        modules = {f["module"] for f in self.fixtures}
        expected_prefixes = {
            "资料分析", "言语理解", "判断推理", "数量关系", "常识判断",
            "归纳概括", "综合分析", "提出对策", "应用文", "文章写作",
            "组织计划", "人际关系", "应急处突",
        }
        for prefix in expected_prefixes:
            self.assertTrue(any(module.startswith(prefix) for module in modules), prefix)
        # 综合分析在申论和面试中均应独立覆盖。
        self.assertTrue(any(f["domain"] == "interview" and f["module"].startswith("综合分析") for f in self.fixtures))

    def test_complete_14_by_3_scenario_matrix(self) -> None:
        required_paths = {
            "xingce": {"verbal", "judgment", "quantitative", "data_analysis", "common_political_knowledge"},
            "shenlun": {"summary", "comprehensive_analysis", "recommendation", "official_writing", "essay"},
            "interview": {"comprehensive_analysis", "organization", "interpersonal", "emergency"},
        }
        expected = {
            (domain, path, mode)
            for domain, paths in required_paths.items()
            for path in paths
            for mode in ("success", "ambiguous", "offline")
        }
        present = {(f["domain"], f["path"], f["mode"]) for f in self.fixtures}
        self.assertEqual(len(self.fixtures), 42)
        self.assertEqual(present, expected)
        self.assertEqual(len({f["fixture_id"] for f in self.fixtures}), 42)

    def test_every_fixture_validates(self) -> None:
        self.assertEqual(len(self.fixtures), 42)
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["fixture_id"]):
                validate_fixture(fixture)

    def test_rejects_ground_truth_cause_claim(self) -> None:
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["diagnosis"]["candidate_causes"][0]["is_ground_truth"] = True
        with self.assertRaisesRegex(ContractError, "ground truth"):
            validate_fixture(fixture)

    def test_rejects_non_independent_verification(self) -> None:
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["independent_verify"]["prompt"] = fixture["task"]["prompt"]
        with self.assertRaisesRegex(ContractError, "different prompt"):
            validate_fixture(fixture)


class DeterministicAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixtures = load_fixtures()

    def test_passing_sample_scores_higher_than_failing_sample(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["fixture_id"]):
                passing = score_attempt(fixture, fixture["samples"]["passing_response"])
                failing = score_attempt(fixture, fixture["samples"]["failing_response"])
                self.assertGreater(passing.score, failing.score)
                self.assertTrue(passing.passed)
                self.assertFalse(failing.passed)
                self.assertGreater(len(failing.cause_candidates), 0)

    def test_success_scenarios_pass_with_no_asserted_cause(self) -> None:
        success = [f for f in self.fixtures if f["mode"] == "success"]
        self.assertEqual(len(success), 14)
        for fixture in success:
            result = score_attempt(fixture, fixture["scenario_response"])
            self.assertTrue(result.passed, fixture["fixture_id"])
            self.assertEqual(result.cause_candidates, ())

    def test_ambiguous_scenarios_request_probe_and_keep_multiple_hypotheses(self) -> None:
        ambiguous = [f for f in self.fixtures if f["mode"] == "ambiguous"]
        self.assertEqual(len(ambiguous), 14)
        for fixture in ambiguous:
            result = score_attempt(fixture, fixture["scenario_response"])
            semantics = fixture["expected_semantics"]
            self.assertFalse(result.passed, fixture["fixture_id"])
            self.assertGreaterEqual(len(result.cause_candidates), semantics["minimum_candidates"])
            self.assertEqual(semantics["agent_action"], "request_discriminating_probe")
            self.assertTrue(fixture["probe"]["prompt"])
            self.assertTrue(all(not c.is_ground_truth for c in result.cause_candidates))

    def test_offline_scenarios_use_only_local_deterministic_fallback(self) -> None:
        offline = [f for f in self.fixtures if f["mode"] == "offline"]
        self.assertEqual(len(offline), 14)
        for fixture in offline:
            execution = fixture["execution"]
            self.assertEqual(execution["connectivity"], "offline")
            self.assertEqual(execution["cloud_calls_expected"], 0)
            self.assertFalse(execution["provider_invoked"])
            self.assertEqual(execution["fallback"], "deterministic_local")
            first = score_attempt(fixture, fixture["scenario_response"]).to_dict()
            second = score_attempt(fixture, fixture["scenario_response"]).to_dict()
            self.assertEqual(first, second)
            self.assertEqual(fixture["expected_semantics"]["score"], "deterministic_local")
            self.assertEqual(
                fixture["expected_semantics"]["agent_action"],
                "local_probe_then_defer_generative_feedback",
            )

    def test_replay_is_byte_stable(self) -> None:
        for fixture in self.fixtures:
            response = fixture["samples"]["failing_response"]
            first = score_attempt(fixture, response).to_dict()
            second = score_attempt(fixture, response).to_dict()
            self.assertEqual(first, second, fixture["fixture_id"])

    def test_all_candidates_remain_unconfirmed(self) -> None:
        for fixture in self.fixtures:
            result = score_attempt(fixture, fixture["samples"]["failing_response"])
            for candidate in result.cause_candidates:
                self.assertEqual(candidate.status, "unconfirmed_hypothesis")
                self.assertFalse(candidate.is_ground_truth)
            if result.cause_candidates:
                self.assertAlmostEqual(sum(c.probability for c in result.cause_candidates), 1.0)

    def test_score_observations_are_not_causal_labels(self) -> None:
        forbidden = {"cause", "misconception", "ground_truth"}
        for fixture in self.fixtures:
            result = score_attempt(fixture, fixture["samples"]["failing_response"])
            self.assertTrue(result.observations)
            for observation in result.observations:
                self.assertNotIn(observation.kind, forbidden)


if __name__ == "__main__":
    unittest.main()
