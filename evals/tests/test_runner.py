from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


RUNNER_PATH = Path(__file__).resolve().parents[1] / "run_all.py"
SPEC = importlib.util.spec_from_file_location("hermes_eval_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class JsonSchemaSubsetTests(unittest.TestCase):
    def test_rejects_missing_and_unknown_properties(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {"name": {"type": "string", "minLength": 1}},
        }
        self.assertTrue(runner.validate_json({}, schema))
        self.assertTrue(runner.validate_json({"name": "ok", "extra": 1}, schema))
        self.assertEqual(runner.validate_json({"name": "ok"}, schema), [])

    def test_contract_fixture_is_valid(self) -> None:
        fixture = runner.load_json(runner.FIXTURE_DIR / "xingce_data_analysis_ambiguous.json")
        schema = runner.load_json(runner.CONTRACT_DIR / "representative_case.schema.json")
        self.assertEqual(runner.validate_json(fixture, schema), [])

    def test_local_refs_all_of_and_bounds_fail_closed(self) -> None:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "items"],
            "properties": {
                "score": {"allOf": [{"$ref": "#/$defs/bounded"}]},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"$ref": "#/$defs/bounded"},
                },
            },
            "$defs": {
                "bounded": {"type": "number", "minimum": 0, "maximum": 1}
            },
        }
        self.assertEqual(
            runner.validate_json({"score": 0.5, "items": [0, 1]}, schema), []
        )
        errors = runner.validate_json({"score": 2, "items": [-1, 0, 1]}, schema)
        self.assertTrue(any("above maximum" in error for error in errors))
        self.assertTrue(any("below minimum" in error for error in errors))
        self.assertTrue(any("longer than maxItems" in error for error in errors))

    def test_one_of_conditionals_lengths_and_uniqueness_fail_closed(self) -> None:
        schema = {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "value", "tags"],
                    "properties": {
                        "kind": {"const": "text"},
                        "value": {"type": "string", "maxLength": 3},
                        "tags": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string"},
                        },
                    },
                    "if": {
                        "properties": {"kind": {"const": "text"}},
                        "required": ["kind"],
                    },
                    "then": {
                        "properties": {"value": {"pattern": "^[a-z]+$"}}
                    },
                },
                {"type": "null"},
            ]
        }
        self.assertEqual(
            runner.validate_json(
                {"kind": "text", "value": "abc", "tags": ["a", "b"]},
                schema,
            ),
            [],
        )
        errors = runner.validate_json(
            {"kind": "text", "value": "ABCD", "tags": ["a", "a"]},
            schema,
        )
        self.assertTrue(any("oneOf" in error for error in errors))
        self.assertTrue(
            runner.validate_json(
                {"kind": "text", "value": "abc", "tags": []},
                {"oneOf": [{"type": "object"}, {"type": "object"}]},
            )
        )

    def test_new_contracts_close_every_typed_object(self) -> None:
        def assert_closed(schema: object, path: str = "$") -> None:
            if isinstance(schema, dict):
                declared_type = schema.get("type")
                if declared_type == "object" or (
                    isinstance(declared_type, list) and "object" in declared_type
                ):
                    self.assertIs(
                        schema.get("additionalProperties"),
                        False,
                        f"open object at {path}",
                    )
                for key, value in schema.items():
                    assert_closed(value, f"{path}.{key}")
            elif isinstance(schema, list):
                for index, value in enumerate(schema):
                    assert_closed(value, f"{path}[{index}]")

        for name in (
            "assistance-result.schema.json",
            "misconception-dossier.schema.json",
            "today-plan.schema.json",
            "review-schedule.schema.json",
            "source-document.schema.json",
            "source-span.schema.json",
            "study-artifact-content.schema.json",
            "study-artifact.schema.json",
            "study-candidate-skill-link.schema.json",
            "study-pack-attempt-result.schema.json",
            "study-pack-attempt.schema.json",
            "study-pack-detail.schema.json",
            "study-pack.schema.json",
            "study-verifier-decision.schema.json",
        ):
            assert_closed(runner.load_json(runner.CONTRACT_DIR / name))

    def test_assistance_contract_rejects_verification_and_client_claims(self) -> None:
        schema = runner.load_json(
            runner.CONTRACT_DIR / "assistance-result.schema.json"
        )
        valid = {
            "schema_version": "hermes.assistance-result.v1",
            "run_id": "run-1",
            "state": "awaiting_probe",
            "state_version": 6,
            "prompt_instance_id": "run-1:probe:1",
            "assistance": {
                "ordinal": 1,
                "action": "retry",
                "title": "Retry",
                "content": "Try once more.",
                "target_cause_ids": ["cause-1"],
                "content_version": "content-v1",
                "policy_version": "assistance-evidence-policy.v1",
                "diagnostic_evidence_weight": 1.0,
                "calibration_status": "engineering_policy_unvalidated",
                "phase": "probe",
                "independence_effect": "discounts_probe_evidence",
            },
            "remaining_levels": 5,
            "idempotent_replay": False,
            "trace_verified": True,
            "links": {
                "respond": "/v1/attempts/run-1/responses",
                "misconception": "/v1/misconceptions/run-1",
                "trace": "/v1/runs/run-1/trace",
            },
        }
        self.assertEqual(runner.validate_json(valid, schema), [])
        invalid = json.loads(json.dumps(valid))
        invalid["state"] = "awaiting_verification"
        invalid["state_version"] = 0
        invalid["assistance"]["phase"] = "verification"
        invalid["assistance"]["diagnostic_evidence_weight"] = 9
        invalid["assistance"]["confirmed_cause"] = "cause-1"
        self.assertGreaterEqual(len(runner.validate_json(invalid, schema)), 5)

    def test_dossier_contract_rejects_causal_cohort_and_numeric_claims(self) -> None:
        schema = runner.load_json(
            runner.CONTRACT_DIR / "misconception-dossier.schema.json"
        )
        event_hash = "a" * 64
        fixture_hash = "b" * 64
        valid = {
            "schema_version": "hermes.misconception-dossier.v1",
            "projection_version": "misconception-dossier-projection.v1",
            "dossier_id": "run-1",
            "run_id": "run-1",
            "fixture_id": "fixture-1",
            "domain": "xingce",
            "module": "data-analysis",
            "skills": [{"skill_id": "skill-1", "weight": 1.0}],
            "state": "awaiting_probe",
            "learning_status": "no_misconception_observed",
            "observations": {
                "score": {"score": 1, "max_score": 1, "passed": True},
                "items": [
                    {
                        "observation_id": "answer_correct",
                        "kind": "score",
                        "value": True,
                        "evidence": "exact comparison",
                    }
                ],
                "event": {"seq": 1, "kind": "phase_completed", "event_hash": event_hash},
            },
            "hypothesis_semantics": "ranked_candidates_never_causal_ground_truth",
            "hypotheses": [],
            "uncertainty": 0,
            "probe": {
                "prompt": "Retention check",
                "targets": ["retention"],
                "assessment_status": "not_assessed",
                "event": None,
            },
            "assistance_history": [],
            "resolution": {
                "status": "no_misconception_observed",
                "independently_verified": False,
                "effective": None,
                "verification_event": None,
                "update_event": None,
                "reflection_event": None,
                "note": "No cause is confirmed.",
            },
            "next_action": {
                "action": "answer_targeted_probe",
                "prompt_instance_id": "run-1:probe:1",
            },
            "cohort_evidence": {
                "status": "unavailable",
                "sample_size": 0,
                "reason": "No eligible sample.",
                "display_policy": "Do not show population claims.",
            },
            "provenance": {
                "trace_verified": True,
                "source_trace_version": 5,
                "source_event_hash": event_hash,
                "fixture_content_sha256": fixture_hash,
            },
            "links": {
                "trace": "/v1/runs/run-1/trace",
                "replay": "/v1/runs/run-1/replay",
            },
        }
        self.assertEqual(runner.validate_json(valid, schema), [])
        invalid = json.loads(json.dumps(valid))
        invalid["uncertainty"] = 3
        invalid["confirmed_cause"] = "cause-1"
        invalid["cohort_evidence"]["peer_error_rate"] = 0.8
        invalid["provenance"]["source_trace_version"] = 0
        invalid["provenance"]["source_event_hash"] = "not-a-hash"
        self.assertGreaterEqual(len(runner.validate_json(invalid, schema)), 5)

    def test_schedule_contracts_pin_truthful_identifier_and_window_shapes(self) -> None:
        today = runner.load_json(
            runner.CONTRACT_DIR / "today-plan.schema.json"
        )
        review = runner.load_json(
            runner.CONTRACT_DIR / "review-schedule.schema.json"
        )
        today_task = today["$defs"]["task"]
        review_task = review["$defs"]["task"]
        workload = today["$defs"]["basis"]["properties"][
            "workload_guardrail"
        ]
        self.assertIn("max_non_accepted_tasks", workload["required"])
        self.assertNotIn("max_new_tasks", workload["properties"])
        self.assertIn("ordinal", today_task["required"])
        self.assertNotIn("ordinal", review_task["required"])
        for task in (today_task, review_task):
            self.assertEqual(
                task["properties"]["policy_offset_days"]["enum"], [1, 3]
            )
        for schema in (today, review):
            activity = schema["$defs"]["activity_ref"]
            self.assertIn("novelty_status", activity["required"])
            self.assertEqual(
                activity["properties"]["novelty_status"]["const"],
                "same_fixture_retest_not_novel_item",
            )
            claim_status = schema["$defs"]["evidence_ref"]["properties"][
                "claim_status"
            ]["enum"]
            self.assertNotIn("refuted_hypothesis", claim_status)
            window_properties = schema["$defs"]["schedule_window"][
                "properties"
            ]
            self.assertNotIn("base_offset_days", window_properties)
            self.assertNotIn("applied_offset_days", window_properties)


