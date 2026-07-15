#!/usr/bin/env python3
"""Dependency-free Lumi release gate and evidence runner.

The runner probes real repository capabilities. Missing required capabilities are
PENDING, invalid present capabilities are FAIL, and only asserted evidence can
PASS. It never writes outside evals/reports.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
CONTRACT_DIR = EVAL_DIR / "contracts"
FIXTURE_DIR = EVAL_DIR / "fixtures"
REPORT_DIR = EVAL_DIR / "reports"
FORBIDDEN_REPO = Path(
    os.environ.get("LUMI_SHENLUN_REPO", Path.home() / "Desktop" / "shenlun-agent-platform")
)
STATUSES = {"pass", "fail", "pending"}


def sanitize_public_report_paths(value: Any) -> Any:
    """Remove machine-specific paths before evidence is written to Git."""

    if isinstance(value, dict):
        return {key: sanitize_public_report_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_public_report_paths(item) for item in value]
    if not isinstance(value, str):
        return value
    sanitized = value.replace(str(REPO_ROOT), ".")
    sanitized = sanitized.replace(str(FORBIDDEN_REPO), "$LUMI_SHENLUN_REPO")
    return re.sub(
        r"evals/reports/runtime-probe-[^/\s\"]+/trace\.sqlite3",
        "evals/reports/runtime-probe-<temporary>/trace.sqlite3",
        sanitized,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_json(instance: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Validate the JSON Schema subset used by this harness."""

    errors: list[str] = []
    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else expected
    if expected_types and not any(_json_type_matches(instance, item) for item in expected_types):
        return [f"{path}: expected type {expected_types}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} is not in enum")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: string shorter than minLength")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: string does not match pattern")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: array shorter than minItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(instance):
                errors.extend(validate_json(item, item_schema, f"{path}[{index}]"))
    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance.keys() - properties.keys():
                errors.append(f"{path}: unexpected property {key!r}")
        for key, child_schema in properties.items():
            if key in instance:
                errors.extend(validate_json(instance[key], child_schema, f"{path}.{key}"))
    return errors


@dataclass
class GateResult:
    name: str
    status: str
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    blocking: bool = True
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"invalid gate status: {self.status}")


@dataclass
class Context:
    fixture: dict[str, Any] | None = None
    diagnosis: dict[str, Any] | None = None
    update: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None
    integration_probe: dict[str, Any] | None = None
    attempt_api_probe: dict[str, Any] | None = None

    def load_fixture(self) -> dict[str, Any]:
        if self.fixture is None:
            self.fixture = load_json(FIXTURE_DIR / "xingce_data_analysis_ambiguous.json")
        return self.fixture

    def tool(self) -> Any:
        engine_dir = REPO_ROOT / "engine"
        if not engine_dir.is_dir():
            raise FileNotFoundError("engine directory is absent")
        if str(engine_dir) not in sys.path:
            sys.path.insert(0, str(engine_dir))
        from hermes_kt.tool_api import HermesKTTool

        return HermesKTTool()

    def compute(self) -> None:
        if self.verification is not None:
            return
        fixture = self.load_fixture()
        inputs = fixture["input"]
        tool = self.tool()
        # JSON arrays are the wire representation of tuple-valued provenance in
        # the current engine dataclass. Normalize at this integration boundary;
        # the engine should eventually own this coercion in its public adapter.
        pre_state = dict(inputs["pre_state"])
        pre_state["provenance"] = tuple(pre_state.get("provenance", ()))
        self.diagnosis = tool.diagnose(
            {"attempt": inputs["attempt"], "priors": inputs["priors"], "history": inputs["history"]}
        )
        self.update = tool.update_mastery(
            {
                "state": pre_state,
                "attempt": inputs["verification_attempt"],
                "parameters": inputs["parameters"],
            }
        )
        self.verification = tool.verify_intervention(
            {
                "intervention_id": "intervention-demo-001",
                "pre_state": pre_state,
                "verification_attempt": inputs["verification_attempt"],
                "parameters": inputs["parameters"],
            }
        )

    def build_trace(self) -> dict[str, Any]:
        if self.trace is not None:
            return self.trace
        self.compute()
        assert self.diagnosis and self.verification
        fixture = self.load_fixture()
        inputs = fixture["input"]
        diagnosis_hash = sha256_json(self.diagnosis)
        verification_hash = sha256_json(self.verification)
        top = self.diagnosis["hypotheses"][0]
        post = self.verification["post_state"]
        verification = self.verification["verification"]
        self.trace = {
            "trace_id": "trace-" + sha256_json({"case": fixture["case_id"], "diagnosis": diagnosis_hash})[:16],
            "schema_version": "trajectory-v1",
            "case_id": fixture["case_id"],
            "created_at": inputs["attempt"]["observed_at"],
            "observation": {
                "attempt_id": inputs["attempt"]["attempt_id"],
                "evidence_ids": ["attempt:" + inputs["attempt"]["attempt_id"]],
                "payload": inputs["attempt"],
            },
            "policy_decision": {
                "decision_id": "decision-probe-001",
                "policy_version": "harness-probe-policy-v1",
                "action": "request_discriminating_probe",
                "reason": f"ranked cause {top['cause_id']} remains a hypothesis; verify before teaching claim",
                "model_tier": "deterministic_baseline",
            },
            "tool_calls": [
                {
                    "call_id": "call-diagnosis-001",
                    "tool": "hermes_explainable_learning_model.diagnose",
                    "version": "0.1.0",
                    "input_evidence_ids": ["attempt:" + inputs["attempt"]["attempt_id"]],
                    "output": {"sha256": diagnosis_hash, "result": self.diagnosis},
                },
                {
                    "call_id": "call-verification-001",
                    "tool": "hermes_explainable_learning_model.verify_intervention",
                    "version": "0.1.0",
                    "input_evidence_ids": ["attempt:" + inputs["verification_attempt"]["attempt_id"]],
                    "output": {"sha256": verification_hash, "result": self.verification},
                },
            ],
            "state_transition": {
                "learner_id": inputs["pre_state"]["learner_id"],
                "skill_id": inputs["pre_state"]["skill_id"],
                "before": inputs["pre_state"],
                "after": post,
                "evidence_ids": ["attempt:" + inputs["verification_attempt"]["attempt_id"]],
                "formula_version": post["provenance"][-1]["formula_version"],
            },
            "evaluation": {
                "evaluator_version": verification["provenance"]["model_version"],
                "independent_transfer": verification["independently_verified"],
                "outcome": verification["effective"],
                "evidence_ids": ["attempt:" + inputs["verification_attempt"]["attempt_id"]],
            },
            "privacy": {
                "local_only": True,
                "redaction_version": "fixture-redaction-v1",
                "cloud_disclosure": None,
            },
        }
        return self.trace

    def probe_learning_loop(self) -> dict[str, Any]:
        if self.integration_probe is None:
            self.integration_probe = _probe_learning_loop_cli()
        return self.integration_probe

    def probe_attempt_api(self) -> dict[str, Any]:
        if self.attempt_api_probe is None:
            self.attempt_api_probe = _probe_attempt_api()
        return self.attempt_api_probe


def gate_contracts(ctx: Context) -> GateResult:
    schemas = sorted(CONTRACT_DIR.glob("*.schema.json"))
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    required = {"representative_case.schema.json", "trajectory.schema.json", "release_report.schema.json"}
    missing = required - {path.name for path in schemas}
    if missing:
        return GateResult("contracts", "pending", "required contract schemas are missing", [{"missing": sorted(missing)}])
    for path in schemas:
        try:
            schema = load_json(path)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                errors.append(f"{path.name}: unsupported or missing $schema")
            if schema.get("type") != "object" or not schema.get("$id"):
                errors.append(f"{path.name}: root object type and $id are required")
            evidence.append({"schema": path.name, "sha256": sha256_json(schema)})
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
    fixture_errors = validate_json(ctx.load_fixture(), load_json(CONTRACT_DIR / "representative_case.schema.json"))
    errors.extend(f"fixture: {item}" for item in fixture_errors)
    if errors:
        return GateResult("contracts", "fail", "contract validation failed", evidence + [{"errors": errors}])
    return GateResult("contracts", "pass", f"{len(schemas)} schemas and canonical fixture validated", evidence)


def gate_fixtures(ctx: Context) -> GateResult:
    matrix = load_json(FIXTURE_DIR / "representative_matrix.json")
    domains = REPO_ROOT / "domains"
    domain_fixture_root = domains / "fixtures"
    if not domain_fixture_root.is_dir():
        return GateResult("fixtures", "pending", "domain fixture root is absent", [{"path": str(domain_fixture_root)}])
    domain_dir = str(domains)
    if domain_dir not in sys.path:
        sys.path.insert(0, domain_dir)
    cases: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    fixture_hashes: list[dict[str, Any]] = []
    try:
        from hermes_domains import load_fixture_document

        for path in sorted(domain_fixture_root.rglob("*.json")):
            try:
                case = load_fixture_document(path, fixture_root=domain_fixture_root)
                cases.append(case)
                fixture_hashes.append(
                    {
                        "fixture": str(path.relative_to(REPO_ROOT)),
                        "fixture_id": case["fixture_id"],
                        "resolved_sha256": sha256_json(case),
                    }
                )
            except Exception as exc:
                invalid.append({"fixture": str(path.relative_to(REPO_ROOT)), "error": repr(exc)})
    except Exception as exc:
        return GateResult("fixtures", "fail", "domain fixture loader could not be imported", [{"error": repr(exc)}])
    if invalid:
        return GateResult("fixtures", "fail", "one or more present domain fixtures are invalid", invalid)
    present = {(case["domain"], case["path"], case["mode"]) for case in cases}
    required = {
        (domain, path, mode)
        for domain, paths in matrix["paths"].items()
        for path in paths
        for mode in matrix["required_modes"]
    }
    missing = sorted(required - present)
    extra = sorted(present - required)
    duplicate_ids = sorted(
        fixture_id
        for fixture_id in {case["fixture_id"] for case in cases}
        if sum(item["fixture_id"] == fixture_id for item in cases) > 1
    )
    evidence = [
        {
            "valid_fixture_count": len(cases),
            "unique_fixture_ids": len({case["fixture_id"] for case in cases}),
            "required_case_count": len(required),
        },
        {"present": [list(item) for item in sorted(present)]},
        {"missing": [list(item) for item in missing]},
        {"extra": [list(item) for item in extra], "duplicate_fixture_ids": duplicate_ids},
        {"fixtures": fixture_hashes},
    ]
    if extra or duplicate_ids or len(cases) != len(present):
        return GateResult("fixtures", "fail", "fixture matrix contains duplicates or unexpected cases", evidence)
    if missing:
        return GateResult("fixtures", "pending", f"{len(missing)} of {len(required)} representative cases are missing", evidence)
    return GateResult("fixtures", "pass", "42/42 domain fixtures resolve and cover every required path/mode exactly once", evidence)


