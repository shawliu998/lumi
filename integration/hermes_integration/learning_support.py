from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from hermes_kt.assistance import ASSISTANCE_POLICY_VERSION, assistance_level
from hermes_domains.text_semantics import (
    has_affirmed_alias,
    has_negated_alias,
    statement_is_rejected,
)


PROBE_ASSESSMENT_VERSION = "authored-probe-assessment.v1"


def fixture_content_hash(fixture: Mapping[str, Any]) -> str:
    encoded = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def prompt_instance_id(run_id: str, phase: str) -> str:
    if phase not in {"probe", "verification"}:
        raise ValueError("prompt phase must be probe or verification")
    return f"{run_id}:{phase}:1"


def authored_assistance_step(fixture: Mapping[str, Any], ordinal: int) -> dict[str, Any]:
    steps = fixture["assistance_ladder"]["steps"]
    if ordinal < 1 or ordinal > len(steps):
        raise LookupError("assistance ladder is exhausted")
    content = dict(steps[ordinal - 1])
    policy = assistance_level(str(content["action"]))
    if policy.ordinal != ordinal:
        raise ValueError("fixture assistance order does not match policy")
    return {
        "ordinal": ordinal,
        **content,
        "content_version": fixture["assistance_ladder"]["content_version"],
        "policy_version": ASSISTANCE_POLICY_VERSION,
        "diagnostic_evidence_weight": policy.diagnostic_evidence_weight,
        "calibration_status": "engineering_policy_unvalidated",
    }


def assistance_events_for_prompt(
    events: Iterable[Any], prompt_id: str
) -> list[Any]:
    return [
        event
        for event in events
        if event.kind == "assistance_delivered"
        and event.payload.get("prompt_instance_id") == prompt_id
    ]


def assess_probe_response(
    fixture: Mapping[str, Any],
    response: str,
    *,
    response_event_seq: int,
    response_event_hash: str,
    diagnostic_evidence_weight: float,
) -> dict[str, Any]:
    """Apply only an authored deterministic probe rubric.

    A supported or refuted hypothesis remains a hypothesis; this evidence is
    never promoted to causal ground truth. Fixtures without a rubric fail
    closed and keep every candidate unconfirmed.
    """

    assessment = fixture.get("probe", {}).get("assessment")
    if isinstance(assessment, dict) and assessment.get("evaluator") == "growth_formula_v1":
        return _assess_growth_formula(
            assessment,
            response,
            response_event_seq=response_event_seq,
            response_event_hash=response_event_hash,
            diagnostic_evidence_weight=diagnostic_evidence_weight,
        )
    rules = assessment.get("rules", []) if isinstance(assessment, dict) else []
    folded = response.casefold()
    by_cause: dict[str, dict[str, Any]] = {}
    for rule in rules:
        support = _condition_matches(folded, rule.get("support_if"))
        refute = _condition_matches(folded, rule.get("refute_if"))
        if diagnostic_evidence_weight == 0 or support == refute:
            status = "unconfirmed_hypothesis"
            direction = "insufficient_or_mixed"
        elif support:
            status = "supported_hypothesis"
            direction = "supports"
        else:
            status = "refuted_hypothesis"
            direction = "refutes"
        by_cause[str(rule["cause_id"])] = {
            "cause_id": str(rule["cause_id"]),
            "claim_status": status,
            "evidence_direction": direction,
            "diagnostic_evidence_weight": diagnostic_evidence_weight,
            "source_response_event": {
                "seq": response_event_seq,
                "event_hash": response_event_hash,
            },
            "rubric_version": assessment.get("schema_version", PROBE_ASSESSMENT_VERSION),
        }
    return {
        "schema_version": "hermes.probe-assessment-event.v1",
        "evaluator_version": PROBE_ASSESSMENT_VERSION,
        "authored_rubric_available": bool(rules),
        "diagnostic_evidence_weight": diagnostic_evidence_weight,
        "assessments": list(by_cause.values()),
        "source_response_event": {
            "seq": response_event_seq,
            "event_hash": response_event_hash,
        },
        "semantics": "evidence_for_ranked_hypotheses_not_causal_confirmation",
    }


