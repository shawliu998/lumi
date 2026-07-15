from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


NEXT_SCOPE_RECOMMENDATION_SCHEMA_VERSION = "lumi.next-scope-recommendation.v1"
NEXT_SCOPE_POLICY_ID = "lumi.practice.next-scope"
NEXT_SCOPE_POLICY_VERSION = "1.0.0"
RECENT_QUESTION_AVOIDANCE_LIMIT = 16

_MISSING = object()


@dataclass(frozen=True)
class _Evidence:
    attempt_id: str
    session_id: str
    question_id: str
    diagnostic_unit_id: str
    evidence_family_id: str
    correct: bool
    independent_evidence: bool
    answered_at: datetime
    error_signature_id: str | None
    cause_candidates: tuple[str, ...]


@dataclass(frozen=True)
class _Scope:
    scope_id: str
    diagnostic_unit_ids: frozenset[str]


@dataclass(frozen=True)
class _SkillAssessment:
    payload: dict[str, Any]
    weakness_supported: bool
    latest_failure_at: datetime


def recommend_next_scope(
    *,
    attempts: Iterable[Mapping[str, Any] | object],
    scopes: Iterable[Mapping[str, Any] | object],
    current_scope_id: str | None,
    mixed_scope_id: str,
    decided_at: datetime | str,
    recent_question_limit: int = RECENT_QUESTION_AVOIDANCE_LIMIT,
) -> dict[str, Any]:
    """Recommend the scope of the next fixed-eight direct-practice session.

    The policy is intentionally conservative. A skill can redirect practice only
    after independent failures from at least two sessions and two evidence
    families. Cause labels remain ranked, reversible hypotheses. The returned
    object contains JSON-native values so a service can persist and replay the
    complete decision without importing engine dataclasses.

    ``serving_hints.soft_avoid_question_ids`` is a server-side soft constraint,
    not part of the learner-facing recommendation. It may be relaxed when the
    eligible content pool would otherwise be exhausted.
    """

    decision_time = _datetime("decided_at", decided_at)
    normalized_scopes = _normalize_scopes(scopes, mixed_scope_id=mixed_scope_id)
    scope_by_id = {scope.scope_id: scope for scope in normalized_scopes}
    if current_scope_id is not None:
        _identifier("current_scope_id", current_scope_id)
        if current_scope_id not in scope_by_id:
            raise ValueError(f"unknown current_scope_id: {current_scope_id}")
    if not isinstance(recent_question_limit, int) or isinstance(recent_question_limit, bool):
        raise ValueError("recent_question_limit must be an integer")
    if recent_question_limit < 0 or recent_question_limit > 128:
        raise ValueError("recent_question_limit must be between 0 and 128")

    evidence = _normalize_evidence(attempts, decided_at=decision_time)
    module_scopes = tuple(
        scope for scope in normalized_scopes if scope.scope_id != mixed_scope_id
    )
    unit_to_scope = {
        unit_id: scope.scope_id
        for scope in module_scopes
        for unit_id in scope.diagnostic_unit_ids
    }
    in_scope = tuple(item for item in evidence if item.diagnostic_unit_id in unit_to_scope)
    independent = tuple(item for item in in_scope if item.independent_evidence)
    independent_ids = {item.attempt_id for item in independent}
    non_independent_ids = [
        item.attempt_id for item in in_scope if item.attempt_id not in independent_ids
    ]
    out_of_catalog_ids = [
        item.attempt_id for item in evidence if item.diagnostic_unit_id not in unit_to_scope
    ]

    skill_assessments: dict[str, _SkillAssessment] = {}
    for unit_id in sorted(unit_to_scope):
        unit_attempts = tuple(
            item for item in independent if item.diagnostic_unit_id == unit_id
        )
        assessment = _assess_skill(
            unit_id=unit_id,
            scope_id=unit_to_scope[unit_id],
            attempts=unit_attempts,
        )
        if assessment is not None:
            skill_assessments[unit_id] = assessment

    module_summaries: list[dict[str, Any]] = []
    module_ranking: dict[str, tuple[int, int, datetime]] = {}
    for scope in sorted(module_scopes, key=lambda item: item.scope_id):
        module_attempts = tuple(
            item for item in independent if item.diagnostic_unit_id in scope.diagnostic_unit_ids
        )
        weak_assessments = tuple(
            skill_assessments[unit_id]
            for unit_id in sorted(scope.diagnostic_unit_ids)
            if unit_id in skill_assessments
            and skill_assessments[unit_id].weakness_supported
        )
        failure_count = sum(not item.correct for item in module_attempts)
        sessions = {item.session_id for item in module_attempts}
        if weak_assessments:
            status = "weakness_supported"
            reasons = ("module_contains_cross_session_supported_weakness",)
            latest_failure_at = max(item.latest_failure_at for item in weak_assessments)
            supporting_failure_count = sum(
                item.payload["independent_failure_count"] for item in weak_assessments
            )
            module_ranking[scope.scope_id] = (
                len(weak_assessments),
                supporting_failure_count,
                latest_failure_at,
            )
            latest_supported_failure_at = _iso(latest_failure_at)
        elif len(module_attempts) < 2 or len(sessions) < 2:
            status = "evidence_insufficient"
            reasons = ("module_lacks_cross_session_independent_evidence",)
            latest_supported_failure_at = None
        else:
            status = "no_supported_weakness"
            reasons = ("cross_session_evidence_has_no_supported_weakness",)
            latest_supported_failure_at = None
        module_summaries.append(
            {
                "scope_id": scope.scope_id,
                "status": status,
                "independent_attempt_count": len(module_attempts),
                "independent_failure_count": failure_count,
                "distinct_session_count": len(sessions),
                "weak_skill_ids": [
                    item.payload["diagnostic_unit_id"] for item in weak_assessments
                ],
                "latest_supported_failure_at": latest_supported_failure_at,
                "reason_codes": list(reasons),
                "evidence_refs": [item.attempt_id for item in module_attempts],
            }
        )

    recommended_scope_id, decision_reasons, decision_evidence = _choose_scope(
        module_ranking=module_ranking,
        skill_assessments=skill_assessments,
        current_scope_id=current_scope_id,
        mixed_scope_id=mixed_scope_id,
    )
    recent_question_ids = _recent_distinct_question_ids(
        evidence, limit=recent_question_limit
    )
    serving_reason_codes = [
        "recent_question_avoidance_is_soft",
        "soft_constraint_may_be_relaxed_if_pool_is_exhausted",
    ]
    if not recent_question_ids:
        serving_reason_codes.append("no_recent_question_exposure")

    return {
        "schema_version": NEXT_SCOPE_RECOMMENDATION_SCHEMA_VERSION,
        "decided_at": _iso(decision_time),
        "policy": {
            "id": NEXT_SCOPE_POLICY_ID,
            "version": NEXT_SCOPE_POLICY_VERSION,
            "confidence_semantics": "ordinal_policy_score_not_probability",
        },
        "decision": {
            "recommended_scope_id": recommended_scope_id,
            "current_scope_id": current_scope_id,
            "practice_action": "start_next_fixed_eight_direct_practice",
            "ranking_basis": [
                "supported_weak_skill_count_desc",
                "supporting_failure_count_desc",
                "latest_supported_failure_at_desc",
                "keep_current_scope_on_exact_tie",
                "scope_id_asc",
            ],
            "reason_codes": list(decision_reasons),
            "evidence_refs": decision_evidence,
        },
        "module_summaries": module_summaries,
        "skill_weakness_summaries": [
            skill_assessments[unit_id].payload for unit_id in sorted(skill_assessments)
        ],
        "evidence_accounting": {
            "total_attempt_count": len(evidence),
            "independent_in_scope_count": len(independent),
            "non_independent_excluded_from_weakness_refs": non_independent_ids,
            "out_of_catalog_evidence_refs": out_of_catalog_ids,
        },
        "serving_hints": {
            "visibility": "service_internal",
            "soft_avoid_question_ids": recent_question_ids,
            "limit": recent_question_limit,
            "reason_codes": serving_reason_codes,
        },
    }


