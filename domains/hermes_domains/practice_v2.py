from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence


PRACTICE_MANIFEST_SCHEMA_VERSION = "hermes.practice-manifest.v2"
PRACTICE_PACKAGE_SCHEMA_VERSION = "hermes.practice-package.v2"
QUESTION_VERSION_SCHEMA_VERSION = "hermes.question-version.v2"
PUBLIC_QUESTION_SCHEMA_VERSION = "hermes.question-public.v2"
DEFAULT_PRACTICE_ROOT = Path(__file__).resolve().parents[1] / "practice_v2"

TARGET_DIAGNOSTIC_UNIT_ID = "xingce.data-analysis.direct-growth-rate"
FILLER_DIAGNOSTIC_UNIT_ID = "xingce.data-analysis.mixed-spacing"

CURRENT_DENOMINATOR_SIGNATURE = "growth.current-as-denominator"
RATIO_WITHOUT_MINUS_ONE_SIGNATURE = "growth.ratio-without-minus-one"
DROPPED_NEGATIVE_SIGNATURE = "growth.decrease-sign-dropped"
REQUIRED_ERROR_SIGNATURES = {
    CURRENT_DENOMINATOR_SIGNATURE,
    RATIO_WITHOUT_MINUS_ONE_SIGNATURE,
    DROPPED_NEGATIVE_SIGNATURE,
}

_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PracticeValidationError(ValueError):
    """A practice package is malformed, unreviewed, unsafe, or inconsistent."""


