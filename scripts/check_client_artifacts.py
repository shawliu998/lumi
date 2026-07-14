#!/usr/bin/env python3
"""Fail closed when the Lumi client handoff evidence is incomplete."""

from __future__ import annotations

import json
import hashlib
import re
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
QA = CLIENT / "qa"

SCREENSHOTS = {
    "p01-authentic-overview-empty-real-1280x720.png": (1280, 720),
    "p01-authentic-overview-connected-real-1280x720.png": (1280, 720),
    "p01-authentic-report-connected-real-1280x720.png": (1280, 720),
    "p01-authentic-probe-assistance-real-1280x720.png": (1280, 720),
    "p01-authentic-dossier-probe-real-1280x720.png": (1280, 720),
    "p01-authentic-independent-verification-real-1280x720.png": (1280, 720),
    "p01-authentic-comparison-overview-connected.png": (1800, 526),
    "p01-authentic-comparison-report-connected.png": (1800, 526),
    "p01-authentic-comparison-tools-probe-assistance.png": (1800, 526),
    "p01-authentic-comparison-tools-dossier-probe.png": (1800, 526),
    "p01-authentic-comparison-tools-independent-verification.png": (1800, 526),
    "p02-overview-connected-not-created-1280x720.png": (1280, 720),
    "p02-practice-final-contract-1280x720.png": (1280, 720),
    "p02-practice-evidence-collapsed-1280x720.png": (1280, 720),
    "p02-practice-evidence-expanded-1280x720.png": (1280, 720),
    "p02-report-review-schedule-1280x720.png": (1280, 720),
    "p02-report-readable-narrow-640x720.png": (640, 720),
    "p02-historical-plan-conflict-1280x720.png": (1280, 720),
    "p02-no-pending-review-1280x720.png": (1280, 720),
    "p02-offline-fail-closed-1280x720.png": (1280, 720),
    "p02-error-500-fail-closed-1280x720.png": (1280, 720),
    "p02-practice-narrow-640x720.png": (640, 720),
    "p02-compare-overview-khanmigo.png": (1816, 562),
    "p02-compare-practice-khanmigo.png": (1816, 562),
    "p02-compare-report-khanmigo.png": (1816, 562),
    "p02-budget-below-accepted-retry-1280x720.png": (1280, 720),
    "p02-budget-retry-success-1280x720.png": (1280, 720),
    "p02-compare-budget-conflict-khanmigo.png": (1816, 562),
    "question-bank-offline-assets-1280x720.png": (1280, 720),
    "question-bank-offline-assets-640x720.png": (640, 720),
}

BANNED_PATTERNS = {
    "gradient": re.compile(r"(?:linear|radial|conic)-gradient\s*\(", re.I),
    "backdrop-filter": re.compile(r"backdrop-filter\s*:", re.I),
    "whole-window-zoom": re.compile(r"\.app-window\s*\{[^}]*\bzoom\s*:", re.I | re.S),
    "whole-window-scale": re.compile(
        r"\.app-window\s*\{[^}]*transform\s*:\s*scale\s*\(", re.I | re.S
    ),
    "ai-marketing-copy": re.compile(r"AI\s*助手|智能助手|一键生成|赋能学习", re.I),
}

STALE_QA_PATTERNS = {
    "legacy fake attempt count": re.compile(r"\b129\b"),
    "legacy fabricated recent attempts": re.compile(r"最近\s*3\s*次"),
    "legacy mock-data claim": re.compile(r"rendered mock data|当前显示演示数据", re.I),
    "legacy client test count": re.compile(r"\b5/5\b"),
    "legacy release run": re.compile(r"run-20260711T051110Z"),
    "legacy Sol task": re.compile(r"019f4f2c-22d6-7973-9c03-d6079ffbe9bd"),
}

PRODUCTION_TRUTH_PATTERNS = {
    "fabricated learner profile": re.compile(r"广东省考|林同学"),
    "legacy fake report constants": re.compile(
        r"\b(?:SKILL_GROUPS|ACTIVITY_ROWS|REVIEW_ROWS|taskRows)\b"
    ),
    "legacy demo write path": re.compile(r"查看演示流程|当前显示演示数据"),
    "legacy fake attempt count": re.compile(r"\b129\b"),
    "raw Today planning copy": re.compile(r"Today\s*(?:最多|中|展示|计划)"),
    "raw accepted state in planning copy": re.compile(r"非\s*accepted\s*任务", re.I),
    "AI recommendation marketing copy": re.compile(r"AI\s*推荐", re.I),
}


def png_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError("not a genuine PNG")
    return struct.unpack(">II", raw[16:24])


def main() -> int:
    failures: list[str] = []
    evidence: dict[str, object] = {}

    qa_report = CLIENT / "design-qa.md"
    if not qa_report.is_file():
        failures.append("client/design-qa.md is missing")
    else:
        report = qa_report.read_text(encoding="utf-8")
        if "final result: passed" not in report:
            failures.append("design QA does not declare final result: passed")
        for phrase in (
            "技能证据",
            "非纵向掌握",
            "state harness",
            "real `0.2.0` sidecar",
        ):
            if phrase not in report:
                failures.append(f"design QA is missing current truthfulness evidence: {phrase}")
        for label, pattern in STALE_QA_PATTERNS.items():
            if pattern.search(report):
                failures.append(f"stale design QA claim detected: {label}")

    qa_readme = QA / "README.md"
    qa_readme_text = qa_readme.read_text(encoding="utf-8") if qa_readme.is_file() else ""
    if (
        "Files beginning with `p02-` are the current P0.2" not in qa_readme_text
        or "Only files beginning with `p01-authentic-`" not in qa_readme_text
    ):
        failures.append("client/qa does not distinguish current authentic evidence from superseded captures")

    screenshot_evidence: dict[str, object] = {}
    for name, expected_dimensions in SCREENSHOTS.items():
        path = QA / name
        if not path.is_file():
            failures.append(f"missing final screenshot: {name}")
            continue
        try:
            dimensions = png_dimensions(path)
        except ValueError as exc:
            failures.append(f"{name}: {exc}")
            continue
        if dimensions != expected_dimensions:
            failures.append(
                f"{name}: expected {expected_dimensions[0]}x{expected_dimensions[1]}, "
                f"got {dimensions[0]}x{dimensions[1]}"
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if qa_report.is_file() and digest not in report:
            failures.append(f"{name}: current SHA-256 is absent from design QA")
        screenshot_evidence[name] = {
            "width": dimensions[0],
            "height": dimensions[1],
            "bytes": path.stat().st_size,
            "sha256": digest,
        }
    evidence["screenshots"] = screenshot_evidence

    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((CLIENT / "src").glob("**/*"))
        if path.is_file() and path.suffix in {".css", ".js", ".jsx", ".html"}
    )
    for label, pattern in BANNED_PATTERNS.items():
        if pattern.search(source_text):
            failures.append(f"banned client pattern detected: {label}")

    production_source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((CLIENT / "src").glob("**/*"))
        if path.is_file()
        and path.suffix in {".css", ".js", ".jsx", ".html"}
        and not path.name.endswith(".test.js")
    )
    for label, pattern in PRODUCTION_TRUTH_PATTERNS.items():
        if pattern.search(production_source_text):
            failures.append(f"fabricated client evidence detected: {label}")

    dist_index = CLIENT / "dist" / "index.html"
    if not dist_index.is_file():
        failures.append("client/dist/index.html is missing")
    else:
        evidence["dist_index_bytes"] = dist_index.stat().st_size

    payload = {
        "schema": "hermes.client-artifacts.v0",
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "evidence": evidence,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