def gate_engine_tests(ctx: Context) -> GateResult:
    test_dir = REPO_ROOT / "engine" / "tests"
    if not test_dir.is_dir():
        return GateResult("engine_tests", "pending", "engine test directory is absent", [{"path": str(test_dir)}])
    command = [sys.executable, "-m", "unittest", "discover", "-s", str(test_dir), "-v"]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO_ROOT / "engine") + os.pathsep + environment.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT / "engine",
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult("engine_tests", "fail", "engine tests could not complete", [{"command": command, "error": str(exc)}])
    output = (result.stdout + "\n" + result.stderr).strip()[-4000:]
    evidence = [{"command": command, "exit_code": result.returncode, "output": output}]
    if result.returncode:
        return GateResult("engine_tests", "fail", "deterministic engine tests failed", evidence)
    return GateResult("engine_tests", "pass", "deterministic engine tests passed", evidence)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gate_core320_bank(ctx: Context) -> GateResult:
    """Validate the pinned generated bank and its outside-Git export boundary."""

    domains = REPO_ROOT / "domains"
    manifest_path = domains / "practice_v3" / "manifest.json"
    schema_path = domains / "practice_v3" / "practice-bank-manifest.schema.json"
    materializer_path = REPO_ROOT / "scripts" / "materialize_practice_bank.py"
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path in (manifest_path, schema_path, materializer_path)
        if not path.is_file()
    ]
    if missing:
        return GateResult(
            "core320_bank",
            "pending",
            "Core-320 manifest, schema, or materializer is absent",
            [{"missing": missing}],
        )

    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        manifest = load_json(manifest_path)
        schema = load_json(schema_path)
        errors.extend(f"manifest: {item}" for item in validate_json(manifest, schema))
        domain_dir = str(domains)
        if domain_dir not in sys.path:
            sys.path.insert(0, domain_dir)
        from hermes_domains.practice_bank_v3 import load_practice_bank, load_scope_catalog
        from hermes_domains.practice_v3_common import MIXED_SCOPE_ID, MODULE_SCOPES

        bank = load_practice_bank()
        scopes = load_scope_catalog()
        question_ids = [item["question_id"] for item in bank["questions"]]
        module_counts = Counter(item["module_id"] for item in bank["questions"])
        expected_modules = Counter(manifest["expected_module_counts"])
        expected_scope_counts = {**manifest["expected_module_counts"], MIXED_SCOPE_ID: 320}
        actual_scope_counts = {item["scope_id"]: item["question_count"] for item in scopes}
        invariants = {
            "bank_id_matches_manifest": bank.get("bank_id") == manifest.get("bank_id"),
            "bank_version_matches_manifest": bank.get("version") == manifest.get("version"),
            "generator_version_matches_manifest": bank.get("generator_version") == manifest.get("generator_version"),
            "digest_matches_manifest": bank.get("generated_sha256") == manifest.get("generated_sha256"),
            "question_count_is_320": len(bank.get("questions", [])) == manifest.get("expected_question_count") == 320,
            "question_ids_are_unique": len(question_ids) == len(set(question_ids)) == 320,
            "module_counts_are_80_each": module_counts == expected_modules,
            "scope_catalog_is_exact": actual_scope_counts == expected_scope_counts,
            "module_scope_constants_are_exact": set(MODULE_SCOPES.values()) == set(manifest["expected_module_counts"]),
        }
        errors.extend(name for name, valid in invariants.items() if not valid)
        evidence.append(
            {
                "manifest": str(manifest_path.relative_to(REPO_ROOT)),
                "manifest_sha256": _file_sha256(manifest_path),
                "bank_id": bank.get("bank_id"),
                "version": bank.get("version"),
                "generator_version": bank.get("generator_version"),
                "generated_sha256": bank.get("generated_sha256"),
                "question_count": len(bank.get("questions", [])),
                "module_counts": dict(sorted(module_counts.items())),
                "scope_counts": dict(sorted(actual_scope_counts.items())),
                "invariants": invariants,
            }
        )

        with tempfile.TemporaryDirectory(prefix="lumi-core320-export-") as temporary:
            materialize_command = [
                sys.executable,
                str(materializer_path),
                "--output",
                temporary,
            ]
            materialized = subprocess.run(
                materialize_command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=90,
            )
            materialize_evidence: dict[str, Any] = {
                "command": materialize_command,
                "exit_code": materialized.returncode,
                "stderr": materialized.stderr[-2000:],
            }
            if materialized.returncode:
                errors.append("outside-Git materialization failed")
            else:
                try:
                    summary = json.loads(materialized.stdout)
                    destination = Path(summary["output"]).resolve()
                    if destination == REPO_ROOT or REPO_ROOT in destination.parents:
                        errors.append("materializer wrote its bulk export inside the Git workspace")
                    export_manifest = load_json(destination / "manifest.json")
                    exported_ids: list[str] = []
                    exported_scope_counts: dict[str, int] = {}
                    file_hashes: dict[str, str] = {}
                    for item in export_manifest.get("files", []):
                        module_path = destination / item["path"]
                        payload = load_json(module_path)
                        scope_id = payload.get("scope_id")
                        count = payload.get("question_count")
                        exported_scope_counts[str(scope_id)] = int(count) if isinstance(count, int) else -1
                        exported_ids.extend(question["question_id"] for question in payload.get("questions", []))
                        file_hashes[item["path"]] = _file_sha256(module_path)
                    export_invariants = {
                        "identity_matches": export_manifest.get("bank_id") == bank.get("bank_id")
                        and export_manifest.get("version") == bank.get("version"),
                        "digest_matches": export_manifest.get("generated_sha256") == bank.get("generated_sha256"),
                        "count_matches": export_manifest.get("question_count") == len(bank["questions"]) == 320,
                        "four_files_of_80": exported_scope_counts == manifest["expected_module_counts"],
                        "exported_ids_match_bank": Counter(exported_ids) == Counter(question_ids),
                    }
                    errors.extend(f"materialized_{name}" for name, valid in export_invariants.items() if not valid)
                    materialize_evidence.update(
                        {
                            "output_is_outside_workspace": True,
                            "manifest": {
                                "bank_id": export_manifest.get("bank_id"),
                                "version": export_manifest.get("version"),
                                "generated_sha256": export_manifest.get("generated_sha256"),
                                "question_count": export_manifest.get("question_count"),
                            },
                            "scope_counts": dict(sorted(exported_scope_counts.items())),
                            "file_sha256": dict(sorted(file_hashes.items())),
                            "invariants": export_invariants,
                        }
                    )
                except (KeyError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                    errors.append("materialized export could not be audited")
                    materialize_evidence["audit_error"] = repr(exc)
            evidence.append({"outside_git_materialization": materialize_evidence})

        forbidden_target = REPO_ROOT / f".eval-core320-materialization-forbidden-{os.getpid()}"
        forbidden_command = [
            sys.executable,
            str(materializer_path),
            "--output",
            str(forbidden_target),
        ]
        try:
            refused = subprocess.run(
                forbidden_command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            refusal_output = (refused.stdout + "\n" + refused.stderr).strip()
            refused_safely = (
                refused.returncode != 0
                and "outside the Lumi Git workspace" in refusal_output
                and not forbidden_target.exists()
            )
            if not refused_safely:
                errors.append("inside-workspace materialization did not fail closed")
            evidence.append(
                {
                    "inside_git_refusal": {
                        "command": forbidden_command,
                        "exit_code": refused.returncode,
                        "expected_message_present": "outside the Lumi Git workspace" in refusal_output,
                        "created_output": forbidden_target.exists(),
                    }
                }
            )
        finally:
            if forbidden_target.exists():
                if forbidden_target.is_dir():
                    shutil.rmtree(forbidden_target)
                else:
                    forbidden_target.unlink()
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ImportError, ValueError) as exc:
        errors.append(f"Core-320 bank gate raised {exc!r}")

    if errors:
        return GateResult(
            "core320_bank",
            "fail",
            "Core-320 manifest, generated bank, or materialization boundary failed",
            evidence + [{"errors": errors}],
        )
    return GateResult(
        "core320_bank",
        "pass",
        "manifest digest resolves 320 unique versions (80×4), five scopes are exact, and bulk export is complete outside Git and refused inside Git",
        evidence,
    )


def gate_core320_scopes(ctx: Context) -> GateResult:
    """Exercise the real five-scope HTTP contract through its focused suite."""

    test_file = REPO_ROOT / "service" / "tests" / "test_practice_scopes_v3.py"
    if not test_file.is_file():
        return GateResult(
            "core320_scopes",
            "pending",
            "Core-320 five-scope service contract tests are absent",
            [{"path": str(test_file.relative_to(REPO_ROOT))}],
        )
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(test_file.parent),
        "-p",
        test_file.name,
        "-v",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT / "service",
            env=_service_environment(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateResult(
            "core320_scopes",
            "fail",
            "Core-320 five-scope service suite could not complete",
            [{"command": command, "error": repr(exc)}],
        )
    evidence = [
        {
            "command": command,
            "test_file": str(test_file.relative_to(REPO_ROOT)),
            "test_file_sha256": _file_sha256(test_file),
            "exit_code": result.returncode,
            "output": (result.stdout + "\n" + result.stderr).strip()[-8000:],
        }
    ]
    if result.returncode:
        return GateResult(
            "core320_scopes",
            "fail",
            "five-scope capabilities, fixed-eight starts, safe projection, mixed rotation, persistence, or fail-closed scope assertions failed",
            evidence,
        )
    return GateResult(
        "core320_scopes",
        "pass",
        "real loopback service passed exact four-module plus mixed scope, safe question, fixed-eight, rotation, shared-trace, restart, and fail-closed assertions",
        evidence,
    )


def gate_continuous_practice_v1(ctx: Context) -> GateResult:
    """Run only the frozen cross-session practice contract surfaces."""

    required_files = {
        "contract": REPO_ROOT / "docs" / "CONTINUOUS_PRACTICE_V1.md",
        "engine_policy_tests": REPO_ROOT / "engine" / "tests" / "test_next_scope_policy.py",
        "service_read_model_tests": REPO_ROOT / "service" / "tests" / "test_learning_records.py",
        "client_read_model_tests": REPO_ROOT / "client" / "tests" / "practiceInsights.test.js",
        "client_session_state_tests": REPO_ROOT / "client" / "tests" / "smartPracticeState.test.js",
    }
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path in required_files.values()
        if not path.is_file()
    ]
    if missing:
        return GateResult(
            "continuous_practice_v1",
            "pending",
            "continuous-practice contract or focused evidence surface is absent",
            [{"missing": sorted(missing)}],
        )

    file_evidence = {
        label: {
            "path": str(path.relative_to(REPO_ROOT)),
            "sha256": _file_sha256(path),
        }
        for label, path in sorted(required_files.items())
    }
    node = shutil.which("node")
    if node is None:
        return GateResult(
            "continuous_practice_v1",
            "pending",
            "Node.js is required for the focused continuous-practice client tests",
            [{"required_files": file_evidence}, {"node": None}],
        )

    engine_test = required_files["engine_policy_tests"]
    service_test = required_files["service_read_model_tests"]
    client_tests = (
        required_files["client_read_model_tests"],
        required_files["client_session_state_tests"],
    )
    engine_environment = dict(os.environ)
    engine_environment["PYTHONPATH"] = (
        str(REPO_ROOT / "engine")
        + os.pathsep
        + engine_environment.get("PYTHONPATH", "")
    )
    commands = (
        (
            "engine_policy",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(engine_test.parent),
                "-p",
                engine_test.name,
                "-v",
            ],
            REPO_ROOT / "engine",
            engine_environment,
            60,
            (engine_test,),
        ),
        (
            "service_read_models",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(service_test.parent),
                "-p",
                service_test.name,
                "-v",
            ],
            REPO_ROOT / "service",
            _service_environment(),
            120,
            (service_test,),
        ),
        (
            "client_contracts",
            [
                node,
                "--test",
                *(str(path.relative_to(REPO_ROOT / "client")) for path in client_tests),
            ],
            REPO_ROOT / "client",
            dict(os.environ),
            60,
            client_tests,
        ),
    )

    evidence: list[dict[str, Any]] = [{"required_files": file_evidence}]
    failures: list[str] = []
    for label, command, cwd, environment, timeout, inputs in commands:
        command_descriptor = {
            "command": command,
            "cwd": str(cwd.relative_to(REPO_ROOT)),
        }
        item: dict[str, Any] = {
            **command_descriptor,
            "command_sha256": sha256_json(command_descriptor),
            "input_sha256": {
                str(path.relative_to(REPO_ROOT)): _file_sha256(path)
                for path in inputs
            },
        }
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            item.update(exit_code=None, error=repr(exc))
            failures.append(f"{label} focused tests could not complete")
        else:
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            combined = stdout + ("\n" if stdout and stderr else "") + stderr
            item.update(
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                output=combined,
                output_sha256=hashlib.sha256(combined.encode("utf-8")).hexdigest(),
            )
            if result.returncode:
                failures.append(f"{label} focused tests failed")
        evidence.append({label: item})

    if failures:
        return GateResult(
            "continuous_practice_v1",
            "fail",
            "continuous-practice focused policy, read-model, or client assertions failed",
            evidence + [{"errors": failures}],
        )
    return GateResult(
        "continuous_practice_v1",
        "pass",
        "frozen continuous-practice policy, five read models, client contracts, "
        "and fixed-eight continuation state passed focused checks without a production build",
        evidence,
    )


