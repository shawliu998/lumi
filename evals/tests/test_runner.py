from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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

    def test_core320_manifest_and_materialization_boundary_close_the_gate(self) -> None:
        result = runner.gate_core320_bank(runner.Context())
        self.assertEqual(result.status, "pass", result.evidence)
        bank = result.evidence[0]
        self.assertEqual(bank["question_count"], 320)
        self.assertEqual(bank["scope_counts"]["xingce.mixed.core"], 320)

    def test_core320_five_scope_service_contract_closes_the_gate(self) -> None:
        result = runner.gate_core320_scopes(runner.Context())
        self.assertEqual(result.status, "pass", result.evidence)
        self.assertIn("four-module plus mixed", result.summary)

    def test_continuous_practice_focused_contract_closes_the_gate(self) -> None:
        result = runner.gate_continuous_practice_v1(runner.Context())
        self.assertEqual(result.status, "pass", result.evidence)
        self.assertIn("without a production build", result.summary)
        labels = {next(iter(item)) for item in result.evidence}
        self.assertTrue(
            {
                "required_files",
                "engine_policy",
                "service_read_models",
                "client_contracts",
            }.issubset(labels)
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


class ContinuousPracticeGateDeterminismTests(unittest.TestCase):
    @staticmethod
    def _completed(command, **kwargs):
        return runner.subprocess.CompletedProcess(
            command,
            0,
            stdout="focused stdout\n",
            stderr="focused stderr\n",
        )

    def test_missing_contract_surface_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(runner, "REPO_ROOT", Path(temporary)):
                result = runner.gate_continuous_practice_v1(runner.Context())
        self.assertEqual(result.status, "pending")
        self.assertEqual(
            result.evidence[0]["missing"],
            [
                "client/tests/practiceInsights.test.js",
                "client/tests/smartPracticeState.test.js",
                "docs/CONTINUOUS_PRACTICE_V1.md",
                "engine/tests/test_next_scope_policy.py",
                "service/tests/test_learning_records.py",
            ],
        )

    def test_focused_command_evidence_is_deterministic_and_never_builds(self) -> None:
        with mock.patch.object(
            runner.subprocess,
            "run",
            side_effect=self._completed,
        ):
            first = runner.gate_continuous_practice_v1(runner.Context())
            second = runner.gate_continuous_practice_v1(runner.Context())
        self.assertEqual(first.status, "pass")
        self.assertEqual(first.evidence, second.evidence)
        serialized = json.dumps(first.evidence)
        self.assertNotIn("npm run build", serialized)
        self.assertNotIn('"build"', serialized)
        for item in first.evidence[1:]:
            command = next(iter(item.values()))
            self.assertEqual(command["exit_code"], 0)
            self.assertEqual(len(command["command_sha256"]), 64)
            self.assertEqual(len(command["output_sha256"]), 64)
            self.assertTrue(command["input_sha256"])

    def test_present_but_failing_focused_test_is_fail(self) -> None:
        def failed(command, **kwargs):
            return runner.subprocess.CompletedProcess(
                command,
                1
                if any(str(part).endswith("test_next_scope_policy.py") for part in command)
                else 0,
                stdout="",
                stderr="deterministic failure",
            )

        with mock.patch.object(runner.subprocess, "run", side_effect=failed):
            result = runner.gate_continuous_practice_v1(runner.Context())
        self.assertEqual(result.status, "fail")
        self.assertIn("engine_policy focused tests failed", result.evidence[-1]["errors"])

    def test_missing_node_runtime_is_pending_after_file_hashes(self) -> None:
        with mock.patch.object(runner.shutil, "which", return_value=None):
            result = runner.gate_continuous_practice_v1(runner.Context())
        self.assertEqual(result.status, "pending")
        self.assertEqual(result.evidence[-1], {"node": None})
        self.assertEqual(
            set(result.evidence[0]["required_files"]),
            {
                "contract",
                "engine_policy_tests",
                "service_read_model_tests",
                "client_read_model_tests",
                "client_session_state_tests",
            },
        )


if __name__ == "__main__":
    unittest.main()
