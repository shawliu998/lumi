#!/usr/bin/env python3
"""Read-only repository boundary checks for Lumi development."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SHENLUN_REPO = Path(
    os.environ.get("LUMI_SHENLUN_REPO", Path.home() / "Desktop" / "shenlun-agent-platform")
)
EXPECTED_SHENLUN_HEAD = os.environ.get(
    "LUMI_SHENLUN_EXPECTED_HEAD", "b5a6a4065cf401d54b2809ce7639217c95db3f5d"
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=SHENLUN_REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    evidence = {
        "path": str(SHENLUN_REPO),
        "exists": SHENLUN_REPO.is_dir(),
        "expected_head": EXPECTED_SHENLUN_HEAD,
    }
    if not evidence["exists"]:
        evidence.update(status="fail", reason="read-only repository is missing")
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 1

    try:
        head = git("rev-parse", "HEAD")
        porcelain = git("status", "--porcelain=v1")
    except subprocess.CalledProcessError as exc:
        evidence.update(status="fail", reason=exc.stderr.strip() or str(exc))
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 1

    evidence.update(
        actual_head=head,
        working_tree_clean=not bool(porcelain),
        baseline_head_unchanged=head == EXPECTED_SHENLUN_HEAD,
    )
    ok = evidence["working_tree_clean"] and evidence["baseline_head_unchanged"]
    evidence["status"] = "pass" if ok else "fail"
    if not ok:
        evidence["reason"] = (
            "Shared Shenlun repository changed from the frozen baseline. "
            "Stop and determine whether an external collaborator updated it."
        )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
