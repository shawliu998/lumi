from __future__ import annotations

import math
import re
from typing import Any, Mapping

from .contract import validate_fixture
from .models import CauseCandidate, ScoreObservation, ScoreResult
from .text_semantics import has_affirmed_alias


def _contains(text: str, term: str) -> bool:
    return has_affirmed_alias(text, (term,))


def _normalise_candidates(
    fixture: Mapping[str, Any], active_evidence: set[str]
) -> tuple[CauseCandidate, ...]:
    candidates = []
    for raw in fixture["diagnosis"]["candidate_causes"]:
        matched = tuple(ref for ref in raw["evidence_refs"] if ref in active_evidence)
        if not matched:
            continue
        # A generic incorrect-answer flag is weak. An authored distractor or
        # rubric pattern is more discriminating, but still produces only a
        # candidate for the next probe rather than a causal label.
        prior = float(raw["synthetic_prior"])
        generic_count = sum(ref == "answer_incorrect" for ref in matched)
        specific_count = len(matched) - generic_count
        likelihood = 1.0 + 0.10 * generic_count + 2.0 * specific_count
        candidates.append((raw, matched, max(1e-9, prior * likelihood)))
    total = sum(score for _, _, score in candidates)
    if not candidates or total <= 0:
        return ()
    ranked = [
        CauseCandidate(
            cause_id=raw["cause_id"],
            label=raw["label"],
            probability=score / total,
            prior=float(raw["synthetic_prior"]),
            evidence_ids=matched,
        )
        for raw, matched, score in candidates
    ]
    ranked.sort(key=lambda item: (-item.probability, item.cause_id))
    return tuple(ranked)


def _score_xingce(fixture: Mapping[str, Any], response: str) -> ScoreResult:
    selected = response.strip().upper()
    scoring = fixture["scoring"]
    correct = selected == str(scoring["correct_option"]).upper()
    observations = [
        ScoreObservation("selected_option", "response", selected, "learner selection"),
        ScoreObservation("answer_correct", "score", correct, "exact option comparison"),
    ]
    active = {"answer_correct" if correct else "answer_incorrect"}
    distractor = scoring.get("distractor_evidence", {}).get(selected)
    if distractor:
        active.add(distractor)
        observations.append(
            ScoreObservation(distractor, "distractor_pattern", True, f"selected option {selected}")
        )
    score = float(scoring["max_score"] if correct else 0.0)
    return _result(fixture, score, observations, active)


def _rubric_score(
    fixture: Mapping[str, Any], response: str, *, interview: bool
) -> ScoreResult:
    scoring = fixture["scoring"]
    observations: list[ScoreObservation] = []
    active: set[str] = set()
    score = 0.0
    for criterion in scoring["criteria"]:
        matched = [term for term in criterion["keywords"] if _contains(response, term)]
        met = len(matched) >= int(criterion.get("min_hits", 1))
        if met:
            score += float(criterion["points"])
            active.add(f"criterion_met:{criterion['criterion_id']}")
        else:
            active.add(f"criterion_missing:{criterion['criterion_id']}")
        observations.append(
            ScoreObservation(
                f"criterion:{criterion['criterion_id']}",
                "rubric_keyword_match",
                {"met": met, "matched": matched},
                "deterministic synthetic rubric",
            )
        )
    if interview:
        section_hits = len(re.findall(r"(?:第一|第二|第三|首先|其次|最后)", response))
        structured = section_hits >= int(scoring.get("min_structure_markers", 2))
        active.add("structure_present" if structured else "structure_missing")
        observations.append(
            ScoreObservation(
                "structure_markers", "response_feature", section_hits, "enumeration marker count"
            )
        )
    return _result(fixture, score, observations, active)


def _result(
    fixture: Mapping[str, Any],
    score: float,
    observations: list[ScoreObservation],
    active_evidence: set[str],
) -> ScoreResult:
    scoring = fixture["scoring"]
    return ScoreResult(
        fixture_id=fixture["fixture_id"],
        domain=fixture["domain"],
        score=round(score, 4),
        max_score=float(scoring["max_score"]),
        passed=score + math.ulp(float(score)) >= float(scoring["pass_score"]),
        observations=tuple(observations),
        cause_candidates=_normalise_candidates(fixture, active_evidence),
    )


def score_attempt(fixture: Mapping[str, Any], response: str) -> ScoreResult:
    """Score one response with the fixture-selected deterministic adapter."""

    validate_fixture(fixture)
    adapter = fixture["scoring"]["adapter"]
    if adapter == "xingce_mcq_v1":
        return _score_xingce(fixture, response)
    if adapter == "shenlun_rubric_v1":
        return _rubric_score(fixture, response, interview=False)
    if adapter == "interview_rubric_v1":
        return _rubric_score(fixture, response, interview=True)
    raise ValueError(f"unsupported adapter: {adapter}")


def score_verification_response(
    fixture: Mapping[str, Any], response: str
) -> tuple[bool, str]:
    """Score an authored independent-transfer response deterministically.

    The aliases live in the fixture rather than in one global keyword table so
    each transfer task remains inspectable, versionable, and domain specific.
    """

    validate_fixture(fixture)
    condition = fixture["independent_verify"]["pass_condition"]
    scorer = str(condition["scorer"])
    folded = response.strip().casefold()
    if scorer == "exact_option_v1":
        return (
            folded == str(condition["correct_option"]).strip().casefold(),
            scorer,
        )
    if scorer == "authored_dimensions_v1":
        matched = _matched_authored_groups(folded, condition["required_dimensions"])
        return matched >= int(condition["minimum_dimensions"]), scorer
    if scorer == "authored_slots_v1":
        matched = _matched_authored_groups(folded, condition["required_slots"])
        return matched >= int(condition["minimum_slots"]), scorer
    raise ValueError(f"unsupported independent verification scorer: {scorer}")


def _matched_authored_groups(text: str, groups: list[Mapping[str, Any]]) -> int:
    return sum(
        has_affirmed_alias(text, (str(alias) for alias in group["aliases"]))
        for group in groups
    )
