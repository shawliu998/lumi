from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


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


class EvidenceIntegrationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