def _nonempty(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PracticeValidationError(f"{context} must be a non-empty string")
    return value


def _identifier(value: Any, context: str) -> str:
    identifier = _nonempty(value, context)
    if not _IDENTIFIER.fullmatch(identifier):
        raise PracticeValidationError(f"{context} must be a lowercase stable identifier")
    return identifier


def _exact_object(
    value: Any,
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PracticeValidationError(f"{context} must be an object")
    keys = set(value)
    missing = required - keys
    if missing:
        raise PracticeValidationError(f"{context} missing required fields: {sorted(missing)}")
    unknown = keys - required - (optional or set())
    if unknown:
        raise PracticeValidationError(f"{context} has unknown fields: {sorted(unknown)}")
    return value


def _string_list(value: Any, context: str, *, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise PracticeValidationError(f"{context} must contain at least {minimum} item(s)")
    result = [_nonempty(item, f"{context} item") for item in value]
    if len(result) != len(set(result)):
        raise PracticeValidationError(f"{context} must not contain duplicates")
    return result


def _positive_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PracticeValidationError(f"{context} must be a positive integer")
    return value


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise PracticeValidationError(f"{context} must be a boolean")
    return value


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PracticeValidationError(f"{context} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise PracticeValidationError(f"{context} must be finite")
    return number


def _normalise_prompt(value: str) -> str:
    return "".join(value.split()).casefold()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PracticeValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PracticeValidationError(f"non-finite JSON value: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PracticeValidationError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PracticeValidationError(f"{path.name} must contain a JSON object")
    return parsed


def _validate_diagnostic_unit(value: Any) -> Mapping[str, Any]:
    unit = _exact_object(
        value,
        required={
            "diagnostic_unit_id",
            "name",
            "ability_boundary",
            "excluded_skills",
            "expected_core_question_count",
            "expected_filler_question_count",
            "minimum_independent_evidence_families",
            "minimum_delayed_validation_questions",
        },
        context="diagnostic_unit",
    )
    if _identifier(unit["diagnostic_unit_id"], "diagnostic_unit.diagnostic_unit_id") != TARGET_DIAGNOSTIC_UNIT_ID:
        raise PracticeValidationError("this package must target the direct growth-rate diagnostic unit")
    _nonempty(unit["name"], "diagnostic_unit.name")
    _string_list(unit["ability_boundary"], "diagnostic_unit.ability_boundary", minimum=3)
    _string_list(unit["excluded_skills"], "diagnostic_unit.excluded_skills", minimum=3)
    if _positive_int(unit["expected_core_question_count"], "expected_core_question_count") != 18:
        raise PracticeValidationError("growth-rate v2 requires exactly 18 core questions")
    if _positive_int(unit["expected_filler_question_count"], "expected_filler_question_count") != 8:
        raise PracticeValidationError("growth-rate v2 requires exactly 8 filler questions")
    if _positive_int(unit["minimum_independent_evidence_families"], "minimum_independent_evidence_families") < 6:
        raise PracticeValidationError("at least six independent evidence families are required")
    if _positive_int(unit["minimum_delayed_validation_questions"], "minimum_delayed_validation_questions") < 4:
        raise PracticeValidationError("at least four delayed-validation questions are required")
    return unit


def _validate_content_source(value: Any, index: int) -> str:
    source = _exact_object(
        value,
        required={
            "content_source_id",
            "content_origin",
            "reference_title",
            "reference_page_range",
            "source_use",
            "rights_status",
            "authorization_status",
            "source_text_included",
            "author",
            "authored_at",
            "review_status",
        },
        context=f"content_sources[{index}]",
    )
    source_id = _identifier(source["content_source_id"], f"content_sources[{index}].content_source_id")
    if source["content_origin"] != "synthetic_original":
        raise PracticeValidationError("practice content must be synthetic original")
    if source["reference_title"] != "三色笔记-行测理.pdf":
        raise PracticeValidationError("the concept reference title must be explicit")
    page_range = _exact_object(
        source["reference_page_range"],
        required={"pdf_start", "pdf_end", "printed_start", "printed_end"},
        context=f"content_sources[{index}].reference_page_range",
    )
    expected_pages = {"pdf_start": 3, "pdf_end": 5, "printed_start": 1, "printed_end": 3}
    if dict(page_range) != expected_pages:
        raise PracticeValidationError("growth-rate concept reference must be PDF 3-5 / printed 1-3")
    if source["source_use"] != "concept_structure_reference":
        raise PracticeValidationError("reference use must be limited to concept structure")
    if source["rights_status"] != "rights_review_required":
        raise PracticeValidationError("reference rights status must remain review-required")
    if source["authorization_status"] != "internal_mvp_only":
        raise PracticeValidationError("content authorization must be limited to the internal MVP")
    if source["source_text_included"] is not False:
        raise PracticeValidationError("source text must not be included")
    _nonempty(source["author"], f"content_sources[{index}].author")
    authored_at = _nonempty(source["authored_at"], f"content_sources[{index}].authored_at")
    if not _DATE.fullmatch(authored_at):
        raise PracticeValidationError("content source authored_at must use YYYY-MM-DD")
    if source["review_status"] != "human_review_required_before_external_release":
        raise PracticeValidationError("external release must remain gated by human review")
    return source_id


def _validate_error_signature(value: Any, index: int) -> str:
    signature = _exact_object(
        value,
        required={"signature_id", "label", "observable_rule", "semantics"},
        context=f"error_signatures[{index}]",
    )
    signature_id = _identifier(signature["signature_id"], f"error_signatures[{index}].signature_id")
    _nonempty(signature["label"], f"error_signatures[{index}].label")
    _nonempty(signature["observable_rule"], f"error_signatures[{index}].observable_rule")
    if signature["semantics"] != "observed_option_pattern_not_mental_cause":
        raise PracticeValidationError("error signatures must remain observed patterns, not mental causes")
    return signature_id


def _validate_cause_candidate(value: Any, index: int) -> str:
    cause = _exact_object(
        value,
        required={"cause_id", "label", "semantics"},
        context=f"cause_candidates[{index}]",
    )
    cause_id = _identifier(cause["cause_id"], f"cause_candidates[{index}].cause_id")
    _nonempty(cause["label"], f"cause_candidates[{index}].label")
    if cause["semantics"] != "actionable_withdrawable_hypothesis_not_ground_truth":
        raise PracticeValidationError("cause candidates must remain withdrawable hypotheses")
    return cause_id


def _validate_interventions(
    value: Any,
    *,
    signature_ids: set[str],
    cause_ids: set[str],
) -> None:
    interventions = _exact_object(
        value,
        required={"microtutorials", "probes"},
        context="interventions",
    )
    tutorials = interventions["microtutorials"]
    probes = interventions["probes"]
    if not isinstance(tutorials, list) or len(tutorials) < 3:
        raise PracticeValidationError("at least three reviewed-shape microtutorial assets are required")
    if not isinstance(probes, list) or not probes:
        raise PracticeValidationError("at least one optional structured probe asset is required")

    asset_ids: list[str] = []
    covered_signatures: set[str] = set()
    covered_causes: set[str] = set()
    for index, raw_tutorial in enumerate(tutorials):
        tutorial = _exact_object(
            raw_tutorial,
            required={
                "schema_version",
                "asset_id",
                "version",
                "kind",
                "target_signature_ids",
                "target_cause_id",
                "title",
                "estimated_seconds",
                "principle",
                "worked_contrast",
                "return_action",
                "authorization_status",
                "review_status",
            },
            context=f"interventions.microtutorials[{index}]",
        )
        if tutorial["schema_version"] != "hermes.intervention-asset.v2":
            raise PracticeValidationError("unsupported intervention asset schema_version")
        asset_ids.append(_identifier(tutorial["asset_id"], f"microtutorials[{index}].asset_id"))
        version = _nonempty(tutorial["version"], f"microtutorials[{index}].version")
        if not _SEMVER.fullmatch(version):
            raise PracticeValidationError("microtutorial version must be semantic x.y.z")
        if tutorial["kind"] != "microtutorial":
            raise PracticeValidationError("microtutorial asset kind is invalid")
        targets = set(_string_list(tutorial["target_signature_ids"], "microtutorial target_signature_ids"))
        if not targets.issubset(signature_ids):
            raise PracticeValidationError("microtutorial references an unknown error signature")
        cause_id = tutorial["target_cause_id"]
        if cause_id not in cause_ids:
            raise PracticeValidationError("microtutorial references an unknown cause candidate")
        seconds = _positive_int(tutorial["estimated_seconds"], "microtutorial estimated_seconds")
        if not 30 <= seconds <= 60:
            raise PracticeValidationError("microtutorials must fit the 30-60 second intervention budget")
        for field in ("title", "principle", "worked_contrast", "return_action"):
            _nonempty(tutorial[field], f"microtutorials[{index}].{field}")
        if tutorial["authorization_status"] != "internal_mvp_only":
            raise PracticeValidationError("microtutorial authorization must be internal-MVP-only")
        if tutorial["review_status"] != "human_review_required":
            raise PracticeValidationError("microtutorial assets must retain the human-review-required marker")
        covered_signatures.update(targets)
        covered_causes.add(cause_id)

    for index, raw_probe in enumerate(probes):
        probe = _exact_object(
            raw_probe,
            required={
                "schema_version",
                "asset_id",
                "version",
                "kind",
                "trigger_signature_ids",
                "candidate_cause_ids",
                "title",
                "prompt",
                "response_mode",
                "options",
                "option_results",
                "optional",
                "uses_session_slot",
                "authorization_status",
                "review_status",
            },
            context=f"interventions.probes[{index}]",
        )
        if probe["schema_version"] != "hermes.intervention-asset.v2":
            raise PracticeValidationError("unsupported probe asset schema_version")
        asset_ids.append(_identifier(probe["asset_id"], f"probes[{index}].asset_id"))
        version = _nonempty(probe["version"], f"probes[{index}].version")
        if not _SEMVER.fullmatch(version):
            raise PracticeValidationError("probe version must be semantic x.y.z")
        if probe["kind"] != "structured_probe":
            raise PracticeValidationError("probe asset kind is invalid")
        triggers = set(_string_list(probe["trigger_signature_ids"], "probe trigger_signature_ids"))
        candidates = set(_string_list(probe["candidate_cause_ids"], "probe candidate_cause_ids", minimum=2))
        if not triggers.issubset(signature_ids) or not candidates.issubset(cause_ids):
            raise PracticeValidationError("probe references an unknown signature or cause")
        _nonempty(probe["title"], f"probes[{index}].title")
        _nonempty(probe["prompt"], f"probes[{index}].prompt")
        if probe["response_mode"] != "single_choice":
            raise PracticeValidationError("structured probes must use single_choice")
        options = probe["options"]
        results = probe["option_results"]
        if not isinstance(options, Mapping) or len(options) < 3:
            raise PracticeValidationError("structured probes need at least three options")
        for option_id, text in options.items():
            _identifier(option_id.lower(), "probe option ID")
            _nonempty(text, f"probe option {option_id}")
        if not isinstance(results, Mapping) or set(results) != set(options):
            raise PracticeValidationError("every probe option needs exactly one result mapping")
        supported: set[str] = set()
        for option_id, raw_result in results.items():
            result = _exact_object(
                raw_result,
                required={"supported_cause_id", "observation"},
                context=f"probe option_results.{option_id}",
            )
            cause_id = result["supported_cause_id"]
            if cause_id is not None:
                if cause_id not in candidates:
                    raise PracticeValidationError("probe option supports a cause outside its candidate set")
                supported.add(cause_id)
            _nonempty(result["observation"], f"probe option_results.{option_id}.observation")
        if len(supported) < 2:
            raise PracticeValidationError("a disambiguation probe must distinguish at least two causes")
        if probe["optional"] is not True or probe["uses_session_slot"] is not True:
            raise PracticeValidationError("a probe must be optional and consume one fixed session slot")
        if probe["authorization_status"] != "internal_mvp_only":
            raise PracticeValidationError("probe authorization must be internal-MVP-only")
        if probe["review_status"] != "human_review_required":
            raise PracticeValidationError("probe assets must retain the human-review-required marker")

    if len(asset_ids) != len(set(asset_ids)):
        raise PracticeValidationError("intervention asset IDs must be unique")
    if covered_signatures != signature_ids:
        raise PracticeValidationError("every error signature needs a versioned microtutorial")
    if not cause_ids.issubset(covered_causes):
        raise PracticeValidationError("every declared cause needs a controlled microtutorial")


def _validate_material_group(value: Any, index: int) -> str:
    group = _exact_object(
        value,
        required={"material_group_id", "label", "kind", "independence_policy"},
        context=f"material_groups[{index}]",
    )
    group_id = _identifier(group["material_group_id"], f"material_groups[{index}].material_group_id")
    _nonempty(group["label"], f"material_groups[{index}].label")
    if group["kind"] not in {"standalone_synthetic_record", "shared_synthetic_material"}:
        raise PracticeValidationError("material group kind is unsupported")
    if group["independence_policy"] != "same_group_not_independent":
        raise PracticeValidationError("material groups must block same-group independence")
    return group_id


def _validate_evidence_family(value: Any, index: int) -> str:
    family = _exact_object(
        value,
        required={"evidence_family_id", "label", "construction_note", "independence_policy"},
        context=f"evidence_families[{index}]",
    )
    family_id = _identifier(family["evidence_family_id"], f"evidence_families[{index}].evidence_family_id")
    _nonempty(family["label"], f"evidence_families[{index}].label")
    _nonempty(family["construction_note"], f"evidence_families[{index}].construction_note")
    if family["independence_policy"] != "same_family_not_independent":
        raise PracticeValidationError("evidence families must block same-family independence")
    return family_id


def _validate_roles(value: Any, *, filler: bool, context: str) -> Mapping[str, bool]:
    roles = _exact_object(
        value,
        required={
            "regular_practice",
            "near_transfer",
            "delayed_validation",
            "reserved_unexposed",
            "filler",
            "evidence_eligible",
        },
        context=context,
    )
    for key in roles:
        _boolean(roles[key], f"{context}.{key}")
    if roles["filler"] is not filler:
        raise PracticeValidationError(f"{context}.filler conflicts with diagnostic unit")
    if filler:
        if not roles["regular_practice"] or roles["evidence_eligible"]:
            raise PracticeValidationError("fillers must be regular spacing items excluded from evidence")
        if roles["near_transfer"] or roles["delayed_validation"] or roles["reserved_unexposed"]:
            raise PracticeValidationError("fillers cannot be transfer or reserved validation items")
    else:
        if not roles["evidence_eligible"]:
            raise PracticeValidationError("core growth-rate questions must be evidence eligible")
        if not (roles["regular_practice"] or roles["near_transfer"] or roles["delayed_validation"]):
            raise PracticeValidationError("core questions need at least one eligible learning role")
        if roles["delayed_validation"]:
            if not roles["reserved_unexposed"]:
                raise PracticeValidationError("delayed validation must be reserved unexposed")
            if roles["regular_practice"] or roles["near_transfer"]:
                raise PracticeValidationError("reserved delayed items cannot enter ordinary or near-transfer practice")
        elif roles["reserved_unexposed"]:
            raise PracticeValidationError("only delayed validation items may be reserved")
    return roles


def _validate_question(
    value: Any,
    *,
    index: int,
    package: Mapping[str, Any],
    source_ids: set[str],
    material_ids: set[str],
    family_ids: set[str],
    signature_ids: set[str],
    cause_ids: set[str],
) -> Mapping[str, Any]:
    question = _exact_object(
        value,
        required={
            "schema_version",
            "question_id",
            "version",
            "status",
            "domain",
            "user_facing_type",
            "diagnostic_unit_id",
            "content_source_id",
            "material_group_id",
            "evidence_family_id",
            "target_change_direction",
            "prompt",
            "response_mode",
            "options",
            "scoring",
            "role_eligibility",
            "feedback",
        },
        optional={"calculation"},
        context=f"questions[{index}]",
    )
    if question["schema_version"] != QUESTION_VERSION_SCHEMA_VERSION:
        raise PracticeValidationError("unsupported question schema_version")
    _identifier(question["question_id"], f"questions[{index}].question_id")
    version = _nonempty(question["version"], f"questions[{index}].version")
    if not _SEMVER.fullmatch(version):
        raise PracticeValidationError("question version must be semantic x.y.z")
    if question["status"] != "published_internal":
        raise PracticeValidationError("only internally published question versions may load")
    if question["domain"] != package["domain"] or question["user_facing_type"] != package["user_facing_type"]:
        raise PracticeValidationError("question domain/type must match its package")

    diagnostic_unit_id = _identifier(question["diagnostic_unit_id"], f"questions[{index}].diagnostic_unit_id")
    filler = diagnostic_unit_id == FILLER_DIAGNOSTIC_UNIT_ID
    if not filler and diagnostic_unit_id != TARGET_DIAGNOSTIC_UNIT_ID:
        raise PracticeValidationError("question references an unsupported diagnostic unit")
    if question["content_source_id"] not in source_ids:
        raise PracticeValidationError("question references an unknown content source")
    if question["material_group_id"] not in material_ids:
        raise PracticeValidationError("question references an unknown material group")
    if question["evidence_family_id"] not in family_ids:
        raise PracticeValidationError("question references an unknown evidence family")

    direction = question["target_change_direction"]
    if filler:
        if direction != "not_applicable":
            raise PracticeValidationError("filler direction must be not_applicable")
    elif direction not in {"increase", "decrease"}:
        raise PracticeValidationError("core question direction must be increase or decrease")

    _nonempty(question["prompt"], f"questions[{index}].prompt")
    if question["response_mode"] != "single_choice":
        raise PracticeValidationError("practice v2 currently supports single-choice questions only")
    options = question["options"]
    if not isinstance(options, Mapping) or set(options) != {"A", "B", "C", "D"}:
        raise PracticeValidationError("question options must contain exactly A, B, C, and D")
    option_texts = [_nonempty(options[key], f"questions[{index}].options.{key}") for key in "ABCD"]
    if len(set(option_texts)) != 4:
        raise PracticeValidationError("question option texts must be unique")

    scoring = _exact_object(
        question["scoring"],
        required={"adapter", "max_score", "correct_option", "canonical_answer", "error_option_mappings"},
        context=f"questions[{index}].scoring",
    )
    if scoring["adapter"] != "xingce_mcq_v2" or scoring["max_score"] != 1:
        raise PracticeValidationError("question scoring must use one-point xingce_mcq_v2")
    correct = scoring["correct_option"]
    if correct not in options:
        raise PracticeValidationError("correct_option must reference a question option")
    if scoring["canonical_answer"] != options[correct]:
        raise PracticeValidationError("canonical_answer must equal the correct option text")
    mappings = scoring["error_option_mappings"]
    expected_wrong = set(options) - {correct}
    if not isinstance(mappings, Mapping) or set(mappings) != expected_wrong:
        raise PracticeValidationError("every and only wrong option must have an error mapping")

    mapped_signatures: set[str] = set()
    for option_id, raw_mapping in mappings.items():
        mapping = _exact_object(
            raw_mapping,
            required={"signature_id", "cause_candidate_ids", "observation"},
            context=f"questions[{index}].scoring.error_option_mappings.{option_id}",
        )
        signature_id = mapping["signature_id"]
        cause_candidates = mapping["cause_candidate_ids"]
        if not isinstance(cause_candidates, list):
            raise PracticeValidationError("error mapping cause_candidate_ids must be a list")
        normalized_causes = [
            _identifier(cause_id, "error mapping cause candidate") for cause_id in cause_candidates
        ]
        if len(normalized_causes) != len(set(normalized_causes)):
            raise PracticeValidationError("error mapping cause candidates must be unique")
        if not set(normalized_causes).issubset(cause_ids):
            raise PracticeValidationError("error mapping references an unknown cause candidate")
        if signature_id is not None:
            if not isinstance(signature_id, str) or signature_id not in signature_ids:
                raise PracticeValidationError("error option mapping references an unknown signature")
            if not normalized_causes:
                raise PracticeValidationError("a diagnostic signature needs at least one cause candidate")
            mapped_signatures.add(signature_id)
        elif normalized_causes:
            raise PracticeValidationError("non-diagnostic options cannot assert cause candidates")
        _nonempty(mapping["observation"], f"error mapping {option_id}.observation")

    roles = _validate_roles(
        question["role_eligibility"],
        filler=filler,
        context=f"questions[{index}].role_eligibility",
    )
    feedback = _exact_object(
        question["feedback"],
        required={"first_error_principle", "full_explanation"},
        context=f"questions[{index}].feedback",
    )
    _nonempty(feedback["first_error_principle"], f"questions[{index}].feedback.first_error_principle")
    _nonempty(feedback["full_explanation"], f"questions[{index}].feedback.full_explanation")

    if filler:
        if "calculation" in question:
            raise PracticeValidationError("mixed filler questions must not masquerade as growth-rate evidence")
        if mapped_signatures:
            raise PracticeValidationError("filler wrong options cannot emit target-unit error signatures")
        return question

    calculation = _exact_object(
        question.get("calculation"),
        required={"base_value", "current_value", "expected_rate_percent", "rounding_decimals"},
        context=f"questions[{index}].calculation",
    )
    base = _finite_number(calculation["base_value"], "calculation.base_value")
    current = _finite_number(calculation["current_value"], "calculation.current_value")
    expected_rate = _finite_number(calculation["expected_rate_percent"], "calculation.expected_rate_percent")
    decimals = calculation["rounding_decimals"]
    if base <= 0 or current < 0:
        raise PracticeValidationError("growth-rate quantities must have positive base and non-negative current")
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 2:
        raise PracticeValidationError("rounding_decimals must be an integer from 0 to 2")
    computed = round((current - base) / base * 100, decimals)
    if not math.isclose(expected_rate, computed, abs_tol=10 ** (-(decimals + 1))):
        raise PracticeValidationError("expected growth rate does not match base/current values")
    if (direction == "increase") != (current > base):
        raise PracticeValidationError("target_change_direction conflicts with base/current values")
    if (direction == "decrease") != (current < base):
        raise PracticeValidationError("target_change_direction conflicts with base/current values")
    expected_answer = f"{expected_rate:.{decimals}f}%" if decimals else f"{int(expected_rate)}%"
    if scoring["canonical_answer"] != expected_answer:
        raise PracticeValidationError("canonical answer does not match deterministic growth-rate calculation")
    if CURRENT_DENOMINATOR_SIGNATURE not in mapped_signatures:
        raise PracticeValidationError("every core item must map the current-denominator distractor")
    if RATIO_WITHOUT_MINUS_ONE_SIGNATURE not in mapped_signatures:
        raise PracticeValidationError("every core item must map the ratio-without-minus-one distractor")
    if direction == "decrease" and DROPPED_NEGATIVE_SIGNATURE not in mapped_signatures:
        raise PracticeValidationError("every decrease item must map the dropped-negative distractor")
    if direction == "increase" and DROPPED_NEGATIVE_SIGNATURE in mapped_signatures:
        raise PracticeValidationError("increase items cannot emit the dropped-negative signature")
    if roles["delayed_validation"] and direction not in {"increase", "decrease"}:
        raise PracticeValidationError("delayed validation must assess the target calculation")
    return question


def are_independent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Return whether two question versions can contribute independent evidence."""

    required = ("question_id", "evidence_family_id", "material_group_id")
    for field in required:
        if field not in left or field not in right:
            raise PracticeValidationError(f"independence check requires {field}")
    return (
        left["question_id"] != right["question_id"]
        and left["evidence_family_id"] != right["evidence_family_id"]
        and left["material_group_id"] != right["material_group_id"]
    )


def validate_independent_evidence(
    package: Mapping[str, Any],
    question_ids: Sequence[str],
) -> None:
    """Fail closed unless every selected question is eligible and pairwise independent."""

    if len(question_ids) != len(set(question_ids)):
        raise PracticeValidationError("independent evidence cannot repeat a question ID")
    questions = {question["question_id"]: question for question in package.get("questions", [])}
    selected: list[Mapping[str, Any]] = []
    for question_id in question_ids:
        question = questions.get(question_id)
        if question is None:
            raise PracticeValidationError(f"unknown question ID in independent evidence: {question_id}")
        roles = question["role_eligibility"]
        if not roles["evidence_eligible"] or roles["filler"]:
            raise PracticeValidationError("filler or ineligible questions cannot count as independent evidence")
        selected.append(question)
    for left, right in combinations(selected, 2):
        if not are_independent(left, right):
            raise PracticeValidationError("independent evidence shares an evidence family or material group")


def validate_practice_package(package: Mapping[str, Any]) -> None:
    """Validate integrity, provenance, scoring, independence, and role isolation."""

    package = _exact_object(
        package,
        required={
            "schema_version",
            "package_id",
            "version",
            "title",
            "domain",
            "path",
            "user_facing_type",
            "diagnostic_unit",
            "content_sources",
            "error_signatures",
            "cause_candidates",
            "interventions",
            "material_groups",
            "evidence_families",
            "questions",
        },
        context="practice package",
    )
    if package["schema_version"] != PRACTICE_PACKAGE_SCHEMA_VERSION:
        raise PracticeValidationError("unsupported practice package schema_version")
    _identifier(package["package_id"], "package_id")
    version = _nonempty(package["version"], "version")
    if not _SEMVER.fullmatch(version):
        raise PracticeValidationError("package version must be semantic x.y.z")
    _nonempty(package["title"], "title")
    if package["domain"] != "xingce" or package["path"] != "data_analysis":
        raise PracticeValidationError("growth-rate v2 must be an xingce data-analysis package")
    if package["user_facing_type"] != "资料分析":
        raise PracticeValidationError("growth-rate v2 user-facing type must be 资料分析")
    unit = _validate_diagnostic_unit(package["diagnostic_unit"])

    sources = package["content_sources"]
    if not isinstance(sources, list) or not sources:
        raise PracticeValidationError("content_sources must contain at least one source")
    source_ids = [_validate_content_source(item, index) for index, item in enumerate(sources)]
    if len(source_ids) != len(set(source_ids)):
        raise PracticeValidationError("content source IDs must be unique")

    signatures = package["error_signatures"]
    if not isinstance(signatures, list):
        raise PracticeValidationError("error_signatures must be a list")
    signature_ids = [_validate_error_signature(item, index) for index, item in enumerate(signatures)]
    if set(signature_ids) != REQUIRED_ERROR_SIGNATURES or len(signature_ids) != 3:
        raise PracticeValidationError("growth-rate v2 must declare exactly the three required error signatures")

    causes = package["cause_candidates"]
    if not isinstance(causes, list) or len(causes) < 3:
        raise PracticeValidationError("at least three actionable cause candidates are required")
    cause_ids = [_validate_cause_candidate(item, index) for index, item in enumerate(causes)]
    if len(cause_ids) != len(set(cause_ids)):
        raise PracticeValidationError("cause candidate IDs must be unique")
    _validate_interventions(
        package["interventions"],
        signature_ids=set(signature_ids),
        cause_ids=set(cause_ids),
    )

    materials = package["material_groups"]
    families = package["evidence_families"]
    if not isinstance(materials, list) or not materials:
        raise PracticeValidationError("material_groups must be a non-empty list")
    if not isinstance(families, list) or not families:
        raise PracticeValidationError("evidence_families must be a non-empty list")
    material_ids = [_validate_material_group(item, index) for index, item in enumerate(materials)]
    family_ids = [_validate_evidence_family(item, index) for index, item in enumerate(families)]
    if len(material_ids) != len(set(material_ids)):
        raise PracticeValidationError("material group IDs must be unique")
    if len(family_ids) != len(set(family_ids)):
        raise PracticeValidationError("evidence family IDs must be unique")

    questions = package["questions"]
    if not isinstance(questions, list) or not questions:
        raise PracticeValidationError("questions must be a non-empty list")
    validated = [
        _validate_question(
            question,
            index=index,
            package=package,
            source_ids=set(source_ids),
            material_ids=set(material_ids),
            family_ids=set(family_ids),
            signature_ids=set(signature_ids),
            cause_ids=set(cause_ids),
        )
        for index, question in enumerate(questions)
    ]
    question_ids = [question["question_id"] for question in validated]
    if len(question_ids) != len(set(question_ids)):
        raise PracticeValidationError("question IDs must be unique within the package")
    normalised_prompts = [_normalise_prompt(question["prompt"]) for question in validated]
    if len(normalised_prompts) != len(set(normalised_prompts)):
        raise PracticeValidationError("question prompts must be distinct")

    core = [question for question in validated if not question["role_eligibility"]["filler"]]
    filler = [question for question in validated if question["role_eligibility"]["filler"]]
    if len(core) != unit["expected_core_question_count"]:
        raise PracticeValidationError("core question count does not match the diagnostic unit contract")
    if len(filler) != unit["expected_filler_question_count"]:
        raise PracticeValidationError("filler question count does not match the diagnostic unit contract")

    core_families = {question["evidence_family_id"] for question in core}
    if len(core_families) < unit["minimum_independent_evidence_families"]:
        raise PracticeValidationError("core content has too few independent evidence families")
    delayed = [question for question in core if question["role_eligibility"]["delayed_validation"]]
    if len(delayed) < unit["minimum_delayed_validation_questions"]:
        raise PracticeValidationError("too few delayed-validation eligible questions")
    validate_independent_evidence(package, [question["question_id"] for question in delayed])

    signature_families: dict[str, set[str]] = {signature_id: set() for signature_id in signature_ids}
    for question in core:
        for mapping in question["scoring"]["error_option_mappings"].values():
            signature_id = mapping["signature_id"]
            if signature_id:
                signature_families[signature_id].add(question["evidence_family_id"])
    if len(signature_families[CURRENT_DENOMINATOR_SIGNATURE]) < 6:
        raise PracticeValidationError("current-denominator signature needs at least six evidence families")
    if len(signature_families[RATIO_WITHOUT_MINUS_ONE_SIGNATURE]) < 6:
        raise PracticeValidationError("ratio-without-minus-one signature needs at least six evidence families")
    if len(signature_families[DROPPED_NEGATIVE_SIGNATURE]) < 4:
        raise PracticeValidationError("dropped-negative signature needs at least four evidence families")

    referenced_sources = {question["content_source_id"] for question in validated}
    referenced_materials = {question["material_group_id"] for question in validated}
    referenced_families = {question["evidence_family_id"] for question in validated}
    if referenced_sources != set(source_ids):
        raise PracticeValidationError("content source registry contains an unused source")
    if referenced_materials != set(material_ids):
        raise PracticeValidationError("material group registry contains an unused group")
    if referenced_families != set(family_ids):
        raise PracticeValidationError("evidence family registry contains an unused family")


def _validate_manifest(value: Any) -> list[Mapping[str, Any]]:
    manifest = _exact_object(
        value,
        required={"schema_version", "package_id", "version", "created_at", "packages"},
        context="practice manifest",
    )
    if manifest["schema_version"] != PRACTICE_MANIFEST_SCHEMA_VERSION:
        raise PracticeValidationError("unsupported practice manifest schema_version")
    _identifier(manifest["package_id"], "practice manifest.package_id")
    version = _nonempty(manifest["version"], "practice manifest.version")
    if not _SEMVER.fullmatch(version):
        raise PracticeValidationError("practice manifest version must be semantic x.y.z")
    created_at = _nonempty(manifest["created_at"], "practice manifest.created_at")
    if not _DATE.fullmatch(created_at):
        raise PracticeValidationError("practice manifest created_at must use YYYY-MM-DD")
    entries = manifest["packages"]
    if not isinstance(entries, list) or not entries:
        raise PracticeValidationError("practice manifest must list at least one package")
    ids: list[str] = []
    paths: list[str] = []
    for index, raw_entry in enumerate(entries):
        entry = _exact_object(
            raw_entry,
            required={"package_id", "version", "path", "sha256"},
            context=f"practice manifest.packages[{index}]",
        )
        ids.append(_identifier(entry["package_id"], f"manifest package[{index}].package_id"))
        entry_version = _nonempty(entry["version"], f"manifest package[{index}].version")
        if not _SEMVER.fullmatch(entry_version):
            raise PracticeValidationError("manifest package version must be semantic x.y.z")
        relative = _nonempty(entry["path"], f"manifest package[{index}].path")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".json":
            raise PracticeValidationError("manifest package path must be a safe relative JSON path")
        if candidate.name == "manifest.json":
            raise PracticeValidationError("manifest cannot list itself as a practice package")
        paths.append(relative)
        checksum = _nonempty(entry["sha256"], f"manifest package[{index}].sha256")
        if not _SHA256.fullmatch(checksum):
            raise PracticeValidationError("manifest sha256 must be 64 lowercase hexadecimal characters")
    if len(ids) != len(set(ids)):
        raise PracticeValidationError("practice package IDs must be unique")
    if len(paths) != len(set(paths)):
        raise PracticeValidationError("practice package paths must be unique")
    return entries


def _load_packages(root: Path) -> tuple[list[dict[str, Any]], dict[Path, dict[str, Any]]]:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise PracticeValidationError("practice manifest.json is missing")
    manifest = _parse_json(manifest_path.read_bytes(), manifest_path)
    entries = _validate_manifest(manifest)

    listed_paths = {manifest_path.resolve()}
    packages: list[dict[str, Any]] = []
    by_path: dict[Path, dict[str, Any]] = {}
    all_question_ids: set[str] = set()
    for entry in entries:
        path = (root / entry["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise PracticeValidationError("manifest package path escapes the root or does not exist")
        listed_paths.add(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise PracticeValidationError(f"practice package checksum mismatch: {entry['path']}")
        package = _parse_json(raw, path)
        validate_practice_package(package)
        if package["package_id"] != entry["package_id"] or package["version"] != entry["version"]:
            raise PracticeValidationError("manifest identity/version does not match practice package")
        question_ids = {question["question_id"] for question in package["questions"]}
        if all_question_ids & question_ids:
            raise PracticeValidationError("question IDs must be globally unique across practice packages")
        all_question_ids.update(question_ids)
        packages.append(package)
        by_path[path] = package

    actual_json = {path.resolve() for path in root.rglob("*.json")}
    unexpected = actual_json - listed_paths
    if unexpected:
        names = sorted(str(path.relative_to(root)) for path in unexpected)
        raise PracticeValidationError(f"unlisted practice JSON files are not allowed: {names}")
    return packages, by_path


def load_practice_catalog(practice_root: Path | None = None) -> list[dict[str, Any]]:
    """Return answer-free package descriptors after manifest and semantic validation."""

    packages, _ = _load_packages(practice_root or DEFAULT_PRACTICE_ROOT)
    catalog: list[dict[str, Any]] = []
    for package in packages:
        questions = package["questions"]
        core = [question for question in questions if not question["role_eligibility"]["filler"]]
        filler = [question for question in questions if question["role_eligibility"]["filler"]]
        delayed = [question for question in core if question["role_eligibility"]["delayed_validation"]]
        catalog.append(
            {
                "package_id": package["package_id"],
                "version": package["version"],
                "title": package["title"],
                "domain": package["domain"],
                "path": package["path"],
                "user_facing_type": package["user_facing_type"],
                "diagnostic_unit_id": package["diagnostic_unit"]["diagnostic_unit_id"],
                "counts": {
                    "questions": len(questions),
                    "core": len(core),
                    "filler": len(filler),
                    "delayed_validation_eligible": len(delayed),
                    "evidence_families": len({question["evidence_family_id"] for question in core}),
                },
            }
        )
    return copy.deepcopy(catalog)


def load_practice_package(
    path_or_id: Path | str,
    *,
    practice_root: Path | None = None,
) -> dict[str, Any]:
    """Load one manifest-authorized, fully validated internal practice package."""

    root = (practice_root or DEFAULT_PRACTICE_ROOT).resolve()
    packages, by_path = _load_packages(root)
    raw_request = str(path_or_id)
    if isinstance(path_or_id, Path) or raw_request.endswith(".json") or "/" in raw_request:
        requested = Path(path_or_id)
        requested = requested.resolve() if requested.is_absolute() else (root / requested).resolve()
        package = by_path.get(requested)
    else:
        package = next((item for item in packages if item["package_id"] == raw_request), None)
    if package is None:
        raise PracticeValidationError(f"practice package is not listed in the manifest: {path_or_id}")
    return copy.deepcopy(package)


def load_question_version(
    question_id: str,
    *,
    practice_root: Path | None = None,
) -> dict[str, Any]:
    """Load one trusted internal QuestionVersion by stable question ID."""

    _identifier(question_id, "question_id")
    packages, _ = _load_packages(practice_root or DEFAULT_PRACTICE_ROOT)
    for package in packages:
        for question in package["questions"]:
            if question["question_id"] == question_id:
                return copy.deepcopy(question)
    raise PracticeValidationError(f"unknown question version: {question_id}")


def safe_question_view(question: Mapping[str, Any]) -> dict[str, Any]:
    """Build the pre-submission client payload without answers or diagnostic metadata."""

    _identifier(question.get("question_id"), "question.question_id")
    version = _nonempty(question.get("version"), "question.version")
    if not _SEMVER.fullmatch(version):
        raise PracticeValidationError("question.version must be semantic x.y.z")
    prompt = _nonempty(question.get("prompt"), "question.prompt")
    options = question.get("options")
    if not isinstance(options, Mapping) or set(options) != {"A", "B", "C", "D"}:
        raise PracticeValidationError("safe question view requires A-D options")
    safe_options = {key: _nonempty(options[key], f"question.options.{key}") for key in "ABCD"}
    return {
        "schema_version": PUBLIC_QUESTION_SCHEMA_VERSION,
        "question_id": question["question_id"],
        "version": version,
        "domain": _nonempty(question.get("domain"), "question.domain"),
        "user_facing_type": _nonempty(question.get("user_facing_type"), "question.user_facing_type"),
        "prompt": prompt,
        "response_mode": "single_choice",
        "options": safe_options,
    }


def score_question_version(question: Mapping[str, Any], response: str) -> dict[str, Any]:
    """Deterministically score a submitted option and emit only observed evidence."""

    selected = _nonempty(response, "response").strip().upper()
    options = question.get("options")
    scoring = question.get("scoring")
    if not isinstance(options, Mapping) or selected not in options:
        raise PracticeValidationError("response must be one of the question options")
    if not isinstance(scoring, Mapping) or scoring.get("correct_option") not in options:
        raise PracticeValidationError("question scoring is invalid")
    correct = selected == scoring["correct_option"]
    signature_id = None
    observation = None
    if not correct:
        mapping = scoring.get("error_option_mappings", {}).get(selected)
        if not isinstance(mapping, Mapping):
            raise PracticeValidationError("selected wrong option has no error mapping")
        signature_id = mapping.get("signature_id")
        cause_candidate_ids = copy.deepcopy(mapping.get("cause_candidate_ids", []))
        observation = mapping.get("observation")
    else:
        cause_candidate_ids = []
    return {
        "question_id": question["question_id"],
        "question_version": question["version"],
        "selected_option": selected,
        "correct": correct,
        "observed_error_signature_id": signature_id,
        "cause_candidate_ids": cause_candidate_ids,
        "observation": observation,
    }
