from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .contract import ContractError, validate_fixture, validate_overlay


def load_fixture_document(path: Path, *, fixture_root: Path | None = None) -> dict[str, Any]:
    """Load a full fixture or resolve one constrained scenario overlay.

    Overlays keep shared synthetic learning content single-sourced while each
    scenario remains an independently addressable and fully validated fixture.
    Resolution is restricted to the same fixture root; nested/chained overlays
    are rejected to make replay and provenance obvious.
    """

    root = (fixture_root or path.parent).resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") == "hermes.domain-fixture.v1":
        validate_fixture(raw)
        return raw
    validate_overlay(raw)
    base_path = (path.parent / raw["extends"]).resolve()
    if base_path.parent != path.parent.resolve():
        raise ContractError("overlay base must be in the same domain directory")
    if root != base_path and root not in base_path.parents:
        raise ContractError("overlay base escapes fixture root")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if base.get("schema_version") != "hermes.domain-fixture.v1":
        raise ContractError("overlay must extend a full non-overlay fixture")
    if raw["domain"] != base.get("domain") or raw["path"] != base.get("path"):
        raise ContractError("overlay domain and path must match its base fixture")
    resolved = copy.deepcopy(base)
    for key in (
        "fixture_id", "domain", "path", "mode", "scenario_response",
        "execution", "expected_semantics",
    ):
        resolved[key] = copy.deepcopy(raw[key])
    resolved["provenance"]["scenario_overlay"] = path.name
    resolved["provenance"]["base_fixture"] = raw["extends"]
    validate_fixture(resolved)
    return resolved
