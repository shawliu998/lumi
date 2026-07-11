#!/usr/bin/env python3
"""Dependency-free Lumi release gate and evidence runner.

The runner probes real repository capabilities. Missing required capabilities are
PENDING, invalid present capabilities are FAIL, and only asserted evidence can
PASS. It persists release artifacts only in evals/reports; black-box probes may
use automatically removed operating-system temporary directories.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import select
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
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
REPORT_PII_PATTERNS = (
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[ID]"),
)
REPORT_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIzaSy[A-Za-z0-9_-]{33}"),
    re.compile(r"npm_[A-Za-z0-9]{36}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
LOCAL_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9:])/(?:Users|var|private|tmp|Volumes|Library|Applications|opt|usr)/[^\s\"'<>|]+",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _eval_opaque_identifier(prefix: str, label: str) -> str:
    """Derive a stable non-PII public identifier for black-box evaluation."""

    if prefix not in {"r", "c"}:
        raise ValueError("opaque evaluation identifier prefix must be r or c")
    digest = hashlib.sha256(
        f"lumi-eval:{prefix}:{label}".encode("utf-8")
    ).digest()[:20]
    alphabet = "ABCDEFGHIJKLMNOP"
    encoded = "".join(
        f"{alphabet[byte >> 4]}{alphabet[byte & 15]}" for byte in digest
    )
    return f"{prefix}_{encoded}"


def _eval_public_run_id(label: str) -> str:
    return _eval_opaque_identifier("r", label)


def _eval_public_command_id(label: str) -> str:
    return _eval_opaque_identifier("c", label)


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


def _resolve_local_schema_ref(root_schema: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if reference == "#":
        return root_schema
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON Schema references are supported: {reference!r}")
    target: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, Mapping) or part not in target:
            raise ValueError(f"unresolved local JSON Schema reference: {reference!r}")
        target = target[part]
    if not isinstance(target, Mapping):
        raise ValueError(f"local JSON Schema reference is not an object: {reference!r}")
    return target


def validate_json(
    instance: Any,
    schema: Mapping[str, Any],
    path: str = "$",
    *,
    _root_schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate the dependency-free JSON Schema subset used by this harness.

    The release contracts intentionally use only local references, ``allOf``,
    primitive types, closed objects, bounded numbers/arrays, and string
    constraints. Unsupported remote references fail closed instead of silently
    accepting an instance.
    """

    root_schema = _root_schema or schema
    errors: list[str] = []
    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            errors.append(f"{path}: $ref must be a string")
        else:
            try:
                referenced = _resolve_local_schema_ref(root_schema, reference)
            except ValueError as exc:
                errors.append(f"{path}: {exc}")
            else:
                errors.extend(
                    validate_json(instance, referenced, path, _root_schema=root_schema)
                )
    all_of = schema.get("allOf", [])
    if not isinstance(all_of, list):
        errors.append(f"{path}: allOf must be an array")
    else:
        for index, child_schema in enumerate(all_of):
            if not isinstance(child_schema, Mapping):
                errors.append(f"{path}: allOf[{index}] must be an object")
                continue
            errors.extend(
                validate_json(instance, child_schema, path, _root_schema=root_schema)
            )
    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else expected
    if expected_types and not any(_json_type_matches(instance, item) for item in expected_types):
        return [f"{path}: expected type {expected_types}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: value {instance!r} is not in enum")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: number is below minimum {schema['minimum']!r}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: number is above maximum {schema['maximum']!r}")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: string shorter than minLength")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: string does not match pattern")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: array shorter than minItems")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: array longer than maxItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(instance):
                errors.extend(
                    validate_json(
                        item,
                        item_schema,
                        f"{path}[{index}]",
                        _root_schema=root_schema,
                    )
                )
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
                errors.extend(
                    validate_json(
                        instance[key],
                        child_schema,
                        f"{path}.{key}",
                        _root_schema=root_schema,
                    )
                )
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
    schedule_api_probe: dict[str, Any] | None = None
    service_tests_probe: dict[str, Any] | None = None

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
                    "version": "0.2.0",
                    "input_evidence_ids": ["attempt:" + inputs["attempt"]["attempt_id"]],
                    "output": {"sha256": diagnosis_hash, "result": self.diagnosis},
                },
                {
                    "call_id": "call-verification-001",
                    "tool": "hermes_explainable_learning_model.verify_intervention",
                    "version": "0.2.0",
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

    def probe_schedule_api(self) -> dict[str, Any]:
        if self.schedule_api_probe is None:
            self.schedule_api_probe = _probe_schedule_api()
        return self.schedule_api_probe

    def probe_service_tests(self) -> dict[str, Any]:
        if self.service_tests_probe is None:
            self.service_tests_probe = _probe_service_tests()
        return self.service_tests_probe


def gate_contracts(ctx: Context) -> GateResult:
    schemas = sorted(CONTRACT_DIR.glob("*.schema.json"))
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    required = {
        "representative_case.schema.json",
        "trajectory.schema.json",
        "release_report.schema.json",
        "assistance-result.schema.json",
        "misconception-dossier.schema.json",
        "today-plan.schema.json",
        "review-schedule.schema.json",
    }
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


def _run_unittest_surface(root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-v"]
    # Integration tests exercise the real cross-package boundary and therefore
    # need the same repository package roots as the CLI probe below.  Giving
    # every surface the shared environment also prevents a test from passing
    # only because the caller happened to export a local PYTHONPATH.
    environment = _integration_environment()
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


def _probe_service_tests() -> dict[str, Any]:
    """Run the complete sidecar test surface once per release Context."""

    service = REPO_ROOT / "service"
    test_dir = service / "tests"
    if not test_dir.is_dir():
        return {
            "status": "pending",
            "exit_code": None,
            "errors": ["service test directory is absent"],
        }
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        str(test_dir),
        "-v",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=service,
            env=_service_environment(),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "fail",
            "command": command,
            "exit_code": -1,
            "output": "",
            "errors": [f"complete service tests could not finish: {exc!r}"],
        }
    output = (result.stdout + "\n" + result.stderr).strip()[-12000:]
    return {
        "status": "pass" if result.returncode == 0 else "fail",
        "command": command,
        "exit_code": result.returncode,
        "output": output,
        "errors": [] if result.returncode == 0 else ["complete service tests failed"],
    }


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


class _ScheduleEvalClock:
    def __init__(self, value: date) -> None:
        self.value = value

    def __call__(self) -> date:
        return self.value


class _ScheduleHTTPHarness:
    """Real loopback HTTP harness with an injectable local calendar.

    The production application and HTTP router are used unchanged.  The clock
    is injectable solely so one release probe can prove +1/+3 day behavior and
    historical-plan protections without waiting several wall-clock days.
    """

    def __init__(self, root: Path, *, start: date = date(2026, 7, 11)) -> None:
        for package in ("service", "integration", "runtime", "domains", "engine"):
            path = str(REPO_ROOT / package)
            if path not in sys.path:
                sys.path.insert(0, path)
        from hermes_service.api import create_server
        from hermes_service.application import SidecarApplication

        self._create_server = create_server
        self._application_type = SidecarApplication
        self.database = root / "schedule-eval.sqlite3"
        self.clock = _ScheduleEvalClock(start)
        self._servers: list[Any] = []
        self._threads: list[threading.Thread] = []
        self.base_url = self.start_server()

    def start_server(self, *, clock: Callable[[], date] | None = None) -> str:
        application = self._application_type(
            self.database,
            today_provider=clock or self.clock,
        )
        server = self._create_server(application, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._servers.append(server)
        self._threads.append(thread)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def close(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=2)
        self._servers.clear()
        self._threads.clear()

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        return _http_json(base_url or self.base_url, method, path, body)

    def create_plan(
        self,
        command_id: str,
        *,
        budget: int = 60,
        exam_date: str | None = None,
        body_overrides: Mapping[str, Any] | None = None,
        raw_command_id: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "plan_date": self.clock.value.isoformat(),
            "exam_date": exam_date
            if exam_date is not None
            else (self.clock.value + timedelta(days=30)).isoformat(),
            "daily_budget_minutes": budget,
            "expected_version": 0,
            "command_id": (
                command_id
                if raw_command_id
                else _eval_public_command_id(command_id)
            ),
        }
        if body_overrides:
            body.update(body_overrides)
        return self.request("POST", "/v1/today-plans", body)

    def seed_attempt(
        self,
        run_id: str,
        *,
        initial_response: str = "A",
        verification_response: str = "A",
    ) -> dict[str, Any]:
        initial = self.request(
            "POST",
            "/v1/attempts",
            {
                "fixture_id": "xingce.data-analysis.growth-rate.synthetic-01",
                "response": initial_response,
                "confidence": 0.6,
                "response_time_seconds": 20,
                "run_id": _eval_public_run_id(run_id),
            },
        )
        if initial["status"] != 201:
            raise RuntimeError(
                f"initial attempt returned {initial['status']}: {initial['payload']!r}"
            )
        attempt = initial["payload"]
        probe = self.request(
            "POST",
            attempt["links"]["respond"],
            {
                "phase": "probe",
                "expected_version": attempt["state_version"],
                "expected_state": "awaiting_probe",
                "prompt_instance_id": attempt["probe"]["prompt_instance_id"],
                "response": "120÷100",
                "confidence": 0.8,
                "response_time_seconds": 15,
            },
        )
        if probe["status"] != 200:
            raise RuntimeError(
                f"probe continuation returned {probe['status']}: {probe['payload']!r}"
            )
        after_probe = probe["payload"]
        verification = self.request(
            "POST",
            after_probe["links"]["respond"],
            {
                "phase": "verification",
                "expected_version": after_probe["state_version"],
                "expected_state": "awaiting_verification",
                "prompt_instance_id": after_probe["verification"][
                    "prompt_instance_id"
                ],
                "response": verification_response,
                "confidence": 0.9,
                "response_time_seconds": 20,
            },
        )
        if verification["status"] != 200:
            raise RuntimeError(
                "verification continuation returned "
                f"{verification['status']}: {verification['payload']!r}"
            )
        completed = verification["payload"]
        if completed.get("state") != "completed":
            raise RuntimeError("attempt did not reach the completed state")
        return completed

    def seed_evaluation_fixture(self, run_id: str) -> dict[str, Any]:
        """Persist one completed non-learner run through the internal eval path.

        This deliberately bypasses the public HTTP API.  Synthetic/evaluation
        trajectories are useful to exercise deterministic fixtures, but they
        must never be constructible as learner activity or appear in learner
        projections.
        """

        from hermes_integration.loop import run_scenario

        session, result = run_scenario(
            "success",
            self.database,
            run_id=run_id,
        )
        try:
            return {
                "run_id": result.state.run_id,
                "status": result.state.status.value,
                "evidence_origin": result.state.context.get("evidence_origin"),
                "trace_verified": session.store.verify(result.state.run_id),
            }
        finally:
            session.store.close()

    def task_command(
        self,
        plan: Mapping[str, Any],
        task: Mapping[str, Any],
        action: str,
        command_id: str,
        *,
        expected_version: int | None = None,
        expected_task_version: int | None = None,
        postpone_until: str | None = None,
        extra: Mapping[str, Any] | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "action": action,
            "expected_version": (
                int(plan["version"])
                if expected_version is None
                else expected_version
            ),
            "expected_task_version": (
                int(task["version"])
                if expected_task_version is None
                else expected_task_version
            ),
            "command_id": _eval_public_command_id(command_id),
        }
        if postpone_until is not None:
            body["postpone_until"] = postpone_until
        if extra:
            body.update(extra)
        return self.request(
            "POST",
            f"/v1/today-plans/{plan['plan_id']}/tasks/{task['task_id']}/commands",
            body,
            base_url=base_url,
        )


@dataclass
class _ScheduleChecks:
    errors: list[str] = field(default_factory=list)
    count: int = 0

    def that(self, condition: bool, message: str) -> None:
        self.count += 1
        if not condition:
            self.errors.append(message)

    def equal(self, actual: Any, expected: Any, message: str) -> None:
        self.that(actual == expected, f"{message}: expected {expected!r}, got {actual!r}")


def _json_pointer_value(document: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    current = document
    for encoded in pointer[1:].split("/"):
        part = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, Mapping):
            current = current[part]
        else:
            raise KeyError(part)
    return current


def _schedule_contract_checks(
    payload: Mapping[str, Any],
    contract_name: str,
    checks: _ScheduleChecks,
    label: str,
) -> None:
    schema = load_json(CONTRACT_DIR / contract_name)
    for error in validate_json(payload, schema):
        checks.that(False, f"{label} contract: {error}")


def _schedule_claim_checks(
    plan: Mapping[str, Any],
    schedule: Mapping[str, Any],
    checks: _ScheduleChecks,
    label: str,
) -> None:
    excluded = set(plan.get("basis", {}).get("excluded_inputs", []))
    checks.that(
        {
            "cohort_statistics",
            "peer_comparison",
            "population_effect",
            "authoritative_longitudinal_mastery",
            "learner_fatigue_signal",
        }.issubset(excluded),
        f"{label}: unsupported cohort/peer/mastery/fatigue inputs are not excluded",
    )
    checks.equal(
        plan.get("mastery_write_capability"),
        False,
        f"{label}: TodayPlan must not write mastery",
    )
    checks.equal(
        schedule.get("mastery_write_capability"),
        False,
        f"{label}: ReviewSchedule must not write mastery",
    )
    checks.equal(
        schedule.get("population_evidence"),
        "unavailable",
        f"{label}: population evidence must be unavailable",
    )
    forbidden_keys = {
        "peer_rate",
        "peer_error_rate",
        "cohort_rate",
        "cohort_size",
        "population_error_rate",
        "forgetting_probability",
        "fatigue_score",
        "mastery_gain",
        "mastery_delta",
        "predicted_mastery",
        "retention_probability",
    }
    forbidden_phrases = (
        re.compile(r"(?i)peer (?:error )?rate|cohort average|forgetting probability|fatigue score|mastery (?:gain|increase)"),
        re.compile(r"掌握度(?:已)?提升|同学平均错误率|遗忘概率|疲劳分数"),
    )

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                checks.that(
                    str(key) not in forbidden_keys,
                    f"{label}: unsupported claim field at {path}.{key}",
                )
                visit(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, str) and "excluded_inputs" not in path:
            for pattern in forbidden_phrases:
                checks.that(
                    pattern.search(value) is None,
                    f"{label}: unsupported claim language at {path}",
                )

    visit(plan, "plan")
    visit(schedule, "schedule")


def _schedule_evidence_checks(
    harness: _ScheduleHTTPHarness,
    tasks: Iterable[Mapping[str, Any]],
    checks: _ScheduleChecks,
    label: str,
) -> int:
    trace_cache: dict[str, Mapping[str, Any]] = {}
    semantic_contracts = {
        "verification_effective": (
            "trace_skill_evidence",
            "phase_completed",
            "update",
            r"/output/evidence/verification_effective",
        ),
        "initial_answer_passed": (
            "trace_observation",
            "phase_completed",
            "observe",
            r"/output/score/passed",
        ),
        "candidate_hypothesis": (
            "candidate_cause",
            "phase_completed",
            "diagnose",
            r"/output/diagnosis/hypotheses/\d+/status",
        ),
        "candidate_claim_status": (
            "candidate_cause",
            "probe_assessed",
            None,
            r"/assessments/\d+/claim_status",
        ),
        "terminal_completed": (
            "trace_terminal",
            "phase_completed",
            "reflect",
            r"/state_after/status",
        ),
    }
    resolved = 0
    for task in tasks:
        checks.equal(
            task.get("definition_status"),
            "authored_engineering_estimate_unvalidated",
            f"{label}: task duration definition must be unvalidated",
        )
        checks.equal(
            task.get("schedule_window", {}).get("calibration"),
            "fixed_engineering_policy_unvalidated",
            f"{label}: schedule window must be unvalidated",
        )
        skip_consequence = str(task.get("skip_consequence", ""))
        checks.that(
            "保留在 ReviewSchedule" in skip_consequence
            and "公平轮候" in skip_consequence,
            f"{label}: skip consequence must disclose fair queue retention",
        )
        checks.that(
            "下一学习日重新出现" not in skip_consequence,
            f"{label}: skip consequence makes an impossible next-day guarantee",
        )
        success_criterion = str(task.get("success_criterion", ""))
        checks.that(
            "同题组独立复测" in success_criterion
            and "不构成未见平行题上的迁移验证" in success_criterion,
            f"{label}: success criterion must disclose same-fixture retest limits",
        )
        checks.that(
            "无提示的新题" not in success_criterion,
            f"{label}: success criterion fabricates novel-item transfer",
        )
        for field_name in (
            "policy_offset_days",
            "base_due_on",
            "initial_due_on",
            "scheduling_adjustment",
        ):
            checks.equal(
                task.get("schedule_window", {}).get(field_name),
                task.get(field_name),
                f"{label}: schedule window {field_name} must match the task",
            )
        activity = task.get("activity_ref", {})
        checks.equal(
            activity.get("availability"),
            "launchable",
            f"{label}: task activity must be launchable",
        )
        checks.equal(
            activity.get("launch_endpoint"),
            "/v1/attempts",
            f"{label}: task launch endpoint must be executable",
        )
        checks.equal(
            activity.get("novelty_status"),
            "same_fixture_retest_not_novel_item",
            f"{label}: activity novelty limitation",
        )
        for evidence_ref in task.get("evidence_refs", []):
            if not isinstance(evidence_ref, Mapping):
                checks.that(False, f"{label}: evidence ref is not structured")
                continue
            run_id = str(evidence_ref.get("run_id", ""))
            if run_id not in trace_cache:
                response = harness.request("GET", f"/v1/runs/{run_id}/trace")
                checks.equal(
                    response["status"],
                    200,
                    f"{label}: evidence source trace must be readable",
                )
                if response["status"] != 200:
                    continue
                trace_cache[run_id] = response["payload"]
            trace = trace_cache[run_id]
            checks.equal(
                trace.get("trace_verified"),
                True,
                f"{label}: evidence source trace hash chain",
            )
            events = trace.get("events", [])
            event = next(
                (
                    item
                    for item in events
                    if item.get("seq") == evidence_ref.get("event_seq")
                ),
                None,
            )
            checks.that(event is not None, f"{label}: evidence event seq is missing")
            if not isinstance(event, Mapping):
                continue
            semantic = evidence_ref.get("semantic")
            expected_contract = semantic_contracts.get(str(semantic))
            checks.that(
                expected_contract is not None,
                f"{label}: evidence semantic is unsupported",
            )
            if expected_contract is None:
                continue
            expected_kind, expected_event_kind, expected_phase, pointer_pattern = (
                expected_contract
            )
            checks.equal(
                evidence_ref.get("source_type"),
                "trace_event",
                f"{label}: evidence source type",
            )
            checks.equal(
                evidence_ref.get("kind"),
                expected_kind,
                f"{label}: semantic evidence kind binding",
            )
            checks.equal(
                evidence_ref.get("event_kind"),
                expected_event_kind,
                f"{label}: semantic event kind binding",
            )
            checks.equal(
                evidence_ref.get("phase"),
                expected_phase,
                f"{label}: semantic phase binding",
            )
            pointer = str(evidence_ref.get("json_pointer", ""))
            checks.that(
                re.fullmatch(pointer_pattern, pointer) is not None,
                f"{label}: semantic JSON pointer binding",
            )
            canonical_ref = (
                f"trace:{run_id}:event:{evidence_ref.get('event_seq')}:"
                f"{evidence_ref.get('event_hash')}#pointer={pointer}"
            )
            checks.equal(
                evidence_ref.get("ref"),
                canonical_ref,
                f"{label}: canonical evidence ref",
            )
            checks.equal(
                event.get("event_hash"),
                evidence_ref.get("event_hash"),
                f"{label}: evidence hash must match trace",
            )
            checks.equal(
                event.get("kind"),
                evidence_ref.get("event_kind"),
                f"{label}: evidence kind must match trace",
            )
            if expected_phase is not None:
                checks.equal(
                    event.get("payload", {}).get("phase"),
                    expected_phase,
                    f"{label}: cited event payload phase",
                )
            try:
                pointed = _json_pointer_value(
                    event.get("payload", {}), pointer
                )
            except (KeyError, IndexError, TypeError, ValueError):
                checks.that(False, f"{label}: evidence JSON pointer cannot be resolved")
                continue
            if semantic == "terminal_completed":
                checks.equal(pointed, "completed", f"{label}: terminal evidence value")
            elif semantic in {"verification_effective", "initial_answer_passed"}:
                checks.that(
                    isinstance(pointed, bool),
                    f"{label}: boolean evidence semantic is not boolean",
                )
            elif semantic in {"candidate_hypothesis", "candidate_claim_status"}:
                checks.equal(
                    pointed,
                    evidence_ref.get("claim_status"),
                    f"{label}: candidate claim status must match trace",
                )
                checks.equal(
                    evidence_ref.get("confirmation_status"),
                    "unconfirmed",
                    f"{label}: candidate cause must remain unconfirmed",
                )
            resolved += 1
    return resolved


def _schedule_replay_checks(
    harness: _ScheduleHTTPHarness,
    plan: Mapping[str, Any],
    tasks: Iterable[Mapping[str, Any]],
    checks: _ScheduleChecks,
    label: str,
) -> int:
    responses = [
        harness.request("GET", f"/v1/today-plans/{plan['plan_id']}/replay")
    ]
    responses.extend(
        harness.request("GET", f"/v1/review-schedule/{task['task_id']}/replay")
        for task in tasks
    )
    for response in responses:
        checks.equal(response["status"], 200, f"{label}: replay HTTP status")
        checks.equal(
            response["payload"].get("trace_verified"),
            True,
            f"{label}: replay hash chain",
        )
        checks.equal(
            response["payload"].get("projection_verified"),
            True,
            f"{label}: replay projection",
        )
    return len(responses)


def _schedule_seed_due_plan(
    harness: _ScheduleHTTPHarness,
    prefix: str,
    *,
    count: int = 1,
    offset_days: int = 1,
    initial_response: str = "B",
    verification_response: str = "A",
    budget: int = 60,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attempts = [
        harness.seed_attempt(
            f"eval-{prefix}-{index}",
            initial_response=initial_response,
            verification_response=verification_response,
        )
        for index in range(count)
    ]
    seeded = harness.create_plan(f"plan-{prefix}-seed", budget=60)
    if seeded["status"] != 201:
        raise RuntimeError(f"seed plan failed: {seeded!r}")
    harness.clock.value += timedelta(days=offset_days)
    due = harness.create_plan(f"plan-{prefix}-due", budget=budget)
    if due["status"] != 201:
        raise RuntimeError(f"due plan failed: {due!r}")
    return attempts, due["payload"]


def _probe_schedule_api() -> dict[str, Any]:
    """Exercise the P0.2 TodayPlan/ReviewSchedule contract over real HTTP."""

    if not (REPO_ROOT / "service" / "hermes_service" / "api.py").is_file():
        return {
            "status": "pending",
            "errors": ["sidecar schedule HTTP surface is absent"],
            "cases": {},
        }
    cases: dict[str, Any] = {}
    all_errors: list[str] = []
    total_assertions = 0

    def run_case(
        name: str,
        callback: Callable[[_ScheduleHTTPHarness, _ScheduleChecks], dict[str, Any]],
    ) -> None:
        nonlocal total_assertions
        checks = _ScheduleChecks()
        summary: dict[str, Any] = {}
        try:
            case_root = temporary_root / name
            case_root.mkdir()
            harness = _ScheduleHTTPHarness(case_root)
            try:
                summary = callback(harness, checks)
            finally:
                harness.close()
        except Exception as exc:
            checks.errors.append(f"case raised {exc!r}")
        total_assertions += checks.count
        prefixed = [f"{name}: {error}" for error in checks.errors]
        all_errors.extend(prefixed)
        cases[name] = {
            **summary,
            "assertion_count": checks.count,
            "status": "fail" if checks.errors else "pass",
            "errors": checks.errors,
        }

    def empty_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        created = harness.create_plan("empty-plan-command")
        checks.equal(created["status"], 201, "empty plan HTTP status")
        plan = created["payload"]
        schedule_response = harness.request("GET", "/v1/review-schedule")
        checks.equal(schedule_response["status"], 200, "empty schedule HTTP status")
        schedule = schedule_response["payload"]
        checks.equal(plan.get("status"), "empty", "empty plan status")
        checks.equal(plan.get("empty_reason"), "no_recorded_evidence", "empty reason")
        checks.equal(plan.get("tasks"), [], "empty plan tasks")
        checks.equal(schedule.get("count"), 0, "empty schedule count")
        _schedule_contract_checks(plan, "today-plan.schema.json", checks, "empty")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "empty")
        _schedule_claim_checks(plan, schedule, checks, "empty")
        _schedule_replay_checks(harness, plan, [], checks, "empty")
        replayed = harness.create_plan("empty-plan-command")
        checks.equal(replayed["status"], 201, "empty command receipt replay status")
        checks.equal(replayed["payload"], plan, "empty command receipt exact replay")
        return {
            "empty_reason": plan.get("empty_reason"),
            "receipt_exact_replay": replayed["payload"] == plan,
            "projection_verified": plan.get("event_stream", {}).get("projection_verified"),
        }

    def synthetic_origin_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        public_run = harness.request(
            "POST",
            "/v1/runs",
            {"mode": "success", "run_id": "eval-public-run-must-not-exist"},
        )
        capabilities_response = harness.request("GET", "/v1/capabilities")
        checks.equal(
            public_run["status"],
            404,
            "synthetic public run creation route must not exist",
        )
        checks.equal(
            public_run["payload"].get("error", {}).get("code"),
            "route_not_found",
            "synthetic public run creation uses the closed not-found envelope",
        )
        checks.equal(
            capabilities_response["status"],
            200,
            "synthetic origin capabilities status",
        )
        capabilities = capabilities_response["payload"]
        endpoints = capabilities.get("endpoints", {})
        features = capabilities.get("features", [])
        checks.that(
            "run" not in endpoints,
            "capabilities still advertise public synthetic run creation",
        )
        checks.that(
            "learning_modes" not in capabilities,
            "capabilities still advertise prefilled evaluation modes as product learning modes",
        )
        checks.that(
            "offline-deterministic-path" not in features,
            "capabilities still advertise the removed demo-only offline path",
        )
        seeded = harness.seed_evaluation_fixture("eval-synthetic-origin")
        checks.equal(seeded.get("status"), "completed", "synthetic internal run status")
        checks.equal(
            seeded.get("evidence_origin"),
            "evaluation_fixture",
            "synthetic internal evidence origin",
        )
        checks.equal(
            seeded.get("trace_verified"),
            True,
            "synthetic internal trace verification",
        )
        created = harness.create_plan("synthetic-origin-plan")
        checks.equal(created["status"], 201, "synthetic-origin plan status")
        plan = created["payload"]
        schedule_response = harness.request("GET", "/v1/review-schedule")
        health_response = harness.request("GET", "/v1/health")
        skills_response = harness.request("GET", "/v1/skills/report")
        misconception_report_response = harness.request("GET", "/v1/misconceptions")
        dossier_response = harness.request(
            "GET", f"/v1/misconceptions/{seeded['run_id']}"
        )
        checks.equal(schedule_response["status"], 200, "synthetic origin schedule status")
        checks.equal(health_response["status"], 200, "synthetic origin health status")
        checks.equal(skills_response["status"], 200, "synthetic origin skills status")
        checks.equal(
            misconception_report_response["status"],
            200,
            "synthetic origin misconception report status",
        )
        checks.equal(
            dossier_response["status"],
            404,
            "synthetic origin dossier must be publicly invisible",
        )
        checks.equal(
            dossier_response["payload"].get("error", {}).get("code"),
            "run_not_found",
            "synthetic origin dossier uses the closed not-found envelope",
        )
        schedule = schedule_response["payload"]
        health = health_response["payload"]
        skills = skills_response["payload"]
        misconception_report = misconception_report_response["payload"]
        checks.equal(plan.get("empty_reason"), "no_recorded_evidence", "synthetic origin exclusion")
        checks.equal(schedule.get("count"), 0, "synthetic origin schedule exclusion")
        checks.equal(health.get("run_count"), 0, "synthetic origin health exclusion")
        checks.equal(skills.get("skill_count"), 0, "synthetic origin skills exclusion")
        checks.equal(
            misconception_report.get("count"),
            0,
            "synthetic origin misconception report exclusion",
        )
        checks.that(
            seeded["run_id"] not in canonical_json(
                {
                    "plan": plan,
                    "schedule": schedule,
                    "health": health,
                    "skills": skills,
                    "misconceptions": misconception_report,
                    "dossier_error": dossier_response["payload"],
                }
            ),
            "synthetic run identifier leaked into a learner-facing projection",
        )
        _schedule_contract_checks(plan, "today-plan.schema.json", checks, "synthetic-origin")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "synthetic-origin")
        return {
            "seed_path": "internal_evaluation_fixture",
            "evidence_origin": seeded.get("evidence_origin"),
            "public_run_status": public_run["status"],
            "capabilities_run_advertised": "run" in endpoints,
            "offline_demo_feature_advertised": "offline-deterministic-path"
            in features,
            "synthetic_origin_excluded": (
                not plan.get("tasks")
                and schedule.get("count") == 0
                and health.get("run_count") == 0
                and skills.get("skill_count") == 0
                and misconception_report.get("count") == 0
                and dossier_response["status"] == 404
            ),
            "learner_projection_counts": {
                "health_runs": health.get("run_count"),
                "skills": skills.get("skill_count"),
                "misconceptions": misconception_report.get("count"),
                "review_tasks": schedule.get("count"),
                "today_tasks": len(plan.get("tasks", [])),
            },
            "dossier_status": dossier_response["status"],
        }

    def branch_case(
        name: str,
        *,
        initial_response: str,
        verification_response: str,
        expected_kind: str,
        offset_days: int,
    ) -> Callable[[_ScheduleHTTPHarness, _ScheduleChecks], dict[str, Any]]:
        def evaluate(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
            completed = harness.seed_attempt(
                f"eval-{name}-human",
                initial_response=initial_response,
                verification_response=verification_response,
            )
            checks.equal(completed.get("state"), "completed", f"{name}: completed human attempt")
            seed = harness.create_plan(f"plan-{name}-seed")
            checks.equal(seed["status"], 201, f"{name}: seed plan status")
            schedule_response = harness.request("GET", "/v1/review-schedule")
            checks.equal(schedule_response["status"], 200, f"{name}: review schedule status")
            schedule = schedule_response["payload"]
            checks.equal(schedule.get("count"), 1, f"{name}: one review task")
            if not schedule.get("items"):
                return {"task_kind": None}
            task = schedule["items"][0]
            checks.equal(task.get("task_kind"), expected_kind, f"{name}: task branch")
            checks.equal(task.get("due_on"), (harness.clock.value + timedelta(days=offset_days)).isoformat(), f"{name}: due offset")
            checks.equal(task.get("policy_offset_days"), offset_days, f"{name}: authored policy offset")
            checks.equal(task.get("scheduling_adjustment"), "on_policy_window", f"{name}: on-window adjustment")
            if expected_kind == "cause_probe":
                checks.equal(task.get("cause_confirmation_status"), "unconfirmed", f"{name}: cause remains unconfirmed")
                checks.that(task.get("cause_label") in task.get("reason", ""), f"{name}: authored cause label is visible")
                checks.that(task.get("cause_id") not in task.get("reason", ""), f"{name}: raw cause id is not user-facing")
            else:
                checks.equal(task.get("cause_confirmation_status"), None, f"{name}: no confirmed cause field")
            _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, name)
            resolved = _schedule_evidence_checks(harness, [task], checks, name)
            harness.clock.value += timedelta(days=offset_days)
            due_response = harness.create_plan(f"plan-{name}-due")
            checks.equal(due_response["status"], 201, f"{name}: due plan status")
            due = due_response["payload"]
            checks.equal(len(due.get("tasks", [])), 1, f"{name}: due task appears")
            _schedule_contract_checks(due, "today-plan.schema.json", checks, name)
            _schedule_claim_checks(due, schedule, checks, name)
            replay_count = _schedule_replay_checks(harness, due, [task], checks, name)
            return {
                "source": "real_POST_v1_attempts_human_local_interactive",
                "task_kind": task.get("task_kind"),
                "due_offset_days": offset_days,
                "cause_confirmation_status": task.get("cause_confirmation_status"),
                "definition_status": task.get("definition_status"),
                "resolved_evidence_ref_count": resolved,
                "verified_replay_count": replay_count,
            }

        return evaluate

    def budget_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        _, plan = _schedule_seed_due_plan(
            harness,
            "budget",
            count=2,
            offset_days=1,
            initial_response="B",
            verification_response="A",
            budget=20,
        )
        schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        used = sum(int(task["expected_duration_minutes"]) for task in plan.get("tasks", []))
        checks.equal(schedule.get("count"), 2, "budget: both due tasks remain scheduled")
        checks.equal(len(plan.get("tasks", [])), 1, "budget: only one task fits")
        checks.that(used <= 20, "budget: selected tasks overrun the daily budget")
        checks.equal(plan.get("basis", {}).get("due_review_count"), 2, "budget: due count")
        _schedule_contract_checks(plan, "today-plan.schema.json", checks, "budget")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "budget")
        return {"daily_budget_minutes": 20, "selected_minutes": used, "due_count": schedule.get("count")}

    def overdue_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        harness.seed_attempt(
            "eval-overdue-human",
            initial_response="A",
            verification_response="C",
        )
        harness.clock.value += timedelta(days=10)
        created = harness.create_plan("overdue-catch-up-plan")
        checks.equal(created["status"], 201, "overdue: plan status")
        plan = created["payload"]
        schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(schedule.get("count"), 1, "overdue: one retained task")
        if not schedule.get("items"):
            return {"scheduling_adjustment": None}
        task = schedule["items"][0]
        checks.equal(task.get("task_kind"), "delayed_retention", "overdue: task kind")
        checks.equal(task.get("policy_offset_days"), 3, "overdue: policy offset remains authored +3")
        checks.equal(task.get("initial_due_on"), harness.clock.value.isoformat(), "overdue: catch-up date is today")
        checks.equal(task.get("due_on"), task.get("initial_due_on"), "overdue: current due date")
        checks.equal(task.get("scheduling_adjustment"), "overdue_catch_up", "overdue: adjustment is explicit")
        checks.that(task.get("base_due_on") < task.get("initial_due_on"), "overdue: base due precedes catch-up date")
        checks.that("逾期补排" in task.get("reason", ""), "overdue: reason discloses catch-up")
        checks.that("不代表仍按 +3 天执行" in task.get("reason", ""), "overdue: reason rejects false +3 execution claim")
        checks.that(plan.get("basis", {}).get("workload_guardrail", {}).get("overdue_catch_up_count", 0) > 0, "overdue: plan records catch-up count")
        _schedule_contract_checks(plan, "today-plan.schema.json", checks, "overdue")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "overdue")
        _schedule_evidence_checks(harness, [task], checks, "overdue")
        return {
            "task_kind": task.get("task_kind"),
            "policy_offset_days": task.get("policy_offset_days"),
            "base_due_on": task.get("base_due_on"),
            "initial_due_on": task.get("initial_due_on"),
            "scheduling_adjustment": task.get("scheduling_adjustment"),
        }

    def old_evidence_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        harness.seed_attempt(
            "eval-old-evidence-human",
            initial_response="B",
            verification_response="A",
        )
        harness.clock.value += timedelta(days=20)
        created = harness.create_plan("old-evidence-catch-up-plan")
        checks.equal(created["status"], 201, "old evidence: plan status")
        plan = created["payload"]
        schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(schedule.get("count"), 1, "old evidence: task is not discarded")
        if not schedule.get("items"):
            return {"eligible_evidence_count": 0}
        task = schedule["items"][0]
        guardrail = plan.get("basis", {}).get("workload_guardrail", {})
        checks.equal(task.get("task_kind"), "independent_retry", "old evidence: +1 retry branch")
        checks.equal(task.get("policy_offset_days"), 1, "old evidence: authored +1 offset")
        checks.equal(task.get("scheduling_adjustment"), "overdue_catch_up", "old evidence: overdue disclosed")
        checks.that(task.get("base_due_on") < task.get("initial_due_on"), "old evidence: base and catch-up dates differ")
        checks.equal(task.get("initial_due_on"), harness.clock.value.isoformat(), "old evidence: catch-up is today")
        checks.that("逾期补排" in task.get("reason", ""), "old evidence: reason discloses catch-up")
        checks.equal(guardrail.get("eligible_evidence_count"), 1, "old evidence: eligible count")
        checks.equal(guardrail.get("recent_evidence_count"), 0, "old evidence: outside 14-day recency")
        checks.equal(len(plan.get("tasks", [])), 1, "old evidence: catch-up appears in Today")
        _schedule_contract_checks(plan, "today-plan.schema.json", checks, "old-evidence")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "old-evidence")
        _schedule_evidence_checks(harness, [task], checks, "old-evidence")
        return {
            "age_days": 20,
            "task_kind": task.get("task_kind"),
            "policy_offset_days": task.get("policy_offset_days"),
            "scheduling_adjustment": task.get("scheduling_adjustment"),
            "eligible_evidence_count": guardrail.get("eligible_evidence_count"),
            "recent_evidence_count": guardrail.get("recent_evidence_count"),
        }

    def recovery_load_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        for index in range(3):
            harness.seed_attempt(
                f"eval-recovery-human-{index}",
                initial_response="A",
                verification_response="A",
            )
        seeded = harness.create_plan("recovery-seed-plan", budget=60)
        checks.equal(seeded["status"], 201, "recovery: seed plan status")
        seed_schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(seed_schedule.get("count"), 3, "recovery: all failed tasks persist")
        checks.equal(len(seeded["payload"].get("tasks", [])), 0, "recovery: future tasks are not shown early")
        harness.clock.value += timedelta(days=1)
        due_response = harness.create_plan("recovery-due-plan", budget=60)
        checks.equal(due_response["status"], 201, "recovery: due plan status")
        due = due_response["payload"]
        schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        guardrail = due.get("basis", {}).get("workload_guardrail", {})
        checks.equal(schedule.get("count"), 3, "recovery: ReviewSchedule retains all tasks")
        checks.equal(len(due.get("tasks", [])), 1, "recovery: Today presents one task")
        checks.equal(guardrail.get("mode"), "recovery_load", "recovery: workload mode")
        checks.equal(guardrail.get("recent_failed_attempt_count"), 3, "recovery: failed-run count")
        checks.equal(guardrail.get("max_non_accepted_tasks"), 1, "recovery: non-accepted presentation limit")
        checks.that(all(item.get("task_kind") == "cause_probe" for item in schedule.get("items", [])), "recovery: each task is cause-specific")
        _schedule_contract_checks(due, "today-plan.schema.json", checks, "recovery")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "recovery")
        first_task = due["tasks"][0]
        first_skip = harness.task_command(
            due, first_task, "skip", "recovery-skip-first"
        )
        checks.equal(first_skip["status"], 200, "recovery: first skip status")
        harness.clock.value += timedelta(days=1)
        second_response = harness.create_plan("recovery-second-day", budget=60)
        checks.equal(second_response["status"], 201, "recovery: second-day plan status")
        second_plan = second_response["payload"]
        checks.equal(len(second_plan.get("tasks", [])), 1, "recovery: second day presents one")
        second_task = second_plan["tasks"][0]
        checks.that(
            second_task["task_id"] != first_task["task_id"],
            "recovery: repeatedly skipped task monopolized the next day",
        )
        second_skip = harness.task_command(
            second_plan, second_task, "skip", "recovery-skip-second"
        )
        checks.equal(second_skip["status"], 200, "recovery: second skip status")
        harness.clock.value += timedelta(days=1)
        third_response = harness.create_plan("recovery-third-day", budget=60)
        checks.equal(third_response["status"], 201, "recovery: third-day plan status")
        third_plan = third_response["payload"]
        checks.equal(len(third_plan.get("tasks", [])), 1, "recovery: third day presents one")
        third_task = third_plan["tasks"][0]
        rotation = [
            first_task["task_id"],
            second_task["task_id"],
            third_task["task_id"],
        ]
        checks.equal(len(set(rotation)), 3, "recovery: three-day fair rotation")
        final_schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(final_schedule.get("count"), 3, "recovery: fair rotation loses no task")
        return {
            "failed_attempt_count": guardrail.get("recent_failed_attempt_count"),
            "review_schedule_count": schedule.get("count"),
            "today_task_count": len(due.get("tasks", [])),
            "max_non_accepted_tasks": guardrail.get("max_non_accepted_tasks"),
            "three_day_unique_task_count": len(set(rotation)),
        }

    def partial_migration_restart_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        _, plan = _schedule_seed_due_plan(harness, "partial-migration")
        original_task = plan["tasks"][0]
        task_id = original_task["task_id"]
        plan_id = plan["plan_id"]
        legacy_accept = harness.task_command(
            plan,
            original_task,
            "accept",
            "partial-migration-legacy-accept",
        )
        checks.equal(legacy_accept["status"], 200, "partial migration: legacy accept status")
        harness.close()
        connection = sqlite3.connect(harness.database)
        try:
            connection.executescript(
                """
                PRAGMA foreign_keys = OFF;
                BEGIN IMMEDIATE;
                CREATE TABLE review_schedule_tasks_partial (
                    task_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    task_kind TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    expected_duration_minutes INTEGER NOT NULL,
                    success_criterion TEXT NOT NULL,
                    skip_consequence TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    activity_ref_json TEXT NOT NULL,
                    cause_id TEXT,
                    cause_label TEXT,
                    cause_confirmation_status TEXT,
                    definition_status TEXT NOT NULL,
                    policy_offset_days INTEGER,
                    base_due_on TEXT,
                    initial_due_on TEXT,
                    scheduling_adjustment TEXT,
                    completion_semantics TEXT,
                    state TEXT NOT NULL,
                    due_on TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO review_schedule_tasks_partial
                SELECT task_id, source_key, task_kind, domain, skill_id, reason,
                       expected_duration_minutes, success_criterion,
                       skip_consequence, evidence_refs_json, activity_ref_json,
                       cause_id, cause_label, cause_confirmation_status,
                       definition_status, NULL, NULL, NULL, NULL,
                       completion_semantics, state, due_on, version,
                       created_at, updated_at
                FROM review_schedule_tasks;

                CREATE TABLE today_plan_tasks_partial (
                    plan_id TEXT NOT NULL REFERENCES today_plans(plan_id),
                    task_id TEXT NOT NULL REFERENCES review_schedule_tasks(task_id),
                    ordinal INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    task_snapshot_json TEXT,
                    PRIMARY KEY(plan_id, task_id),
                    UNIQUE(plan_id, ordinal)
                );
                INSERT INTO today_plan_tasks_partial
                SELECT plan_id, task_id, ordinal, state, NULL
                FROM today_plan_tasks;

                DROP TABLE today_plan_tasks;
                DROP TABLE review_schedule_tasks;
                ALTER TABLE review_schedule_tasks_partial
                    RENAME TO review_schedule_tasks;
                ALTER TABLE today_plan_tasks_partial RENAME TO today_plan_tasks;
                COMMIT;
                PRAGMA foreign_keys = ON;
                """
            )
            rows = connection.execute(
                "SELECT task_id, activity_ref_json FROM review_schedule_tasks"
            ).fetchall()
            for legacy_task_id, encoded_activity in rows:
                activity = json.loads(encoded_activity)
                activity.pop("novelty_status", None)
                connection.execute(
                    """
                    UPDATE review_schedule_tasks
                    SET activity_ref_json = ?,
                        success_criterion = ?, skip_consequence = ?
                    WHERE task_id = ?
                    """,
                    (
                        canonical_json(activity),
                        "在无提示的新题中独立达到既定评分标准。",
                        "若跳过，任务将在下一学习日重新出现。",
                        legacy_task_id,
                    ),
                )
            connection.execute(
                "DROP TRIGGER IF EXISTS schedule_command_results_no_update"
            )
            receipt_rows = connection.execute(
                "SELECT command_id, response_json FROM schedule_command_results"
            ).fetchall()
            for receipt_command_id, encoded_response in receipt_rows:
                receipt = json.loads(encoded_response)
                changed = False
                for receipt_task in receipt.get("tasks", []):
                    activity = receipt_task.get("activity_ref", {})
                    if isinstance(activity, dict):
                        activity.pop("novelty_status", None)
                    receipt_task["success_criterion"] = (
                        "在无提示的新题中独立达到既定评分标准。"
                    )
                    receipt_task["skip_consequence"] = (
                        "若跳过，任务将在下一学习日重新出现。"
                    )
                    changed = True
                if changed:
                    connection.execute(
                        """
                        UPDATE schedule_command_results SET response_json = ?
                        WHERE command_id = ?
                        """,
                        (canonical_json(receipt), receipt_command_id),
                    )
            connection.execute(
                """
                CREATE TRIGGER schedule_command_results_no_update
                BEFORE UPDATE ON schedule_command_results BEGIN
                    SELECT RAISE(ABORT, 'schedule command results are immutable');
                END
                """
            )
            connection.commit()
        finally:
            connection.close()

        recovered_base = harness.start_server()
        harness.base_url = recovered_base
        schedule_response = harness.request(
            "GET", "/v1/review-schedule", base_url=recovered_base
        )
        checks.equal(schedule_response["status"], 200, "partial migration: schedule restart status")
        schedule = schedule_response["payload"]
        plan_response = harness.request(
            "GET", f"/v1/today-plans/{plan_id}", base_url=recovered_base
        )
        checks.equal(plan_response["status"], 200, "partial migration: plan restart status")
        recovered_plan = plan_response["payload"]
        recovered_task = next(
            item for item in schedule.get("items", []) if item["task_id"] == task_id
        )
        checks.equal(recovered_task.get("policy_offset_days"), 1, "partial migration: policy offset repaired")
        checks.equal(recovered_task.get("base_due_on"), recovered_task.get("due_on"), "partial migration: base due repaired")
        checks.equal(recovered_task.get("initial_due_on"), recovered_task.get("due_on"), "partial migration: initial due repaired")
        checks.equal(recovered_task.get("scheduling_adjustment"), "on_policy_window", "partial migration: adjustment repaired")
        checks.equal(recovered_task.get("activity_ref", {}).get("novelty_status"), "same_fixture_retest_not_novel_item", "partial migration: novelty disclosure repaired")
        checks.that("同题组独立复测" in recovered_task.get("success_criterion", ""), "partial migration: success criterion repaired")
        checks.that("公平轮候" in recovered_task.get("skip_consequence", ""), "partial migration: skip consequence repaired")
        checks.equal(recovered_plan["tasks"][0].get("task_id"), task_id, "partial migration: snapshot rebuilt")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "partial-migration")
        _schedule_contract_checks(recovered_plan, "today-plan.schema.json", checks, "partial-migration")
        checks.equal(recovered_task.get("state"), "accepted", "partial migration: task state retained")
        legacy_create_retry = harness.create_plan(
            "plan-partial-migration-due", budget=60
        )
        checks.equal(legacy_create_retry["status"], 409, "partial migration: legacy create receipt fails closed")
        checks.equal(legacy_create_retry["payload"].get("error", {}).get("code"), "command_conflict", "partial migration: legacy create receipt code")
        legacy_transition_retry = harness.task_command(
            plan,
            original_task,
            "accept",
            "partial-migration-legacy-accept",
            base_url=recovered_base,
        )
        checks.equal(legacy_transition_retry["status"], 409, "partial migration: legacy transition receipt fails closed")
        checks.equal(legacy_transition_retry["payload"].get("error", {}).get("code"), "command_conflict", "partial migration: legacy transition receipt code")
        current_after_conflicts = harness.request(
            "GET", f"/v1/today-plans/{plan_id}", base_url=recovered_base
        )
        checks.equal(current_after_conflicts["payload"], recovered_plan, "partial migration: reload remains authoritative")
        task_replay = harness.request(
            "GET", f"/v1/review-schedule/{task_id}/replay", base_url=recovered_base
        )
        plan_replay = harness.request(
            "GET", f"/v1/today-plans/{plan_id}/replay", base_url=recovered_base
        )
        checks.equal(task_replay["payload"].get("frames", [])[-1].get("kind"), "task_contract_migrated", "partial migration: task migration event")
        checks.equal(plan_replay["payload"].get("frames", [])[-1].get("kind"), "today_plan_contract_migrated", "partial migration: plan migration event")
        checks.equal(task_replay["payload"].get("projection_verified"), True, "partial migration: task projection replay")
        checks.equal(plan_replay["payload"].get("projection_verified"), True, "partial migration: plan projection replay")

        verification = sqlite3.connect(harness.database)
        try:
            remaining_nulls = verification.execute(
                """
                SELECT COUNT(*) FROM review_schedule_tasks
                WHERE policy_offset_days IS NULL OR base_due_on IS NULL
                   OR initial_due_on IS NULL OR scheduling_adjustment IS NULL
                """
            ).fetchone()[0]
            missing_snapshots = verification.execute(
                """
                SELECT COUNT(*) FROM today_plan_tasks
                WHERE task_snapshot_json IS NULL OR trim(task_snapshot_json) = ''
                """
            ).fetchone()[0]
            migration_count = verification.execute(
                """
                SELECT COUNT(*) FROM schedule_migrations
                WHERE kind = 'pre_release_schedule_contract_v2'
                """
            ).fetchone()[0]
        finally:
            verification.close()
        checks.equal(remaining_nulls, 0, "partial migration: four task fields fully repaired")
        checks.equal(missing_snapshots, 0, "partial migration: snapshots fully repaired")
        checks.equal(migration_count, 1, "partial migration: one auditable contract migration")

        from hermes_runtime.schedule import ScheduleStore

        healthy_reopen = ScheduleStore(harness.database)
        healthy_reopen_changes = healthy_reopen._connection.total_changes
        healthy_reopen.close()
        checks.equal(healthy_reopen_changes, 0, "partial migration: healthy reopen is write-free")
        second_recovered_base = harness.start_server()
        second_schedule = harness.request(
            "GET", "/v1/review-schedule", base_url=second_recovered_base
        )
        checks.equal(second_schedule["status"], 200, "partial migration: second HTTP restart status")
        checks.equal(second_schedule["payload"], schedule, "partial migration: second restart is stable")
        return {
            "nullable_fields_repaired": 5,
            "remaining_task_field_nulls": remaining_nulls,
            "missing_task_snapshots": missing_snapshots,
            "auditable_contract_migration_count": migration_count,
            "healthy_reopen_total_changes": healthy_reopen_changes,
            "second_restart_stable": second_schedule["payload"] == schedule,
            "legacy_create_receipt_status": legacy_create_retry["status"],
            "legacy_transition_receipt_status": legacy_transition_retry["status"],
        }

    def dynamic_arrival_fairness_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        for index in range(3):
            harness.seed_attempt(
                f"eval-dynamic-initial-human-{index}",
                initial_response="A",
                verification_response="A",
            )
        seed = harness.create_plan("dynamic-arrival-seed")
        checks.equal(seed["status"], 201, "dynamic fairness: seed plan status")
        harness.clock.value += timedelta(days=1)
        first_response = harness.create_plan("dynamic-arrival-first-due")
        checks.equal(first_response["status"], 201, "dynamic fairness: first due plan status")
        first_plan = first_response["payload"]
        checks.equal(len(first_plan.get("tasks", [])), 1, "dynamic fairness: first task shown")
        oldest_task = first_plan["tasks"][0]
        first_skip = harness.task_command(
            first_plan,
            oldest_task,
            "skip",
            "dynamic-arrival-skip-oldest",
        )
        checks.equal(first_skip["status"], 200, "dynamic fairness: oldest skip status")

        oldest_return_day: int | None = None
        presentation_ids = [oldest_task["task_id"]]
        latest_plan = first_plan
        for day_index in range(1, 9):
            harness.seed_attempt(
                f"eval-dynamic-new-human-{day_index}",
                initial_response="A",
                verification_response="A",
            )
            harness.clock.value += timedelta(days=1)
            response = harness.create_plan(
                f"dynamic-arrival-day-{day_index}", budget=60
            )
            checks.equal(response["status"], 201, f"dynamic fairness day {day_index}: plan status")
            latest_plan = response["payload"]
            checks.equal(len(latest_plan.get("tasks", [])), 1, f"dynamic fairness day {day_index}: presentation cap")
            shown = latest_plan["tasks"][0]
            presentation_ids.append(shown["task_id"])
            if shown["task_id"] == oldest_task["task_id"] and oldest_return_day is None:
                oldest_return_day = day_index
            schedule = harness.request("GET", "/v1/review-schedule")["payload"]
            checks.equal(schedule.get("count"), day_index + 3, f"dynamic fairness day {day_index}: no task loss")
            if day_index < 8:
                skipped = harness.task_command(
                    latest_plan,
                    shown,
                    "skip",
                    f"dynamic-arrival-skip-{day_index}",
                )
                checks.equal(skipped["status"], 200, f"dynamic fairness day {day_index}: skip status")
        checks.that(oldest_return_day is not None, "dynamic fairness: oldest skipped task starved for eight days")
        checks.that(
            oldest_return_day is not None and oldest_return_day <= 8,
            "dynamic fairness: oldest skipped task exceeded bounded return",
        )
        final_schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(final_schedule.get("count"), 11, "dynamic fairness: final ReviewSchedule count")
        _schedule_contract_checks(latest_plan, "today-plan.schema.json", checks, "dynamic-fairness")
        _schedule_contract_checks(final_schedule, "review-schedule.schema.json", checks, "dynamic-fairness")
        return {
            "days_with_new_arrivals": 8,
            "oldest_return_day": oldest_return_day,
            "final_review_schedule_count": final_schedule.get("count"),
            "presentation_count": len(presentation_ids),
        }

    def strict_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        _, plan = _schedule_seed_due_plan(harness, "strict")
        task = plan["tasks"][0]
        before = harness.request("GET", plan["links"]["self"])["payload"]
        forbidden_fields = {
            "action_date": harness.clock.value.isoformat(),
            "completion_evidence_ref": "forged",
            "mastery": 0.9,
            "peer_rate": 0.75,
            "forgetting_probability": 0.42,
        }
        for index, (field_name, value) in enumerate(forbidden_fields.items()):
            response = harness.task_command(
                plan,
                task,
                "accept",
                f"strict-field-{index}",
                extra={field_name: value},
            )
            checks.equal(response["status"], 400, f"strict: reject {field_name}")
            checks.equal(response["payload"].get("error", {}).get("code"), "invalid_body", f"strict: {field_name} error code")
        sensitive_ids = {
            "phone": "cmd-13800138000",
            "national_id": "cmd-11010519491231002X",
            "openai_key": "cmd-s" + "k-" + "A" * 32,
            "github_classic": "cmd-gh" + "p_" + "A" * 36,
            "github_fine_grained": "cmd-github" + "_pat_" + "A" * 40,
            "google_api_key": "cmd-AIza" + "Sy" + "A" * 33,
            "npm_token": "cmd-n" + "pm_" + "A" * 36,
            "slack_bot_token": (
                "cmd-xo" + "xb-" + "123456789012-123456789012-" + "A" * 24
            ),
        }
        for sensitive_class, command_id in sensitive_ids.items():
            # A plan already exists for this date.  If an identifier escaped
            # validation the request would reach the ordinary 409 plan path;
            # the required 400 therefore proves the opaque ID was rejected,
            # while the existing plan prevents one broken vector from mutating
            # state and masking the remaining vectors.
            response = harness.create_plan(command_id, raw_command_id=True)
            checks.equal(
                response["status"],
                400,
                f"strict: {sensitive_class} plan command id status",
            )
            checks.equal(
                response["payload"].get("error", {}).get("code"),
                "invalid_command_id",
                f"strict: {sensitive_class} plan command id code",
            )
            checks.that(
                command_id not in canonical_json(response["payload"]),
                f"strict: error echoed {sensitive_class} plan command id",
            )
        stale = harness.task_command(
            plan,
            task,
            "accept",
            "strict-stale-task",
            expected_task_version=int(task["version"]) + 1,
        )
        checks.equal(stale["status"], 409, "strict: stale task version status")
        checks.equal(stale["payload"].get("error", {}).get("code"), "stale_task_version", "strict: stale task version code")
        invalid_plan = harness.create_plan(
            "strict-extra-plan",
            body_overrides={"peer_rate": 0.8},
        )
        checks.equal(invalid_plan["status"], 400, "strict: plan rejects unknown claim field")
        after = harness.request("GET", plan["links"]["self"])["payload"]
        checks.equal(after, before, "strict: rejected writes leave plan unchanged")
        return {
            "forbidden_field_count": len(forbidden_fields),
            "sensitive_id_count": len(sensitive_ids),
            "sensitive_id_classes": sorted(sensitive_ids),
            "rejected_writes_are_noop": after == before,
        }

    def fresh_create_receipt_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        second_base = harness.start_server()
        body = {
            "plan_date": harness.clock.value.isoformat(),
            "exam_date": (harness.clock.value + timedelta(days=30)).isoformat(),
            "daily_budget_minutes": 60,
            "expected_version": 0,
            "command_id": _eval_public_command_id(
                "fresh-create-shared-receipt"
            ),
        }
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    harness.request,
                    "POST",
                    "/v1/today-plans",
                    body,
                    base_url=base_url,
                )
                for base_url in (harness.base_url, second_base)
            ]
            results = [future.result(timeout=10) for future in futures]
        checks.equal(
            [item["status"] for item in results],
            [201, 201],
            "fresh create: duplicate receipt statuses",
        )
        checks.equal(
            results[0]["payload"],
            results[1]["payload"],
            "fresh create: exact persisted receipt replay",
        )
        plan = results[0]["payload"]
        checks.equal(plan.get("version"), 1, "fresh create: one plan version")
        loaded = harness.request("GET", plan["links"]["self"])
        checks.equal(loaded["status"], 200, "fresh create: plan is readable")
        checks.equal(loaded["payload"], plan, "fresh create: one persisted projection")
        replay = harness.request("GET", plan["links"]["replay"])
        checks.equal(replay["status"], 200, "fresh create: replay status")
        checks.equal(replay["payload"].get("frame_count"), 1, "fresh create: one create event")
        checks.equal(replay["payload"].get("projection_verified"), True, "fresh create: projection replay")
        conflict_body = dict(body)
        conflict_body["daily_budget_minutes"] = 30
        conflict = harness.request(
            "POST", "/v1/today-plans", conflict_body, base_url=second_base
        )
        checks.equal(conflict["status"], 409, "fresh create: changed command conflicts")
        checks.equal(conflict["payload"].get("error", {}).get("code"), "command_conflict", "fresh create: conflict code")
        return {
            "cross_instance": True,
            "http_statuses": [item["status"] for item in results],
            "receipt_exact_replay": results[0]["payload"] == results[1]["payload"],
            "event_frame_count": replay["payload"].get("frame_count"),
        }

    def cas_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        _, plan = _schedule_seed_due_plan(harness, "cas", count=2, budget=60)
        first, second = plan["tasks"]
        second_base = harness.start_server()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    harness.task_command,
                    plan,
                    first,
                    "accept",
                    "cas-shared-receipt",
                    base_url=base_url,
                )
                for base_url in (harness.base_url, second_base)
            ]
            duplicates = [future.result(timeout=10) for future in futures]
        checks.equal([item["status"] for item in duplicates], [200, 200], "CAS: duplicate receipt statuses")
        checks.equal(duplicates[0]["payload"], duplicates[1]["payload"], "CAS: exact command receipt replay")
        after_duplicate = duplicates[0]["payload"]
        checks.equal(after_duplicate.get("version"), 2, "CAS: duplicate writes one plan version")
        plan_replay_after_duplicate = harness.request(
            "GET", after_duplicate["links"]["replay"]
        )
        second_replay_before = harness.request(
            "GET", f"/v1/review-schedule/{second['task_id']}/replay"
        )
        checks.equal(
            plan_replay_after_duplicate["payload"].get("frame_count"),
            2,
            "CAS: duplicate receipt appends one plan event",
        )
        checks.equal(
            second_replay_before["payload"].get("frame_count"),
            1,
            "CAS: untouched task has only its create event",
        )
        conflict = harness.task_command(
            plan,
            first,
            "skip",
            "cas-shared-receipt",
        )
        checks.equal(conflict["status"], 409, "CAS: reused command conflict status")
        checks.equal(conflict["payload"].get("error", {}).get("code"), "command_conflict", "CAS: reused command conflict code")
        after_conflict = harness.request("GET", plan["links"]["self"])
        checks.equal(
            after_conflict["payload"].get("version"),
            2,
            "CAS: command conflict makes no partial plan write",
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    harness.task_command,
                    plan,
                    second,
                    "accept",
                    command_id,
                    expected_version=2,
                    base_url=base_url,
                )
                for base_url, command_id in (
                    (harness.base_url, "cas-writer-one"),
                    (second_base, "cas-writer-two"),
                )
            ]
            contenders = [future.result(timeout=10) for future in futures]
        checks.equal(sorted(item["status"] for item in contenders), [200, 409], "CAS: exactly one writer wins")
        rejected = next((item for item in contenders if item["status"] == 409), {"payload": {}})
        checks.equal(rejected["payload"].get("error", {}).get("code"), "stale_schedule_version", "CAS: losing writer is stale")
        final_plan = harness.request("GET", plan["links"]["self"])
        checks.equal(final_plan["status"], 200, "CAS: final plan status")
        checks.equal(final_plan["payload"].get("version"), 3, "CAS: one CAS transition committed")
        final_states = {
            item["task_id"]: item["state"]
            for item in final_plan["payload"].get("tasks", [])
        }
        checks.equal(final_states.get(first["task_id"]), "accepted", "CAS: first task state")
        checks.equal(final_states.get(second["task_id"]), "accepted", "CAS: second task state")
        final_plan_replay = harness.request("GET", plan["links"]["replay"])
        final_first_replay = harness.request(
            "GET", f"/v1/review-schedule/{first['task_id']}/replay"
        )
        final_second_replay = harness.request(
            "GET", f"/v1/review-schedule/{second['task_id']}/replay"
        )
        checks.equal(final_plan_replay["payload"].get("frame_count"), 3, "CAS: plan has two transition events")
        checks.equal(final_first_replay["payload"].get("frame_count"), 2, "CAS: first task changed exactly once")
        checks.equal(final_second_replay["payload"].get("frame_count"), 2, "CAS: second task changed exactly once")
        for replay, replay_label in (
            (final_plan_replay, "plan"),
            (final_first_replay, "first task"),
            (final_second_replay, "second task"),
        ):
            checks.equal(replay["payload"].get("trace_verified"), True, f"CAS: {replay_label} hash replay")
            checks.equal(replay["payload"].get("projection_verified"), True, f"CAS: {replay_label} projection replay")
        return {
            "cross_instance": True,
            "receipt_exact_replay": duplicates[0]["payload"] == duplicates[1]["payload"],
            "cas_statuses": sorted(item["status"] for item in contenders),
            "final_plan_version": final_plan["payload"].get("version"),
            "final_plan_frame_count": final_plan_replay["payload"].get("frame_count"),
        }

    def resurface_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        _, old_plan = _schedule_seed_due_plan(harness, "resurface", count=2)
        first, second = old_plan["tasks"]
        skipped = harness.task_command(old_plan, first, "skip", "resurface-skip")
        checks.equal(skipped["status"], 200, "resurface: skip status")
        next_day = harness.clock.value + timedelta(days=1)
        postponed = harness.task_command(
            skipped["payload"],
            second,
            "postpone",
            "resurface-postpone",
            postpone_until=next_day.isoformat(),
        )
        checks.equal(postponed["status"], 200, "resurface: postpone status")
        checks.equal(postponed["payload"].get("status"), "handled", "resurface: old plan handled")
        harness.clock.value = next_day
        current_response = harness.create_plan("resurface-current-plan")
        checks.equal(current_response["status"], 201, "resurface: current plan status")
        current = current_response["payload"]
        checks.equal({item["task_id"] for item in current.get("tasks", [])}, {first["task_id"], second["task_id"]}, "resurface: both tasks return")
        checks.that(all(item.get("state") == "scheduled" for item in current.get("tasks", [])), "resurface: returned tasks are scheduled")
        replay_count = _schedule_replay_checks(harness, current, current.get("tasks", []), checks, "resurface")
        for task in current.get("tasks", []):
            replay = harness.request("GET", f"/v1/review-schedule/{task['task_id']}/replay")
            frames = replay["payload"].get("frames", [])
            checks.equal(frames[-1].get("kind") if frames else None, "task_resurfaced", "resurface: terminal replay event")
        historical = harness.task_command(
            old_plan,
            first,
            "accept",
            "resurface-old-plan-write",
            expected_version=int(postponed["payload"]["version"]),
            expected_task_version=int(current["tasks"][0]["version"]),
        )
        checks.equal(historical["status"], 409, "resurface: historical write status")
        checks.equal(historical["payload"].get("error", {}).get("code"), "historical_plan_read_only", "resurface: historical write code")
        return {"resurfaced_task_count": len(current.get("tasks", [])), "verified_replay_count": replay_count, "historical_read_only": historical["status"] == 409}

    def historical_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        _, old_plan = _schedule_seed_due_plan(harness, "historical")
        task = old_plan["tasks"][0]
        harness.clock.value += timedelta(days=1)
        current_response = harness.create_plan("historical-current-plan")
        checks.equal(current_response["status"], 201, "historical: current plan status")
        current = current_response["payload"]
        checks.equal(current["tasks"][0].get("version"), task.get("version"), "historical: task version is unchanged")
        rejected = harness.task_command(old_plan, task, "accept", "historical-old-write")
        checks.equal(rejected["status"], 409, "historical: old plan write status")
        checks.equal(rejected["payload"].get("error", {}).get("code"), "historical_plan_read_only", "historical: old plan write code")
        unchanged = harness.request("GET", current["links"]["self"])["payload"]
        checks.equal(unchanged["tasks"][0].get("state"), "scheduled", "historical: current task unchanged")
        return {"task_version_unchanged": current["tasks"][0].get("version") == task.get("version"), "historical_read_only": rejected["status"] == 409}

    def skewed_sidecar_clock_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        harness.seed_attempt(
            "eval-skewed-clock-human",
            initial_response="B",
            verification_response="A",
        )
        seed = harness.create_plan("skewed-clock-seed")
        checks.equal(seed["status"], 201, "skewed clock: seed plan status")
        old_day = harness.clock.value + timedelta(days=1)
        new_day = old_day + timedelta(days=1)
        old_base = harness.start_server(clock=_ScheduleEvalClock(old_day))
        new_base = harness.start_server(clock=_ScheduleEvalClock(new_day))

        def create_at(base_url: str, day: date, command_id: str) -> dict[str, Any]:
            return harness.request(
                "POST",
                "/v1/today-plans",
                {
                    "plan_date": day.isoformat(),
                    "exam_date": (day + timedelta(days=30)).isoformat(),
                    "daily_budget_minutes": 60,
                    "expected_version": 0,
                    "command_id": _eval_public_command_id(command_id),
                },
                base_url=base_url,
            )

        old_response = create_at(old_base, old_day, "skewed-clock-old-plan")
        checks.equal(old_response["status"], 201, "skewed clock: old-date plan status")
        old_plan = old_response["payload"]
        new_response = create_at(new_base, new_day, "skewed-clock-new-plan")
        checks.equal(new_response["status"], 201, "skewed clock: new-date plan status")
        new_plan = new_response["payload"]
        stale_create = create_at(
            old_base, old_day, "skewed-clock-old-late-create"
        )
        checks.equal(stale_create["status"], 409, "skewed clock: stale create status")
        checks.equal(stale_create["payload"].get("error", {}).get("code"), "historical_plan_read_only", "skewed clock: stale create code")
        old_task = old_plan["tasks"][0]
        rejected = harness.task_command(
            old_plan,
            old_task,
            "accept",
            "skewed-clock-old-write",
            base_url=old_base,
        )
        checks.equal(rejected["status"], 409, "skewed clock: stale sidecar write status")
        checks.equal(rejected["payload"].get("error", {}).get("code"), "historical_plan_read_only", "skewed clock: stale sidecar write code")
        current = harness.request(
            "GET", new_plan["links"]["self"], base_url=new_base
        )
        checks.equal(current["status"], 200, "skewed clock: current plan readable")
        checks.equal(current["payload"].get("version"), 1, "skewed clock: current plan unchanged")
        checks.equal(current["payload"]["tasks"][0].get("state"), "scheduled", "skewed clock: task unchanged")
        replay = harness.request(
            "GET", new_plan["links"]["replay"], base_url=new_base
        )
        checks.equal(replay["payload"].get("frame_count"), 1, "skewed clock: no partial event")
        checks.equal(replay["payload"].get("projection_verified"), True, "skewed clock: current projection replay")
        return {
            "old_plan_date": old_plan.get("plan_date"),
            "current_plan_date": new_plan.get("plan_date"),
            "stale_create_status": stale_create["status"],
            "old_write_status": rejected["status"],
            "current_plan_version": current["payload"].get("version"),
        }

    def missed_existing_on_policy_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        _, due_plan = _schedule_seed_due_plan(harness, "missed-on-policy")
        original_task = due_plan["tasks"][0]
        checks.equal(original_task.get("scheduling_adjustment"), "on_policy_window", "missed existing: original adjustment")
        checks.equal(original_task.get("initial_due_on"), original_task.get("base_due_on"), "missed existing: original due is on policy")
        harness.clock.value += timedelta(days=1)
        next_response = harness.create_plan("missed-on-policy-next-day")
        checks.equal(next_response["status"], 201, "missed existing: next-day plan status")
        next_plan = next_response["payload"]
        checks.equal(len(next_plan.get("tasks", [])), 1, "missed existing: task remains due")
        task = next_plan["tasks"][0]
        checks.equal(task.get("task_id"), original_task.get("task_id"), "missed existing: same immutable task")
        checks.equal(task.get("scheduling_adjustment"), "on_policy_window", "missed existing: no retrospective catch-up relabel")
        checks.equal(task.get("base_due_on"), original_task.get("base_due_on"), "missed existing: base due remains immutable")
        checks.equal(task.get("initial_due_on"), original_task.get("initial_due_on"), "missed existing: initial due remains immutable")
        checks.equal(task.get("due_on"), original_task.get("due_on"), "missed existing: due projection is not rewritten")
        checks.equal(
            next_plan.get("basis", {}).get("workload_guardrail", {}).get("overdue_catch_up_count"),
            0,
            "missed existing: on-policy task is not counted as authored catch-up",
        )
        _schedule_contract_checks(next_plan, "today-plan.schema.json", checks, "missed-existing")
        return {
            "task_id_unchanged": task.get("task_id") == original_task.get("task_id"),
            "scheduling_adjustment": task.get("scheduling_adjustment"),
            "overdue_catch_up_count": next_plan.get("basis", {}).get("workload_guardrail", {}).get("overdue_catch_up_count"),
        }

    def accepted_continues_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        for index in range(3):
            harness.seed_attempt(
                f"eval-accepted-carry-human-{index}",
                initial_response="A",
                verification_response="A",
            )
        seed = harness.create_plan("accepted-carry-seed")
        checks.equal(seed["status"], 201, "accepted carry: seed plan status")
        harness.clock.value += timedelta(days=1)
        first_response = harness.create_plan("accepted-carry-first-day")
        checks.equal(first_response["status"], 201, "accepted carry: first-day plan status")
        first_plan = first_response["payload"]
        checks.equal(len(first_plan.get("tasks", [])), 1, "accepted carry: recovery cap")
        task = first_plan["tasks"][0]
        accepted = harness.task_command(
            first_plan, task, "accept", "accepted-carry-command"
        )
        checks.equal(accepted["status"], 200, "accepted carry: accept status")
        accepted_task = accepted["payload"]["tasks"][0]
        checks.equal(accepted_task.get("state"), "accepted", "accepted carry: initial state")
        harness.clock.value += timedelta(days=1)
        next_response = harness.create_plan("accepted-carry-next-day")
        checks.equal(next_response["status"], 201, "accepted carry: next-day plan status")
        next_plan = next_response["payload"]
        checks.equal(len(next_plan.get("tasks", [])), 2, "accepted carry: commitment plus one non-accepted task")
        checks.equal(next_plan["tasks"][0].get("task_id"), task.get("task_id"), "accepted carry: commitment is first")
        continued = next(
            item for item in next_plan["tasks"] if item["task_id"] == task["task_id"]
        )
        checks.equal(continued.get("task_id"), task.get("task_id"), "accepted carry: same task")
        checks.equal(continued.get("state"), "accepted", "accepted carry: state is retained")
        checks.equal(continued.get("version"), accepted_task.get("version"), "accepted carry: no synthetic transition")
        next_schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(next_schedule.get("count"), 3, "accepted carry: competing tasks remain queued")
        replay_before_complete = harness.request(
            "GET", f"/v1/review-schedule/{task['task_id']}/replay"
        )
        frames = replay_before_complete["payload"].get("frames", [])
        checks.equal(frames[-1].get("kind") if frames else None, "task_accepted", "accepted carry: no resurface event")
        completed = harness.task_command(
            next_plan,
            continued,
            "complete",
            "accepted-carry-complete",
        )
        checks.equal(completed["status"], 200, "accepted carry: completion status")
        completed_task = next(
            item
            for item in completed["payload"]["tasks"]
            if item["task_id"] == task["task_id"]
        )
        checks.equal(completed_task.get("state"), "completed", "accepted carry: commitment completes")
        checks.equal(completed["payload"].get("status"), "active", "accepted carry: competing task remains active")
        _schedule_contract_checks(next_plan, "today-plan.schema.json", checks, "accepted-carry")
        return {
            "task_id_unchanged": continued.get("task_id") == task.get("task_id"),
            "state_next_day": continued.get("state"),
            "replay_terminal_before_complete": frames[-1].get("kind") if frames else None,
        }

    def accepted_budget_retry_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        _, first_plan = _schedule_seed_due_plan(harness, "accepted-budget")
        task = first_plan["tasks"][0]
        accepted = harness.task_command(
            first_plan, task, "accept", "accepted-budget-accept"
        )
        checks.equal(accepted["status"], 200, "accepted budget: accept status")
        accepted_task = accepted["payload"]["tasks"][0]
        harness.clock.value += timedelta(days=1)
        schedule_before = harness.request("GET", "/v1/review-schedule")["payload"]
        replay_before = harness.request(
            "GET", f"/v1/review-schedule/{task['task_id']}/replay"
        )["payload"]
        retry_command = "accepted-budget-retry-command"
        low = harness.create_plan(retry_command, budget=5)
        checks.equal(low["status"], 409, "accepted budget: low budget status")
        checks.equal(low["payload"].get("error", {}).get("code"), "budget_below_accepted_commitment", "accepted budget: low budget code")
        checks.equal(set(low["payload"]), {"error"}, "accepted budget: closed error envelope")
        checks.equal(set(low["payload"].get("error", {})), {"code", "message", "request_id"}, "accepted budget: closed error fields")
        checks.that(str(accepted_task["expected_duration_minutes"]) in low["payload"].get("error", {}).get("message", ""), "accepted budget: error discloses required minutes")
        absent = harness.request(
            "GET", f"/v1/today-plans/today-{harness.clock.value.isoformat()}"
        )
        checks.equal(absent["status"], 404, "accepted budget: failed create leaves no plan")
        schedule_after_low = harness.request("GET", "/v1/review-schedule")["payload"]
        replay_after_low = harness.request(
            "GET", f"/v1/review-schedule/{task['task_id']}/replay"
        )["payload"]
        checks.equal(schedule_after_low, schedule_before, "accepted budget: failed create leaves task projection unchanged")
        checks.equal(replay_after_low, replay_before, "accepted budget: failed create appends no task event")
        high = harness.create_plan(
            retry_command,
            budget=int(accepted_task["expected_duration_minutes"]),
        )
        checks.equal(high["status"], 201, "accepted budget: raised-budget retry status")
        high_plan = high["payload"]
        checks.equal(len(high_plan.get("tasks", [])), 1, "accepted budget: accepted task actionable")
        checks.equal(high_plan["tasks"][0].get("state"), "accepted", "accepted budget: state retained")
        checks.equal(high_plan["tasks"][0].get("task_id"), task.get("task_id"), "accepted budget: same task")
        _schedule_contract_checks(high_plan, "today-plan.schema.json", checks, "accepted-budget")
        return {
            "low_budget_status": low["status"],
            "error_code": low["payload"].get("error", {}).get("code"),
            "retry_same_command_id": True,
            "high_budget_status": high["status"],
            "required_minutes": accepted_task["expected_duration_minutes"],
        }

    def multiple_accepted_commitments_case(
        harness: _ScheduleHTTPHarness, checks: _ScheduleChecks
    ) -> dict[str, Any]:
        for index in range(3):
            harness.seed_attempt(
                f"eval-multi-accepted-human-{index}",
                initial_response="A",
                verification_response="A",
            )
        seed = harness.create_plan("multi-accepted-seed")
        checks.equal(seed["status"], 201, "multi accepted: seed plan status")
        harness.clock.value += timedelta(days=1)
        current_response = harness.create_plan("multi-accepted-day-1", budget=60)
        checks.equal(current_response["status"], 201, "multi accepted: day 1 status")
        current = current_response["payload"]
        for index in range(3):
            scheduled = [
                task for task in current.get("tasks", []) if task.get("state") == "scheduled"
            ]
            checks.equal(len(scheduled), 1, f"multi accepted: round {index + 1} has one new commitment")
            if not scheduled:
                break
            accepted = harness.task_command(
                current,
                scheduled[0],
                "accept",
                f"multi-accepted-accept-{index + 1}",
            )
            checks.equal(accepted["status"], 200, f"multi accepted: round {index + 1} accept status")
            current = accepted["payload"]
            if index < 2:
                harness.clock.value += timedelta(days=1)
                next_response = harness.create_plan(
                    f"multi-accepted-day-{index + 2}", budget=60
                )
                checks.equal(next_response["status"], 201, f"multi accepted: day {index + 2} status")
                current = next_response["payload"]
        harness.clock.value += timedelta(days=1)
        final_response = harness.create_plan("multi-accepted-final", budget=60)
        checks.equal(final_response["status"], 201, "multi accepted: final plan status")
        final_plan = final_response["payload"]
        tasks = final_plan.get("tasks", [])
        guardrail = final_plan.get("basis", {}).get("workload_guardrail", {})
        checks.equal(len(tasks), 3, "multi accepted: every commitment is actionable")
        checks.that(all(task.get("state") == "accepted" for task in tasks), "multi accepted: all states retained")
        checks.equal(guardrail.get("mode"), "recovery_load", "multi accepted: degraded mode")
        checks.equal(guardrail.get("max_non_accepted_tasks"), 1, "multi accepted: non-accepted task cap")
        checks.equal(final_plan.get("basis", {}).get("selected_task_count"), 3, "multi accepted: selected count includes all commitments")
        checks.that(len(tasks) > int(guardrail.get("max_non_accepted_tasks", 0)), "multi accepted: commitments are not counted against non-accepted cap")
        total_minutes = sum(int(task["expected_duration_minutes"]) for task in tasks)
        checks.that(total_minutes <= 60, "multi accepted: commitments exceed supplied budget")
        schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(schedule.get("count"), 3, "multi accepted: schedule count")
        checks.that(all(task.get("state") == "accepted" for task in schedule.get("items", [])), "multi accepted: schedule states")
        _schedule_contract_checks(final_plan, "today-plan.schema.json", checks, "multi-accepted")
        _schedule_contract_checks(schedule, "review-schedule.schema.json", checks, "multi-accepted")
        return {
            "accepted_commitment_count": len(tasks),
            "mode": guardrail.get("mode"),
            "max_non_accepted_tasks": guardrail.get("max_non_accepted_tasks"),
            "selected_task_count": final_plan.get("basis", {}).get("selected_task_count"),
            "required_minutes": total_minutes,
        }

    def completion_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        completed_attempt = harness.seed_attempt(
            "eval-completion-overdue-human",
            initial_response="A",
            verification_response="C",
        )
        run_id = completed_attempt["run_id"]
        harness.clock.value += timedelta(days=10)
        plan_response = harness.create_plan("completion-overdue-plan")
        checks.equal(plan_response["status"], 201, "completion: overdue plan status")
        plan = plan_response["payload"]
        task = plan["tasks"][0]
        checks.equal(task.get("scheduling_adjustment"), "overdue_catch_up", "completion: starts from overdue task")
        trace_before = harness.request("GET", f"/v1/runs/{run_id}/trace")["payload"]
        skills_before = harness.request("GET", "/v1/skills/report")["payload"]
        accepted = harness.task_command(plan, task, "accept", "completion-accept")
        checks.equal(accepted["status"], 200, "completion: accept status")
        accepted_task = next(item for item in accepted["payload"]["tasks"] if item["task_id"] == task["task_id"])
        completed = harness.task_command(
            accepted["payload"],
            accepted_task,
            "complete",
            "completion-user-marked",
        )
        checks.equal(completed["status"], 200, "completion: complete status")
        result = completed["payload"]
        completed_task = next(item for item in result["tasks"] if item["task_id"] == task["task_id"])
        checks.equal(completed_task.get("completion_semantics"), "user_marked_not_learning_evidence", "completion: semantics")
        checks.equal(result.get("mastery_write_capability"), False, "completion: no mastery write")
        trace_after = harness.request("GET", f"/v1/runs/{run_id}/trace")["payload"]
        skills_after = harness.request("GET", "/v1/skills/report")["payload"]
        checks.equal(trace_after, trace_before, "completion: learning trace unchanged")
        checks.equal(skills_after, skills_before, "completion: KT projection unchanged")
        replay_count = _schedule_replay_checks(harness, result, [completed_task], checks, "completion")
        harness.clock.value += timedelta(days=1)
        next_response = harness.create_plan("completion-next-day-plan")
        checks.equal(next_response["status"], 201, "completion: next-day plan status")
        next_plan = next_response["payload"]
        next_schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(next_plan.get("status"), "empty", "completion: next-day plan is empty")
        checks.equal(next_plan.get("empty_reason"), "no_pending_review_tasks", "completion: next-day empty reason")
        checks.equal(next_plan.get("tasks"), [], "completion: no pending Today task")
        checks.equal(next_schedule.get("count"), 1, "completion: completed task remains auditable")
        checks.equal(next_schedule["items"][0].get("state"), "completed", "completion: schedule task remains completed")
        checks.equal(
            next_plan.get("basis", {}).get("workload_guardrail", {}).get("overdue_catch_up_count"),
            0,
            "completion: completed overdue task is excluded from pending catch-up count",
        )
        _schedule_contract_checks(next_plan, "today-plan.schema.json", checks, "completion-next-day")
        _schedule_contract_checks(next_schedule, "review-schedule.schema.json", checks, "completion-next-day")
        return {
            "completion_semantics": completed_task.get("completion_semantics"),
            "learning_trace_unchanged": trace_after == trace_before,
            "skill_report_unchanged": skills_after == skills_before,
            "verified_replay_count": replay_count,
            "next_day_empty_reason": next_plan.get("empty_reason"),
            "next_day_overdue_catch_up_count": next_plan.get("basis", {}).get("workload_guardrail", {}).get("overdue_catch_up_count"),
        }

    def exam_case(harness: _ScheduleHTTPHarness, checks: _ScheduleChecks) -> dict[str, Any]:
        harness.seed_attempt(
            "eval-exam-human",
            initial_response="A",
            verification_response="A",
        )
        created = harness.create_plan(
            "exam-deadline-plan",
            exam_date=harness.clock.value.isoformat(),
        )
        checks.equal(created["status"], 201, "exam: plan status")
        plan = created["payload"]
        schedule = harness.request("GET", "/v1/review-schedule")["payload"]
        checks.equal(plan.get("empty_reason"), "task_due_after_exam", "exam: withhold reason")
        checks.equal(schedule.get("count"), 0, "exam: no impossible task persisted")
        checks.that(plan.get("basis", {}).get("workload_guardrail", {}).get("withheld_exam_deadline_count", 0) > 0, "exam: withheld count recorded")
        _schedule_contract_checks(plan, "today-plan.schema.json", checks, "exam")
        return {"empty_reason": plan.get("empty_reason"), "withheld_count": plan.get("basis", {}).get("workload_guardrail", {}).get("withheld_exam_deadline_count")}

    try:
        with tempfile.TemporaryDirectory(prefix="lumi-schedule-gate-") as directory:
            temporary_root = Path(directory)
            run_case("empty", empty_case)
            run_case("synthetic_origin_excluded", synthetic_origin_case)
            run_case(
                "failed_with_candidate",
                branch_case(
                    "failed-candidate",
                    initial_response="A",
                    verification_response="A",
                    expected_kind="cause_probe",
                    offset_days=1,
                ),
            )
            run_case(
                "successful_transfer",
                branch_case(
                    "successful-transfer",
                    initial_response="A",
                    verification_response="C",
                    expected_kind="delayed_retention",
                    offset_days=3,
                ),
            )
            run_case(
                "correct_first_failed_transfer",
                branch_case(
                    "correct-first-failed-transfer",
                    initial_response="B",
                    verification_response="A",
                    expected_kind="independent_retry",
                    offset_days=1,
                ),
            )
            run_case("budget", budget_case)
            run_case("overdue_plus_3_catch_up", overdue_case)
            run_case("overdue_plus_1_old_evidence", old_evidence_case)
            run_case("three_failure_recovery_load", recovery_load_case)
            run_case("partial_migration_restart", partial_migration_restart_case)
            run_case("dynamic_arrival_fairness", dynamic_arrival_fairness_case)
            run_case("strict_input", strict_case)
            run_case("fresh_create_receipt", fresh_create_receipt_case)
            run_case("receipt_and_cas", cas_case)
            run_case("skip_postpone_resurface", resurface_case)
            run_case("historical_plan", historical_case)
            run_case("skewed_sidecar_clock", skewed_sidecar_clock_case)
            run_case("missed_existing_on_policy", missed_existing_on_policy_case)
            run_case("accepted_continues_next_day", accepted_continues_case)
            run_case("accepted_budget_retry", accepted_budget_retry_case)
            run_case("multiple_accepted_commitments", multiple_accepted_commitments_case)
            run_case("user_marked_completion", completion_case)
            run_case("exam_deadline", exam_case)
    except (OSError, RuntimeError) as exc:
        all_errors.append(f"schedule HTTP probe could not run: {exc!r}")
    return {
        "schema_version": "lumi.today-plan-eval-evidence.v1",
        "status": "fail" if all_errors else "pass",
        "transport": "real_loopback_http_with_production_router",
        "calendar": "injected_local_date_provider_for_deterministic_day_transitions",
        "assertion_count": total_assertions,
        "case_count": len(cases),
        "cases": cases,
        "errors": all_errors,
    }


