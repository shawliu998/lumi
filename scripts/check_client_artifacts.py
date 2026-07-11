#!/usr/bin/env python3
"""Fail closed when the Lumi client handoff evidence is incomplete."""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
QA = CLIENT / "qa"

SCREENSHOTS = (
    "overview-1440x1024.png",
    "tools-1440x1024.png",
    "reports-1440x1024.png",
)

BANNED_PATTERNS = {
    "gradient": re.compile(r"(?:linear|radial|conic)-gradient\s*\(", re.I),
    "backdrop-filter": re.compile(r"backdrop-filter\s*:", re.I),
    "whole-window-zoom": re.compile(r"\.app-window\s*\{[^}]*\bzoom\s*:", re.I | re.S),
    "whole-window-scale": re.compile(
        r"\.app-window\s*\{[^}]*transform\s*:\s*scale\s*\(", re.I | re.S
    ),
    "ai-marketing-copy": re.compile(r"AI\s*助手|智能助手|一键生成|赋能学习", re.I),
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
        if not re.search(r"No actionable P0, P1, or P2", report, re.I):
            failures.append("design QA does not explicitly close P0/P1/P2")

    screenshot_evidence: dict[str, object] = {}
    for name in SCREENSHOTS:
        path = QA / name
        if not path.is_file():
            failures.append(f"missing final screenshot: {name}")
            continue
        try:
            dimensions = png_dimensions(path)
        except ValueError as exc:
            failures.append(f"{name}: {exc}")
            continue
        if dimensions != (1440, 1024):
            failures.append(f"{name}: expected 1440x1024, got {dimensions[0]}x{dimensions[1]}")
        screenshot_evidence[name] = {
            "width": dimensions[0],
            "height": dimensions[1],
            "bytes": path.stat().st_size,
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