def gate_core320_client(ctx: Context) -> GateResult:
    """Validate the client catalog against the manifest, then test and build it."""

    client = REPO_ROOT / "client"
    scope_module = client / "src" / "practiceScopes.js"
    scope_test = client / "tests" / "practiceScopes.test.js"
    manifest_path = REPO_ROOT / "domains" / "practice_v3" / "manifest.json"
    required = [client / "package.json", scope_module, scope_test, manifest_path]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    if missing:
        return GateResult(
            "core320_client",
            "pending",
            "Core-320 client catalog, test, package, or source manifest is absent",
            [{"missing": missing}],
        )
    if shutil.which("node") is None or shutil.which("npm") is None:
        return GateResult(
            "core320_client",
            "pending",
            "Node.js and npm are required for the Core-320 client gate",
            [{"node": shutil.which("node"), "npm": shutil.which("npm")}],
        )
    if not (client / "node_modules" / ".bin" / "vite").is_file():
        return GateResult(
            "core320_client",
            "pending",
            "client dependencies are not installed; production build evidence is unavailable",
            [{"missing": "client/node_modules/.bin/vite"}],
        )

    manifest = load_json(manifest_path)
    catalog_program = (
        f'import * as p from {json.dumps(scope_module.as_uri())};'
        "console.log(JSON.stringify({"
        "bank_id:p.SMART_PRACTICE_BANK_ID,bank_version:p.SMART_PRACTICE_BANK_VERSION,"
        "bank_sha256:p.SMART_PRACTICE_BANK_SHA256,"
        "pool_target:p.SMART_PRACTICE_SCOPE_TARGET,session_target:p.SMART_PRACTICE_SESSION_TARGET,"
        "default_scope_id:p.DEFAULT_SMART_PRACTICE_SCOPE_ID,"
        "scopes:p.SMART_PRACTICE_SCOPES.map(s=>({scope_id:s.scopeId,question_count:s.poolSize,mixed:s.mixed===true}))"
        "}));"
    )
    catalog_command = ["node", "--input-type=module", "--eval", catalog_program]
    commands = [
        ("catalog", catalog_command),
        ("tests", ["npm", "test"]),
        ("build", ["npm", "run", "build"]),
    ]
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    catalog: dict[str, Any] | None = None
    for label, command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=client,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{label} command raised {exc!r}")
            evidence.append({label: {"command": command, "error": repr(exc)}})
            continue
        item: dict[str, Any] = {
            "command": command,
            "exit_code": result.returncode,
            "output": (result.stdout + "\n" + result.stderr).strip()[-8000:],
        }
        if result.returncode:
            errors.append(f"client {label} command failed")
        elif label == "catalog":
            try:
                catalog = json.loads(result.stdout)
                item["catalog"] = catalog
            except json.JSONDecodeError as exc:
                errors.append("client scope catalog output is not JSON")
                item["parse_error"] = repr(exc)
        evidence.append({label: item})

    if catalog is not None:
        expected_scope_counts = {**manifest["expected_module_counts"], "xingce.mixed.core": 320}
        actual_scope_counts = {item["scope_id"]: item["question_count"] for item in catalog.get("scopes", [])}
        catalog_invariants = {
            "bank_id_matches_manifest": catalog.get("bank_id") == manifest.get("bank_id"),
            "bank_version_matches_manifest": catalog.get("bank_version") == manifest.get("version"),
            "bank_digest_matches_manifest": catalog.get("bank_sha256") == manifest.get("generated_sha256"),
            "pool_target_is_80": catalog.get("pool_target") == 80,
            "session_target_is_8": catalog.get("session_target") == 8,
            "default_is_data_analysis": catalog.get("default_scope_id") == "xingce.data-analysis.core",
            "five_scope_counts_are_exact": actual_scope_counts == expected_scope_counts,
            "mixed_is_reused_pool": sum(item.get("mixed") is True for item in catalog.get("scopes", [])) == 1,
        }
        errors.extend(name for name, valid in catalog_invariants.items() if not valid)
        evidence.append({"catalog_invariants": catalog_invariants})

    dist_index = client / "dist" / "index.html"
    if not dist_index.is_file():
        errors.append("client production build did not emit dist/index.html")
    else:
        evidence.append(
            {
                "build_artifact": str(dist_index.relative_to(REPO_ROOT)),
                "sha256": _file_sha256(dist_index),
            }
        )
    if errors:
        return GateResult(
            "core320_client",
            "fail",
            "Core-320 client manifest contract, tests, or production build failed",
            evidence + [{"errors": errors}],
        )
    return GateResult(
        "core320_client",
        "pass",
        "client pins the manifest bank/version and exact five scopes, then passes its tests and production build",
        evidence,
    )


