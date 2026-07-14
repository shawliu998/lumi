from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


class ContractError(ValueError):
    pass


DOMAINS = {"xingce", "shenlun", "interview"}
DOMAIN_PATHS = {
    "xingce": {"verbal", "judgment", "quantitative", "data_analysis", "common_political_knowledge"},
    "shenlun": {"summary", "comprehensive_analysis", "recommendation", "official_writing", "essay"},
    "interview": {"comprehensive_analysis", "organization", "interpersonal", "emergency"},
}
ADAPTERS = {"xingce_mcq_v1", "shenlun_rubric_v1", "interview_rubric_v1"}
RESPONSE_MODES = {"single_choice", "short_text", "long_text", "spoken_text"}
VERIFICATION_SCORERS = {
    "exact_option_v1",
    "authored_dimensions_v1",
    "authored_slots_v1",
}
REQUIRED_LOOP_FIELDS = (
    "skills",
    "diagnosis",
    "probe",
    "teach",
    "independent_verify",
    "assistance_ladder",
)
MODES = {"success", "ambiguous", "offline"}
ASSISTANCE_ACTIONS = (
    "retry",
    "locate_evidence",
    "rule_hint",
    "analogous_example",
    "worked_step",
    "full_explanation",
)


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
    fixture_path = _require(fixture, "path", str)
    if fixture_path not in DOMAIN_PATHS[domain]:
        raise ContractError("fixture path is not valid for its domain")
    mode = _require(fixture, "mode", str)
    if mode not in MODES:
        raise ContractError(f"unsupported mode: {mode}")
    execution = _require(fixture, "execution", dict)
    if execution.get("scorer") != "deterministic_local":
        raise ContractError("fixture scorer must be deterministic_local")
    cloud_calls = execution.get("cloud_calls_expected")
    if isinstance(cloud_calls, bool) or not isinstance(cloud_calls, int) or cloud_calls < 0:
        raise ContractError("cloud_calls_expected must be a non-negative integer")
    if execution.get("provider_invoked", False) is not False:
        raise ContractError("fixture cannot claim that a provider was invoked")
    if mode == "offline":
        if execution.get("connectivity") != "offline":
            raise ContractError("offline fixture must declare offline connectivity")
        if execution.get("cloud_calls_expected") != 0:
            raise ContractError("offline fixture must expect zero cloud calls")
        if execution.get("fallback") != "deterministic_local":
            raise ContractError("offline fixture must use deterministic_local fallback")
        if execution.get("provider_invoked") is not False:
            raise ContractError("offline fixture must explicitly declare provider_invoked false")
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
    evidence_list = [_require(item, "evidence_id", str) for item in evidence]
    if any(not item.strip() for item in evidence_list) or len(evidence_list) != len(set(evidence_list)):
        raise ContractError("evidence ids must be non-empty and unique")
    evidence_ids = set(evidence_list)
    candidates = _require(diagnosis, "candidate_causes", list)
    if not candidates:
        raise ContractError("at least one cause candidate is required")
    candidate_ids = [_require(cause, "cause_id", str) for cause in candidates]
    if any(not item.strip() for item in candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
        raise ContractError("cause ids must be non-empty and unique")
    for cause in candidates:
        _require(cause, "label", str)
        prior = _require(cause, "synthetic_prior", (int, float))
        if not 0 <= prior <= 1:
            raise ContractError("synthetic_prior must be in [0, 1]")
        if cause.get("is_ground_truth", False):
            raise ContractError("low-cost candidate cannot be ground truth")
        refs = _require(cause, "evidence_refs", list)
        if not set(refs).issubset(evidence_ids):
            raise ContractError("candidate references unknown evidence")

    assistance = _require(fixture, "assistance_ladder", dict)
    if assistance.get("schema_version") != "hermes.assistance-content.v1":
        raise ContractError("unsupported assistance content schema")
    content_version = _require(assistance, "content_version", str)
    if not content_version.strip():
        raise ContractError("assistance content_version cannot be empty")
    steps = _require(assistance, "steps", list)
    if tuple(step.get("action") for step in steps) != ASSISTANCE_ACTIONS:
        raise ContractError("assistance ladder must contain the six ordered actions")
    cause_ids = {str(cause["cause_id"]) for cause in candidates}
    for step in steps:
        if not _require(step, "title", str).strip() or not _require(step, "content", str).strip():
            raise ContractError("assistance title and content cannot be empty")
        targets = _require(step, "target_cause_ids", list)
        if not targets:
            raise ContractError("assistance step must target at least one authored cause")
        if any(not isinstance(target, str) or not target.strip() for target in targets):
            raise ContractError("assistance targets must be non-empty strings")
        if len(targets) != len(set(targets)):
            raise ContractError("assistance targets must be unique within a step")
        if not set(targets).issubset(cause_ids):
            raise ContractError("assistance step references unknown cause")

    for stage in ("probe", "teach", "independent_verify"):
        node = fixture[stage]
        _require(node, "prompt", str)
    probe_targets = _require(fixture["probe"], "targets", list)
    if not probe_targets or any(not isinstance(target, str) or not target.strip() for target in probe_targets):
        raise ContractError("probe targets must be non-empty cause ids")
    if len(probe_targets) != len(set(probe_targets)):
        raise ContractError("probe targets must be unique")
    if not set(probe_targets).issubset(cause_ids):
        raise ContractError("probe references unknown cause")
    if set(probe_targets) != cause_ids:
        raise ContractError("probe targets must cover every authored cause")
    probe_assessment = _require(fixture["probe"], "assessment", dict)
    if probe_assessment.get("schema_version") != "hermes.probe-assessment.v1":
        raise ContractError("unsupported probe assessment schema")
    if probe_assessment is not None:
        evaluator = probe_assessment.get("evaluator", "authored_terms_v1")
        if evaluator == "growth_formula_v1":
            cause_map = _require(probe_assessment, "cause_map", dict)
            if set(cause_map) != {"denominator", "increment", "ratio"}:
                raise ContractError("growth formula assessment requires three named causes")
            mapped = list(cause_map.values())
            if any(not isinstance(item, str) or not item.strip() for item in mapped):
                raise ContractError("growth formula assessment causes must be non-empty strings")
            if len(mapped) != len(set(mapped)) or not set(mapped).issubset(set(probe_targets)):
                raise ContractError("growth formula assessment causes must be unique probe targets")
        elif evaluator == "authored_terms_v1":
            rules = _require(probe_assessment, "rules", list)
            rule_ids = [_require(rule, "cause_id", str) for rule in rules]
            if len(rule_ids) != len(set(rule_ids)):
                raise ContractError("probe assessment cause rules must be unique")
            if set(rule_ids) != set(probe_targets):
                raise ContractError("probe assessment rules must cover every probe target")
            for rule in rules:
                if rule.get("cause_id") not in set(probe_targets):
                    raise ContractError("probe assessment references a non-target cause")
                if not any(key in rule for key in ("support_if", "refute_if")):
                    raise ContractError("probe assessment rule must support or refute")
                for key in ("support_if", "refute_if"):
                    condition = rule.get(key)
                    if condition is None:
                        continue
                    if not isinstance(condition, dict):
                        raise ContractError("probe assessment condition must be an object")
                    if not any(condition.get(name) for name in ("all_terms", "any_terms", "none_terms")):
                        raise ContractError("probe assessment condition must contain authored terms")
                    all_terms = condition.get("all_terms", [])
                    if len(all_terms) < 2:
                        raise ContractError("probe assessment conditions require two authored evidence phrases")
                    for name in ("all_terms", "any_terms", "none_terms"):
                        terms = condition.get(name, [])
                        if not isinstance(terms, list) or any(
                            not isinstance(term, str) or not term.strip() for term in terms
                        ):
                            raise ContractError("probe assessment terms must be non-empty strings")
                        if any(len(term.strip()) < 3 for term in terms):
                            raise ContractError("probe assessment evidence phrases are too short")
                        if len(terms) != len(set(terms)):
                            raise ContractError("probe assessment terms must be unique")
        else:
            raise ContractError("unsupported probe assessment evaluator")
        cause_samples = _require(probe_assessment, "cause_samples", list)
        sample_ids = [_require(sample, "cause_id", str) for sample in cause_samples]
        if len(sample_ids) != len(set(sample_ids)) or set(sample_ids) != set(probe_targets):
            raise ContractError("probe assessment samples must uniquely cover every probe target")
        for sample in cause_samples:
            responses = [
                _require(sample, key, str)
                for key in ("supporting_response", "refuting_response", "ambiguous_response")
            ]
            if any(not response.strip() for response in responses) or len(set(responses)) != 3:
                raise ContractError("probe assessment polarity samples must be non-empty and distinct")
    variants = _require(fixture["teach"], "variants", list)
    variant_ids = [_require(variant, "cause_id", str) for variant in variants]
    if len(variant_ids) != len(set(variant_ids)) or set(variant_ids) != cause_ids:
        raise ContractError("teaching variants must uniquely cover every authored cause")
    for variant in variants:
        if not _require(variant, "prompt", str).strip() or not _require(variant, "strategy", str).strip():
            raise ContractError("teaching variant prompt and strategy cannot be empty")
    verify = fixture["independent_verify"]
    if verify["prompt"].strip() == task["prompt"].strip():
        raise ContractError("independent verification must use a different prompt")
    response_mode = _require(verify, "response_mode", str)
    if response_mode not in RESPONSE_MODES:
        raise ContractError("unsupported independent verification response_mode")
    condition = _require(verify, "pass_condition", dict)
    _validate_verification_condition(condition, response_mode)
    verification_samples = _require(verify, "samples", dict)
    passing = _require(verification_samples, "passing_response", str)
    failing = _require(verification_samples, "failing_response", str)
    if not passing.strip() or not failing.strip() or passing.strip() == failing.strip():
        raise ContractError("verification samples must be non-empty and distinct")
    initial_samples = _require(fixture, "samples", dict)
    initial_passing = _require(initial_samples, "passing_response", str)
    initial_failing = _require(initial_samples, "failing_response", str)
    if not initial_passing.strip() or not initial_failing.strip():
        raise ContractError("attempt samples must be non-empty")
    if adapter != "xingce_mcq_v1":
        initial_adversarial = _require(initial_samples, "adversarial_negation_response", str)
        verification_adversarial = _require(
            verification_samples, "adversarial_negation_response", str
        )
        if not initial_adversarial.strip() or not verification_adversarial.strip():
            raise ContractError("text rubrics require adversarial negation samples")

    provenance = _require(fixture, "provenance", dict)
    if provenance.get("content_origin") != "synthetic_original":
        raise ContractError("representative fixtures must be synthetic original content")


def validate_overlay(overlay: Mapping[str, Any]) -> None:
    if overlay.get("schema_version") != "hermes.domain-fixture-overlay.v1":
        raise ContractError("unsupported overlay schema_version")
    _require(overlay, "fixture_id", str)
    extends = _require(overlay, "extends", str)
    if Path(extends).name != extends or not extends.endswith(".json"):
        raise ContractError("overlay extends must be one JSON basename in the same directory")
    domain = _require(overlay, "domain", str)
    if domain not in DOMAINS:
        raise ContractError("unsupported overlay domain")
    overlay_path = _require(overlay, "path", str)
    if overlay_path not in DOMAIN_PATHS[domain]:
        raise ContractError("overlay path is not valid for its domain")
    mode = _require(overlay, "mode", str)
    if mode not in {"ambiguous", "offline"}:
        raise ContractError("overlay mode must be ambiguous or offline")
    _require(overlay, "scenario_response", str)
    execution = _require(overlay, "execution", dict)
    if execution.get("scorer") != "deterministic_local":
        raise ContractError("overlay scorer must be deterministic_local")
    if execution.get("cloud_calls_expected") != 0:
        raise ContractError("overlay must expect zero cloud calls")
    if execution.get("provider_invoked", False) is not False:
        raise ContractError("overlay must not invoke a provider")
    if mode == "offline" and (
        execution.get("connectivity") != "offline"
        or execution.get("cloud_calls_expected") != 0
        or execution.get("provider_invoked") is not False
        or execution.get("fallback") != "deterministic_local"
    ):
        raise ContractError("offline overlay must declare no provider, deterministic local fallback, and zero cloud calls")
    semantics = _require(overlay, "expected_semantics", dict)
    if semantics.get("cause_status") != "unconfirmed_hypothesis":
        raise ContractError("scenario causes must remain unconfirmed hypotheses")
    if mode == "ambiguous":
        if (
            execution.get("connectivity") != "local"
            or execution.get("fallback") != "not_needed"
            or semantics.get("score") != "fail"
            or semantics.get("agent_action") != "request_discriminating_probe"
            or not isinstance(semantics.get("minimum_candidates"), int)
            or semantics.get("minimum_candidates") < 2
        ):
            raise ContractError("ambiguous overlay semantics must request a discriminating local probe")
    elif (
        semantics.get("score") != "deterministic_local"
        or semantics.get("agent_action") != "local_probe_then_defer_generative_feedback"
    ):
        raise ContractError("offline overlay semantics must declare deterministic local handling")


def _validate_verification_condition(condition: Mapping[str, Any], response_mode: str) -> None:
    scorer = _require(condition, "scorer", str)
    if scorer not in VERIFICATION_SCORERS:
        raise ContractError("unsupported independent verification scorer")
    if scorer == "exact_option_v1":
        if response_mode != "single_choice":
            raise ContractError("exact option verification requires single_choice response_mode")
        correct = _require(condition, "correct_option", str)
        options = _require(condition, "options", dict)
        if len(options) < 2 or correct not in options:
            raise ContractError("verification options must contain the correct option")
        if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip() for key, value in options.items()):
            raise ContractError("verification options must be non-empty strings")
        return
    if response_mode == "single_choice":
        raise ContractError("single_choice verification requires exact_option_v1")
    if scorer == "authored_dimensions_v1":
        _validate_authored_groups(condition, "required_dimensions", "dimension_id", "minimum_dimensions")
        return
    _validate_authored_groups(condition, "required_slots", "slot_id", "minimum_slots")


def _validate_authored_groups(
    condition: Mapping[str, Any], list_key: str, id_key: str, minimum_key: str
) -> None:
    groups = _require(condition, list_key, list)
    if not groups:
        raise ContractError("verification rubric must contain authored groups")
    ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ContractError("verification rubric groups must be objects")
        group_id = _require(group, id_key, str)
        aliases = _require(group, "aliases", list)
        if not group_id.strip() or not aliases:
            raise ContractError("verification rubric group ids and aliases cannot be empty")
        if any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContractError("verification aliases must be non-empty strings")
        if len(aliases) != len(set(aliases)):
            raise ContractError("verification aliases must be unique within a group")
        ids.append(group_id)
    if len(ids) != len(set(ids)):
        raise ContractError("verification rubric group ids must be unique")
    minimum = _require(condition, minimum_key, int)
    if isinstance(minimum, bool) or not 1 <= minimum <= len(groups):
        raise ContractError("verification rubric threshold is out of bounds")