class EvidenceIntegrationTests(unittest.TestCase):
    def test_all_persisted_and_tracked_reports_are_safe(self) -> None:
        self.assertEqual(runner._tracked_report_safety_findings(), [])
        self.assertEqual(
            runner._report_safety_findings(runner.iter_persisted_report_files()), []
        )

    def test_engine_evidence_and_trace_are_real_and_valid(self) -> None:
        context = runner.Context()
        context.compute()
        self.assertIsNotNone(context.diagnosis)
        self.assertIsNotNone(context.update)
        self.assertIsNotNone(context.verification)
        trace = context.build_trace()
        schema = runner.load_json(runner.CONTRACT_DIR / "trajectory.schema.json")
        self.assertEqual(runner.validate_json(trace, schema), [])
        self.assertEqual(trace["evaluation"]["independent_transfer"], True)
        self.assertIn("formula_version", trace["state_transition"])

    def test_golden_fixture_uses_only_sample_zero_engineering_priors(self) -> None:
        context = runner.Context()
        context.compute()
        assert context.diagnosis is not None
        sources = context.diagnosis["provenance"]["prior_sources"]
        self.assertTrue(sources)
        self.assertTrue(
            all(
                source["kind"] == "engineering_prior"
                and source["sample_size"] == 0
                and "synthetic" in source["source_version"]
                for source in sources
            )
        )
        for hypothesis in context.diagnosis["hypotheses"]:
            self.assertEqual(hypothesis["prior_kind"], "engineering_prior")
            self.assertIn("engineering_prior", hypothesis["evidence"])
            self.assertNotIn("cohort_prior", hypothesis["evidence"])
        serialized = runner.canonical_json(context.diagnosis)
        self.assertNotIn("cohort_component", serialized)
        self.assertNotIn("cohort_sources", serialized)

    def test_domain_matrix_is_complete_and_real(self) -> None:
        result = runner.gate_fixtures(runner.Context())
        self.assertEqual(result.status, "pass")
        self.assertIn("42/42", result.summary)

    def test_report_contract_and_status_precedence(self) -> None:
        report, _ = runner.run_gates(["contracts", "fixtures"])
        self.assertEqual(report["overall_status"], "pass")
        schema = runner.load_json(runner.CONTRACT_DIR / "release_report.schema.json")
        self.assertEqual(runner.validate_json(report, schema), [])

    def test_real_integrated_teaching_modes_close_the_gate(self) -> None:
        context = runner.Context()
        result = runner.gate_teaching_transfer(context)
        self.assertEqual(result.status, "pass", result.evidence)
        probe = context.integration_probe
        self.assertIsNotNone(probe)
        assert probe is not None
        self.assertEqual(set(probe["runs"]), {"success", "ambiguous", "offline"})
        self.assertTrue(all(run["replay"]["trace_verified"] for run in probe["runs"].values()))

    def test_real_http_continuation_closes_the_gate(self) -> None:
        result = runner.gate_attempt_continuation(runner.Context())
        self.assertEqual(result.status, "pass", result.evidence)
        self.assertIn("awaiting_probe", result.summary)

    def test_real_http_progressive_assistance_closes_the_gate(self) -> None:
        context = runner.Context()
        result = runner.gate_progressive_assistance(context)
        self.assertEqual(result.status, "pass", result.evidence)
        compact = runner._compact_attempt_api_evidence(context.attempt_api_probe or {})
        levels = compact["cases"]["progressive_assistance"]["delivered_levels"]
        self.assertEqual(len(levels), 6)
        self.assertEqual(levels[-1]["action"], "full_explanation")
        self.assertEqual(levels[-1]["diagnostic_evidence_weight"], 0.0)
        self.assertEqual([item["remaining_levels"] for item in levels], [5, 4, 3, 2, 1, 0])
        self.assertEqual(context.service_tests_probe["status"], "pass")

    def test_real_http_misconception_dossier_closes_the_gate(self) -> None:
        context = runner.Context()
        result = runner.gate_misconception_dossier(context)
        self.assertEqual(result.status, "pass", result.evidence)
        compact = runner._compact_attempt_api_evidence(context.attempt_api_probe or {})
        dossier = compact["cases"]["misconception_dossier"]
        self.assertEqual(
            dossier["claim_statuses"]["ratio-growth-confusion"],
            "supported_hypothesis",
        )
        self.assertEqual(dossier["cohort_evidence_status"], "unavailable")
        self.assertEqual(dossier["correct_hypothesis_count"], 0)

        raw = deepcopy(
            context.attempt_api_probe["cases"]["misconception_dossier"]["dossier"][
                "payload"
            ]
        )
        raw["state"] = "processing_probe"
        raw["learning_status"] = "processing_probe_response"
        raw["resolution"]["status"] = "processing_probe_response"
        raw["next_action"] = {
            "action": "restart_attempt_after_processing_failure",
            "target": "/v1/attempts",
            "reason": "The prior probe response was consumed but processing did not finish.",
        }
        schema = runner.load_json(
            runner.CONTRACT_DIR / "misconception-dossier.schema.json"
        )
        self.assertEqual(runner.validate_json(raw, schema), [])
        self.assertTrue(dossier["provenance_matches_trace"])
        self.assertTrue(dossier["correct_provenance_matches_trace"])
        self.assertTrue(dossier["correct_contract_valid"])
        self.assertTrue(dossier["pii_redacted"])
        self.assertGreater(
            dossier["evidence_ref_counts"]["ratio-growth-confusion"]["supporting"],
            0,
        )
        self.assertGreater(
            dossier["evidence_ref_counts"]["denominator-current-base-confusion"]["refuting"],
            0,
        )
        self.assertEqual(context.service_tests_probe["status"], "pass")

    def test_real_http_today_plan_and_review_schedule_close_the_gate(self) -> None:
        context = runner.Context()
        result = runner.gate_today_plan_schedule(context)
        self.assertEqual(result.status, "pass", result.evidence)
        probe = context.schedule_api_probe
        self.assertIsNotNone(probe)
        assert probe is not None
        self.assertGreater(probe["assertion_count"], 100)
        self.assertEqual(probe["case_count"], 23)
        self.assertTrue(
            all(case["status"] == "pass" for case in probe["cases"].values())
        )
        synthetic = probe["cases"]["synthetic_origin_excluded"]
        self.assertEqual(synthetic["seed_path"], "internal_evaluation_fixture")
        self.assertEqual(synthetic["evidence_origin"], "evaluation_fixture")
        self.assertEqual(synthetic["public_run_status"], 404)
        self.assertFalse(synthetic["capabilities_run_advertised"])
        self.assertFalse(synthetic["offline_demo_feature_advertised"])
        self.assertTrue(synthetic["synthetic_origin_excluded"])
        self.assertEqual(
            synthetic["learner_projection_counts"],
            {
                "health_runs": 0,
                "skills": 0,
                "misconceptions": 0,
                "review_tasks": 0,
                "today_tasks": 0,
            },
        )
        self.assertEqual(synthetic["dossier_status"], 404)
        for human_case in (
            "failed_with_candidate",
            "successful_transfer",
            "correct_first_failed_transfer",
        ):
            self.assertEqual(
                probe["cases"][human_case]["source"],
                "real_POST_v1_attempts_human_local_interactive",
            )
        self.assertEqual(
            probe["cases"]["strict_input"]["sensitive_id_classes"],
            [
                "github_classic",
                "github_fine_grained",
                "google_api_key",
                "national_id",
                "npm_token",
                "openai_key",
                "phone",
                "slack_bot_token",
            ],
        )
        self.assertEqual(
            probe["cases"]["successful_transfer"]["task_kind"],
            "delayed_retention",
        )
        self.assertEqual(
            probe["cases"]["overdue_plus_1_old_evidence"][
                "recent_evidence_count"
            ],
            0,
        )
        self.assertEqual(
            probe["cases"]["three_failure_recovery_load"][
                "review_schedule_count"
            ],
            3,
        )
        self.assertEqual(
            probe["cases"]["three_failure_recovery_load"][
                "three_day_unique_task_count"
            ],
            3,
        )
        self.assertEqual(
            probe["cases"]["partial_migration_restart"][
                "healthy_reopen_total_changes"
            ],
            0,
        )
        self.assertEqual(
            probe["cases"]["partial_migration_restart"][
                "legacy_create_receipt_status"
            ],
            409,
        )
        self.assertLessEqual(
            probe["cases"]["dynamic_arrival_fairness"]["oldest_return_day"],
            8,
        )
        self.assertEqual(
            probe["cases"]["accepted_budget_retry"]["error_code"],
            "budget_below_accepted_commitment",
        )
        self.assertGreater(
            probe["cases"]["multiple_accepted_commitments"][
                "accepted_commitment_count"
            ],
            probe["cases"]["multiple_accepted_commitments"][
                "max_non_accepted_tasks"
            ],
        )
        self.assertTrue(
            probe["cases"]["user_marked_completion"][
                "skill_report_unchanged"
            ]
        )

    def test_schedule_probe_is_cached_per_context(self) -> None:
        result = {"status": "pass", "errors": [], "cases": {}}
        with patch.object(runner, "_probe_schedule_api", return_value=result) as probe:
            context = runner.Context()
            self.assertIs(context.probe_schedule_api(), result)
            self.assertIs(context.probe_schedule_api(), result)
        probe.assert_called_once_with()

    def test_schedule_gate_no_write_does_not_create_reports(self) -> None:
        original_report_dir = runner.REPORT_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                absent_report_dir = Path(directory) / "reports-must-stay-absent"
                runner.REPORT_DIR = absent_report_dir
                self.assertEqual(
                    runner.main(["--gate", "today_plan_schedule", "--no-write"]),
                    0,
                )
                self.assertFalse(absent_report_dir.exists())
        finally:
            runner.REPORT_DIR = original_report_dir

    def test_study_pack_probe_is_cached_per_context(self) -> None:
        result = {
            "schema_version": "lumi.study-pack-eval-evidence.v1",
            "status": "pass",
            "test_input_non_learner": True,
            "learner_projection_eligible": False,
            "errors": [],
        }
        with patch.object(runner, "_probe_study_pack", return_value=result) as probe:
            context = runner.Context()
            self.assertIs(context.probe_study_pack(), result)
            self.assertIs(context.probe_study_pack(), result)
        probe.assert_called_once_with()

    def test_study_pack_gate_no_write_does_not_create_reports(self) -> None:
        result = {
            "schema_version": "lumi.study-pack-eval-evidence.v1",
            "status": "pass",
            "test_input_non_learner": True,
            "learner_projection_eligible": False,
            "errors": [],
        }
        original_report_dir = runner.REPORT_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                absent_report_dir = Path(directory) / "reports-must-stay-absent"
                runner.REPORT_DIR = absent_report_dir
                with patch.object(
                    runner, "_probe_study_pack", return_value=result
                ), patch("builtins.print") as output:
                    self.assertEqual(
                        runner.main(["--gate", "study_pack", "--no-write"]),
                        0,
                    )
                self.assertFalse(absent_report_dir.exists())
                rendered = str(output.call_args.args[0])
                self.assertIn("--no-write", rendered)
                self.assertIn("no report or evidence file was created", rendered)
                self.assertNotIn("beside this file", rendered)
        finally:
            runner.REPORT_DIR = original_report_dir

    def test_study_pack_dependency_probe_never_bootstraps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ,
                {"LUMI_STUDY_PACK_PYTHON": str(root / "missing-python")},
            ), patch.object(
                runner, "_study_pack_pypdf_version", return_value=None
            ):
                with self.assertRaises(runner._StudyPackProbeFailure) as caught:
                    runner._study_pack_isolated_interpreter(root)
            self.assertEqual(
                str(caught.exception),
                "study_pack_eval_dependencies_unavailable",
            )
            self.assertEqual(list(root.iterdir()), [])

    def test_study_pack_compaction_drops_arbitrary_source_answer_and_record(self) -> None:
        raw_source = "这是绝不能写入评测报告的完整中文材料。"
        raw_answer = "这是绝不能写入评测报告的学生答案。"
        raw_ascii = "privateanswercanary"
        probe = {
            "schema_version": "lumi.study-pack-eval-evidence.v1",
            "status": "pass",
            "test_input_non_learner": True,
            "learner_projection_eligible": False,
            "saved_product_attempt_record_count": 0,
            "product_external_network_calls": 0,
            "protected_path_accesses_observed": 0,
            "raw_source": raw_source,
            "source_cases": {
                "pasted_text": {
                    "source_sha256": "a" * 64,
                    "answer_sha256": "b" * 64,
                    "raw_answer": raw_answer,
                    "attempt": {
                        "schema_version": "lumi.study-pack-attempt.v1",
                        "answer": raw_answer,
                    },
                }
            },
            "errors": [raw_source, raw_ascii],
        }
        compact = runner._compact_study_pack_evidence(probe)
        serialized = json.dumps(compact, ensure_ascii=False)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_answer, serialized)
        self.assertNotIn(raw_ascii, serialized)
        self.assertNotIn("lumi.study-pack-attempt.v1", serialized)
        self.assertNotIn("raw_source", serialized)
        self.assertNotIn("raw_answer", serialized)
        self.assertNotIn("product_external_network_calls", serialized)
        self.assertNotIn("protected_path_accesses_observed", serialized)
        self.assertEqual(compact["test_input_non_learner"], True)
        self.assertEqual(compact["learner_projection_eligible"], False)
        self.assertIn("unsafe_error_redacted", serialized)

    def test_written_study_pack_evidence_uses_closed_compaction(self) -> None:
        raw_source = "持久证据不能保存这段中文原文。"
        raw_answer = "持久证据不能保存这段中文答案。"
        context = runner.Context()
        context.study_pack_probe = {
            "schema_version": "lumi.study-pack-eval-evidence.v1",
            "status": "pass",
            "test_input_non_learner": True,
            "learner_projection_eligible": False,
            "source_cases": {
                "pasted_text": {
                    "source_sha256": "a" * 64,
                    "answer_sha256": "b" * 64,
                    "raw_source": raw_source,
                    "raw_answer": raw_answer,
                }
            },
            "errors": [],
        }
        original_report_dir = runner.REPORT_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                runner.REPORT_DIR = Path(directory)
                runner.write_outputs(
                    {
                        "run_id": "run-study-pack-compaction",
                        "generated_at": "2026-07-11T00:00:00+00:00",
                        "repository": "/local/repository",
                        "overall_status": "pass",
                        "summary": {
                            "pass": 1,
                            "fail": 0,
                            "pending": 0,
                            "total": 1,
                        },
                        "gates": [],
                    },
                    context,
                )
                serialized = (
                    Path(directory) / "study-pack-evidence-latest.json"
                ).read_text(encoding="utf-8")
        finally:
            runner.REPORT_DIR = original_report_dir
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_answer, serialized)
        self.assertNotIn("raw_source", serialized)
        self.assertNotIn("raw_answer", serialized)
        self.assertIn('"test_input_non_learner": true', serialized)
        self.assertIn('"learner_projection_eligible": false', serialized)

    def test_written_schedule_evidence_is_sanitized(self) -> None:
        secret_canary = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz"
        context = runner.Context()
        context.schedule_api_probe = {
            "schema_version": "lumi.today-plan-eval-evidence.v1",
            "status": "fail",
            "errors": [
                "raw.canary@example.invalid /Users/private/schedule "
                + secret_canary
            ],
            "cases": {},
        }
        original_report_dir = runner.REPORT_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                runner.REPORT_DIR = Path(directory)
                runner.write_outputs(
                    {
                        "run_id": "run-test-schedule",
                        "generated_at": "2026-07-11T00:00:00+00:00",
                        "repository": "/Users/private/project",
                        "overall_status": "fail",
                        "summary": {
                            "pass": 0,
                            "fail": 1,
                            "pending": 0,
                            "total": 1,
                        },
                        "gates": [],
                    },
                    context,
                )
                serialized = (
                    Path(directory) / "today-plan-evidence-latest.json"
                ).read_text()
        finally:
            runner.REPORT_DIR = original_report_dir
        self.assertNotIn("raw.canary@example.invalid", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn(secret_canary, serialized)
        self.assertIn("[EMAIL]", serialized)
        self.assertIn("[REDACTED_SECRET]", serialized)

    def test_extended_opaque_secret_shapes_are_sanitized(self) -> None:
        canaries = [
            "s" + "k-" + "A" * 32,
            "gh" + "p_" + "A" * 36,
            "github" + "_pat_" + "A" * 40,
            "AIza" + "Sy" + "A" * 33,
            "n" + "pm_" + "A" * 36,
            "xo" + "xb-" + "123456789012-123456789012-" + "A" * 24,
        ]
        sanitized = runner._sanitize_report_string(" ".join(canaries))
        for canary in canaries:
            self.assertNotIn(canary, sanitized)
        self.assertEqual(sanitized.count("[REDACTED_SECRET]"), len(canaries))

    def test_eval_public_ids_are_stable_opaque_and_domain_separated(self) -> None:
        run_id = runner._eval_public_run_id("same logical label")
        command_id = runner._eval_public_command_id("same logical label")
        self.assertRegex(run_id, r"^r_[A-P]{40}$")
        self.assertRegex(command_id, r"^c_[A-P]{40}$")
        self.assertEqual(
            run_id,
            runner._eval_public_run_id("same logical label"),
        )
        self.assertNotEqual(
            run_id.removeprefix("r_"),
            command_id.removeprefix("c_"),
        )
        self.assertNotEqual(run_id, runner._eval_public_run_id("other label"))

    def test_p0_gates_propagate_shared_probe_failures(self) -> None:
        broken = runner.Context()
        broken.attempt_api_probe = {
            "status": "fail",
            "assistance_status": "pass",
            "dossier_status": "pass",
            "errors": ["sidecar startup failed"],
            "assistance_errors": [],
            "dossier_errors": [],
            "cases": {},
        }
        broken.service_tests_probe = {
            "status": "pass",
            "exit_code": 0,
            "errors": [],
        }
        self.assertEqual(runner.gate_progressive_assistance(broken).status, "fail")
        self.assertEqual(runner.gate_misconception_dossier(broken).status, "fail")

    def test_complete_service_tests_are_cached_per_context(self) -> None:
        result = {"status": "pass", "exit_code": 0, "errors": []}
        with patch.object(runner, "_probe_service_tests", return_value=result) as probe:
            context = runner.Context()
            self.assertIs(context.probe_service_tests(), result)
            self.assertIs(context.probe_service_tests(), result)
        probe.assert_called_once_with()

    def test_service_test_evidence_never_persists_raw_failure_output(self) -> None:
        raw_source = "服务测试失败时也不能落盘这段中文材料。"
        raw_answer = "服务测试失败时也不能落盘这段中文答案。"
        output = (
            "test_closed (tests.TestCase.test_closed) ... FAIL\n"
            "Ran 12 tests\nFAILED (failures=1)\n"
            + raw_source
            + raw_answer
        )
        summarized = runner._unittest_output_evidence(output, 1)
        self.assertEqual(summarized["test_count"], 12)
        self.assertEqual(summarized["failure_count"], 1)
        self.assertEqual(
            summarized["stable_failure_codes"], ["fail:test_closed"]
        )
        self.assertNotIn(raw_source, json.dumps(summarized, ensure_ascii=False))
        compact = runner._compact_service_test_evidence(
            {
                "status": "fail",
                **summarized,
                "output": output,
                "errors": [raw_source, raw_answer],
                "stable_failure_codes": [
                    *summarized["stable_failure_codes"],
                    raw_answer,
                ],
            }
        )
        serialized = json.dumps(compact, ensure_ascii=False)
        self.assertNotIn(raw_source, serialized)
        self.assertNotIn(raw_answer, serialized)
        self.assertNotIn("output", compact)
        self.assertNotIn("errors", compact)
        self.assertEqual(compact["raw_output_saved"], False)
        self.assertTrue(
            any(
                code.startswith("unsafe_failure_code_redacted:")
                for code in compact["stable_failure_codes"]
            )
        )

    def test_real_study_pack_release_gate_when_strict_interpreter_is_available(
        self,
    ) -> None:
        configured = os.environ.get("LUMI_STUDY_PACK_PYTHON")
        candidates = [
            Path(configured).expanduser() if configured else None,
            runner.REPO_ROOT
            / "desktop"
            / ".sidecar-venv"
            / "bin"
            / "python",
            Path(sys.executable),
        ]
        if not any(
            candidate is not None
            and candidate.is_file()
            and runner._study_pack_pypdf_version(candidate) == "6.10.0"
            for candidate in candidates
        ):
            self.skipTest("strict Study Pack evaluation interpreter unavailable")
        context = runner.Context()
        result = runner.gate_study_pack(context)
        self.assertEqual(result.status, "pass", result.evidence)
        probe = context.study_pack_probe or {}
        self.assertEqual(probe["test_input_non_learner"], True)
        self.assertEqual(probe["learner_projection_eligible"], False)
        self.assertEqual(probe["saved_product_attempt_record_count"], 0)
        self.assertEqual(
            probe["ephemeral_evaluation_fixture_attempt_count"], 2
        )
        self.assertEqual(probe["ephemeral_human_attempt_count"], 0)
        self.assertEqual(probe["eval_dependency_network_calls"], 0)
        self.assertEqual(
            probe["product_isolation_evidence"],
            {
                "method": "capability_and_generator_metadata_not_access_audit",
                "external_network_endpoint_advertised": False,
                "ocr_feature_advertised": False,
                "web_feature_advertised": False,
                "pdf_worker_subprocess_isolated": True,
            },
        )
        self.assertEqual(
            probe["protected_repository_boundary"]["readonly_gate_result"],
            "delegated_to_readonly_boundary_gate",
        )
        self.assertTrue(probe["learning_storage_isolation"]["unchanged"])
        self.assertEqual(
            probe["fixture_reproducibility"]["reproducible_cases"], 2
        )
        self.assertGreaterEqual(probe["negative_case_count"], 20)
        self.assertTrue(
            all(
                case["citation_count"] == case["citation_verified_count"]
                and case[
                    "artifact_generator_isolation_metadata_checked_count"
                ]
                == case[
                    "artifact_generator_isolation_metadata_verified_count"
                ]
                and case["ephemeral_evaluation_fixture_attempt_count"] == 1
                and case["ephemeral_human_attempt_count"] == 0
                and case["persistence_privacy"][
                    "evaluation_fixture_event_count"
                ]
                == 1
                and case["persistence_privacy"][
                    "human_local_interactive_event_count"
                ]
                == 0
                for case in probe["source_cases"].values()
            )
        )
        compact = runner._compact_study_pack_evidence(probe)
        serialized = json.dumps(compact, ensure_ascii=False)
        pasted_source = (
            runner.FIXTURE_DIR / "study_pack" / "pasted_text.txt"
        ).read_text(encoding="utf-8")
        synthetic_case = runner.load_json(
            runner.FIXTURE_DIR / "study_pack" / "pasted_text.case.json"
        )
        first_private_answer = next(
            item["content"]["answer"]
            for item in synthetic_case["private_artifact_contents"]
            if item["content"]["schema_version"]
            == "study_pack.practice_item.v1"
        )
        self.assertNotIn(pasted_source, serialized)
        self.assertNotIn(first_private_answer, serialized)
        self.assertNotIn(
            '"evidence_origin": "human_local_interactive"', serialized
        )

    def test_attempt_evidence_compaction_keeps_only_hash_and_redaction(self) -> None:
        compact = runner._compact_attempt_api_evidence(
            {
                "status": "pass",
                "errors": [],
                "cases": {
                    "pii": {
                        "request": {"response_sha256": "abc", "contains_pii_test_data": True},
                        "response": {
                            "status": 201,
                            "payload": {
                                "schema_version": "hermes.attempt-result.v1",
                                "response_evidence": {"redacted_text": "[EMAIL]"},
                            },
                        },
                    }
                },
            }
        )
        serialized = json.dumps(compact)
        self.assertIn("[EMAIL]", serialized)
        self.assertIn("response_sha256", serialized)
        self.assertNotIn("example.invalid", serialized)

    def test_written_attempt_evidence_uses_compacted_projection(self) -> None:
        secret_canary = "sk-" + "abcdefghijklmnopqrstuvwxyz"
        probe = {
            "status": "fail",
            "errors": [
                "raw.canary@example.invalid /Users/private/secret "
                + secret_canary
                + " /Users/a1-6/Desktop/shenlun-agent-platform xingcetiku"
            ],
            "cases": {
                "pii": {
                    "request": {
                        "response_sha256": "abc",
                        "contains_pii_test_data": True,
                        "run_id": "13800138000",
                        "raw_debug_canary": "raw.canary@example.invalid",
                    },
                    "response": {
                        "status": 201,
                        "payload": {
                            "schema_version": "hermes.attempt-session.v1",
                            "response_evidence": {"redacted_text": "[EMAIL]"},
                            "raw_debug_canary": "raw.canary@example.invalid",
                        },
                    },
                    "trace": {
                        "status": 200,
                        "payload": {"raw_debug_canary": "raw.canary@example.invalid"},
                    },
                }
            },
        }
        context = runner.Context()
        context.attempt_api_probe = probe
        original_report_dir = runner.REPORT_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                runner.REPORT_DIR = Path(directory)
                runner.write_outputs(
                    {
                        "run_id": "run-test",
                        "generated_at": "2026-07-11T00:00:00+00:00",
                        "repository": "/Users/private/project",
                        "overall_status": "fail",
                        "counts": {"pass": 0, "fail": 1, "pending": 0},
                        "summary": {"pass": 0, "fail": 1, "pending": 0},
                        "gates": [],
                    },
                    context,
                )
                serialized = (Path(directory) / "attempt-api-evidence-latest.json").read_text()
        finally:
            runner.REPORT_DIR = original_report_dir
        self.assertNotIn("raw.canary@example.invalid", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("13800138000", serialized)
        self.assertNotIn(secret_canary, serialized)
        self.assertNotIn("shenlun-agent-platform", serialized)
        self.assertNotIn("xingcetiku", serialized)
        self.assertIn("[EMAIL]", serialized)
        self.assertIn("[REDACTED_SECRET]", serialized)

    def test_attempt_probe_uses_system_temp_not_reports_directory(self) -> None:
        original_report_dir = runner.REPORT_DIR
        try:
            with tempfile.TemporaryDirectory() as directory:
                absent_report_dir = Path(directory) / "reports-must-stay-absent"
                runner.REPORT_DIR = absent_report_dir
                probe = runner._probe_attempt_api()
                self.assertEqual(probe["status"], "pass", probe.get("errors"))
                self.assertFalse(absent_report_dir.exists())
        finally:
            runner.REPORT_DIR = original_report_dir


if __name__ == "__main__":
    unittest.main()