def _assess_skill(
    *,
    unit_id: str,
    scope_id: str,
    attempts: tuple[_Evidence, ...],
) -> _SkillAssessment | None:
    failures = tuple(item for item in attempts if not item.correct)
    if not failures:
        return None
    failure_sessions = {item.session_id for item in failures}
    failure_families = {item.evidence_family_id for item in failures}
    latest_failure = failures[-1]
    recovery_successes = tuple(
        item
        for item in attempts
        if item.correct and item.answered_at > latest_failure.answered_at
    )
    recovery_supported = (
        len(recovery_successes) >= 2
        and len({item.session_id for item in recovery_successes}) >= 2
        and len({item.evidence_family_id for item in recovery_successes}) >= 2
    )
    weakness_threshold_met = (
        len(failures) >= 2
        and len(failure_sessions) >= 2
        and len(failure_families) >= 2
    )
    if weakness_threshold_met and recovery_supported:
        status = "recovery_supported"
        reason_codes = (
            "historical_weakness_supported_across_sessions_and_families",
            "two_cross_session_cross_family_successes_follow_latest_failure",
        )
        weakness_supported = False
    elif weakness_threshold_met:
        status = "weakness_supported"
        reason_codes = (
            "two_independent_failures_across_sessions_and_families",
            "recovery_not_yet_supported",
        )
        weakness_supported = True
    else:
        status = "watch"
        missing = []
        if len(failures) < 2:
            missing.append("fewer_than_two_independent_failures")
        if len(failure_sessions) < 2:
            missing.append("failure_evidence_not_cross_session")
        if len(failure_families) < 2:
            missing.append("failure_evidence_not_cross_family")
        reason_codes = tuple(missing)
        weakness_supported = False

    payload = {
        "scope_id": scope_id,
        "diagnostic_unit_id": unit_id,
        "status": status,
        "independent_attempt_count": len(attempts),
        "independent_failure_count": len(failures),
        "distinct_session_count": len({item.session_id for item in attempts}),
        "distinct_failure_family_count": len(failure_families),
        "recovery_success_count": len(recovery_successes),
        "latest_failure_at": _iso(latest_failure.answered_at),
        "reason_codes": list(reason_codes),
        "evidence_refs": [item.attempt_id for item in attempts],
        "supporting_failure_evidence_refs": [item.attempt_id for item in failures],
        "cause_hypotheses": _cause_hypotheses(failures),
    }
    return _SkillAssessment(
        payload=payload,
        weakness_supported=weakness_supported,
        latest_failure_at=latest_failure.answered_at,
    )