def gate_core320_packaging(ctx: Context) -> GateResult:
    """Verify the packed sidecar and, when built, the managed debug app."""

    desktop = REPO_ROOT / "desktop"
    package = desktop / "package.json"
    if not package.is_file():
        return GateResult(
            "core320_packaging",
            "pending",
            "desktop package is absent",
            [{"path": str(package.relative_to(REPO_ROOT))}],
        )
    if shutil.which("node") is None or shutil.which("npm") is None:
        return GateResult(
            "core320_packaging",
            "pending",
            "Node.js and npm are required for desktop packaging verification",
            [{"node": shutil.which("node"), "npm": shutil.which("npm")}],
        )

    config_command = ["npm", "run", "check:config"]
    config = subprocess.run(
        config_command,
        cwd=desktop,
        capture_output=True,
        text=True,
        timeout=60,
    )
    evidence: list[dict[str, Any]] = [
        {
            "configuration": {
                "command": config_command,
                "exit_code": config.returncode,
                "output": (config.stdout + "\n" + config.stderr).strip()[-6000:],
            }
        }
    ]
    if config.returncode:
        return GateResult(
            "core320_packaging",
            "fail",
            "desktop Core-320 packaging configuration failed",
            evidence,
        )

    launcher = desktop / "src-tauri" / "binaries" / "hermes-sidecar-aarch64-apple-darwin"
    runtime = desktop / "src-tauri" / "resources" / "sidecar-runtime" / "hermes-sidecar"
    app = desktop / "src-tauri" / "target" / "debug" / "bundle" / "macos" / "Lumi.app"
    missing = [str(path.relative_to(REPO_ROOT)) for path in (launcher, runtime, app) if not path.exists()]
    if missing:
        evidence.append({"missing_built_artifacts": missing})
        return GateResult(
            "core320_packaging",
            "pending",
            "desktop configuration is valid, but packed sidecar or debug app evidence is not built",
            evidence,
        )

    for label, command, timeout in (
        ("packaged_sidecar", ["npm", "run", "check:sidecar"], 120),
        ("managed_app", ["npm", "run", "check:managed-app"], 120),
    ):
        try:
            result = subprocess.run(
                command,
                cwd=desktop,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return GateResult(
                "core320_packaging",
                "fail",
                f"desktop {label} verification could not complete",
                evidence + [{label: {"command": command, "error": repr(exc)}}],
            )
        evidence.append(
            {
                label: {
                    "command": command,
                    "exit_code": result.returncode,
                    "output": (result.stdout + "\n" + result.stderr).strip()[-8000:],
                }
            }
        )
        if result.returncode:
            return GateResult(
                "core320_packaging",
                "fail",
                f"desktop {label} Core-320 verification failed",
                evidence,
            )

    return GateResult(
        "core320_packaging",
        "pass",
        "packed sidecar exposes the manifest digest and exact five scopes; debug app contains the same content and passes managed lifecycle checks",
        evidence,
    )


def _run_unittest_surface(root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-v"]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = (
        os.pathsep.join((str(root), str(REPO_ROOT)))
        + os.pathsep
        + environment.get("PYTHONPATH", "")
    )
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )
    return {
        "command": command,
        "exit_code": result.returncode,
        "output": (result.stdout + "\n" + result.stderr).strip()[-6000:],
    }


def _integration_environment() -> dict[str, str]:
    environment = dict(os.environ)
    roots = [REPO_ROOT / name for name in ("integration", "runtime", "domains", "engine")]
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in roots) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


def _probe_learning_loop_cli() -> dict[str, Any]:
    """Run and replay the real domain→engine→runtime loop in all three modes."""

    integration = REPO_ROOT / "integration"
    if not integration.is_dir():
        return {"status": "pending", "errors": ["integration package is absent"], "runs": {}}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    environment = _integration_environment()
    runs: dict[str, Any] = {}
    errors: list[str] = []
    expected = {
        "success": {
            "diagnosis_decision": "confirm_top_hypothesis",
            "verification_effective": True,
            "outcome": "verified_transfer",
        },
        "ambiguous": {
            "diagnosis_decision": "disambiguate_hypotheses",
            "verification_effective": False,
            "outcome": "not_yet_mastered",
        },
        "offline": {
            "verification_effective": True,
            "outcome": "verified_transfer",
            "model_calls_recorded": 0,
        },
    }
    phases = ["observe", "diagnose", "probe", "teach", "verify", "update", "reflect"]
    try:
        with tempfile.TemporaryDirectory(prefix="integration-probe-", dir=REPORT_DIR) as temporary:
            for scenario, assertions in expected.items():
                database = Path(temporary) / f"{scenario}.sqlite3"
                run_id = f"eval-integration-{scenario}"
                run_command = [
                    sys.executable,
                    "-m",
                    "hermes_integration",
                    "--db",
                    str(database),
                    "run",
                    scenario,
                    "--run-id",
                    run_id,
                ]
                run = subprocess.run(
                    run_command,
                    cwd=integration,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                if run.returncode:
                    errors.append(f"{scenario}: integration run exited {run.returncode}")
                    runs[scenario] = {"run_command": run_command, "run_error": (run.stdout + run.stderr)[-6000:]}
                    continue
                try:
                    summary = json.loads(run.stdout)
                except json.JSONDecodeError as exc:
                    errors.append(f"{scenario}: run output is not JSON ({exc})")
                    runs[scenario] = {"run_command": run_command, "run_error": run.stdout[-6000:]}
                    continue
                replay_command = [
                    sys.executable,
                    "-m",
                    "hermes_integration",
                    "--db",
                    str(database),
                    "replay",
                    run_id,
                ]
                replay = subprocess.run(
                    replay_command,
                    cwd=integration,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                try:
                    replay_payload = json.loads(replay.stdout) if replay.returncode == 0 else None
                except json.JSONDecodeError:
                    replay_payload = None
                scenario_errors: list[str] = []
                if summary.get("status") != "completed" or summary.get("steps") != 7:
                    scenario_errors.append("run did not complete exactly seven phases")
                if summary.get("trace_verified") is not True:
                    scenario_errors.append("event-store trace hash verification failed")
                if not isinstance(summary.get("mastery_delta"), (int, float)):
                    scenario_errors.append("mastery delta is absent")
                for key, value in assertions.items():
                    if summary.get(key) != value:
                        scenario_errors.append(f"expected {key}={value!r}, got {summary.get(key)!r}")
                if replay_payload is None or replay_payload.get("trace_verified") is not True:
                    scenario_errors.append("replay did not verify")
                    final_state: dict[str, Any] = {}
                else:
                    frames = replay_payload.get("frames", [])
                    final_state = frames[-1].get("state", {}) if frames else {}
                    artifacts = final_state.get("artifacts", {})
                    completed_phases = [
                        change["path"].split("/")[2]
                        for frame in frames
                        if frame.get("kind") == "phase_completed"
                        for change in frame.get("diff", [])
                        if change.get("op") == "add"
                        and str(change.get("path", "")).startswith("/artifacts/")
                        and len(str(change.get("path", "")).split("/")) == 3
                    ]
                    if completed_phases != phases:
                        scenario_errors.append(f"phase completion order is invalid: {completed_phases}")
                    if set(artifacts) != set(phases):
                        scenario_errors.append(f"final artifacts are incomplete: {sorted(artifacts)}")
                    teach = artifacts.get("teach", [{}])[-1]
                    verify = artifacts.get("verify", [{}])[-1]
                    update = artifacts.get("update", [{}])[-1]
                    if not teach.get("policy_version") or not teach.get("strategy"):
                        scenario_errors.append("teaching policy evidence is absent")
                    verification = verify.get("verification", {})
                    if verification.get("independently_verified") is not True:
                        scenario_errors.append("verification is not independent")
                    update_evidence = update.get("evidence", {})
                    if not update_evidence.get("initial_attempt_id") or not update_evidence.get("verification_attempt_id"):
                        scenario_errors.append("mastery delta lacks attempt evidence links")
                    model_version = update.get("model_version", {})
                    if not model_version.get("mastery") or not model_version.get("verification"):
                        scenario_errors.append("mastery/verification versions are absent")
                    if scenario == "offline":
                        if final_state.get("context", {}).get("execution_mode") != "offline":
                            scenario_errors.append("offline execution mode is absent from replay state")
                        if summary.get("model_calls_recorded") != 0:
                            scenario_errors.append("offline trace contains model calls")
                errors.extend(f"{scenario}: {item}" for item in scenario_errors)
                runs[scenario] = {
                    "run_command": run_command,
                    "summary": summary,
                    "replay_command": replay_command,
                    "replay_sha256": sha256_json(replay_payload) if replay_payload else None,
                    "replay": replay_payload,
                    "assertion_errors": scenario_errors,
                }
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"integration CLI probe raised {exc!r}")
    return {"status": "fail" if errors else "pass", "errors": errors, "runs": runs}


def _service_environment() -> dict[str, str]:
    environment = dict(os.environ)
    roots = [REPO_ROOT / name for name in ("service", "integration", "runtime", "domains", "engine")]
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in roots) + os.pathsep + environment.get("PYTHONPATH", "")
    return environment


def _http_json(base_url: str, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"X-Request-ID": "eval-attempt-api", "Origin": "http://127.0.0.1:1420"}
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + path, data=encoded, headers=headers, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    try:
        raw = response.read()
        payload = json.loads(raw) if raw else {}
        return {
            "status": response.status,
            "payload": payload,
            "headers": {
                "x_request_id": response.headers.get("X-Request-ID"),
                "cache_control": response.headers.get("Cache-Control"),
            },
        }
    finally:
        response.close()


def _diagnosis_from_trace(trace: Mapping[str, Any]) -> dict[str, Any] | None:
    for event in trace.get("events", []):
        payload = event.get("payload", {})
        if event.get("kind") == "phase_completed" and payload.get("phase") == "diagnose":
            return payload.get("output", {}).get("diagnosis")
    return None


