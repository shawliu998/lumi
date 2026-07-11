from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
