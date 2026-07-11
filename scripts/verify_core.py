#!/usr/bin/env python3
"""Run deterministic Lumi checks without installing project dependencies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
XINGCE = Path(os.environ.get("LUMI_XINGCE_ROOT", Path.home() / "Documents" / "xingcetiku"))


def command(name: str, argv: list[str], cwd: Path) -> dict[str, object]:
    env = dict(os.environ)
    local_packages = [
        ROOT / "engine",
        ROOT / "runtime",
        ROOT / "domains",
        ROOT / "integration",
        ROOT / "service",
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
    checks: list[tuple[str, list[str], Path]] = [
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

    optional_suites = {
        "agent-runtime": ROOT / "runtime",
        "domain-slices": ROOT / "domains",
        "integrated-learning-loop": ROOT / "integration",
        "local-sidecar": ROOT / "service",
    }
    for name, directory in optional_suites.items():
        if (directory / "tests").is_dir():
            checks.append(
                (
                    name,
                    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                    directory,
                )
            )

    if (ROOT / "evals" / "run_all.py").is_file():
        checks.append(
            (
                "release-evidence",
                [sys.executable, "evals/run_all.py"],
                ROOT,
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

    results = [command(name, argv, cwd) for name, argv, cwd in checks]
    report = {
        "schema": "hermes.core-verification.v0",
        "status": "pass" if all(r["status"] == "pass" for r in results) else "fail",
        "checks": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