def _assess_growth_formula(
    assessment: Mapping[str, Any],
    response: str,
    *,
    response_event_seq: int,
    response_event_hash: str,
    diagnostic_evidence_weight: float,
) -> dict[str, Any]:
    cause_map = assessment["cause_map"]
    classification = _classify_growth_formula(response)
    directions = {
        "correct": {"denominator": "refutes", "increment": "refutes", "ratio": "refutes"},
        "current_denominator": {"denominator": "supports", "increment": "refutes", "ratio": "refutes"},
        "ratio_only": {"denominator": "refutes", "increment": "refutes", "ratio": "supports"},
        "naked_increment": {
            "denominator": "insufficient_or_mixed",
            "increment": "supports",
            "ratio": "insufficient_or_mixed",
        },
        "reject_current_denominator": {
            "denominator": "refutes",
            "increment": "insufficient_or_mixed",
            "ratio": "insufficient_or_mixed",
        },
        "reject_ratio_only": {
            "denominator": "insufficient_or_mixed",
            "increment": "insufficient_or_mixed",
            "ratio": "refutes",
        },
        "reject_naked_increment": {
            "denominator": "insufficient_or_mixed",
            "increment": "refutes",
            "ratio": "insufficient_or_mixed",
        },
        "ambiguous": {
            "denominator": "insufficient_or_mixed",
            "increment": "insufficient_or_mixed",
            "ratio": "insufficient_or_mixed",
        },
    }[classification]
    if diagnostic_evidence_weight == 0:
        directions = {name: "insufficient_or_mixed" for name in directions}
    items = []
    for name in ("denominator", "increment", "ratio"):
        direction = directions[name]
        status = {
            "supports": "supported_hypothesis",
            "refutes": "refuted_hypothesis",
            "insufficient_or_mixed": "unconfirmed_hypothesis",
        }[direction]
        items.append(
            {
                "cause_id": str(cause_map[name]),
                "claim_status": status,
                "evidence_direction": direction,
                "diagnostic_evidence_weight": diagnostic_evidence_weight,
                "source_response_event": {
                    "seq": response_event_seq,
                    "event_hash": response_event_hash,
                },
                "rubric_version": str(assessment["schema_version"]),
                "evaluator": "growth_formula_v1",
                "classification": classification,
            }
        )
    return {
        "schema_version": "hermes.probe-assessment-event.v1",
        "evaluator_version": "growth_formula_v1",
        "authored_rubric_available": True,
        "diagnostic_evidence_weight": diagnostic_evidence_weight,
        "assessments": items,
        "source_response_event": {
            "seq": response_event_seq,
            "event_hash": response_event_hash,
        },
        "semantics": "evidence_for_ranked_hypotheses_not_causal_confirmation",
    }


def _classify_growth_formula(response: str) -> str:
    text = response.casefold().strip()
    normalized = re.sub(r"\s+", "", text)
    normalized = normalized.translate(
        str.maketrans({"（": "(", "）": ")", "－": "-", "—": "-", "−": "-", "÷": "/"})
    )
    normalized = normalized.replace("除以", "/").replace("减去", "-").replace("减", "-")
    normalized = normalized.rstrip("。；;，,")

    numeric_delta_over_base = bool(re.search(r"\(?120-100\)?/100", normalized))
    symbolic_delta_over_base = bool(
        re.search(r"\(?现期(?:量)?-基期(?:量)?\)?/基期(?:量)?", normalized)
    )
    named_delta_over_base = bool(re.search(r"增长量/基期(?:量)?", normalized))
    textual_delta_over_base = "基期" in normalized and (
        (
            "增长量" in normalized
            and any(term in normalized for term in ("比值", "比重", "比例", "百分比", "占基期"))
        )
        or (
            "现期" in normalized
            and any(term in normalized for term in ("差", "相减"))
            and any(term in normalized for term in ("/基期", "比值", "比重", "比例", "百分比"))
        )
    )
    ratio_expression = bool(
        re.search(r"(?:120|现期(?:量)?)/(?:100|基期(?:量)?)", normalized)
    )
    correct_formula = (
        numeric_delta_over_base
        or symbolic_delta_over_base
        or named_delta_over_base
        or textual_delta_over_base
        or (ratio_expression and "-1" in normalized)
        or (ratio_expression and any(term in normalized for term in ("20%", "=0.2", "增长率为0.2", "增长率0.2")))
        or normalized in {"20%", "0.2", "百分之二十"}
    )
    if correct_formula and statement_is_rejected(response):
        return "ambiguous"
    if correct_formula:
        return "correct"

    current_denominator = (
        bool(re.search(r"(?:分母(?:是|为)|作分母|作为分母).*现期", normalized))
        or bool(re.search(r"现期(?:量)?.*(?:作|作为)分母", normalized))
        or bool(re.search(r"(?:增长量|\(?120-100\)?|\(?现期(?:量)?-基期(?:量)?\)?)/现期(?:量)?", normalized))
        or bool(re.search(r"\(?120-100\)?/120", normalized))
        or (
            "增长量" in normalized
            and "现期" in normalized
            and any(term in normalized for term in ("占现期", "比值", "比重", "比例", "百分比"))
        )
    )
    if current_denominator:
        if statement_is_rejected(response):
            return "reject_current_denominator"
        return "current_denominator"

    if ratio_expression:
        if statement_is_rejected(response):
            return "reject_ratio_only"
        return "ratio_only"

    naked_increment = (
        "/" not in normalized
        and "%" not in normalized
        and (
            normalized in {"20", "增长量", "120-100", "现期-基期", "现期量-基期量"}
            or bool(re.fullmatch(r"(?:增长量|120-100|现期(?:量)?-基期(?:量)?)(?:(?:=|为)20)?", normalized))
        )
    )
    if naked_increment:
        if has_negated_alias(response, ("20是增长率", "增长量就是增长率", "增长量是增长率")):
            return "reject_naked_increment"
        return "naked_increment"
    return "ambiguous"


def _condition_matches(text: str, condition: Any) -> bool:
    if not isinstance(condition, Mapping):
        return False
    all_terms = [str(term) for term in condition.get("all_terms", [])]
    any_terms = [str(term) for term in condition.get("any_terms", [])]
    none_terms = [str(term) for term in condition.get("none_terms", [])]
    if all_terms and not all(has_affirmed_alias(text, (term,)) for term in all_terms):
        return False
    if any_terms and not has_affirmed_alias(text, any_terms):
        return False
    if none_terms and (
        has_affirmed_alias(text, none_terms) or has_negated_alias(text, none_terms)
    ):
        return False
    return bool(all_terms or any_terms or none_terms)
