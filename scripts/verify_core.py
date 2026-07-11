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
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
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
        checks.append(
            (
                "desktop-configuration",
                ["npm", "run", "check:config"],
                desktop,
            )
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
