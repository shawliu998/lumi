from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .contract import ContractError


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_ROOT = DOMAIN_ROOT / "content" / "xingce" / "p031-data-analysis-v1"
DEFAULT_MANIFEST_PATH = DEFAULT_RELEASE_ROOT / "manifest.json"
DEFAULT_OVERLAY_PATH = DEFAULT_RELEASE_ROOT / "pedagogical-overlay.json"
DEFAULT_PAYLOAD_PATH = DOMAIN_ROOT / "local_content" / "xingce" / "p031-data-analysis-v1.json"

_SOURCE_TEXT_KEYS = {"material_text", "stem_text", "explanation_text", "options", "answer_labels"}
_PUBLIC_SECRET_KEYS = {"answer_labels", "correct_option", "explanation_text", "content_answer_signature"}


class ProductActivityError(ContractError):
    """A local product activity failed a provenance or safety check."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProductActivityError(f"{label} not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductActivityError(f"cannot read valid {label}: {path}") from exc
    if not isinstance(raw, dict):
        raise ProductActivityError(f"{label} must be a JSON object")
    return raw


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(mapping: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    value = mapping.get(key)
    if not isinstance(value, kind):
        raise ProductActivityError(f"field {key} has invalid type or is missing")
    return value


def _assert_no_keys(value: Any, forbidden: set[str], *, context: str) -> None:
    if isinstance(value, Mapping):
        overlap = forbidden.intersection(value)
        if overlap:
            raise ProductActivityError(f"{context} leaks forbidden fields: {sorted(overlap)}")
        for child in value.values():
            _assert_no_keys(child, forbidden, context=context)
    elif isinstance(value, list):
        for child in value:
            _assert_no_keys(child, forbidden, context=context)


def _options(item: Mapping[str, Any]) -> dict[str, str]:
    rows = _require(item, "options", list)
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ProductActivityError("option must be an object")
        label = _require(row, "label", str).strip().upper()
        text = _require(row, "text", str).strip()
        if label in result or not text:
            raise ProductActivityError("options must have unique labels and non-empty text")
        result[label] = text
    if list(result) != ["A", "B", "C", "D"]:
        raise ProductActivityError("product activity requires exactly ordered A-D options")
    return result


def _prompt(item: Mapping[str, Any]) -> str:
    material = _require(item, "material_text", str).strip()
    stem = _require(item, "stem_text", str).strip()
    if not material or not stem:
        raise ProductActivityError("local item material and stem must be non-empty")
    return f"{material}\n\n{stem}"


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != "lumi.xingce-item-bundle.v0":
        raise ProductActivityError("unsupported release manifest schema")
    if manifest.get("status") != "internal_evaluation_only":
        raise ProductActivityError("release must remain internal_evaluation_only")
    rights = _require(manifest, "rights", dict)
    if rights.get("distribution") != "local_only" or rights.get("public_repository_payload") != "metadata_and_checksums_only":
        raise ProductActivityError("release rights must remain metadata-only and local_only")
    _assert_no_keys(manifest, _SOURCE_TEXT_KEYS, context="committed manifest")


def _validate_overlay(overlay: Mapping[str, Any], manifest: Mapping[str, Any], manifest_path: Path) -> None:
    if overlay.get("schema_version") != "lumi.product-activity-overlay.v1":
        raise ProductActivityError("unsupported product activity overlay schema")
    if overlay.get("release_id") != manifest.get("release_id"):
        raise ProductActivityError("overlay release_id does not match manifest")
    if overlay.get("release_manifest_sha256") != _sha256(manifest_path):
        raise ProductActivityError("release manifest checksum mismatch")
    _assert_no_keys(overlay, _SOURCE_TEXT_KEYS, context="committed pedagogical overlay")


def _validate_payload(payload: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != "lumi.xingce-local-payload.v0":
        raise ProductActivityError("unsupported local payload schema")
    if payload.get("release_id") != manifest.get("release_id"):
        raise ProductActivityError("payload release_id does not match manifest")
    if payload.get("distribution") != "local_only":
        raise ProductActivityError("product payload must be local_only")
    expected_source_hash = _require(_require(manifest, "source_bundle", dict), "manifest_sha256", str)
    if payload.get("source_manifest_sha256") != expected_source_hash:
        raise ProductActivityError("source bundle checksum mismatch")


def _index_items(document: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for item in _require(document, "items", list):
        if not isinstance(item, Mapping):
            raise ProductActivityError(f"{label} item must be an object")
        question_id = _require(item, "question_id", str)
        if question_id in result:
            raise ProductActivityError(f"duplicate {label} question_id: {question_id}")
        result[question_id] = item
    return result


def _validate_item_binding(manifest_item: Mapping[str, Any], payload_item: Mapping[str, Any]) -> None:
    question_id = _require(manifest_item, "question_id", str)
    if payload_item.get("question_id") != question_id:
        raise ProductActivityError("payload question_id binding mismatch")
    if payload_item.get("diagnostic_role") != manifest_item.get("diagnostic_role"):
        raise ProductActivityError(f"{question_id} diagnostic role mismatch")
    source = _require(payload_item, "source", dict)
    for field in ("content_signature", "content_answer_signature"):
        if source.get(field) != manifest_item.get(field):
            raise ProductActivityError(f"{question_id} {field} mismatch")
    answer = _require(payload_item, "answer_labels", str).strip().upper()
    if answer not in _options(payload_item):
        raise ProductActivityError(f"{question_id} answer is not one A-D option")
    _require(payload_item, "explanation_text", str)
    _prompt(payload_item)


def _public_item(item: Mapping[str, Any]) -> dict[str, Any]:
    source = _require(item, "source", dict)
    return {
        "question_id": item["question_id"],
        "diagnostic_role": item["diagnostic_role"],
        "material_text": item["material_text"],
        "stem_text": item["stem_text"],
        "options": deepcopy(item["options"]),
        "source": {
            key: source[key]
            for key in ("paper_title", "year", "question_no", "source_site", "source_url", "content_signature")
        },
    }


@dataclass(frozen=True, slots=True)
class ProductActivity:
    activity_id: str
    release_id: str
    first_question_id: str
    transfer_question_id: str
    first_content_signature: str
    transfer_content_signature: str
    _first_public: Mapping[str, Any] = field(repr=False)
    _transfer_public: Mapping[str, Any] = field(repr=False)
    _runtime_fixture: Mapping[str, Any] = field(repr=False)

    def public_view(self) -> dict[str, Any]:
        """Return learner-visible content without answers or explanations."""

        view = {
            "schema_version": "lumi.product-activity-public.v1",
            "activity_id": self.activity_id,
            "release_id": self.release_id,
            "first_answer": deepcopy(dict(self._first_public)),
            "independent_transfer": deepcopy(dict(self._transfer_public)),
        }
        _assert_no_keys(view, _PUBLIC_SECRET_KEYS, context="public activity")
        return view

    def to_runtime_fixture(self) -> dict[str, Any]:
        """Return a private in-memory fixture; callers must not serialize it to clients."""

        fixture = deepcopy(dict(self._runtime_fixture))
        validate_product_activity_runtime(fixture)
        return fixture


def validate_product_activity_runtime(fixture: Mapping[str, Any]) -> None:
    """Validate a real local activity without weakening the synthetic fixture contract."""

    if fixture.get("schema_version") != "hermes.domain-fixture.v1":
        raise ProductActivityError("runtime fixture schema mismatch")
    if fixture.get("domain") != "xingce" or fixture.get("path") != "data_analysis":
        raise ProductActivityError("runtime fixture must be a Xingce data-analysis activity")
    execution = _require(fixture, "execution", dict)
    if execution.get("connectivity") != "local" or execution.get("cloud_calls_expected") != 0:
        raise ProductActivityError("runtime product activity must be local with zero cloud calls")
    provenance = _require(fixture, "provenance", dict)
    if provenance.get("content_origin") != "local_versioned_export" or provenance.get("distribution") != "local_only":
        raise ProductActivityError("runtime provenance must identify a local versioned export")
    first = _require(provenance, "first_item", dict)
    transfer = _require(provenance, "transfer_item", dict)
    if first.get("question_id") == transfer.get("question_id"):
        raise ProductActivityError("first and transfer question_id must differ")
    if first.get("content_signature") == transfer.get("content_signature"):
        raise ProductActivityError("first and transfer content signatures must differ")
    task = _require(fixture, "task", dict)
    verify = _require(fixture, "independent_verify", dict)
    if task.get("item_id") != first.get("question_id") or task.get("content_signature") != first.get("content_signature"):
        raise ProductActivityError("first task is not bound to provenance")
    if verify.get("item_id") != transfer.get("question_id") or verify.get("content_signature") != transfer.get("content_signature"):
        raise ProductActivityError("transfer task is not bound to provenance")
    if verify.get("novelty_status") != "unseen_parallel_item":
        raise ProductActivityError("transfer task must be an unseen_parallel_item")
    if _require(verify, "response_mode", str) != "single_choice":
        raise ProductActivityError("product transfer must use single_choice")
    condition = _require(verify, "pass_condition", dict)
    if condition.get("scorer") != "exact_option_v1":
        raise ProductActivityError("product transfer must use exact_option_v1")
    transfer_options = _require(condition, "options", dict)
    if condition.get("correct_option") not in transfer_options:
        raise ProductActivityError("transfer correct option is absent from options")
    samples = _require(verify, "samples", dict)
    if samples.get("passing_response") != condition.get("correct_option") or samples.get("failing_response") == condition.get("correct_option"):
        raise ProductActivityError("transfer samples do not exercise pass and fail")
    diagnosis = _require(fixture, "diagnosis", dict)
    if diagnosis.get("semantics") != "ranked_unconfirmed_hypotheses":
        raise ProductActivityError("diagnosis must remain ranked unconfirmed hypotheses")
    candidates = _require(diagnosis, "candidate_causes", list)
    cause_ids: set[str] = set()
    evidence_ids = {
        _require(item, "evidence_id", str)
        for item in _require(diagnosis, "evidence_catalog", list)
        if isinstance(item, Mapping)
    }
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or candidate.get("is_ground_truth") is not False:
            raise ProductActivityError("candidate causes must never be ground truth")
        cause_id = _require(candidate, "cause_id", str)
        if cause_id in cause_ids:
            raise ProductActivityError("candidate cause ids must be unique")
        cause_ids.add(cause_id)
        prior = candidate.get("synthetic_prior")
        if not isinstance(prior, (int, float)) or not 0 <= float(prior) <= 1:
            raise ProductActivityError("engineering priors must be in [0, 1]")
        if not set(_require(candidate, "evidence_refs", list)).issubset(evidence_ids):
            raise ProductActivityError("candidate references unknown evidence")
    if not cause_ids:
        raise ProductActivityError("product activity needs candidate hypotheses")
    skills = _require(fixture, "skills", list)
    skill_ids = {_require(skill, "skill_id", str) for skill in skills if isinstance(skill, Mapping)}
    if not skill_ids or fixture.get("kt_target_skill_id") not in skill_ids:
        raise ProductActivityError("kt_target_skill_id must identify an authored skill")
    probe = _require(fixture, "probe", dict)
    if set(_require(probe, "targets", list)) != cause_ids:
        raise ProductActivityError("probe targets must cover every candidate cause")
    assessment = _require(probe, "assessment", dict)
    if assessment.get("schema_version") != "hermes.probe-assessment.v1" or assessment.get("evaluator") != "authored_terms_v1":
        raise ProductActivityError("product probe requires an authored assessment")
    rule_ids = {rule.get("cause_id") for rule in _require(assessment, "rules", list) if isinstance(rule, Mapping)}
    sample_ids = {sample.get("cause_id") for sample in _require(assessment, "cause_samples", list) if isinstance(sample, Mapping)}
    if rule_ids != cause_ids or sample_ids != cause_ids:
        raise ProductActivityError("probe assessment must cover every candidate cause")
    teach = _require(fixture, "teach", dict)
    variant_ids = {variant.get("cause_id") for variant in _require(teach, "variants", list) if isinstance(variant, Mapping)}
    if variant_ids != cause_ids:
        raise ProductActivityError("teaching variants must cover every candidate cause")
    assistance = _require(fixture, "assistance_ladder", dict)
    expected_actions = ("retry", "locate_evidence", "rule_hint", "analogous_example", "worked_step", "full_explanation")
    steps = _require(assistance, "steps", list)
    if tuple(step.get("action") for step in steps if isinstance(step, Mapping)) != expected_actions:
        raise ProductActivityError("assistance ladder must contain six ordered actions")
    for step in steps:
        if not isinstance(step, Mapping) or not set(_require(step, "target_cause_ids", list)).issubset(cause_ids):
            raise ProductActivityError("assistance ladder references an unknown cause")


def load_product_activities(
    payload_path: Path | None = None,
    *,
    manifest_path: Path | None = None,
    overlay_path: Path | None = None,
) -> tuple[ProductActivity, ...]:
    """Compile committed metadata plus ignored local content, failing closed."""

    manifest_path = Path(manifest_path or DEFAULT_MANIFEST_PATH)
    overlay_path = Path(overlay_path or DEFAULT_OVERLAY_PATH)
    payload_path = Path(payload_path or DEFAULT_PAYLOAD_PATH)
    manifest = _read_json(manifest_path, "release manifest")
    overlay = _read_json(overlay_path, "pedagogical overlay")
    payload = _read_json(payload_path, "ignored local payload")
    _validate_manifest(manifest)
    _validate_overlay(overlay, manifest, manifest_path)
    _validate_payload(payload, manifest)
    manifest_items = _index_items(manifest, "manifest")
    payload_items = _index_items(payload, "payload")
    if set(manifest_items) != set(payload_items):
        raise ProductActivityError("manifest and payload question sets differ")
    for question_id, manifest_item in manifest_items.items():
        _validate_item_binding(manifest_item, payload_items[question_id])

    activities: list[ProductActivity] = []
    seen_activity_ids: set[str] = set()
    for authored in _require(overlay, "activities", list):
        if not isinstance(authored, Mapping):
            raise ProductActivityError("activity overlay entry must be an object")
        activity_id = _require(authored, "activity_id", str)
        if activity_id in seen_activity_ids:
            raise ProductActivityError(f"duplicate activity_id: {activity_id}")
        seen_activity_ids.add(activity_id)
        first_id = _require(authored, "first_question_id", str)
        transfer_id = _require(authored, "transfer_question_id", str)
        if first_id == transfer_id:
            raise ProductActivityError("first and transfer question_id must differ")
        if first_id not in payload_items or transfer_id not in payload_items:
            raise ProductActivityError("activity references an unknown question_id")
        first_manifest, transfer_manifest = manifest_items[first_id], manifest_items[transfer_id]
        if first_manifest.get("diagnostic_role") != "first_answer":
            raise ProductActivityError("first question must have first_answer role")
        if transfer_manifest.get("diagnostic_role") != "independent_transfer":
            raise ProductActivityError("transfer question must have independent_transfer role")
        if first_manifest.get("content_signature") == transfer_manifest.get("content_signature"):
            raise ProductActivityError("first and transfer content signatures must differ")
        first_item, transfer_item = payload_items[first_id], payload_items[transfer_id]
        first_options, transfer_options = _options(first_item), _options(transfer_item)
        first_answer = _require(first_item, "answer_labels", str).strip().upper()
        transfer_answer = _require(transfer_item, "answer_labels", str).strip().upper()
        candidates = []
        for candidate in _require(_require(authored, "diagnosis", dict), "candidate_causes", list):
            if not isinstance(candidate, Mapping):
                raise ProductActivityError("cause candidate must be an object")
            candidates.append(
                {
                    "cause_id": _require(candidate, "cause_id", str),
                    "label": _require(candidate, "label", str),
                    "synthetic_prior": float(_require(candidate, "engineering_prior", (int, float))),
                    "evidence_refs": list(_require(candidate, "evidence_refs", list)),
                    "is_ground_truth": False,
                }
            )
        diagnosis = deepcopy(dict(_require(authored, "diagnosis", dict)))
        diagnosis["candidate_causes"] = candidates
        failing_option = next(label for label in first_options if label != first_answer)
        fixture = {
            "schema_version": "hermes.domain-fixture.v1",
            "fixture_id": activity_id,
            "domain": "xingce",
            "path": _require(authored, "path", str),
            "mode": "success",
            "module": _require(authored, "module", str),
            "scenario_response": first_answer,
            "execution": {"connectivity": "local", "cloud_calls_expected": 0, "fallback": "not_needed", "scorer": "deterministic_local"},
            "expected_semantics": {"score": "pass", "cause_status": "unconfirmed_hypothesis"},
            "task": {"prompt": _prompt(first_item), "response_mode": "single_choice", "options": first_options, "item_id": first_id, "content_signature": first_manifest["content_signature"]},
            "skills": [{"skill_id": skill["skill_id"], "weight": skill["weight"]} for skill in _require(authored, "skills", list)],
            "kt_target_skill_id": _require(authored, "skills", list)[0]["skill_id"],
            "scoring": {"adapter": "xingce_mcq_v1", "max_score": 1, "pass_score": 1, "correct_option": first_answer, "distractor_evidence": {}},
            "diagnosis": diagnosis,
            "probe": deepcopy(dict(_require(authored, "probe", dict))),
            "teach": deepcopy(dict(_require(authored, "teach", dict))),
            "assistance_ladder": deepcopy(dict(_require(authored, "assistance_ladder", dict))),
            "independent_verify": {
                "prompt": _prompt(transfer_item),
                "response_mode": "single_choice",
                "item_id": transfer_id,
                "content_signature": transfer_manifest["content_signature"],
                "novelty_status": "unseen_parallel_item",
                "pass_condition": {"scorer": "exact_option_v1", "correct_option": transfer_answer, "options": transfer_options},
                "samples": {"passing_response": transfer_answer, "failing_response": next(label for label in transfer_options if label != transfer_answer)},
            },
            "samples": {"passing_response": first_answer, "failing_response": failing_option},
            "provenance": {
                "content_origin": "local_versioned_export",
                "distribution": "local_only",
                "release_id": manifest["release_id"],
                "release_manifest_sha256": _sha256(manifest_path),
                "source_manifest_sha256": payload["source_manifest_sha256"],
                "first_item": {"question_id": first_id, "content_signature": first_manifest["content_signature"], "content_answer_signature": first_manifest["content_answer_signature"]},
                "transfer_item": {"question_id": transfer_id, "content_signature": transfer_manifest["content_signature"], "content_answer_signature": transfer_manifest["content_answer_signature"]},
                "prior_source": "owned_pedagogical_overlay_engineering_prior_v1",
            },
        }
        validate_product_activity_runtime(fixture)
        activities.append(
            ProductActivity(
                activity_id=activity_id,
                release_id=manifest["release_id"],
                first_question_id=first_id,
                transfer_question_id=transfer_id,
                first_content_signature=first_manifest["content_signature"],
                transfer_content_signature=transfer_manifest["content_signature"],
                _first_public=_public_item(first_item),
                _transfer_public=_public_item(transfer_item),
                _runtime_fixture=fixture,
            )
        )
    if not activities:
        raise ProductActivityError("overlay defines no runnable product activities")
    return tuple(activities)


def load_product_activity(
    payload_path: Path | None = None,
    *,
    manifest_path: Path | None = None,
    overlay_path: Path | None = None,
) -> ProductActivity:
    activities = load_product_activities(
        payload_path,
        manifest_path=manifest_path,
        overlay_path=overlay_path,
    )
    if len(activities) != 1:
        raise ProductActivityError("release contains multiple activities; use load_product_activities")
    return activities[0]
