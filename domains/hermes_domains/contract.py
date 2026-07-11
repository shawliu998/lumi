from __future__ import annotations

from typing import Any, Mapping


class ContractError(ValueError):
    pass


DOMAINS = {"xingce", "shenlun", "interview"}
ADAPTERS = {"xingce_mcq_v1", "shenlun_rubric_v1", "interview_rubric_v1"}
REQUIRED_LOOP_FIELDS = ("skills", "diagnosis", "probe", "teach", "independent_verify")
MODES = {"success", "ambiguous", "offline"}


def _require(mapping: Mapping[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in mapping:
        raise ContractError(f"missing required field: {key}")
    value = mapping[key]
    if not isinstance(value, kind):
        raise ContractError(f"field {key} has invalid type")
    return value


def validate_fixture(fixture: Mapping[str, Any]) -> None:
    """Validate the shared, replayable domain contract.

    Semantic checks intentionally reject any fixture that labels a cheap cause
    candidate as ground truth.  A probe or later independent performance is the
    only allowed path to confirmation in downstream systems.
    """

    if _require(fixture, "schema_version", str) != "hermes.domain-fixture.v1":
        raise ContractError("unsupported schema_version")
    _require(fixture, "fixture_id", str)
    domain = _require(fixture, "domain", str)
    if domain not in DOMAINS:
        raise ContractError(f"unsupported domain: {domain}")
    _require(fixture, "module", str)
    _require(fixture, "path", str)
    mode = _require(fixture, "mode", str)
    if mode not in MODES:
        raise ContractError(f"unsupported mode: {mode}")
    execution = _require(fixture, "execution", dict)
    if mode == "offline":
        if execution.get("connectivity") != "offline":
            raise ContractError("offline fixture must declare offline connectivity")
        if execution.get("cloud_calls_expected") != 0:
            raise ContractError("offline fixture must expect zero cloud calls")
        if execution.get("fallback") != "deterministic_local":
            raise ContractError("offline fixture must use deterministic_local fallback")
    scenario_response = _require(fixture, "scenario_response", str)
    if not scenario_response.strip():
        raise ContractError("scenario_response cannot be empty")
    for field in REQUIRED_LOOP_FIELDS:
        _require(fixture, field, dict if field != "skills" else list)

    task = _require(fixture, "task", dict)
    _require(task, "prompt", str)
    _require(task, "response_mode", str)

    scoring = _require(fixture, "scoring", dict)
    adapter = _require(scoring, "adapter", str)
    if adapter not in ADAPTERS:
        raise ContractError(f"unsupported adapter: {adapter}")
    max_score = _require(scoring, "max_score", (int, float))
    pass_score = _require(scoring, "pass_score", (int, float))
    if max_score <= 0 or not 0 <= pass_score <= max_score:
        raise ContractError("invalid scoring bounds")

    skills = fixture["skills"]
    if not skills:
        raise ContractError("at least one skill is required")
    for skill in skills:
        _require(skill, "skill_id", str)
        weight = _require(skill, "weight", (int, float))
        if not 0 < weight <= 1:
            raise ContractError("skill weight must be in (0, 1]")

    diagnosis = fixture["diagnosis"]
    if diagnosis.get("semantics") != "ranked_unconfirmed_hypotheses":
        raise ContractError("diagnosis must use hypothesis semantics")
    evidence = _require(diagnosis, "evidence_catalog", list)
    evidence_ids = {_require(item, "evidence_id", str) for item in evidence}
    candidates = _require(diagnosis, "candidate_causes", list)
    if not candidates:
        raise ContractError("at least one cause candidate is required")
    for cause in candidates:
        _require(cause, "cause_id", str)
        _require(cause, "label", str)
        prior = _require(cause, "synthetic_prior", (int, float))
        if not 0 <= prior <= 1:
            raise ContractError("synthetic_prior must be in [0, 1]")
        if cause.get("is_ground_truth", False):
            raise ContractError("low-cost candidate cannot be ground truth")
        refs = _require(cause, "evidence_refs", list)
        if not set(refs).issubset(evidence_ids):
            raise ContractError("candidate references unknown evidence")

    for stage in ("probe", "teach", "independent_verify"):
        node = fixture[stage]
        _require(node, "prompt", str)
    verify = fixture["independent_verify"]
    if verify["prompt"].strip() == task["prompt"].strip():
        raise ContractError("independent verification must use a different prompt")
    _require(verify, "pass_condition", dict)

    provenance = _require(fixture, "provenance", dict)
    if provenance.get("content_origin") != "synthetic_original":
        raise ContractError("representative fixtures must be synthetic original content")


def validate_overlay(overlay: Mapping[str, Any]) -> None:
    if overlay.get("schema_version") != "hermes.domain-fixture-overlay.v1":
        raise ContractError("unsupported overlay schema_version")
    _require(overlay, "fixture_id", str)
    _require(overlay, "extends", str)
    _require(overlay, "domain", str)
    _require(overlay, "path", str)
    mode = _require(overlay, "mode", str)
    if mode not in {"ambiguous", "offline"}:
        raise ContractError("overlay mode must be ambiguous or offline")
    _require(overlay, "scenario_response", str)
    execution = _require(overlay, "execution", dict)
    if mode == "offline" and (
        execution.get("connectivity") != "offline"
        or execution.get("cloud_calls_expected") != 0
        or execution.get("fallback") != "deterministic_local"
    ):
        raise ContractError("offline overlay must declare deterministic local fallback and zero cloud calls")
    semantics = _require(overlay, "expected_semantics", dict)
    if semantics.get("cause_status") != "unconfirmed_hypothesis":
        raise ContractError("scenario causes must remain unconfirmed hypotheses")
