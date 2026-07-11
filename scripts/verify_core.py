#!/usr/bin/env python3
"""Run deterministic Lumi checks without installing project dependencies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
XINGCE = Path(os.environ.get("LUMI_XINGCE_ROOT", Path.home() / "Documents" / "xingcetiku"))
STUDY_PACK_RUNTIME_PINS = {"pypdf": "6.10.0"}
STUDY_PACK_EVAL_PINS = {
    "jsonschema": "4.25.0",
    "pdfplumber": "0.11.7",
    "pypdf": "6.10.0",
    "reportlab": "4.4.2",
}


def _python_has_exact_pins(candidate: Path, expected: Mapping[str, str]) -> bool:
    probe_source = (
        "import importlib.metadata as m,json; "
        f"expected=json.loads({json.dumps(json.dumps(dict(expected), sort_keys=True))}); "
        "actual={name:m.version(name) for name in expected}; "
        "raise SystemExit(actual != expected)"
    )
    try:
        probe = subprocess.run(
            [str(candidate), "-c", probe_source],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _study_pack_python(expected: Mapping[str, str]) -> str | None:
    configured = os.environ.get("LUMI_STUDY_PACK_PYTHON")
    candidates = [
        Path(configured).expanduser() if configured else None,
        ROOT / "desktop" / ".sidecar-venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        if _python_has_exact_pins(candidate, expected):
            return str(candidate.absolute())
    return None


def command(
    name: str,
    argv: list[str],
    cwd: Path,
    env_overrides: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    local_packages = [
        ROOT / "engine",
        ROOT / "runtime",
        ROOT / "domains",
        ROOT / "integration",
        ROOT / "service",
        ROOT / "study_pack",
    ]
    inherited_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(path) for path in local_packages]
        + ([inherited_pythonpath] if inherited_pythonpath else [])
    )
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=env)
    return {
        "name": name,
        "command": argv,
        "cwd": str(cwd),
        "status": "pass" if result.returncode == 0 else "fail",
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def main() -> int:
    runtime_study_pack_python = _study_pack_python(STUDY_PACK_RUNTIME_PINS)
    strict_eval_python = _study_pack_python(STUDY_PACK_EVAL_PINS)
    runtime_interpreter = runtime_study_pack_python or sys.executable
    checks: list[
        tuple[str, list[str], Path]
        | tuple[str, list[str], Path, Mapping[str, str]]
    ] = [
        (
            "repository-boundaries",
            [sys.executable, "scripts/check_boundaries.py"],
            ROOT,
        ),
        (
            "explainable-kt",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            ROOT / "engine",
        ),
        (
            "xingce-bounded-data-validation",
            [sys.executable, "hermes/scripts/validate_bundle.py", "--limit", "100"],
            XINGCE,
        ),
    ]
    if runtime_study_pack_python is None:
        checks.append(
            (
                "study-pack-runtime-dependencies",
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "sys.stderr.write('study_pack_runtime_dependencies_unavailable: "
                        "build the desktop sidecar or set LUMI_STUDY_PACK_PYTHON to "
                        "an interpreter with pypdf==6.10.0\\n'); "
                        "raise SystemExit(1)"
                    ),
                ],
                ROOT,
            )
        )

    optional_suites = {
        "agent-runtime": (ROOT / "runtime", sys.executable),
        "domain-slices": (ROOT / "domains", sys.executable),
        "integrated-learning-loop": (ROOT / "integration", sys.executable),
        "local-sidecar": (ROOT / "service", runtime_interpreter),
        "local-study-pack": (ROOT / "study_pack", runtime_interpreter),
    }
    for name, (directory, interpreter) in optional_suites.items():
        if (directory / "tests").is_dir():
            checks.append(
                (
                    name,
                    [interpreter, "-m", "unittest", "discover", "-s", "tests", "-v"],
                    directory,
                )
            )

    if (ROOT / "evals" / "run_all.py").is_file():
        if strict_eval_python is None:
            checks.append(
                (
                    "study-pack-eval-dependencies",
                    [
                        sys.executable,
                        "-c",
                        (
                            "import sys; "
                            "sys.stderr.write('study_pack_eval_dependencies_unavailable: "
                            "set LUMI_STUDY_PACK_PYTHON to an interpreter with the exact "
                            "versions in evals/fixtures/study_pack/requirements.txt\\n'); "
                            "raise SystemExit(1)"
                        ),
                    ],
                    ROOT,
                )
            )
        checks.append(
            (
                "release-evidence",
                [sys.executable, "evals/run_all.py"],
                ROOT,
                (
                    {"LUMI_STUDY_PACK_PYTHON": strict_eval_python}
                    if strict_eval_python is not None
                    else {}
                ),
            )
        )

    client = ROOT / "client"
    if (client / "package.json").is_file():
        checks.extend(
            [
                (
                    "client-unit-tests",
                    ["npm", "test", "--", "--run"],
                    client,
                ),
                (
                    "client-production-build",
                    ["npm", "run", "build"],
                    client,
                ),
                (
                    "client-handoff-artifacts",
                    [sys.executable, "scripts/check_client_artifacts.py"],
                    ROOT,
                ),
            ]
        )

    desktop = ROOT / "desktop"
    if (desktop / "package.json").is_file():
        cargo = Path.home() / ".cargo" / "bin" / "cargo"
        cargo_command = str(cargo) if cargo.is_file() else "cargo"
        checks.extend(
            [
                (
                    "desktop-configuration",
                    ["npm", "run", "check:config"],
                    desktop,
                ),
                (
                    "desktop-sidecar-binary",
                    ["npm", "run", "check:sidecar"],
                    desktop,
                ),
                (
                    "desktop-debug-signature",
                    ["npm", "run", "check:signature"],
                    desktop,
                ),
                (
                    "desktop-bundled-sidecar",
                    ["npm", "run", "check:bundled-sidecar"],
                    desktop,
                ),
                (
                    "desktop-cargo-locked",
                    [
                        cargo_command,
                        "check",
                        "--locked",
                        "--manifest-path",
                        "src-tauri/Cargo.toml",
                    ],
                    desktop,
                ),
            ]
        )
        managed_app = (
            desktop
            / "src-tauri"
            / "target"
            / "debug"
            / "bundle"
            / "macos"
            / "Lumi.app"
        )
        if managed_app.is_dir():
            checks.append(
                (
                    "desktop-managed-sidecar",
                    ["npm", "run", "check:managed-app"],
                    desktop,
                )
            )

    # Check specifications may optionally carry scoped environment overrides.
    # Expanding the tuple preserves the three-field default while allowing the
    # release-evidence gate to select its pinned interpreter deterministically.
    results = [command(*check) for check in checks]
    report = {
        "schema": "hermes.core-verification.v0",
        "status": "pass" if all(r["status"] == "pass" for r in results) else "fail",
        "checks": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