def _cause_hypotheses(failures: tuple[_Evidence, ...]) -> list[dict[str, Any]]:
    candidates = sorted(
        {candidate for item in failures for candidate in item.cause_candidates}
    )
    unranked: list[tuple[int, int, str, dict[str, Any]]] = []
    for cause_id in candidates:
        supporting = tuple(item for item in failures if cause_id in item.cause_candidates)
        sessions = {item.session_id for item in supporting}
        families = {item.evidence_family_id for item in supporting}
        unambiguous = all(len(item.cause_candidates) == 1 for item in supporting)
        if len(sessions) >= 2 and len(families) >= 2:
            confidence_score = 75 if unambiguous else 60
            confidence_level = "moderate"
            reasons = ["cause_candidate_repeated_across_sessions_and_families"]
            if not unambiguous:
                reasons.append("candidate_sets_are_ambiguous")
        elif len(supporting) >= 2:
            confidence_score = 45
            confidence_level = "low"
            reasons = ["cause_candidate_repeated_without_cross_session_family_support"]
        else:
            confidence_score = 25
            confidence_level = "low"
            reasons = ["cause_candidate_observed_once"]
        reasons.extend(
            [
                "cause_remains_a_reversible_hypothesis",
                "confidence_score_is_ordinal_not_probability",
            ]
        )
        payload = {
            "cause_id": cause_id,
            "rank": 0,
            "confidence_level": confidence_level,
            "confidence_score": confidence_score,
            "reason_codes": reasons,
            "evidence_refs": [item.attempt_id for item in supporting],
            "error_signature_ids": sorted(
                {
                    item.error_signature_id
                    for item in supporting
                    if item.error_signature_id is not None
                }
            ),
        }
        unranked.append((confidence_score, len(supporting), cause_id, payload))
    unranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    result = []
    for rank, (_, _, _, payload) in enumerate(unranked, start=1):
        payload["rank"] = rank
        result.append(payload)
    return result