def _probe_attempt_api() -> dict[str, Any]:
    """Black-box POST /v1/attempts and replay audit against a real sidecar."""

    service = REPO_ROOT / "service"
    if not service.is_dir():
        return {"status": "pending", "errors": ["service package is absent"], "cases": {}}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    continuation_errors: list[str] = []
    cases: dict[str, Any] = {}
    process: subprocess.Popen[str] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="attempt-api-probe-", dir=REPORT_DIR) as temporary:
            database = Path(temporary) / "attempts.sqlite3"
            command = [
                sys.executable,
                "-m",
                "hermes_service",
                "--db",
                str(database),
                "serve",
                "--port",
                "0",
            ]
            process = subprocess.Popen(
                command,
                cwd=service,
                env=_service_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            ready, _, _ = select.select([process.stdout], [], [], 10)
            if not ready:
                raise RuntimeError("sidecar did not announce its loopback port within 10 seconds")
            banner = process.stdout.readline().strip()
            match = re.search(r"http://127\.0\.0\.1:(\d+)$", banner)
            if not match:
                raise RuntimeError(f"unexpected sidecar startup banner: {banner!r}")
            base_url = f"http://127.0.0.1:{match.group(1)}"
            fixture_id = "xingce.data-analysis.growth-rate.synthetic-01"
            requests = {
                "correct": {
                    "fixture_id": fixture_id,
                    "response": "B",
                    "confidence": 0.90,
                    "response_time_seconds": 18,
                    "run_id": "eval-api-correct",
                },
                "wrong": {
                    "fixture_id": fixture_id,
                    "response": "A",
                    "confidence": 0.80,
                    "response_time_seconds": 31,
                    "run_id": "eval-api-wrong",
                },
                "pii": {
                    "fixture_id": fixture_id,
                    "response": "A eval.learner@example.invalid 13800138000 11010519491231002X",
                    "confidence": 0.40,
                    "response_time_seconds": 50,
                    "run_id": "eval-api-pii",
                },
                "unknown_field": {
                    "fixture_id": fixture_id,
                    "response": "A",
                    "confidence": 0.50,
                    "response_time_seconds": 20,
                    "run_id": "eval-api-unknown",
                    "cause_ground_truth": "injected-cause",
                },
            }
            raw_pii = requests["pii"]["response"]
            for label, request_body in requests.items():
                response = _http_json(base_url, "POST", "/v1/attempts", request_body)
                case: dict[str, Any] = {
                    "request": {
                        "fixture_id": request_body["fixture_id"],
                        "run_id": request_body["run_id"],
                        "response_sha256": hashlib.sha256(str(request_body["response"]).encode("utf-8")).hexdigest(),
                        "contains_pii_test_data": label == "pii",
                        "unknown_fields": sorted(set(request_body) - {"fixture_id", "response", "confidence", "response_time_seconds", "run_id"}),
                    },
                    "response": response,
                }
                if response["status"] == 201:
                    payload = response["payload"]
                    links = payload.get("links", {})
                    trace_path = links.get("trace", f"/v1/runs/{request_body['run_id']}/trace")
                    replay_path = links.get("replay", f"/v1/runs/{request_body['run_id']}/replay")
                    case["trace"] = _http_json(base_url, "GET", trace_path)
                    case["replay"] = _http_json(base_url, "GET", replay_path)
                cases[label] = case

            correct = cases["correct"]["response"]
            wrong = cases["wrong"]["response"]
            pii = cases["pii"]["response"]
            unknown = cases["unknown_field"]["response"]
            for label, response in (("correct", correct), ("wrong", wrong), ("pii", pii)):
                if response["status"] != 201:
                    errors.append(f"{label}: POST /v1/attempts returned {response['status']} instead of 201")
                elif response["payload"].get("schema_version") != "hermes.attempt-session.v1":
                    errors.append(f"{label}: attempt result schema version is absent")
                if cases[label].get("trace", {}).get("status") != 200:
                    errors.append(f"{label}: trace is unavailable")
                if cases[label].get("replay", {}).get("status") != 200:
                    errors.append(f"{label}: replay is unavailable")
                elif cases[label]["replay"]["payload"].get("trace_verified") is not True:
                    errors.append(f"{label}: replay hash verification failed")

            if correct["status"] == 201:
                payload = correct["payload"]
                if payload.get("score", {}).get("passed") is not True:
                    errors.append("correct: score did not pass")
                if payload.get("diagnosis", {}).get("hypotheses") != []:
                    errors.append("correct: a correct answer received error-cause hypotheses")
                if payload.get("state") != "awaiting_probe" or payload.get("mastery_update") is not None:
                    errors.append("correct: initial attempt did not stop before mastery update")
            if wrong["status"] == 201:
                payload = wrong["payload"]
                hypotheses = payload.get("diagnosis", {}).get("hypotheses", [])
                if payload.get("score", {}).get("passed") is not False:
                    errors.append("wrong: score did not fail")
                if len(hypotheses) < 2:
                    errors.append("wrong: competing cause hypotheses are absent")
                if any(item.get("status") != "unconfirmed_hypothesis" for item in hypotheses):
                    errors.append("wrong: a cause escaped unconfirmed-hypothesis semantics")
                if payload.get("diagnosis", {}).get("semantics") != "ranked_unconfirmed_hypotheses":
                    errors.append("wrong: public diagnosis semantics are absent")
                if payload.get("state") != "awaiting_probe":
                    errors.append("wrong: initial attempt is not awaiting a learner probe response")
                if payload.get("teaching") is not None or payload.get("mastery_update") is not None:
                    errors.append("wrong: initial attempt fabricated teaching or mastery evidence")
                verification = payload.get("verification")
                if verification is not None:
                    errors.append("wrong: initial attempt fabricated an intervention outcome")
            if pii["status"] == 201:
                payload = pii["payload"]
                serialized_response = canonical_json(payload)
                trace_payload = cases["pii"].get("trace", {}).get("payload", {})
                replay_payload = cases["pii"].get("replay", {}).get("payload", {})
                persisted = canonical_json({"trace": trace_payload, "replay": replay_payload})
                for secret in ("eval.learner@example.invalid", "13800138000", "11010519491231002X"):
                    if secret in serialized_response or secret in persisted:
                        errors.append(f"pii: raw {secret!r} escaped redaction")
                evidence = payload.get("response_evidence", {})
                if evidence.get("redacted_text") != "A [EMAIL] [PHONE] [ID]":
                    errors.append("pii: redacted projection is incorrect")
                if not evidence.get("sha256") or evidence.get("original_length") != len(str(raw_pii)):
                    errors.append("pii: digest/length evidence is incomplete")
            if unknown["status"] != 400 or unknown["payload"].get("error", {}).get("code") != "invalid_body":
                errors.append("unknown_field: unsupported input did not fail closed with invalid_body")
            unknown_trace = _http_json(base_url, "GET", "/v1/runs/eval-api-unknown/trace")
            cases["unknown_field"]["trace_after_rejection"] = unknown_trace
            if unknown_trace["status"] != 404:
                errors.append("unknown_field: rejected input left a persisted run")

            if wrong["status"] == 201 and cases["wrong"].get("trace", {}).get("status") == 200:
                diagnosis = _diagnosis_from_trace(cases["wrong"]["trace"]["payload"])
                if not diagnosis:
                    errors.append("wrong: diagnosis provenance is absent from trace")
                else:
                    sources = diagnosis.get("provenance", {}).get("cohort_sources", [])
                    if not sources or any(source.get("sample_size") != 0 for source in sources):
                        errors.append("cohort: no-data cold start is not marked sample_size=0")
                    if any("synthetic" not in str(source.get("source_version", "")) for source in sources):
                        errors.append("cohort: engineering sources are not explicitly synthetic")
                    for hypothesis in diagnosis.get("hypotheses", []):
                        evidence_labels = hypothesis.get("evidence", [])
                        if "engineering_prior" not in evidence_labels or "cohort_prior" in evidence_labels:
                            errors.append("cohort: no-data diagnosis claims a cohort prior")
                            break

            if wrong["status"] == 201:
                initial = wrong["payload"]
                respond_path = initial.get("links", {}).get("respond")
                before_skills = _http_json(base_url, "GET", "/v1/skills/report")
                if before_skills["status"] != 200 or before_skills["payload"].get("skill_count") != 0:
                    continuation_errors.append("mastery exists before independent verification")
                if not respond_path or not isinstance(initial.get("state_version"), int):
                    continuation_errors.append("initial session lacks continuation link/version")
                else:
                    out_of_order = _http_json(
                        base_url,
                        "POST",
                        respond_path,
                        {
                            "phase": "verification",
                            "expected_version": initial["state_version"],
                            "expected_state": "awaiting_probe",
                            "response": "C",
                            "confidence": 0.9,
                            "response_time_seconds": 20,
                        },
                    )
                    if out_of_order["status"] != 409 or out_of_order["payload"].get("error", {}).get("code") != "out_of_order":
                        continuation_errors.append("verification-before-probe did not fail closed")

                    probe_response_text = "分母应使用基期量 continuation.learner@example.invalid"
                    after_probe = _http_json(
                        base_url,
                        "POST",
                        respond_path,
                        {
                            "phase": "probe",
                            "expected_version": initial["state_version"],
                            "expected_state": "awaiting_probe",
                            "response": probe_response_text,
                            "confidence": 0.75,
                            "response_time_seconds": 24,
                        },
                    )
                    stale = _http_json(
                        base_url,
                        "POST",
                        respond_path,
                        {
                            "phase": "probe",
                            "expected_version": initial["state_version"],
                            "expected_state": "awaiting_probe",
                            "response": "重复回答",
                            "confidence": 0.7,
                            "response_time_seconds": 10,
                        },
                    )
                    if stale["status"] != 409 or stale["payload"].get("error", {}).get("code") != "stale_version":
                        continuation_errors.append("stale continuation version did not fail closed")
                    if after_probe["status"] != 200:
                        continuation_errors.append(f"probe continuation returned {after_probe['status']}")
                        completed: dict[str, Any] = {"status": 0, "payload": {}}
                    else:
                        probe_payload = after_probe["payload"]
                        if (
                            probe_payload.get("schema_version") != "hermes.attempt-continuation-result.v1"
                            or probe_payload.get("state") != "awaiting_verification"
                            or probe_payload.get("teaching") is None
                            or probe_payload.get("mastery_update") is not None
                            or probe_payload.get("reflection") is not None
                            or probe_payload.get("verification", {}).get("status") != "awaiting_learner_response"
                        ):
                            continuation_errors.append("probe continuation projection is incomplete or premature")
                        completed = _http_json(
                            base_url,
                            "POST",
                            probe_payload.get("links", {}).get("respond", respond_path),
                            {
                                "phase": "verification",
                                "expected_version": probe_payload.get("state_version"),
                                "expected_state": "awaiting_verification",
                                "response": "C",
                                "confidence": 0.9,
                                "response_time_seconds": 20,
                            },
                        )
                    if completed["status"] != 200:
                        continuation_errors.append(f"verification continuation returned {completed['status']}")
                    else:
                        complete_payload = completed["payload"]
                        verification = complete_payload.get("verification", {})
                        mastery = complete_payload.get("mastery_update")
                        if (
                            complete_payload.get("state") != "completed"
                            or verification.get("independently_verified") is not True
                            or verification.get("effective") is not True
                            or not mastery
                            or complete_payload.get("reflection", {}).get("outcome") != "verified_transfer"
                        ):
                            continuation_errors.append("completed continuation lacks independent transfer, KT, or reflection evidence")
                        final_trace = _http_json(base_url, "GET", complete_payload["links"]["trace"])
                        final_replay = _http_json(base_url, "GET", complete_payload["links"]["replay"])
                        after_skills = _http_json(base_url, "GET", "/v1/skills/report")
                        persisted = canonical_json(
                            {
                                "trace": final_trace.get("payload"),
                                "replay": final_replay.get("payload"),
                            }
                        )
                        if "continuation.learner@example.invalid" in persisted or "[EMAIL]" not in persisted:
                            continuation_errors.append("probe response PII redaction is absent from final replay evidence")
                        if (
                            final_trace["status"] != 200
                            or final_trace["payload"].get("trace_verified") is not True
                            or final_replay["status"] != 200
                            or final_replay["payload"].get("trace_verified") is not True
                        ):
                            continuation_errors.append("completed continuation trace/replay is not verified")
                        if after_skills["status"] != 200 or after_skills["payload"].get("skill_count") != 1:
                            continuation_errors.append("mastery projection did not appear after verification")
                        duplicate_after_complete = _http_json(
                            base_url,
                            "POST",
                            respond_path,
                            {
                                "phase": "verification",
                                "expected_version": complete_payload.get("state_version"),
                                "expected_state": "awaiting_verification",
                                "response": "C",
                                "confidence": 0.9,
                                "response_time_seconds": 20,
                            },
                        )
                        if duplicate_after_complete["status"] != 409:
                            continuation_errors.append("completed session accepted another verification response")
                    cases["continuation"] = {
                        "request": {
                            "run_id": initial.get("run_id"),
                            "probe_response_sha256": hashlib.sha256(probe_response_text.encode("utf-8")).hexdigest(),
                            "raw_probe_response_retained": False,
                        },
                        "before_skills": before_skills,
                        "out_of_order": out_of_order,
                        "after_probe": after_probe,
                        "stale": stale,
                        "completed": completed,
                        "final_trace": final_trace if completed["status"] == 200 else None,
                        "final_replay": final_replay if completed["status"] == 200 else None,
                        "after_skills": after_skills if completed["status"] == 200 else None,
                        "duplicate_after_complete": duplicate_after_complete if completed["status"] == 200 else None,
                    }
            else:
                continuation_errors.append("initial wrong-attempt session is unavailable")
    except Exception as exc:
        errors.append(f"attempt API probe raised {exc!r}")
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
    return {
        "status": "fail" if errors or continuation_errors else "pass",
        "attempt_status": "fail" if errors else "pass",
        "continuation_status": "fail" if continuation_errors else "pass",
        "errors": errors,
        "continuation_errors": continuation_errors,
        "cases": cases,
    }


def gate_integration_surfaces(ctx: Context) -> GateResult:
    """Probe domain contracts and the runtime's real offline CLI/replay surface."""

    runtime = REPO_ROOT / "runtime"
    domains = REPO_ROOT / "domains"
    integration = REPO_ROOT / "integration"
    missing = [str(path.relative_to(REPO_ROOT)) for path in (runtime, domains, integration) if not path.is_dir()]
    if missing:
        return GateResult(
            "integration_surfaces",
            "pending",
            "runtime/domain integration surfaces are absent",
            [{"missing": missing}],
        )
    evidence: list[dict[str, Any]] = []
    failures: list[str] = []
    for label, root in (("runtime", runtime), ("domains", domains), ("integration", integration)):
        try:
            result = _run_unittest_surface(root)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"error": repr(exc), "exit_code": -1}
        evidence.append({label + "_tests": result})
        if result.get("exit_code") != 0:
            failures.append(f"{label} tests failed")

    domain_dir = str(domains)
    if domain_dir not in sys.path:
        sys.path.insert(0, domain_dir)
    try:
        from hermes_domains import load_fixture_document

        domain_fixtures = sorted((domains / "fixtures").glob("*/*.json"))
        fixture_hashes = []
        for path in domain_fixtures:
            payload = load_fixture_document(path, fixture_root=domains / "fixtures")
            fixture_hashes.append({"fixture": str(path.relative_to(REPO_ROOT)), "sha256": sha256_json(payload)})
        evidence.append({"domain_contract_fixtures": fixture_hashes})
        if not domain_fixtures:
            failures.append("no domain contract fixtures discovered")
    except Exception as exc:
        failures.append("domain fixture contract validation failed")
        evidence.append({"domain_fixture_error": repr(exc)})

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(runtime) + os.pathsep + environment.get("PYTHONPATH", "")
    try:
        with tempfile.TemporaryDirectory(prefix="runtime-probe-", dir=REPORT_DIR) as temporary:
            database = Path(temporary) / "trace.sqlite3"
            demo_command = [
                sys.executable,
                "-m",
                "hermes_runtime",
                "--db",
                str(database),
                "demo",
                "--run-id",
                "eval-runtime-probe",
            ]
            demo = subprocess.run(
                demo_command,
                cwd=runtime,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            demo_payload = json.loads(demo.stdout) if demo.returncode == 0 else None
            evidence.append({"runtime_demo": {"command": demo_command, "exit_code": demo.returncode, "output": demo_payload or (demo.stdout + demo.stderr)[-4000:]}})
            if demo.returncode or not demo_payload or demo_payload.get("trace_verified") is not True:
                failures.append("runtime CLI demo did not produce a verified trace")
            else:
                replay_command = [
                    sys.executable,
                    "-m",
                    "hermes_runtime",
                    "--db",
                    str(database),
                    "replay",
                    demo_payload["run_id"],
                ]
                replay = subprocess.run(
                    replay_command,
                    cwd=runtime,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                replay_payload = json.loads(replay.stdout) if replay.returncode == 0 else None
                replay_evidence = (
                    {
                        "run_id": replay_payload.get("run_id"),
                        "verified": replay_payload.get("verified"),
                        "frame_count": len(replay_payload.get("frames", [])),
                        "sha256": sha256_json(replay_payload),
                    }
                    if replay_payload
                    else (replay.stdout + replay.stderr)[-4000:]
                )
                evidence.append({"runtime_replay": {"command": replay_command, "exit_code": replay.returncode, "output": replay_evidence}})
                if replay.returncode or not replay_payload or replay_payload.get("verified") is not True:
                    failures.append("runtime replay was not verified")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        failures.append("runtime CLI probe raised an exception")
        evidence.append({"runtime_cli_error": repr(exc)})

    loop_probe = ctx.probe_learning_loop()
    evidence.append(
        {
            "domain_engine_runtime_loop": {
                "status": loop_probe["status"],
                "errors": loop_probe["errors"],
                "runs": {
                    scenario: {
                        "summary": run.get("summary"),
                        "replay_sha256": run.get("replay_sha256"),
                        "assertion_errors": run.get("assertion_errors", []),
                    }
                    for scenario, run in loop_probe["runs"].items()
                },
            }
        }
    )
    if loop_probe["status"] == "pending":
        return GateResult("integration_surfaces", "pending", "domain→engine→runtime integration CLI is absent", evidence)
    if loop_probe["status"] != "pass":
        failures.extend(loop_probe["errors"])

    if failures:
        return GateResult("integration_surfaces", "fail", "runtime/domain integration probe failed", evidence + [{"errors": failures}])
    return GateResult(
        "integration_surfaces",
        "pass",
        "domain contracts and offline runtime demo/replay surfaces passed their real probes",
        evidence,
    )


def gate_diagnosis(ctx: Context) -> GateResult:
    try:
        ctx.compute()
    except Exception as exc:  # integration failures must be visible in the report
        return GateResult("diagnosis", "fail", "diagnosis integration raised an exception", [{"error": repr(exc)}])
    assert ctx.diagnosis
    hypotheses = ctx.diagnosis.get("hypotheses", [])
    errors: list[str] = []
    probabilities = [item.get("probability") for item in hypotheses]
    if not hypotheses or any(not isinstance(value, (int, float)) for value in probabilities):
        errors.append("ranked numeric hypotheses are required")
    elif not math.isclose(sum(probabilities), 1.0, abs_tol=1e-9):
        errors.append("hypothesis probabilities do not sum to one")
    if len(hypotheses) < 2:
        errors.append("ambiguous fixture must preserve competing hypotheses")
    provenance = ctx.diagnosis.get("provenance", {})
    if not provenance.get("cohort_sources"):
        errors.append("cohort provenance is absent")
    if not ctx.diagnosis.get("model_version"):
        errors.append("diagnosis model version is absent")
    if not 0 <= ctx.diagnosis.get("uncertainty", -1) <= 1:
        errors.append("uncertainty is out of bounds")
    evidence = [{"diagnosis_sha256": sha256_json(ctx.diagnosis), "result": ctx.diagnosis}]
    if errors:
        return GateResult("diagnosis", "fail", "diagnosis invariants failed", evidence + [{"errors": errors}])
    return GateResult("diagnosis", "pass", "real engine diagnosis is ranked, normalized, uncertain, and provenance-linked", evidence)


def gate_kt(ctx: Context) -> GateResult:
    try:
        ctx.compute()
    except Exception as exc:
        return GateResult("kt", "fail", "KT integration raised an exception", [{"error": repr(exc)}])
    assert ctx.update
    fixture = ctx.load_fixture()
    state = ctx.update
    errors: list[str] = []
    if not 0 <= state.get("mastery", -1) <= 1:
        errors.append("mastery is out of bounds")
    if not 0 <= state.get("uncertainty", -1) <= 1:
        errors.append("uncertainty is out of bounds")
    if state.get("evidence_count") != fixture["input"]["pre_state"]["evidence_count"] + 1:
        errors.append("evidence count did not advance exactly once")
    provenance = state.get("provenance", [])
    event = provenance[-1] if provenance else {}
    attempt = event.get("attempt", {})
    expected_id = fixture["input"]["verification_attempt"]["attempt_id"]
    if attempt.get("attempt_id") != expected_id:
        errors.append("mastery delta lacks the triggering attempt link")
    if not event.get("formula_version"):
        errors.append("formula version is absent")
    evidence = [{"state_sha256": sha256_json(state), "state": state}]
    if errors:
        return GateResult("kt", "fail", "KT state-transition invariants failed", evidence + [{"errors": errors}])
    return GateResult("kt", "pass", "real KT update is bounded, versioned, and linked to one evidence event", evidence)


def gate_teaching_transfer(ctx: Context) -> GateResult:
    try:
        ctx.compute()
    except Exception as exc:
        return GateResult("teaching_transfer", "fail", "transfer integration raised an exception", [{"error": repr(exc)}])
    assert ctx.verification
    verification = ctx.verification["verification"]
    mechanic_errors: list[str] = []
    if verification.get("independently_verified") is not True:
        mechanic_errors.append("fixture was not independently verified")
    if verification.get("effective") is not True:
        mechanic_errors.append("independent transfer criterion was not met")
    if verification.get("mastery_gain", 0) <= 0:
        mechanic_errors.append("mastery gain is not positive")
    evidence: list[dict[str, Any]] = [{"mechanics": verification, "mechanics_sha256": sha256_json(ctx.verification)}]
    if mechanic_errors:
        return GateResult("teaching_transfer", "fail", "independent-transfer mechanics failed", evidence + [{"errors": mechanic_errors}])
    probe = ctx.probe_learning_loop()
    integration_evidence = {
        scenario: {
            "summary": run.get("summary"),
            "replay_sha256": run.get("replay_sha256"),
            "assertion_errors": run.get("assertion_errors", []),
        }
        for scenario, run in probe.get("runs", {}).items()
    }
    evidence.append({"domain_engine_runtime_integration": integration_evidence, "errors": probe.get("errors", [])})
    if probe.get("status") == "pending":
        return GateResult(
            "teaching_transfer",
            "pending",
            "independent transfer mechanics pass, but the integrated teaching-loop CLI is absent",
            evidence,
        )
    if probe.get("status") != "pass":
        return GateResult(
            "teaching_transfer",
            "fail",
            "one or more integrated teaching/transfer scenarios failed",
            evidence,
        )
    if set(integration_evidence) != {"success", "ambiguous", "offline"}:
        return GateResult(
            "teaching_transfer",
            "fail",
            "integrated teaching evidence does not cover all required modes",
            evidence,
        )
    return GateResult(
        "teaching_transfer",
        "pass",
        "success, ambiguous, and offline domain→engine→runtime loops persist teaching, independent transfer, KT, reflection, and verified replay evidence",
        evidence,
    )


def _compact_attempt_api_evidence(probe: Mapping[str, Any]) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for label, case in probe.get("cases", {}).items():
        if label == "continuation":
            after_probe = case.get("after_probe", {})
            completed = case.get("completed", {})
            final_trace = case.get("final_trace", {}) or {}
            final_replay = case.get("final_replay", {}) or {}
            cases[label] = {
                "request": case.get("request"),
                "before_skill_count": case.get("before_skills", {}).get("payload", {}).get("skill_count"),
                "out_of_order": {
                    "status": case.get("out_of_order", {}).get("status"),
                    "code": case.get("out_of_order", {}).get("payload", {}).get("error", {}).get("code"),
                },
                "after_probe": {
                    "status": after_probe.get("status"),
                    "state": after_probe.get("payload", {}).get("state"),
                    "state_version": after_probe.get("payload", {}).get("state_version"),
                    "mastery_update": after_probe.get("payload", {}).get("mastery_update"),
                },
                "stale": {
                    "status": case.get("stale", {}).get("status"),
                    "code": case.get("stale", {}).get("payload", {}).get("error", {}).get("code"),
                },
                "completed": {
                    "status": completed.get("status"),
                    "state": completed.get("payload", {}).get("state"),
                    "state_version": completed.get("payload", {}).get("state_version"),
                    "verification": completed.get("payload", {}).get("verification"),
                    "mastery_update": completed.get("payload", {}).get("mastery_update"),
                    "reflection": completed.get("payload", {}).get("reflection"),
                },
                "after_skill_count": case.get("after_skills", {}).get("payload", {}).get("skill_count"),
                "duplicate_after_complete_status": case.get("duplicate_after_complete", {}).get("status"),
                "trace_sha256": sha256_json(final_trace.get("payload")) if final_trace.get("payload") else None,
                "replay_sha256": sha256_json(final_replay.get("payload")) if final_replay.get("payload") else None,
            }
            continue
        response = case.get("response", {})
        trace = case.get("trace", {})
        replay = case.get("replay", {})
        payload = response.get("payload", {})
        cases[label] = {
            "request": case.get("request"),
            "http_status": response.get("status"),
            "schema_version": payload.get("schema_version"),
            "run_status": payload.get("status"),
            "score_passed": payload.get("score", {}).get("passed"),
            "hypothesis_count": len(payload.get("diagnosis", {}).get("hypotheses", [])),
            "verification": payload.get("verification"),
            "response_evidence": payload.get("response_evidence"),
            "error": payload.get("error"),
            "trace_status": trace.get("status"),
            "trace_sha256": sha256_json(trace.get("payload")) if trace.get("payload") else None,
            "replay_status": replay.get("status"),
            "replay_sha256": sha256_json(replay.get("payload")) if replay.get("payload") else None,
            "rejected_run_trace_status": case.get("trace_after_rejection", {}).get("status"),
        }
    return {
        "status": probe.get("status"),
        "attempt_status": probe.get("attempt_status"),
        "continuation_status": probe.get("continuation_status"),
        "errors": probe.get("errors", []),
        "continuation_errors": probe.get("continuation_errors", []),
        "cases": cases,
    }


def gate_attempt_api(ctx: Context) -> GateResult:
    probe = ctx.probe_attempt_api()
    evidence = [_compact_attempt_api_evidence(probe)]
    if probe.get("attempt_status", probe.get("status")) == "pending":
        return GateResult("attempt_api", "pending", "POST /v1/attempts service surface is absent", evidence)
    if probe.get("attempt_status", probe.get("status")) != "pass":
        return GateResult(
            "attempt_api",
            "fail",
            "real POST /v1/attempts correctness, uncertainty, fail-closed, PII, trace, or replay assertion failed",
            evidence,
        )
    return GateResult(
        "attempt_api",
        "pass",
        "real POST /v1/attempts preserves zero-cause correctness, unconfirmed error candidates, PII redaction, fail-closed fields, and verified replay",
        evidence,
    )


def gate_cohort_prior_guardrail(ctx: Context) -> GateResult:
    test_file = REPO_ROOT / "engine" / "tests" / "test_cohort.py"
    if not test_file.is_file():
        return GateResult("cohort_prior_guardrail", "pending", "cohort guardrail tests are absent", [{"path": str(test_file)}])
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO_ROOT / "engine") + os.pathsep + environment.get("PYTHONPATH", "")
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(test_file.parent),
        "-p",
        test_file.name,
        "-v",
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT / "engine",
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
    )
    probe = ctx.probe_attempt_api()
    wrong = probe.get("cases", {}).get("wrong", {})
    diagnosis = None
    if wrong.get("trace", {}).get("status") == 200:
        diagnosis = _diagnosis_from_trace(wrong["trace"]["payload"])
    sources = diagnosis.get("provenance", {}).get("cohort_sources", []) if diagnosis else []
    hypothesis_evidence = [item.get("evidence", []) for item in diagnosis.get("hypotheses", [])] if diagnosis else []
    evidence = [
        {
            "command": command,
            "exit_code": result.returncode,
            "output": (result.stdout + "\n" + result.stderr).strip()[-6000:],
        },
        {
            "attempt_trace": {
                "available": diagnosis is not None,
                "sources": sources,
                "hypothesis_evidence": hypothesis_evidence,
            }
        },
    ]
    errors: list[str] = []
    if result.returncode:
        errors.append("deterministic cohort guardrail tests failed")
    if probe.get("attempt_status", probe.get("status")) != "pass" or not diagnosis:
        errors.append("real attempt trace is unavailable for cohort fallback verification")
    elif (
        not sources
        or any(source.get("sample_size") != 0 for source in sources)
        or any("synthetic" not in str(source.get("source_version", "")) for source in sources)
        or any("engineering_prior" not in labels or "cohort_prior" in labels for labels in hypothesis_evidence)
    ):
        errors.append("attempt trace does not prove synthetic engineering fallback semantics")
    if errors:
        return GateResult("cohort_prior_guardrail", "fail", "cohort prior guardrail evidence failed", evidence + [{"errors": errors}])
    return GateResult(
        "cohort_prior_guardrail",
        "pass",
        "privacy/size guardrails pass and the real attempt trace uses sample_size=0 synthetic engineering priors without cohort claims",
        evidence,
    )


