from __future__ import annotations

import copy
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from hermes_domains import (
    ContractError,
    load_fixture_document,
    score_attempt,
    score_verification_response,
    validate_fixture,
    validate_overlay,
)
from hermes_domains.text_semantics import has_affirmed_alias, has_negated_alias


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

    def test_rejects_unknown_and_duplicate_probe_targets(self) -> None:
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["probe"]["targets"].append("unknown-cause")
        with self.assertRaisesRegex(ContractError, "probe references unknown cause"):
            validate_fixture(fixture)
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["probe"]["targets"].append(fixture["probe"]["targets"][0])
        with self.assertRaisesRegex(ContractError, "probe targets must be unique"):
            validate_fixture(fixture)
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["probe"]["targets"].pop()
        with self.assertRaisesRegex(ContractError, "cover every authored cause"):
            validate_fixture(fixture)

    def test_rejects_incomplete_verification_contract(self) -> None:
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["independent_verify"].pop("response_mode")
        with self.assertRaisesRegex(ContractError, "response_mode"):
            validate_fixture(fixture)
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["independent_verify"]["samples"].pop("failing_response")
        with self.assertRaisesRegex(ContractError, "failing_response"):
            validate_fixture(fixture)

    def test_rejects_duplicate_probe_assessment_rules(self) -> None:
        fixture = copy.deepcopy(
            next(item for item in self.fixtures if item["path"] == "data_analysis")
        )
        cause_id = fixture["probe"]["targets"][0]
        rule = {"cause_id": cause_id, "support_if": {"any_terms": ["现期"]}}
        fixture["probe"]["assessment"] = {
            "schema_version": "hermes.probe-assessment.v1",
            "evaluator": "authored_terms_v1",
            "rules": [rule, copy.deepcopy(rule)],
        }
        with self.assertRaisesRegex(ContractError, "cause rules must be unique"):
            validate_fixture(fixture)
        fixture = copy.deepcopy(
            next(
                item
                for item in self.fixtures
                if item["probe"]["assessment"]["evaluator"] == "authored_terms_v1"
            )
        )
        fixture["probe"]["assessment"]["rules"][0]["support_if"]["all_terms"][0] = "错"
        with self.assertRaisesRegex(ContractError, "too short"):
            validate_fixture(fixture)

    def test_rejects_missing_assessment_samples_and_teaching_variants(self) -> None:
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["probe"].pop("assessment")
        with self.assertRaisesRegex(ContractError, "assessment"):
            validate_fixture(fixture)
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["probe"]["assessment"]["cause_samples"].pop()
        with self.assertRaisesRegex(ContractError, "samples must uniquely cover"):
            validate_fixture(fixture)
        fixture = copy.deepcopy(self.fixtures[0])
        fixture["teach"]["variants"].pop()
        with self.assertRaisesRegex(ContractError, "teaching variants"):
            validate_fixture(fixture)

    def test_overlay_rejects_unsafe_path_domain_and_provider_claims(self) -> None:
        overlay_path = FIXTURE_ROOT / "xingce" / "data_analysis_growth_offline.json"
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
        unsafe = copy.deepcopy(overlay)
        unsafe["extends"] = "../interview/comprehensive_ai_service.json"
        with self.assertRaisesRegex(ContractError, "same directory"):
            validate_overlay(unsafe)
        invalid_domain = copy.deepcopy(overlay)
        invalid_domain["domain"] = "bogus"
        with self.assertRaisesRegex(ContractError, "overlay domain"):
            validate_overlay(invalid_domain)
        invoked = copy.deepcopy(overlay)
        invoked["execution"]["provider_invoked"] = True
        with self.assertRaisesRegex(ContractError, "provider"):
            validate_overlay(invoked)

    def test_overlay_cannot_relabel_a_base_fixture_path(self) -> None:
        base_path = FIXTURE_ROOT / "xingce" / "data_analysis_growth.json"
        overlay_path = FIXTURE_ROOT / "xingce" / "data_analysis_growth_offline.json"
        base = json.loads(base_path.read_text(encoding="utf-8"))
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
        overlay["path"] = "verbal"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / base_path.name).write_text(
                json.dumps(base, ensure_ascii=False), encoding="utf-8"
            )
            candidate = root / overlay_path.name
            candidate.write_text(json.dumps(overlay, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "must match its base fixture"):
                load_fixture_document(candidate, fixture_root=root)


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

    def test_growth_distractors_rank_their_specific_candidate_first(self) -> None:
        fixture = next(
            item
            for item in self.fixtures
            if item["path"] == "data_analysis" and item["mode"] == "success"
        )
        expected = {
            "A": "denominator-current-base-confusion",
            "C": "increment-rate-confusion",
            "D": "ratio-growth-confusion",
        }
        for answer, cause_id in expected.items():
            with self.subTest(answer=answer):
                result = score_attempt(fixture, answer)
                self.assertEqual(result.cause_candidates[0].cause_id, cause_id)
                self.assertEqual(result.cause_candidates[0].status, "unconfirmed_hypothesis")

    def test_every_verification_contract_has_executable_positive_and_negative_samples(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["fixture_id"]):
                samples = fixture["independent_verify"]["samples"]
                passed, scorer = score_verification_response(
                    fixture, samples["passing_response"]
                )
                failed, failing_scorer = score_verification_response(
                    fixture, samples["failing_response"]
                )
                self.assertTrue(passed)
                self.assertFalse(failed)
                self.assertEqual(scorer, failing_scorer)

    def test_every_single_choice_verification_authors_visible_options(self) -> None:
        single_choice = [
            fixture
            for fixture in self.fixtures
            if fixture["independent_verify"]["response_mode"] == "single_choice"
        ]
        self.assertEqual(len(single_choice), 15)
        for fixture in single_choice:
            with self.subTest(fixture=fixture["fixture_id"]):
                condition = fixture["independent_verify"]["pass_condition"]
                self.assertEqual(condition["scorer"], "exact_option_v1")
                self.assertIn(condition["correct_option"], condition["options"])
                self.assertGreaterEqual(len(condition["options"]), 2)

    def test_every_resolved_fixture_has_full_probe_and_teaching_coverage(self) -> None:
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["fixture_id"]):
                cause_ids = {
                    item["cause_id"] for item in fixture["diagnosis"]["candidate_causes"]
                }
                assessment = fixture["probe"]["assessment"]
                assessed_ids = (
                    {item["cause_id"] for item in assessment.get("rules", [])}
                    or set(assessment.get("cause_map", {}).values())
                )
                self.assertEqual(set(fixture["probe"]["targets"]), cause_ids)
                self.assertEqual(assessed_ids, cause_ids)
                self.assertEqual(
                    {item["cause_id"] for item in assessment["cause_samples"]},
                    cause_ids,
                )
                self.assertEqual(
                    {item["cause_id"] for item in fixture["teach"]["variants"]},
                    cause_ids,
                )

    def test_text_rubrics_reject_authored_negation_attacks(self) -> None:
        text_fixtures = [fixture for fixture in self.fixtures if fixture["domain"] != "xingce"]
        self.assertEqual(len(text_fixtures), 27)
        for fixture in text_fixtures:
            with self.subTest(fixture=fixture["fixture_id"], stage="initial"):
                response = fixture["samples"]["adversarial_negation_response"]
                result = score_attempt(fixture, response)
                self.assertFalse(result.passed)
                self.assertEqual(result.score, 0.0)
            with self.subTest(fixture=fixture["fixture_id"], stage="verification"):
                response = fixture["independent_verify"]["samples"][
                    "adversarial_negation_response"
                ]
                self.assertFalse(score_verification_response(fixture, response)[0])
                condition = fixture["independent_verify"]["pass_condition"]
                groups = condition.get("required_dimensions", condition.get("required_slots", []))
                self.assertTrue(
                    all(
                        not has_affirmed_alias(response, group["aliases"])
                        for group in groups
                    )
                )

    def test_text_rubrics_reject_action_cancellation_attacks(self) -> None:
        text_fixtures = [fixture for fixture in self.fixtures if fixture["domain"] != "xingce"]
        prefixes = ("必须取消", "应当避免", "应当放弃", "必须停止", "应当废除")
        self.assertEqual(len(text_fixtures), 27)
        for fixture in text_fixtures:
            condition = fixture["independent_verify"]["pass_condition"]
            groups = condition.get("required_dimensions", condition.get("required_slots", []))
            for prefix in prefixes:
                with self.subTest(fixture=fixture["fixture_id"], prefix=prefix, stage="initial"):
                    attack = "；".join(
                        f"{prefix}{criterion['keywords'][0]}"
                        for criterion in fixture["scoring"]["criteria"]
                    )
                    result = score_attempt(fixture, attack)
                    self.assertFalse(result.passed)
                    self.assertEqual(result.score, 0.0)
                with self.subTest(fixture=fixture["fixture_id"], prefix=prefix, stage="verification"):
                    attack = "；".join(
                        f"{prefix}{group['aliases'][0]}" for group in groups
                    )
                    self.assertFalse(score_verification_response(fixture, attack)[0])
                    self.assertTrue(
                        all(not has_affirmed_alias(attack, group["aliases"]) for group in groups)
                    )

    def test_chinese_negation_is_local_and_double_negation_is_not_lost(self) -> None:
        self.assertFalse(has_affirmed_alias("不应保留人工", ("保留人工",)))
        self.assertTrue(has_negated_alias("不应保留人工", ("保留人工",)))
        self.assertFalse(has_affirmed_alias("提高效率、保留人工，以上都不应做", ("提高效率",)))
        self.assertFalse(has_affirmed_alias("提高效率、保留人工，以上都不应做", ("保留人工",)))
        self.assertTrue(has_affirmed_alias("不能不保留人工", ("保留人工",)))
        self.assertTrue(has_affirmed_alias("不能忽视噪声问题", ("噪声",)))
        self.assertTrue(has_affirmed_alias("不应取消人工窗口", ("人工窗口",)))
        self.assertTrue(has_affirmed_alias("应当避免取消人工窗口", ("人工窗口",)))
        self.assertFalse(has_affirmed_alias("必须取消人工窗口", ("人工窗口",)))
        self.assertTrue(has_negated_alias("必须取消人工窗口", ("人工窗口",)))
        self.assertFalse(has_affirmed_alias("应当避免人工窗口", ("人工窗口",)))
        self.assertFalse(has_affirmed_alias("人工窗口必须停止", ("人工窗口",)))
        self.assertTrue(has_affirmed_alias("避免遗漏并保留人工窗口", ("人工窗口",)))
        self.assertTrue(has_affirmed_alias("不能越多越好", ("不能越多越好",)))
        self.assertTrue(has_affirmed_alias("不提高效率，但保留人工", ("保留人工",)))
        self.assertTrue(
            has_affirmed_alias(
                "绿色出行有价值、占道有成本，以上不能一概而论。", ("绿色出行",)
            )
        )


if __name__ == "__main__":
    unittest.main()