def _choose_scope(
    *,
    module_ranking: Mapping[str, tuple[int, int, datetime]],
    skill_assessments: Mapping[str, _SkillAssessment],
    current_scope_id: str | None,
    mixed_scope_id: str,
) -> tuple[str, tuple[str, ...], list[str]]:
    if not module_ranking:
        if current_scope_id is not None:
            return (
                current_scope_id,
                (
                    "no_cross_session_supported_weakness",
                    "insufficient_evidence_keep_current_scope",
                    "direct_practice_only_no_extra_learning_task",
                ),
                [],
            )
        return (
            mixed_scope_id,
            (
                "no_cross_session_supported_weakness",
                "no_current_scope_use_mixed_fallback",
                "direct_practice_only_no_extra_learning_task",
            ),
            [],
        )

    strongest = max(module_ranking.values())
    tied = sorted(
        scope_id for scope_id, ranking in module_ranking.items() if ranking == strongest
    )
    if current_scope_id in tied:
        selected = current_scope_id
        tie_reason = (
            "deterministic_tie_kept_current_scope" if len(tied) > 1 else None
        )
    else:
        selected = tied[0]
        tie_reason = (
            "deterministic_tie_broken_by_scope_id" if len(tied) > 1 else None
        )
    reasons = ["supported_weakness_selected_across_sessions_and_families"]
    if selected == current_scope_id:
        reasons.append("current_scope_has_strongest_supported_weakness")
    else:
        reasons.append("recommended_scope_targets_strongest_supported_weakness")
    if tie_reason is not None:
        reasons.append(tie_reason)
    reasons.append("direct_practice_only_no_extra_learning_task")

    evidence_refs: list[str] = []
    for unit_id in sorted(skill_assessments):
        assessment = skill_assessments[unit_id]
        if (
            assessment.weakness_supported
            and assessment.payload["scope_id"] == selected
        ):
            evidence_refs.extend(assessment.payload["supporting_failure_evidence_refs"])
    return selected, tuple(reasons), list(dict.fromkeys(evidence_refs))


def _normalize_scopes(
    scopes: Iterable[Mapping[str, Any] | object], *, mixed_scope_id: str
) -> tuple[_Scope, ...]:
    _identifier("mixed_scope_id", mixed_scope_id)
    if isinstance(scopes, (str, bytes, Mapping)):
        raise ValueError("scopes must be an iterable of scope records")
    result: list[_Scope] = []
    seen_scope_ids: set[str] = set()
    module_unit_owner: dict[str, str] = {}
    try:
        raw_scopes = tuple(scopes)
    except TypeError:
        raise ValueError("scopes must be iterable") from None
    for raw in raw_scopes:
        scope_id = _identifier("scope_id", _value(raw, "scope_id"))
        if scope_id in seen_scope_ids:
            raise ValueError(f"duplicate scope_id: {scope_id}")
        seen_scope_ids.add(scope_id)
        raw_units = _value(raw, "diagnostic_unit_ids")
        if isinstance(raw_units, (str, bytes, Mapping)):
            raise ValueError("diagnostic_unit_ids must be an iterable of identifiers")
        try:
            units = frozenset(
                _identifier("diagnostic_unit_id", value) for value in raw_units
            )
        except TypeError:
            raise ValueError("diagnostic_unit_ids must be iterable") from None
        if not units:
            raise ValueError(f"scope has no diagnostic units: {scope_id}")
        result.append(_Scope(scope_id=scope_id, diagnostic_unit_ids=units))
        if scope_id != mixed_scope_id:
            for unit_id in units:
                previous = module_unit_owner.get(unit_id)
                if previous is not None:
                    raise ValueError(
                        f"diagnostic unit belongs to multiple module scopes: {unit_id}"
                    )
                module_unit_owner[unit_id] = scope_id
    if mixed_scope_id not in seen_scope_ids:
        raise ValueError(f"mixed scope is missing: {mixed_scope_id}")
    if len(result) < 2:
        raise ValueError("at least one module scope plus the mixed scope is required")
    mixed_units = next(
        scope.diagnostic_unit_ids for scope in result if scope.scope_id == mixed_scope_id
    )
    missing_from_mixed = set(module_unit_owner) - set(mixed_units)
    if missing_from_mixed:
        raise ValueError("mixed scope must contain every module diagnostic unit")
    unmapped_mixed_units = set(mixed_units) - set(module_unit_owner)
    if unmapped_mixed_units:
        raise ValueError("mixed scope cannot contain unmapped diagnostic units")
    return tuple(result)