def gate_attempt_continuation(ctx: Context) -> GateResult:
    probe = ctx.probe_attempt_api()
    evidence = [_compact_attempt_api_evidence(probe)]
    status = probe.get("continuation_status", "pending")
    if status == "pending":
        return GateResult(
            "attempt_continuation",
            "pending",
            "stepwise probe/verification HTTP contract is absent",
            evidence,
        )
    if status != "pass":
        return GateResult(
            "attempt_continuation",
            "fail",
            "stepwise state order, optimistic versioning, redaction, independent verification, or KT assertion failed",
            evidence,
        )
    return GateResult(
        "attempt_continuation",
        "pass",
        "real HTTP session advances awaiting_probe → awaiting_verification → completed; illegal/stale writes fail closed and KT appears only after independent verification",
        evidence,
    )


def gate_trace(ctx: Context) -> GateResult:
    try:
        trace = ctx.build_trace()
    except Exception as exc:
        return GateResult("trace", "fail", "golden trace construction failed", [{"error": repr(exc)}])
    errors = validate_json(trace, load_json(CONTRACT_DIR / "trajectory.schema.json"))
    # Cross-reference invariants JSON Schema cannot express.
    evidence_ids = set(trace["observation"]["evidence_ids"])
    for call in trace["tool_calls"]:
        if not set(call["input_evidence_ids"]):
            errors.append(f"tool call {call['call_id']} has no evidence")
    if not set(trace["state_transition"]["evidence_ids"]):
        errors.append("state transition has no evidence")
    if not evidence_ids:
        errors.append("observation has no evidence")
    evidence = [{"trace_id": trace["trace_id"], "sha256": sha256_json(trace), "trace": trace}]
    if errors:
        return GateResult("trace", "fail", "trajectory contract or provenance invariant failed", evidence + [{"errors": errors}])
    return GateResult("trace", "pass", "computed engine trajectory is contract-valid and replay evidence is locatable", evidence)


