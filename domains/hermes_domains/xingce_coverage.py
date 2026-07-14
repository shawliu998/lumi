"""Deterministic validation for Lumi's all-Xingce coverage contract.

The matrix deliberately records product obligations rather than copying any
question-bank text.  A row can be counted as released only after a reviewed,
immutable Domain Pack and its type-specific learning loop exist.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping

from .contract import ContractError


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE_MATRIX = DOMAIN_ROOT / "content" / "xingce" / "coverage-matrix.v1.json"
_EXPECTED_MODULE_IDS = frozenset(
    {"verbal", "quantitative", "judgment", "data_analysis", "common_knowledge", "political_theory"}
)
_EXPECTED_LOOP_EVIDENCE = frozenset({"selected_response", "confidence", "elapsed_seconds", "optional_rationale"})
_ALLOWED_FORMS = frozenset({"text_mcq", "numeric_or_mcq", "visual_mcq", "material_mcq"})
_ALLOWED_SCORERS = frozenset({"exact_option_v1", "authored_numeric_v1"})
_ALLOWED_RELEASE_STATES = frozenset({"released", "reviewed_release_ready", "planned"})
_OWNER_WAIVER_BASIS = "owner_acceptance_waiver"
_WAIVED_GATE = "type_by_type_human_local_browser_acceptance"
_NO_EFFECT_EVIDENCE = "unavailable"
_RELEASE_CLAIM_SCOPE = "content_and_mechanism_availability_only"


class XingceCoverageError(ContractError):
    """The no-content all-Xingce coverage declaration is malformed."""


def _require(mapping: Mapping[str, Any], key: str, expected: type | tuple[type, ...]) -> Any:
    if key not in mapping:
        raise XingceCoverageError(f"coverage matrix is missing {key}")
    value = mapping[key]
    if not isinstance(value, expected):
        raise XingceCoverageError(f"coverage matrix field {key} has invalid type")
    return value


def load_coverage_matrix(path: str | Path | None = None) -> dict[str, Any]:
    """Load the configured matrix, resolving the default at call time.

    The bundled macOS runtime relocates immutable domain data beneath its
    PyInstaller resource root.  Looking up the default lazily preserves the
    normal repository path while allowing that explicit, read-only relocation
    without monkey-patching a function default captured at import time.
    """

    selected_path = DEFAULT_COVERAGE_MATRIX if path is None else path
    try:
        document = json.loads(Path(selected_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XingceCoverageError("coverage matrix cannot be loaded") from exc
    if not isinstance(document, dict):
        raise XingceCoverageError("coverage matrix root must be an object")
    validate_coverage_matrix(document)
    return document


def validate_coverage_matrix(document: Mapping[str, Any]) -> None:
    if _require(document, "schema_version", str) != "lumi.xingce-coverage-matrix.v1":
        raise XingceCoverageError("unsupported coverage matrix schema")
    if not _require(document, "taxonomy_version", str).strip():
        raise XingceCoverageError("taxonomy_version must be non-empty")
    if not _require(document, "completion_rule", str).strip():
        raise XingceCoverageError("completion_rule must be non-empty")

    modules = _require(document, "canonical_modules", list)
    module_ids = []
    for module in modules:
        if not isinstance(module, Mapping):
            raise XingceCoverageError("module declarations must be objects")
        module_id = _require(module, "id", str)
        if not module_id.strip() or not _require(module, "label", str).strip():
            raise XingceCoverageError("module id and label must be non-empty")
        aliases = _require(module, "source_aliases", list)
        if not aliases or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise XingceCoverageError("module aliases must be non-empty strings")
        module_ids.append(module_id)
    if set(module_ids) != _EXPECTED_MODULE_IDS or len(module_ids) != len(set(module_ids)):
        raise XingceCoverageError("canonical modules must be the six Xingce modules exactly once")

    loop = _require(document, "required_learning_loop", Mapping)
    for key in (
        "minimum_candidate_hypotheses",
        "minimum_discriminating_probes",
        "minimum_targeted_teaching_assets",
        "minimum_unassisted_transfer_items",
        "minimum_delayed_review_items",
    ):
        value = _require(loop, key, int)
        if value < 1:
            raise XingceCoverageError(f"{key} must be at least one")
    if int(loop["minimum_candidate_hypotheses"]) < 2:
        raise XingceCoverageError("each subtype needs at least two competing candidate hypotheses")
    if set(_require(loop, "required_evidence", list)) != _EXPECTED_LOOP_EVIDENCE:
        raise XingceCoverageError("required evidence must keep the four learner-observation fields")
    if "unassisted" not in _require(loop, "state_commit_rule", str):
        raise XingceCoverageError("state commit rule must keep independent evidence separate")

    subtypes = _require(document, "subtypes", list)
    if not subtypes:
        raise XingceCoverageError("coverage matrix must declare subtypes")
    seen_ids: set[str] = set()
    seen_modules: set[str] = set()
    for subtype in subtypes:
        if not isinstance(subtype, Mapping):
            raise XingceCoverageError("subtype declarations must be objects")
        subtype_id = _require(subtype, "id", str)
        if not subtype_id.startswith("xingce.") or subtype_id in seen_ids:
            raise XingceCoverageError("subtype ids must be unique xingce ids")
        seen_ids.add(subtype_id)
        module_id = _require(subtype, "module_id", str)
        if module_id not in _EXPECTED_MODULE_IDS:
            raise XingceCoverageError("subtype references unknown module")
        seen_modules.add(module_id)
        if not _require(subtype, "label", str).strip():
            raise XingceCoverageError("subtype label must be non-empty")
        raw_subcategories = _require(subtype, "raw_subcategories", list)
        if not raw_subcategories or any(not isinstance(item, str) or not item.strip() for item in raw_subcategories):
            raise XingceCoverageError("subtype needs source-category aliases")
        if _require(subtype, "form", str) not in _ALLOWED_FORMS:
            raise XingceCoverageError("unsupported subtype form")
        if _require(subtype, "scorer", str) not in _ALLOWED_SCORERS:
            raise XingceCoverageError("unsupported deterministic scorer")
        dimensions = _require(subtype, "misconception_dimensions", list)
        if len(dimensions) < 2 or any(not isinstance(item, str) or not item.strip() for item in dimensions):
            raise XingceCoverageError("each subtype needs at least two type-specific error dimensions")
        requirements = _require(subtype, "content_requirements", list)
        if len(requirements) != len(set(requirements)) or any(
            not isinstance(item, str) or not item.strip() for item in requirements
        ):
            raise XingceCoverageError("content requirements must be unique non-empty strings")
        if subtype["form"] == "visual_mcq" and not {"immutable_visual_asset", "asset_checksum", "meaningful_alt_text"}.issubset(requirements):
            raise XingceCoverageError("visual subtype lacks immutable accessible asset requirements")
        if subtype["form"] == "material_mcq":
            has_text_material = {"immutable_material", "material_checksum"}.issubset(requirements)
            has_visual_material = {"immutable_visual_asset", "asset_checksum"}.issubset(requirements)
            if "unit_and_scope_metadata" not in requirements or not (has_text_material or has_visual_material):
                raise XingceCoverageError("material subtype lacks frozen material and scope requirements")
        release = subtype.get("release", {"state": "planned"})
        if not isinstance(release, Mapping) or release.get("state") not in _ALLOWED_RELEASE_STATES:
            raise XingceCoverageError("subtype release state must be released, reviewed_release_ready, or planned")
        if release["state"] in {"released", "reviewed_release_ready"}:
            if not isinstance(release.get("pack_id"), str) or not release["pack_id"].strip():
                raise XingceCoverageError("reviewed subtype must bind a reviewed pack id")
            if not isinstance(release.get("pack_version"), str) or not release["pack_version"].strip():
                raise XingceCoverageError("reviewed subtype must bind a reviewed pack version")
            decision_fields = {
                "acceptance_basis",
                "accepted_at",
                "waived_gate",
                "human_effect_evidence",
                "claim_scope",
            }
            if release["state"] == "released":
                if release.get("acceptance_basis") != _OWNER_WAIVER_BASIS:
                    raise XingceCoverageError("released subtype must record owner_acceptance_waiver")
                try:
                    date.fromisoformat(str(release.get("accepted_at", "")))
                except ValueError as exc:
                    raise XingceCoverageError("released subtype accepted_at must be an ISO date") from exc
                if release.get("waived_gate") != _WAIVED_GATE:
                    raise XingceCoverageError("released subtype must identify the waived human-local gate")
                if release.get("human_effect_evidence") != _NO_EFFECT_EVIDENCE:
                    raise XingceCoverageError("released subtype cannot claim human-effect evidence")
                if release.get("claim_scope") != _RELEASE_CLAIM_SCOPE:
                    raise XingceCoverageError("released subtype must keep the release claim bounded")
            elif decision_fields.intersection(release):
                raise XingceCoverageError("review-ready subtype cannot claim an owner release decision")
        elif "pack_id" in release or "pack_version" in release:
            raise XingceCoverageError("planned subtype cannot pretend it has a released pack")
    if seen_modules != _EXPECTED_MODULE_IDS:
        raise XingceCoverageError("every canonical Xingce module must have a subtype")


def coverage_summary(path: str | Path | None = None) -> dict[str, Any]:
    matrix = load_coverage_matrix(path)
    subtypes = matrix["subtypes"]
    released = [item for item in subtypes if item.get("release", {}).get("state") == "released"]
    reviewed_release_ready = [item for item in subtypes if item.get("release", {}).get("state") == "reviewed_release_ready"]
    planned = [item for item in subtypes if item.get("release", {}).get("state", "planned") == "planned"]
    modules = {
        module["id"]: {
            "label": module["label"],
            "total": sum(item["module_id"] == module["id"] for item in subtypes),
            "released": sum(
                item["module_id"] == module["id"] and item.get("release", {}).get("state") == "released"
                for item in subtypes
            ),
            "reviewed_release_ready": sum(
                item["module_id"] == module["id"] and item.get("release", {}).get("state") == "reviewed_release_ready"
                for item in subtypes
            ),
        }
        for module in matrix["canonical_modules"]
    }
    return {
        "schema_version": "lumi.xingce-coverage-summary.v1",
        "taxonomy_version": matrix["taxonomy_version"],
        "total_subtypes": len(subtypes),
        "released_subtypes": len(released),
        "reviewed_release_ready_subtypes": len(reviewed_release_ready),
        "planned_subtypes": len(planned),
        "content_release_ready": len(released) + len(reviewed_release_ready) == len(subtypes),
        "is_complete": len(released) == len(subtypes),
        "modules": modules,
    }