def _diagnosis_from_trace(trace: Mapping[str, Any]) -> dict[str, Any] | None:
    for event in trace.get("events", []):
        payload = event.get("payload", {})
        if event.get("kind") == "phase_completed" and payload.get("phase") == "diagnose":
            return payload.get("output", {}).get("diagnosis")
    return None


FORBIDDEN_CAUSAL_FIELDS = {
    "causal_ground_truth",
    "cause_ground_truth",
    "confirmed_cause",
    "is_ground_truth",
    "peer_error_rate",
    "population_error_rate",
}


def _contains_forbidden_causal_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(FORBIDDEN_CAUSAL_FIELDS.intersection(map(str, value))) or any(
            _contains_forbidden_causal_field(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_causal_field(item) for item in value)
    return False


def _trace_tail(trace: Mapping[str, Any]) -> tuple[int | None, str | None]:
    events = trace.get("events", [])
    if not isinstance(events, list) or not events:
        return None, None
    tail = events[-1]
    if not isinstance(tail, Mapping):
        return None, None
    seq = tail.get("seq")
    event_hash = tail.get("event_hash")
    return (seq if isinstance(seq, int) else None, event_hash if isinstance(event_hash, str) else None)


def _dossier_provenance_matches_trace(
    dossier: Mapping[str, Any], trace: Mapping[str, Any]
) -> bool:
    if trace.get("trace_verified") is not True:
        return False
    seq, event_hash = _trace_tail(trace)
    provenance = dossier.get("provenance", {})
    return (
        isinstance(provenance, Mapping)
        and provenance.get("trace_verified") is True
        and provenance.get("source_trace_version") == seq
        and provenance.get("source_event_hash") == event_hash
    )


def _probe_attempt_api() -> dict[str, Any]:
    """Black-box POST /v1/attempts and replay audit against a real sidecar."""

    service = REPO_ROOT / "service"
    if not service.is_dir():
        return {"status": "pending", "errors": ["service package is absent"], "cases": {}}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    continuation_errors: list[str] = []
    assistance_errors: list[str] = []
    dossier_errors: list[str] = []
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
            pii_secret = "sk-" + "evalcanaryabcdefghijklmnopqrstuvwxyz"
            requests = {
                "correct": {
                    "fixture_id": fixture_id,
                    "response": "B",
                    "confidence": 0.90,
                    "response_time_seconds": 18,
                    "run_id": _eval_public_run_id("api-correct"),
                },
                "wrong": {
                    "fixture_id": fixture_id,
                    "response": "A",
                    "confidence": 0.80,
                    "response_time_seconds": 31,
                    "run_id": _eval_public_run_id("api-wrong"),
                },
                "pii": {
                    "fixture_id": fixture_id,
                    "response": (
                        "A eval.learner@example.invalid 13800138000 "
                        f"11010519491231002X {pii_secret}"
                    ),
                    "confidence": 0.40,
                    "response_time_seconds": 50,
                    "run_id": _eval_public_run_id("api-pii"),
                },
                "unknown_field": {
                    "fixture_id": fixture_id,
                    "response": "A",
                    "confidence": 0.50,
                    "response_time_seconds": 20,
                    "run_id": _eval_public_run_id("api-unknown"),
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
                for secret in (
                    "eval.learner@example.invalid",
                    "13800138000",
                    "11010519491231002X",
                    pii_secret,
                ):
                    if secret in serialized_response or secret in persisted:
                        errors.append(f"pii: raw {secret!r} escaped redaction")
                evidence = payload.get("response_evidence", {})
                if evidence.get("redacted_text") != "A [EMAIL] [PHONE] [ID] [SECRET]":
                    errors.append("pii: redacted projection is incorrect")
                if not evidence.get("sha256") or evidence.get("original_length") != len(str(raw_pii)):
                    errors.append("pii: digest/length evidence is incomplete")
            if unknown["status"] != 400 or unknown["payload"].get("error", {}).get("code") != "invalid_body":
                errors.append("unknown_field: unsupported input did not fail closed with invalid_body")
            unknown_trace = _http_json(
                base_url,
                "GET",
                f"/v1/runs/{requests['unknown_field']['run_id']}/trace",
            )
            cases["unknown_field"]["trace_after_rejection"] = unknown_trace
            if unknown_trace["status"] != 404:
                errors.append("unknown_field: rejected input left a persisted run")

            if wrong["status"] == 201 and cases["wrong"].get("trace", {}).get("status") == 200:
                diagnosis = _diagnosis_from_trace(cases["wrong"]["trace"]["payload"])
                if not diagnosis:
                    errors.append("wrong: diagnosis provenance is absent from trace")
                else:
                    sources = diagnosis.get("provenance", {}).get("prior_sources", [])
                    if not sources or any(source.get("sample_size") != 0 for source in sources):
                        errors.append("cohort: no-data cold start is not marked sample_size=0")
                    if any(source.get("kind") != "engineering_prior" for source in sources):
                        errors.append("cohort: no-data cold start is not labelled engineering_prior")
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
                            "prompt_instance_id": f"{initial.get('run_id')}:verification:1",
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
                            "prompt_instance_id": initial.get("probe", {}).get("prompt_instance_id"),
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
                            "prompt_instance_id": initial.get("probe", {}).get("prompt_instance_id"),
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
                                "prompt_instance_id": probe_payload.get("verification", {}).get("prompt_instance_id"),
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
                                "prompt_instance_id": f"{initial.get('run_id')}:verification:1",
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

            assistance_initial = _http_json(
                base_url,
                "POST",
                "/v1/attempts",
                {
                    "fixture_id": fixture_id,
                    "response": "A",
                    "confidence": 0.8,
                    "response_time_seconds": 28,
                    "run_id": _eval_public_run_id("api-assistance"),
                },
            )
            assistance_deliveries: list[dict[str, Any]] = []
            assistance_exhausted: dict[str, Any] = {"status": 0, "payload": {}}
            assistance_trace: dict[str, Any] = {"status": 0, "payload": {}}
            assistance_dossier: dict[str, Any] = {"status": 0, "payload": {}}
            if assistance_initial["status"] != 201:
                assistance_errors.append(
                    f"assistance fixture attempt returned {assistance_initial['status']}"
                )
            else:
                initial_payload = assistance_initial["payload"]
                version = initial_payload.get("state_version")
                actions = [
                    "retry",
                    "locate_evidence",
                    "rule_hint",
                    "analogous_example",
                    "worked_step",
                    "full_explanation",
                ]
                weights = [1.0, 0.8, 0.65, 0.5, 0.3, 0.0]
                for ordinal, (expected_action, expected_weight) in enumerate(
                    zip(actions, weights), start=1
                ):
                    previous_version = version
                    expected_next_version = (
                        previous_version + 1 if isinstance(previous_version, int) else None
                    )
                    delivered = _http_json(
                        base_url,
                        "POST",
                        initial_payload["links"]["assist"],
                        {
                            "phase": "probe",
                            "expected_version": version,
                            "expected_state": "awaiting_probe",
                            "prompt_instance_id": initial_payload["probe"]["prompt_instance_id"],
                            "action": "next",
                            "elapsed_time_seconds": ordinal * 2,
                            "command_id": _eval_public_command_id(
                                f"api-assistance-{ordinal}"
                            ),
                        },
                    )
                    assistance_deliveries.append(delivered)
                    payload = delivered.get("payload", {})
                    assistance = payload.get("assistance", {})
                    contract_errors = validate_json(
                        payload, load_json(CONTRACT_DIR / "assistance-result.schema.json")
                    )
                    if (
                        delivered.get("status") != 200
                        or contract_errors
                        or assistance.get("ordinal") != ordinal
                        or assistance.get("action") != expected_action
                        or assistance.get("diagnostic_evidence_weight") != expected_weight
                        or assistance.get("calibration_status")
                        != "engineering_policy_unvalidated"
                        or payload.get("state") != "awaiting_probe"
                        or payload.get("state_version") != expected_next_version
                        or payload.get("remaining_levels") != 6 - ordinal
                        or payload.get("idempotent_replay") is not False
                        or payload.get("trace_verified") is not True
                    ):
                        assistance_errors.append(
                            f"assistance level {ordinal} violated contract, order, weight, state, or provenance: {contract_errors}"
                        )
                        break
                    version = payload.get("state_version")
                if len(assistance_deliveries) == 6 and version is not None:
                    assistance_exhausted = _http_json(
                        base_url,
                        "POST",
                        initial_payload["links"]["assist"],
                        {
                            "phase": "probe",
                            "expected_version": version,
                            "expected_state": "awaiting_probe",
                            "prompt_instance_id": initial_payload["probe"]["prompt_instance_id"],
                            "action": "next",
                            "elapsed_time_seconds": 20,
                            "command_id": _eval_public_command_id(
                                "api-assistance-7"
                            ),
                        },
                    )
                    if (
                        assistance_exhausted.get("status") != 409
                        or assistance_exhausted.get("payload", {})
                        .get("error", {})
                        .get("code")
                        != "assistance_exhausted"
                    ):
                        assistance_errors.append("seventh assistance level did not fail closed")
                assistance_trace = _http_json(
                    base_url, "GET", initial_payload["links"]["trace"]
                )
                assistance_dossier = _http_json(
                    base_url, "GET", initial_payload["links"]["misconception"]
                )
                if assistance_trace.get("payload", {}).get("trace_verified") is not True:
                    assistance_errors.append("assistance trace hash verification failed")
                if len(assistance_dossier.get("payload", {}).get("assistance_history", [])) != 6:
                    assistance_errors.append("dossier did not persist six assistance events")
            cases["progressive_assistance"] = {
                "initial": assistance_initial,
                "deliveries": assistance_deliveries,
                "exhausted": assistance_exhausted,
                "trace": assistance_trace,
                "dossier": assistance_dossier,
            }

            dossier_initial = _http_json(
                base_url,
                "POST",
                "/v1/attempts",
                {
                    "fixture_id": fixture_id,
                    "response": "A",
                    "confidence": 0.8,
                    "response_time_seconds": 25,
                    "run_id": _eval_public_run_id("api-dossier"),
                },
            )
            dossier_after_probe: dict[str, Any] = {"status": 0, "payload": {}}
            dossier_result: dict[str, Any] = {"status": 0, "payload": {}}
            dossier_trace: dict[str, Any] = {"status": 0, "payload": {}}
            if dossier_initial["status"] != 201:
                dossier_errors.append(f"dossier fixture attempt returned {dossier_initial['status']}")
            else:
                dossier_initial_payload = dossier_initial["payload"]
                dossier_probe_response = (
                    "120÷100 dossier.learner@example.invalid "
                    "13800138000 11010519491231002X"
                )
                dossier_after_probe = _http_json(
                    base_url,
                    "POST",
                    dossier_initial_payload["links"]["respond"],
                    {
                        "phase": "probe",
                        "expected_version": dossier_initial_payload["state_version"],
                        "expected_state": "awaiting_probe",
                        "prompt_instance_id": dossier_initial_payload["probe"]["prompt_instance_id"],
                        "response": dossier_probe_response,
                        "confidence": 0.6,
                        "response_time_seconds": 12,
                    },
                )
                dossier_result = _http_json(
                    base_url, "GET", dossier_initial_payload["links"]["misconception"]
                )
                dossier_trace = _http_json(
                    base_url, "GET", dossier_initial_payload["links"]["trace"]
                )
                dossier_payload = dossier_result.get("payload", {})
                dossier_trace_payload = dossier_trace.get("payload", {})
                dossier_contract_errors = validate_json(
                    dossier_payload,
                    load_json(CONTRACT_DIR / "misconception-dossier.schema.json"),
                )
                by_cause = {
                    item.get("cause_id"): item
                    for item in dossier_payload.get("hypotheses", [])
                }
                persisted_dossier_evidence = canonical_json(
                    {
                        "continuation": dossier_after_probe.get("payload", {}),
                        "dossier": dossier_payload,
                        "trace": dossier_trace_payload,
                    }
                )
                raw_dossier_canaries = (
                    "dossier.learner@example.invalid",
                    "13800138000",
                    "11010519491231002X",
                )
                if (
                    dossier_after_probe.get("status") != 200
                    or dossier_result.get("status") != 200
                    or dossier_trace.get("status") != 200
                    or dossier_contract_errors
                ):
                    dossier_errors.append("event-sourced dossier is unavailable after probe")
                elif (
                    by_cause.get("denominator-current-base-confusion", {}).get("claim_status")
                    != "refuted_hypothesis"
                    or by_cause.get("ratio-growth-confusion", {}).get("claim_status")
                    != "supported_hypothesis"
                    or not by_cause.get("denominator-current-base-confusion", {}).get(
                        "refuting_evidence"
                    )
                    or not by_cause.get("ratio-growth-confusion", {}).get(
                        "supporting_evidence"
                    )
                    or dossier_payload.get("cohort_evidence", {}).get("status") != "unavailable"
                    or not _dossier_provenance_matches_trace(
                        dossier_payload, dossier_trace_payload
                    )
                ):
                    dossier_errors.append(
                        "dossier lost authored probe evidence, unavailable cohort semantics, or trace provenance"
                    )
                if _contains_forbidden_causal_field(dossier_payload):
                    dossier_errors.append("dossier emitted a causal confirmation label")
                if any(secret in persisted_dossier_evidence for secret in raw_dossier_canaries):
                    dossier_errors.append("dossier or trace persisted raw probe-response PII")
            correct_dossier = (
                _http_json(base_url, "GET", correct["payload"]["links"]["misconception"])
                if correct.get("status") == 201
                else {"status": 0, "payload": {}}
            )
            correct_dossier_payload = correct_dossier.get("payload", {})
            correct_trace = (
                cases.get("correct", {}).get("trace", {})
                if correct.get("status") == 201
                else {"status": 0, "payload": {}}
            )
            correct_contract_errors = validate_json(
                correct_dossier_payload,
                load_json(CONTRACT_DIR / "misconception-dossier.schema.json"),
            )
            if (
                correct_dossier.get("status") != 200
                or correct_trace.get("status") != 200
                or correct_contract_errors
                or correct_dossier_payload.get("hypotheses") != []
                or correct_dossier_payload.get("assistance_history") != []
                or correct_dossier_payload.get("uncertainty") != 0
                or correct_dossier_payload.get("learning_status") != "no_misconception_observed"
                or correct_dossier_payload.get("resolution", {}).get("status")
                != "no_misconception_observed"
                or correct_dossier_payload.get("cohort_evidence", {}).get("status")
                != "unavailable"
                or correct_dossier_payload.get("cohort_evidence", {}).get("sample_size") != 0
                or _contains_forbidden_causal_field(correct_dossier_payload)
                or not _dossier_provenance_matches_trace(
                    correct_dossier_payload, correct_trace.get("payload", {})
                )
            ):
                dossier_errors.append("correct attempt did not project an empty misconception dossier")
            cases["misconception_dossier"] = {
                "request": {
                    "probe_response_sha256": hashlib.sha256(
                        dossier_probe_response.encode("utf-8")
                    ).hexdigest()
                    if dossier_initial["status"] == 201
                    else None,
                    "raw_probe_response_retained": False,
                },
                "initial": dossier_initial,
                "after_probe": dossier_after_probe,
                "dossier": dossier_result,
                "trace": dossier_trace,
                "correct_dossier": correct_dossier,
                "correct_trace": correct_trace,
                "correct_contract_errors": correct_contract_errors,
                "pii_redacted": (
                    not any(secret in persisted_dossier_evidence for secret in raw_dossier_canaries)
                    if dossier_initial["status"] == 201
                    else False
                ),
            }
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
        "status": "fail" if errors or continuation_errors or assistance_errors or dossier_errors else "pass",
        "attempt_status": "fail" if errors else "pass",
        "continuation_status": "fail" if continuation_errors else "pass",
        "assistance_status": "fail" if errors or assistance_errors else "pass",
        "dossier_status": "fail" if errors or dossier_errors else "pass",
        "errors": errors,
        "continuation_errors": continuation_errors,
        "assistance_errors": assistance_errors,
        "dossier_errors": dossier_errors,
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
    prior_sources = provenance.get("prior_sources", [])
    if not prior_sources:
        errors.append("prior provenance is absent")
    elif any(source.get("kind") != "engineering_prior" or source.get("sample_size") != 0 for source in prior_sources):
        errors.append("synthetic golden diagnosis does not use sample-zero engineering priors")
    serialized_diagnosis = canonical_json(ctx.diagnosis)
    if "cohort_component" in serialized_diagnosis or "cohort_sources" in serialized_diagnosis:
        errors.append("synthetic golden diagnosis exposes obsolete cohort-labelled fields")
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


def _sanitize_report_string(value: str) -> str:
    text = value
    replacements = (
        (str(FORBIDDEN_REPO), "[READ_ONLY_REFERENCE]"),
        (str(REPO_ROOT), "[REPO_ROOT]"),
        (str(Path.home()), "[HOME]"),
    )
    for raw, replacement in replacements:
        if raw:
            text = text.replace(raw, replacement)
    text = text.replace(FORBIDDEN_REPO.name, "[READ_ONLY_REFERENCE]")
    text = text.replace("xingcetiku", "[QUESTION_BANK_REFERENCE]")
    for pattern, replacement in REPORT_PII_PATTERNS:
        text = pattern.sub(replacement, text)
    for pattern in REPORT_SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    text = LOCAL_ABSOLUTE_PATH_PATTERN.sub("[ABSOLUTE_PATH]", text)
    if text.startswith("/") and not text.startswith("/v1/"):
        return "[ABSOLUTE_PATH]"
    return text


def _sanitize_report_value(value: Any, key: str = "") -> Any:
    sensitive_keys = {
        "api_key",
        "authorization",
        "password",
        "private_key",
        "secret",
        "token",
        "access_token",
    }
    if key.casefold() in sensitive_keys:
        return "[REDACTED_SECRET]"
    if isinstance(value, str):
        return _sanitize_report_string(value)
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize_report_value(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_report_value(item, key) for item in value]
    return value


def _compact_request_evidence(request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        return {}
    allowed = {
        "fixture_id",
        "response_sha256",
        "contains_pii_test_data",
        "unknown_fields",
        "probe_response_sha256",
        "raw_probe_response_retained",
    }
    result = {str(key): request[key] for key in allowed if key in request}
    if request.get("run_id") is not None:
        result["run_id_sha256"] = hashlib.sha256(
            str(request["run_id"]).encode("utf-8")
        ).hexdigest()
    return result


def _compact_response_evidence(evidence: Any) -> dict[str, Any] | None:
    if not isinstance(evidence, Mapping):
        return None
    redacted_text = str(evidence.get("redacted_text", ""))
    markers = sorted(set(re.findall(r"\[(?:EMAIL|PHONE|ID|SECRET)\]", redacted_text)))
    return {
        "sha256": evidence.get("sha256"),
        "original_length": evidence.get("original_length"),
        "redactions": evidence.get("redactions", []),
        "redaction_markers": markers,
        "policy_version": evidence.get("policy_version"),
    }


def _compact_service_test_evidence(probe: Mapping[str, Any]) -> dict[str, Any]:
    return _sanitize_report_value(
        {
            "status": probe.get("status"),
            "exit_code": probe.get("exit_code"),
            "command": probe.get("command", []),
            "output": probe.get("output", ""),
            "errors": probe.get("errors", []),
        }
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
                "request": _compact_request_evidence(case.get("request")),
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
        if label == "progressive_assistance":
            deliveries = case.get("deliveries", [])
            trace_payload = case.get("trace", {}).get("payload", {})
            dossier_payload = case.get("dossier", {}).get("payload", {})
            cases[label] = {
                "initial_status": case.get("initial", {}).get("status"),
                "delivered_levels": [
                    {
                        "status": item.get("status"),
                        "ordinal": item.get("payload", {}).get("assistance", {}).get("ordinal"),
                        "action": item.get("payload", {}).get("assistance", {}).get("action"),
                        "state_version": item.get("payload", {}).get("state_version"),
                        "remaining_levels": item.get("payload", {}).get("remaining_levels"),
                        "idempotent_replay": item.get("payload", {}).get("idempotent_replay"),
                        "diagnostic_evidence_weight": item.get("payload", {})
                        .get("assistance", {})
                        .get("diagnostic_evidence_weight"),
                        "calibration_status": item.get("payload", {})
                        .get("assistance", {})
                        .get("calibration_status"),
                    }
                    for item in deliveries
                ],
                "exhausted": {
                    "status": case.get("exhausted", {}).get("status"),
                    "code": case.get("exhausted", {})
                    .get("payload", {})
                    .get("error", {})
                    .get("code"),
                },
                "trace_verified": trace_payload.get("trace_verified"),
                "trace_sha256": sha256_json(trace_payload) if trace_payload else None,
                "assistance_history_count": len(dossier_payload.get("assistance_history", [])),
                "cohort_evidence_status": dossier_payload.get("cohort_evidence", {}).get("status"),
            }
            continue
        if label == "misconception_dossier":
            dossier_payload = case.get("dossier", {}).get("payload", {})
            correct_payload = case.get("correct_dossier", {}).get("payload", {})
            trace_payload = case.get("trace", {}).get("payload", {})
            correct_trace_payload = case.get("correct_trace", {}).get("payload", {})
            cases[label] = {
                "request": _compact_request_evidence(case.get("request")),
                "initial_status": case.get("initial", {}).get("status"),
                "probe_status": case.get("after_probe", {}).get("status"),
                "dossier_status": case.get("dossier", {}).get("status"),
                "claim_statuses": {
                    item.get("cause_id"): item.get("claim_status")
                    for item in dossier_payload.get("hypotheses", [])
                },
                "evidence_ref_counts": {
                    item.get("cause_id"): {
                        "supporting": len(item.get("supporting_evidence", [])),
                        "refuting": len(item.get("refuting_evidence", [])),
                    }
                    for item in dossier_payload.get("hypotheses", [])
                },
                "cohort_evidence_status": dossier_payload.get("cohort_evidence", {}).get("status"),
                "trace_verified": dossier_payload.get("provenance", {}).get("trace_verified"),
                "provenance_matches_trace": _dossier_provenance_matches_trace(
                    dossier_payload, trace_payload
                ),
                "pii_redacted": case.get("pii_redacted"),
                "correct_hypothesis_count": len(correct_payload.get("hypotheses", [])),
                "correct_learning_status": correct_payload.get("learning_status"),
                "correct_assistance_history_count": len(
                    correct_payload.get("assistance_history", [])
                ),
                "correct_uncertainty": correct_payload.get("uncertainty"),
                "correct_cohort_evidence_status": correct_payload.get(
                    "cohort_evidence", {}
                ).get("status"),
                "correct_contract_valid": not case.get("correct_contract_errors", []),
                "correct_provenance_matches_trace": _dossier_provenance_matches_trace(
                    correct_payload, correct_trace_payload
                ),
            }
            continue
        response = case.get("response", {})
        trace = case.get("trace", {})
        replay = case.get("replay", {})
        payload = response.get("payload", {})
        cases[label] = {
            "request": _compact_request_evidence(case.get("request")),
            "http_status": response.get("status"),
            "schema_version": payload.get("schema_version"),
            "run_status": payload.get("status"),
            "score_passed": payload.get("score", {}).get("passed"),
            "hypothesis_count": len(payload.get("diagnosis", {}).get("hypotheses", [])),
            "verification": payload.get("verification"),
            "response_evidence": _compact_response_evidence(payload.get("response_evidence")),
            "error": payload.get("error"),
            "trace_status": trace.get("status"),
            "trace_sha256": sha256_json(trace.get("payload")) if trace.get("payload") else None,
            "replay_status": replay.get("status"),
            "replay_sha256": sha256_json(replay.get("payload")) if replay.get("payload") else None,
            "rejected_run_trace_status": case.get("trace_after_rejection", {}).get("status"),
        }
    compact = {
        "status": probe.get("status"),
        "attempt_status": probe.get("attempt_status"),
        "continuation_status": probe.get("continuation_status"),
        "assistance_status": probe.get("assistance_status"),
        "dossier_status": probe.get("dossier_status"),
        "errors": probe.get("errors", []),
        "continuation_errors": probe.get("continuation_errors", []),
        "assistance_errors": probe.get("assistance_errors", []),
        "dossier_errors": probe.get("dossier_errors", []),
        "cases": cases,
    }
    return _sanitize_report_value(compact)


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
    sources = diagnosis.get("provenance", {}).get("prior_sources", []) if diagnosis else []
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
        or any(source.get("kind") != "engineering_prior" for source in sources)
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


def gate_today_plan_schedule(ctx: Context) -> GateResult:
    probe = ctx.probe_schedule_api()
    evidence = [probe]
    status = probe.get("status", "pending")
    if status == "pending":
        return GateResult(
            "today_plan_schedule",
            "pending",
            "TodayPlan and ReviewSchedule HTTP surfaces are absent",
            evidence,
        )
    if status != "pass":
        return GateResult(
            "today_plan_schedule",
            "fail",
            "TodayPlan/ReviewSchedule truthfulness, provenance, timing, budget, command, replay, or KT-separation assertion failed",
            evidence,
        )
    return GateResult(
        "today_plan_schedule",
        "pass",
        "23 real HTTP/storage cases prove empty and three human-attempt branches, canonical trace provenance, same-fixture disclosure, fixed-unvalidated and overdue timing, accepted-budget fail-closed/retry plus fair commitment carry, restart migration, command receipts/CAS with no partial writes, clock-skew historical safety, verified replay, synthetic-origin exclusion, and user-marked completion with no KT write",
        evidence,
    )


def gate_progressive_assistance(ctx: Context) -> GateResult:
    probe = ctx.probe_attempt_api()
    service_tests = ctx.probe_service_tests()
    compact = _compact_attempt_api_evidence(probe)
    evidence = [compact, {"complete_service_tests": _compact_service_test_evidence(service_tests)}]
    status = probe.get("assistance_status", "pending")
    if status == "pending" or service_tests.get("status") == "pending":
        return GateResult(
            "progressive_assistance",
            "pending",
            "versioned assistance endpoint and event evidence are absent",
            evidence,
        )
    case = compact.get("cases", {}).get("progressive_assistance", {})
    delivered_levels = case.get("delivered_levels", [])
    delivered_versions = [item.get("state_version") for item in delivered_levels]
    versions_are_monotonic = (
        len(delivered_versions) == 6
        and all(isinstance(version, int) for version in delivered_versions)
        and delivered_versions == list(range(delivered_versions[0], delivered_versions[0] + 6))
    )
    complete_evidence = (
        service_tests.get("status") == "pass"
        and len(delivered_levels) == 6
        and all(item.get("status") == 200 for item in delivered_levels)
        and versions_are_monotonic
        and [item.get("remaining_levels") for item in delivered_levels]
        == [5, 4, 3, 2, 1, 0]
        and all(item.get("idempotent_replay") is False for item in delivered_levels)
        and case.get("exhausted", {}).get("code") == "assistance_exhausted"
        and case.get("trace_verified") is True
        and case.get("assistance_history_count") == 6
    )
    if (
        status != "pass"
        or service_tests.get("status") != "pass"
        or probe.get("errors")
        or not complete_evidence
    ):
        return GateResult(
            "progressive_assistance",
            "fail",
            "six-level order, evidence discount, exhaustion, persistence, or trace verification failed",
            evidence,
        )
    return GateResult(
        "progressive_assistance",
        "pass",
        "real HTTP assistance advances six server-authored levels, records uncalibrated evidence discounts, fails closed after exhaustion, and preserves a verified trace",
        evidence,
    )


def gate_misconception_dossier(ctx: Context) -> GateResult:
    probe = ctx.probe_attempt_api()
    service_tests = ctx.probe_service_tests()
    compact = _compact_attempt_api_evidence(probe)
    evidence = [compact, {"complete_service_tests": _compact_service_test_evidence(service_tests)}]
    status = probe.get("dossier_status", "pending")
    if status == "pending" or service_tests.get("status") == "pending":
        return GateResult(
            "misconception_dossier",
            "pending",
            "event-sourced misconception dossier endpoint is absent",
            evidence,
        )
    case = compact.get("cases", {}).get("misconception_dossier", {})
    raw_dossier = (
        probe.get("cases", {})
        .get("misconception_dossier", {})
        .get("dossier", {})
        .get("payload", {})
    )
    processing_contract_errors: list[str] = []
    if isinstance(raw_dossier, Mapping) and raw_dossier:
        dossier_schema = load_json(CONTRACT_DIR / "misconception-dossier.schema.json")
        for state_name, learning_status, action in (
            (
                "processing_probe",
                "processing_probe_response",
                "restart_attempt_after_processing_failure",
            ),
            (
                "processing_verification",
                "processing_verification_response",
                "restart_attempt_for_fresh_independent_verification",
            ),
        ):
            processing = json.loads(json.dumps(raw_dossier))
            processing["state"] = state_name
            processing["learning_status"] = learning_status
            processing["resolution"]["status"] = learning_status
            processing["next_action"] = {
                "action": action,
                "target": "/v1/attempts",
                "reason": "A consumed response did not finish processing.",
            }
            processing_contract_errors.extend(
                f"{state_name}: {error}"
                for error in validate_json(processing, dossier_schema)
            )
    else:
        processing_contract_errors.append("real dossier payload is unavailable")
    evidence.append(
        {
            "processing_fail_closed_contract": {
                "states_checked": ["processing_probe", "processing_verification"],
                "errors": processing_contract_errors,
            }
        }
    )
    evidence_counts = case.get("evidence_ref_counts", {})
    complete_evidence = (
        service_tests.get("status") == "pass"
        and not processing_contract_errors
        and case.get("dossier_status") == 200
        and case.get("trace_verified") is True
        and case.get("provenance_matches_trace") is True
        and case.get("pii_redacted") is True
        and case.get("cohort_evidence_status") == "unavailable"
        and evidence_counts.get("denominator-current-base-confusion", {}).get("refuting", 0) > 0
        and evidence_counts.get("ratio-growth-confusion", {}).get("supporting", 0) > 0
        and case.get("correct_hypothesis_count") == 0
        and case.get("correct_learning_status") == "no_misconception_observed"
        and case.get("correct_assistance_history_count") == 0
        and case.get("correct_uncertainty") == 0
        and case.get("correct_cohort_evidence_status") == "unavailable"
        and case.get("correct_contract_valid") is True
        and case.get("correct_provenance_matches_trace") is True
    )
    if (
        status != "pass"
        or service_tests.get("status") != "pass"
        or probe.get("errors")
        or not complete_evidence
    ):
        return GateResult(
            "misconception_dossier",
            "fail",
            "probe evidence, hypothesis status, empty-correct state, cohort unavailability, or trace provenance failed",
            evidence,
        )
    return GateResult(
        "misconception_dossier",
        "pass",
        "real HTTP dossier separates observations, authored probe support/refutation, unconfirmed cause semantics, learning resolution, and unavailable cohort evidence with trace references",
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
    "github_fine_grained_token": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "google_api_key": re.compile(r"AIzaSy[A-Za-z0-9_-]{33}"),
    "npm_token": re.compile(r"npm_[A-Za-z0-9]{36}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
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


def iter_tracked_report_files() -> Iterable[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--", "evals/reports"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    candidates = (
        [REPO_ROOT / line for line in result.stdout.splitlines() if line.strip()]
        if result is not None and result.returncode == 0
        else sorted(REPORT_DIR.glob("*.json"))
    )
    report_root = REPORT_DIR.resolve(strict=False)
    for path in candidates:
        resolved = path.resolve(strict=False)
        if path.is_file() and (resolved == report_root or report_root in resolved.parents):
            yield path


def iter_persisted_report_files() -> Iterable[Path]:
    for path in sorted(REPORT_DIR.iterdir()) if REPORT_DIR.is_dir() else []:
        if path.is_file() and path.suffix in {".json", ".md"}:
            yield path


def _report_safety_findings(paths: Iterable[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in paths:
        relative = str(path.relative_to(REPO_ROOT))
        text = path.read_text(encoding="utf-8", errors="ignore")
        if str(REPO_ROOT) in text or str(Path.home()) in text:
            findings.append({"file": relative, "finding": "absolute_home_or_repository_path"})
        if str(FORBIDDEN_REPO) in text or FORBIDDEN_REPO.name in text:
            findings.append({"file": relative, "finding": "read_only_repository_name_or_path"})
        if LOCAL_ABSOLUTE_PATH_PATTERN.search(text):
            findings.append({"file": relative, "finding": "absolute_local_path"})
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append({"file": relative, "finding": name})
        for pattern, marker in REPORT_PII_PATTERNS:
            if pattern.search(text):
                findings.append({"file": relative, "finding": f"raw_pii_matching_{marker}"})
    return findings


def _tracked_report_safety_findings() -> list[dict[str, Any]]:
    return _report_safety_findings(iter_tracked_report_files())


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
    tracked_report_findings = _tracked_report_safety_findings()
    persisted_report_findings = _report_safety_findings(iter_persisted_report_files())
    findings.extend({"tracked_report": item} for item in tracked_report_findings)
    findings.extend({"persisted_report": item} for item in persisted_report_findings)
    evidence = [
        {"scanned_file_count": sum(1 for _ in iter_source_files()), "secret_findings": findings},
        {"cloud_marker_files": sorted(set(cloud_markers))},
        {"trace_privacy": privacy},
        {
            "tracked_report_count": sum(1 for _ in iter_tracked_report_files()),
            "tracked_report_findings": tracked_report_findings,
            "persisted_report_count": sum(1 for _ in iter_persisted_report_files()),
            "persisted_report_findings": persisted_report_findings,
        },
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
    "today_plan_schedule": gate_today_plan_schedule,
    "progressive_assistance": gate_progressive_assistance,
    "misconception_dossier": gate_misconception_dossier,
    "trace": gate_trace,
    "diagnosis": gate_diagnosis,
    "kt": gate_kt,
    "teaching_transfer": gate_teaching_transfer,
    "privacy": gate_privacy,
    "readonly_boundary": gate_readonly_boundary,
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
        "repository": str(REPO_ROOT),
        "overall_status": overall,
        "summary": {"pass": counts["pass"], "fail": counts["fail"], "pending": counts["pending"], "total": len(results)},
        "gates": [asdict(item) for item in results],
    }
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
            "The JSON report beside this file is authoritative and contains hashes, command output, missing matrix entries, and computed evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: Mapping[str, Any], ctx: Context) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = str(report["run_id"]).removeprefix("run-")
    safe_report = _sanitize_report_value(report)
    report_json = json.dumps(safe_report, ensure_ascii=False, indent=2) + "\n"
    (REPORT_DIR / f"release-{timestamp}.json").write_text(report_json, encoding="utf-8")
    (REPORT_DIR / "latest.json").write_text(report_json, encoding="utf-8")
    (REPORT_DIR / "latest.md").write_text(render_markdown(safe_report), encoding="utf-8")
    if ctx.trace is not None:
        trace_json = json.dumps(
            _sanitize_report_value(ctx.trace), ensure_ascii=False, indent=2
        ) + "\n"
        (REPORT_DIR / "golden-trajectory-latest.json").write_text(trace_json, encoding="utf-8")
    if ctx.integration_probe is not None:
        for scenario, run in ctx.integration_probe.get("runs", {}).items():
            replay = run.get("replay")
            if replay is not None:
                path = REPORT_DIR / f"integration-{scenario}-trajectory-latest.json"
                safe_replay = _sanitize_report_value(replay)
                path.write_text(json.dumps(safe_replay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if ctx.attempt_api_probe is not None:
        path = REPORT_DIR / "attempt-api-evidence-latest.json"
        compact = _compact_attempt_api_evidence(ctx.attempt_api_probe)
        path.write_text(
            json.dumps(_sanitize_report_value(compact), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if ctx.schedule_api_probe is not None:
        path = REPORT_DIR / "today-plan-evidence-latest.json"
        path.write_text(
            json.dumps(
                _sanitize_report_value(ctx.schedule_api_probe),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


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