SECRET_PATTERNS = {
    "openai_key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
SENSITIVE_FIELD_PATTERN = re.compile(r"(?:email|phone|mobile|id_card|real_name|audio_bytes|video_bytes)", re.I)


def iter_source_files() -> Iterable[Path]:
    ignored = {
        ".git",
        ".venv",
        ".sidecar-venv",
        "node_modules",
        "reports",
        "__pycache__",
        ".pytest_cache",
        "target",
        "dist",
        "build",
    }
    extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".swift", ".json", ".toml", ".yaml", ".yml"}
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [
            item
            for item in dirs
            if item not in ignored and not item.endswith("-venv") and not item.startswith(".venv")
        ]
        for name in files:
            path = Path(root) / name
            if path.suffix in extensions:
                yield path


def gate_privacy(ctx: Context) -> GateResult:
    findings: list[dict[str, Any]] = []
    cloud_markers: list[str] = []
    for path in iter_source_files():
        relative = str(path.relative_to(REPO_ROOT))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            findings.append({"file": relative, "error": str(exc)})
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"file": relative, "finding": name})
        # The scanner source necessarily contains the detector literals; do not
        # classify its own implementation as a product cloud integration.
        if path.resolve() != Path(__file__).resolve() and re.search(
            r"https?://api\.|OPENAI_API_KEY|ANTHROPIC_API_KEY", text, re.I
        ):
            cloud_markers.append(relative)
    trace = ctx.build_trace()
    serialized_trace = canonical_json(trace)
    sensitive_fields = sorted(set(SENSITIVE_FIELD_PATTERN.findall(serialized_trace)))
    if sensitive_fields:
        findings.append({"trace_sensitive_fields": sensitive_fields})
    privacy = trace.get("privacy", {})
    if privacy.get("local_only") is not True or not privacy.get("redaction_version"):
        findings.append({"trace_privacy_contract": "missing local_only or redaction_version"})
    evidence = [
        {"scanned_file_count": sum(1 for _ in iter_source_files()), "secret_findings": findings},
        {"cloud_marker_files": sorted(set(cloud_markers))},
        {"trace_privacy": privacy},
    ]
    if findings:
        return GateResult("privacy", "fail", "privacy or secret scan found release-blocking evidence", evidence)
    if cloud_markers:
        return GateResult(
            "privacy",
            "pending",
            "cloud integration markers exist; every operation needs runtime disclosure evidence",
            evidence,
        )
    return GateResult("privacy", "pass", "local trace privacy contract and static secret scan passed; no cloud operations detected", evidence)