def _normalize_evidence(
    attempts: Iterable[Mapping[str, Any] | object], *, decided_at: datetime
) -> tuple[_Evidence, ...]:
    if isinstance(attempts, (str, bytes, Mapping)):
        raise ValueError("attempts must be an iterable of evidence records")
    try:
        raw_attempts = tuple(attempts)
    except TypeError:
        raise ValueError("attempts must be iterable") from None
    by_id: dict[str, _Evidence] = {}
    for raw in raw_attempts:
        correct = _value(raw, "correct")
        independent = _value(raw, "independent_evidence")
        if not isinstance(correct, bool):
            raise ValueError("correct must be a boolean")
        if not isinstance(independent, bool):
            raise ValueError("independent_evidence must be a boolean")
        raw_causes = _value(raw, "cause_candidates", default=())
        if raw_causes is None:
            raw_causes = ()
        if isinstance(raw_causes, (str, bytes, Mapping)):
            raise ValueError("cause_candidates must be an iterable of identifiers")
        try:
            causes = tuple(
                sorted(
                    {
                        _identifier("cause_candidate", value)
                        for value in raw_causes
                    }
                )
            )
        except TypeError:
            raise ValueError("cause_candidates must be iterable") from None
        signature = _value(raw, "error_signature_id", default=None)
        if signature is not None:
            signature = _identifier("error_signature_id", signature)
        if correct and (signature is not None or causes):
            raise ValueError(
                "correct attempt evidence cannot include error signature or cause candidates"
            )
        if not correct and causes and signature is None:
            raise ValueError(
                "cause candidates require an error signature on incorrect evidence"
            )
        answered_at = _datetime("answered_at", _value(raw, "answered_at"))
        if answered_at > decided_at:
            raise ValueError("attempt evidence cannot be later than decided_at")
        item = _Evidence(
            attempt_id=_identifier("attempt_id", _value(raw, "attempt_id")),
            session_id=_identifier("session_id", _value(raw, "session_id")),
            question_id=_identifier("question_id", _value(raw, "question_id")),
            diagnostic_unit_id=_identifier(
                "diagnostic_unit_id", _value(raw, "diagnostic_unit_id")
            ),
            evidence_family_id=_identifier(
                "evidence_family_id", _value(raw, "evidence_family_id")
            ),
            correct=correct,
            independent_evidence=independent,
            answered_at=answered_at,
            error_signature_id=signature,
            cause_candidates=causes,
        )
        previous = by_id.get(item.attempt_id)
        if previous is not None and previous != item:
            raise ValueError(f"conflicting duplicate attempt_id: {item.attempt_id}")
        by_id[item.attempt_id] = item
    return tuple(sorted(by_id.values(), key=lambda item: (item.answered_at, item.attempt_id)))


def _recent_distinct_question_ids(
    attempts: tuple[_Evidence, ...], *, limit: int
) -> list[str]:
    if limit == 0:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in reversed(attempts):
        if item.question_id in seen:
            continue
        seen.add(item.question_id)
        result.append(item.question_id)
        if len(result) == limit:
            break
    return result


def _value(record: Mapping[str, Any] | object, name: str, *, default: Any = _MISSING) -> Any:
    if isinstance(record, Mapping):
        if name in record:
            return record[name]
    elif is_dataclass(record) or hasattr(record, name):
        if hasattr(record, name):
            return getattr(record, name)
    if default is not _MISSING:
        return default
    raise ValueError(f"missing required field: {name}")


def _identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{name} cannot contain surrounding whitespace")
    return value


def _datetime(name: str, value: datetime | str) -> datetime:
    if isinstance(value, str):
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            raise ValueError(f"{name} must be an ISO-8601 datetime") from None
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime or ISO-8601 string")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "NEXT_SCOPE_POLICY_ID",
    "NEXT_SCOPE_POLICY_VERSION",
    "NEXT_SCOPE_RECOMMENDATION_SCHEMA_VERSION",
    "RECENT_QUESTION_AVOIDANCE_LIMIT",
    "recommend_next_scope",
]
