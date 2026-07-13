"""Type-neutral, inspectable policy primitives for Xingce adaptive packs.

This policy never learns a latent cause from a single answer.  It uses the
author's subtype-specific metadata to turn observed entry/probe/transfer
responses into a small, replayable sequence.  The result is deliberately a
proposal for the shared learner-state committer, not a direct KT mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping, Sequence


POLICY_ID = "lumi.xingce-type-policy"
POLICY_VERSION = "1.0.0"
CALIBRATION_STATUS = "uncalibrated"
_CONFIDENCE = frozenset({"low", "medium", "high"})
_CANDIDATE_STATUS = "unconfirmed"


class XingceAdaptivePolicyError(ValueError):
    """The caller supplied records or observations outside the pack contract."""


@dataclass(frozen=True, slots=True)
class Observation:
    selected_response: str
    confidence: Literal["low", "medium", "high"]
    elapsed_seconds: float
    hint_count: int = 0
    rationale: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.selected_response, str) or not self.selected_response.strip():
            raise XingceAdaptivePolicyError("selected_response must be non-empty")
        if self.confidence not in _CONFIDENCE:
            raise XingceAdaptivePolicyError("confidence must be low, medium, or high")
        if not isinstance(self.elapsed_seconds, (int, float)) or isinstance(self.elapsed_seconds, bool) or self.elapsed_seconds < 0:
            raise XingceAdaptivePolicyError("elapsed_seconds must be non-negative")
        if not isinstance(self.hint_count, int) or isinstance(self.hint_count, bool) or self.hint_count < 0:
            raise XingceAdaptivePolicyError("hint_count must be a non-negative integer")
        if self.rationale is not None and (not isinstance(self.rationale, str) or len(self.rationale) > 4000):
            raise XingceAdaptivePolicyError("rationale must be a short optional string")


@dataclass(frozen=True, slots=True)
class CandidateHypothesis:
    cause_id: str
    status: Literal["unconfirmed"]
    rank: int
    evidence_fact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status != _CANDIDATE_STATUS or self.rank < 1 or not self.evidence_fact_ids:
            raise XingceAdaptivePolicyError("candidate hypothesis must stay unconfirmed and evidence-bound")


@dataclass(frozen=True, slots=True)
class EntryDecision:
    entry_record_id: str
    correct: bool
    facts: tuple[dict[str, Any], ...]
    candidates: tuple[CandidateHypothesis, ...]
    probe_record_id: str | None
    next_step: Literal["probe", "review_or_stop"]
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS


@dataclass(frozen=True, slots=True)
class ProbeDecision:
    probe_record_id: str
    correct: bool
    evidence_updates: tuple[dict[str, str], ...]
    teaching_record_id: str | None
    transfer_record_id: str
    target_cause_id: str | None
    next_step: Literal["independent_transfer"] = "independent_transfer"
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS


def _index(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for record in records:
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or record_id in result:
            raise XingceAdaptivePolicyError("records need unique record ids")
        result[record_id] = record
    return result


def _record(index: Mapping[str, Mapping[str, Any]], record_id: str, role: str | None = None) -> Mapping[str, Any]:
    record = index.get(record_id)
    if record is None or (role is not None and record.get("role") != role):
        raise XingceAdaptivePolicyError("record id does not name the required adaptive role")
    return record


def _score(record: Mapping[str, Any], scorer: str, selected_response: str) -> bool:
    if scorer == "exact_option_v1" or record.get("response_mode") == "single_choice":
        correct = record.get("correct_option")
        if not isinstance(correct, str):
            raise XingceAdaptivePolicyError("option scorer record is missing its authored correct option")
        return selected_response == correct
    if scorer != "authored_numeric_v1" or record.get("response_mode") != "numeric":
        raise XingceAdaptivePolicyError("record response mode is incompatible with its deterministic scorer")
    answer = record.get("answer_spec")
    if not isinstance(answer, Mapping):
        raise XingceAdaptivePolicyError("numeric record is missing answer_spec")
    try:
        selected = Decimal(selected_response.strip())
        target = Decimal(str(answer["target"]))
        tolerance = Decimal(str(answer.get("tolerance", 0)))
    except (InvalidOperation, KeyError) as exc:
        raise XingceAdaptivePolicyError("numeric response cannot be deterministically scored") from exc
    return abs(selected - target) <= tolerance


def _facts(prefix: str, observation: Observation, correct: bool) -> tuple[dict[str, Any], ...]:
    return (
        {"fact_id": f"{prefix}:selected_response", "kind": "selected_response", "value": observation.selected_response},
        {"fact_id": f"{prefix}:correctness", "kind": "correctness", "value": correct},
        {"fact_id": f"{prefix}:confidence", "kind": "confidence", "value": observation.confidence},
        {"fact_id": f"{prefix}:elapsed_seconds", "kind": "elapsed_seconds", "value": float(observation.elapsed_seconds)},
        {"fact_id": f"{prefix}:hint_count", "kind": "hint_count", "value": observation.hint_count},
    )


def diagnose_entry(
    records: Sequence[Mapping[str, Any]], *, scorer: str, entry_record_id: str, observation: Observation
) -> EntryDecision:
    """Score one entry answer and select only an authored minimal probe."""

    index = _index(records)
    entry = _record(index, entry_record_id)
    if entry.get("role") not in {"entry_diagnostic", "routing_diagnostic"}:
        raise XingceAdaptivePolicyError("entry must be an authored diagnostic")
    correct = _score(entry, scorer, observation.selected_response)
    facts = _facts(f"entry:{entry_record_id}", observation, correct)
    if correct:
        return EntryDecision(entry_record_id, True, facts, (), None, "review_or_stop")
    causes = entry.get("candidate_misconception_ids")
    route_ids = entry.get("route_probe_ids")
    if not isinstance(causes, list) or len(causes) < 2 or not isinstance(route_ids, list):
        raise XingceAdaptivePolicyError("incorrect entry needs authored competing causes and probes")
    candidates = tuple(
        CandidateHypothesis(str(cause), _CANDIDATE_STATUS, rank, tuple(fact["fact_id"] for fact in facts))
        for rank, cause in enumerate(causes, start=1)
    )
    target_causes = set(causes)
    probes = [
        _record(index, str(record_id), "probe")
        for record_id in route_ids
        if set(_record(index, str(record_id), "probe").get("discriminates", [])) >= target_causes
    ]
    if not probes:
        raise XingceAdaptivePolicyError("entry has no probe that distinguishes every current candidate")
    return EntryDecision(entry_record_id, False, facts, candidates, str(probes[0]["record_id"]), "probe")


def resolve_probe(
    records: Sequence[Mapping[str, Any]], *, scorer: str, entry: EntryDecision, observation: Observation
) -> ProbeDecision:
    """Interpret an authored probe without promoting a hypothesis to fact."""

    if entry.next_step != "probe" or entry.probe_record_id is None or not entry.candidates:
        raise XingceAdaptivePolicyError("probe is unavailable for this entry decision")
    index = _index(records)
    probe = _record(index, entry.probe_record_id, "probe")
    correct = _score(probe, scorer, observation.selected_response)
    evidence_map = probe.get("candidate_evidence_map")
    if not isinstance(evidence_map, Mapping):
        raise XingceAdaptivePolicyError("probe lacks its candidate evidence map")
    updates = []
    for candidate in entry.candidates:
        outcomes = evidence_map.get(candidate.cause_id)
        outcome = outcomes.get(observation.selected_response, "insufficient") if isinstance(outcomes, Mapping) else "insufficient"
        if outcome not in {"support", "refute", "insufficient"}:
            raise XingceAdaptivePolicyError("probe produced an unsupported evidence outcome")
        updates.append({"cause_id": candidate.cause_id, "outcome": outcome, "status": _CANDIDATE_STATUS})
    supported = [item["cause_id"] for item in updates if item["outcome"] == "support"]
    target = supported[0] if supported else None
    teaching = next(
        (
            record for record in index.values()
            if record.get("role") == "teaching_asset" and target is not None and target in record.get("target_candidate_ids", [])
        ),
        None,
    )
    entry_record = _record(index, entry.entry_record_id)
    entry_groups = {entry_record.get("independence_group")}
    transfer = next(
        (
            record for record in index.values()
            if record.get("role") == "independent_transfer"
            and record.get("requires_no_hints") is True
            and record.get("independence_group") not in entry_groups
            and set(record.get("target_skill_ids", [])).intersection(entry_record.get("target_skill_ids", []))
        ),
        None,
    )
    if transfer is None:
        raise XingceAdaptivePolicyError("probe has no unseen independent transfer for the entry skill")
    return ProbeDecision(
        str(probe["record_id"]), correct, tuple(updates),
        str(teaching["record_id"]) if teaching is not None else None,
        str(transfer["record_id"]), target,
    )


def independent_transfer_proposal(
    records: Sequence[Mapping[str, Any]], *, scorer: str, entry: EntryDecision, probe: ProbeDecision, observation: Observation
) -> dict[str, Any]:
    """Create a bounded KT-commit proposal, never mutate learner state itself."""

    index = _index(records)
    transfer = _record(index, probe.transfer_record_id, "independent_transfer")
    entry_record = _record(index, entry.entry_record_id)
    if transfer.get("requires_no_hints") is not True or transfer.get("independence_group") == entry_record.get("independence_group"):
        raise XingceAdaptivePolicyError("transfer is not independent")
    correct = _score(transfer, scorer, observation.selected_response)
    observed = _facts(f"transfer:{transfer['record_id']}", observation, correct)
    if observation.hint_count != 0:
        return {
            "eligible": False,
            "reason": "transfer_was_assisted",
            "state_delta": None,
            "evidence": observed,
            "policy": {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION, "calibration_status": CALIBRATION_STATUS},
        }
    if not correct:
        return {
            "eligible": False,
            "reason": "independent_transfer_not_passed",
            "state_delta": None,
            "evidence": observed,
            "policy": {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION, "calibration_status": CALIBRATION_STATUS},
        }
    return {
        "eligible": True,
        "reason": "unseen_unassisted_transfer_passed",
        "state_delta": {
            "kind": "bounded_independent_transfer_evidence",
            "skill_ids": list(transfer["target_skill_ids"]),
            "candidate_status": _CANDIDATE_STATUS,
            "requires_deterministic_committer": True,
        },
        "evidence": observed,
        "policy": {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION, "calibration_status": CALIBRATION_STATUS},
    }