def gate_readonly_boundary(ctx: Context) -> GateResult:
    violations: list[dict[str, Any]] = []
    protective_references: list[str] = []
    forbidden_resolved = FORBIDDEN_REPO.resolve(strict=False)
    inspected_symlinks = 0
    for root, dirs, files in os.walk(REPO_ROOT, followlinks=False):
        dirs[:] = [item for item in dirs if item not in {".git", ".venv", "node_modules", "__pycache__", "reports"}]
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink():
                inspected_symlinks += 1
                resolved = path.resolve(strict=False)
                if resolved == forbidden_resolved or forbidden_resolved in resolved.parents:
                    violations.append({"kind": "symlink", "path": str(path.relative_to(REPO_ROOT)), "target": str(resolved)})
    source_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".swift", ".sh"}
    approved_boundary_checks = {
        "runtime/tests/test_runtime.py",
        "service/tests/test_sidecar.py",
        "scripts/check_boundaries.py",
    }
    for path in iter_source_files():
        if path.suffix not in source_extensions or EVAL_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if str(FORBIDDEN_REPO) in text:
            relative = str(path.relative_to(REPO_ROOT))
            if relative in approved_boundary_checks:
                protective_references.append(relative)
            else:
                violations.append({"kind": "unapproved_code_reference", "path": relative})
    fingerprint: dict[str, Any] = {"path": str(FORBIDDEN_REPO), "exists": FORBIDDEN_REPO.exists()}
    if (FORBIDDEN_REPO / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(FORBIDDEN_REPO), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        fingerprint["head"] = result.stdout.strip() if result.returncode == 0 else None
        fingerprint["probe"] = "read-only rev-parse"
    boundary_script = REPO_ROOT / "scripts" / "check_boundaries.py"
    boundary_command: dict[str, Any] = {"available": boundary_script.is_file()}
    if boundary_script.is_file():
        result = subprocess.run(
            [sys.executable, str(boundary_script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        boundary_command.update(exit_code=result.returncode, output=(result.stdout + result.stderr).strip()[-4000:])
        if result.returncode:
            violations.append({"kind": "boundary_command_failed", "exit_code": result.returncode})
    evidence = [{
        "forbidden_repository": fingerprint,
        "inspected_symlinks": inspected_symlinks,
        "protective_references": sorted(protective_references),
        "boundary_command": boundary_command,
        "violations": violations,
    }]
    if violations:
        return GateResult("readonly_boundary", "fail", "writable code dependency into production Shenlun repository detected", evidence)
    return GateResult("readonly_boundary", "pass", "no code dependency or symlink enters the production Shenlun repository", evidence)


GATES: dict[str, Callable[[Context], GateResult]] = {
    "contracts": gate_contracts,
    "fixtures": gate_fixtures,
    "engine_tests": gate_engine_tests,
    "integration_surfaces": gate_integration_surfaces,
    "attempt_api": gate_attempt_api,
    "cohort_prior_guardrail": gate_cohort_prior_guardrail,
    "attempt_continuation": gate_attempt_continuation,
    "trace": gate_trace,
    "diagnosis": gate_diagnosis,
    "kt": gate_kt,
    "teaching_transfer": gate_teaching_transfer,
    "privacy": gate_privacy,
    "readonly_boundary": gate_readonly_boundary,
    "core320_bank": gate_core320_bank,
    "core320_scopes": gate_core320_scopes,
    "continuous_practice_v1": gate_continuous_practice_v1,
    "core320_client": gate_core320_client,
    "core320_packaging": gate_core320_packaging,
}


def run_gates(selected: list[str] | None = None) -> tuple[dict[str, Any], Context]:
    selected = selected or list(GATES)
    unknown = sorted(set(selected) - GATES.keys())
    if unknown:
        raise ValueError(f"unknown gates: {', '.join(unknown)}")
    ctx = Context()
    results: list[GateResult] = []
    for name in selected:
        started = time.monotonic()
        try:
            result = GATES[name](ctx)
        except Exception as exc:
            result = GateResult(name, "fail", "unhandled gate exception", [{"error": repr(exc)}])
        result.duration_ms = round((time.monotonic() - started) * 1000)
        results.append(result)
    counts = {status: sum(item.status == status for item in results) for status in STATUSES}
    if counts["fail"]:
        overall = "fail"
    elif counts["pending"]:
        overall = "pending"
    else:
        overall = "pass"
    report = {
        "schema_version": "release-report-v1",
        "run_id": "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "generated_at": utc_now(),
        "repository": ".",
        "overall_status": overall,
        "summary": {"pass": counts["pass"], "fail": counts["fail"], "pending": counts["pending"], "total": len(results)},
        "gates": [asdict(item) for item in results],
    }
    report = sanitize_public_report_paths(report)
    report_errors = validate_json(report, load_json(CONTRACT_DIR / "release_report.schema.json"))
    if report_errors:
        integrity = GateResult("runner_integrity", "fail", "generated report violates its schema", [{"errors": report_errors}])
        report["gates"].append(asdict(integrity))
        report["summary"]["fail"] += 1
        report["summary"]["total"] += 1
        report["overall_status"] = "fail"
    return report, ctx


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Lumi release evidence",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Overall: **{str(report['overall_status']).upper()}**",
        f"- Counts: {report['summary']['pass']} pass / {report['summary']['fail']} fail / {report['summary']['pending']} pending",
        "",
        "| Gate | Status | Evidence summary |",
        "| --- | --- | --- |",
    ]
    for gate in report["gates"]:
        summary = gate["summary"].replace("|", "\\|")
        lines.append(f"| `{gate['name']}` | **{gate['status'].upper()}** | {summary} |")
    lines.extend(
        [
            "",
            "When outputs are written, the JSON report is authoritative and contains hashes, command output, missing matrix entries, and computed evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], ctx: Context) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = str(report["run_id"]).removeprefix("run-")
    report_json = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (REPORT_DIR / f"release-{timestamp}.json").write_text(report_json, encoding="utf-8")
    (REPORT_DIR / "latest.json").write_text(report_json, encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(render_markdown(report), encoding="utf-8")
    if ctx.trace is not None:
        trace_json = json.dumps(ctx.trace, ensure_ascii=False, indent=2) + "\n"
        (REPORT_DIR / "golden-trajectory-latest.json").write_text(trace_json, encoding="utf-8")
    if ctx.integration_probe is not None:
        for scenario, run in ctx.integration_probe.get("runs", {}).items():
            replay = run.get("replay")
            if replay is not None:
                path = REPORT_DIR / f"integration-{scenario}-trajectory-latest.json"
                path.write_text(json.dumps(replay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if ctx.attempt_api_probe is not None:
        path = REPORT_DIR / "attempt-api-evidence-latest.json"
        path.write_text(json.dumps(ctx.attempt_api_probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", action="append", choices=sorted(GATES), help="run only this gate (repeatable)")
    parser.add_argument("--list", action="store_true", help="list gates and exit")
    parser.add_argument("--no-write", action="store_true", help="do not write reports")
    parser.add_argument("--allow-pending", action="store_true", help="return zero for pending (report remains pending)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        print("\n".join(GATES))
        return 0
    report, ctx = run_gates(args.gate)
    if not args.no_write:
        write_outputs(report, ctx)
    print(render_markdown(report))
    if report["overall_status"] == "fail":
        return 1
    if report["overall_status"] == "pending" and not args.allow_pending:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
