"""Deterministic diagnosis and teaching policy for conditional reasoning.

This module deliberately has no persistence, catalog, UI, or model-provider
dependency.  A caller supplies already-validated authored pack records and the
observed answer.  The policy returns an inspectable recommendation; it never
asserts a learner's latent cause or writes mastery.

The two public stages mirror the learning loop:

``diagnose_entry``
    Separates scoring facts from at least two *unconfirmed* competing causes
    and selects one authored discriminating probe when possible.

``resolve_probe``
    Interprets the response only as support, refutation, or insufficient
    evidence, then selects a matching teaching asset and an unseen independent
    transfer item.  Neither result is a confirmation or a KT update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence


POLICY_ID = "lumi.judgment-conditional-policy"
POLICY_VERSION = "0.1.0"
CALIBRATION_STATUS = "uncalibrated"

_UNCONFIRMED = "unconfirmed"
_ENTRY_ROLES = frozenset({"entry_diagnostic", "routing_diagnostic"})
_PROBE_ROLE = "probe"
_TEACHING_ROLE = "teaching_asset"
_TRANSFER_ROLE = "independent_transfer"
_ALLOWED_CONFIDENCE = frozenset({"low", "medium", "high"})


class JudgmentPolicyError(ValueError):
    """Raised when policy inputs cannot be interpreted deterministically."""


@dataclass(frozen=True, slots=True)
class EntryObservation:
    """Scored entry-answer facts supplied by the scoring layer.

    ``correct_option`` is private scorer input, not a claim about a learner.
    ``hint_count`` records help received before the response; it never turns a
    response into independent-transfer evidence.
    """

    selected_option: str
    correct_option: str
    confidence: Literal["low", "medium", "high"]
    elapsed_seconds: float
    hint_count: int

    def __post_init__(self) -> None:
        selected = _option(self.selected_option, "selected_option")
        correct = _option(self.correct_option, "correct_option")
        confidence = str(self.confidence).strip().lower()
        if confidence not in _ALLOWED_CONFIDENCE:
            raise JudgmentPolicyError("confidence must be low, medium, or high")
        if not isinstance(self.elapsed_seconds, (int, float)) or isinstance(self.elapsed_seconds, bool):
            raise JudgmentPolicyError("elapsed_seconds must be a non-negative number")
        if self.elapsed_seconds < 0:
            raise JudgmentPolicyError("elapsed_seconds must be a non-negative number")
        if not isinstance(self.hint_count, int) or isinstance(self.hint_count, bool) or self.hint_count < 0:
            raise JudgmentPolicyError("hint_count must be a non-negative integer")
        object.__setattr__(self, "selected_option", selected)
        object.__setattr__(self, "correct_option", correct)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "elapsed_seconds", float(self.elapsed_seconds))

    @property
    def is_correct(self) -> bool:
        return self.selected_option == self.correct_option


@dataclass(frozen=True, slots=True)
class DecisionFact:
    """Observed, auditable input fact.  Facts are never inferred causes."""

    fact_id: str
    kind: str
    value: Any
    evidence: str


@dataclass(frozen=True, slots=True)
class HistoricalCandidateEvidence:
    """A replayable, non-diagnostic summary from earlier local sessions.

    Counts are observations of prior probe outcomes, not probabilities or an
    inferred learner trait.  They may break a tie only after the *current*
    probe supports more than one authored candidate; history alone can never
    select teaching, confirm a cause, or update learner state.
    """

    cause_id: str
    supported_count: int = 0
    refuted_count: int = 0
    insufficient_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.cause_id, str) or not self.cause_id.strip():
            raise JudgmentPolicyError("historical cause_id must be non-empty")
        for value in (self.supported_count, self.refuted_count, self.insufficient_count):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise JudgmentPolicyError("historical evidence counts must be non-negative integers")


@dataclass(frozen=True, slots=True)
class CandidateCause:
    """A ranked explanation that remains explicitly unconfirmed."""

    cause_id: str
    status: Literal["unconfirmed"]
    rank: int
    evidence_fact_ids: tuple[str, ...]
    rationale: str
    is_ground_truth: bool = False

    def __post_init__(self) -> None:
        if self.status != _UNCONFIRMED or self.is_ground_truth:
            raise JudgmentPolicyError("candidate causes must remain unconfirmed and non-ground-truth")
        if self.rank < 1:
            raise JudgmentPolicyError("candidate rank must start at one")
        if not self.evidence_fact_ids:
            raise JudgmentPolicyError("candidate cause requires observed evidence")


@dataclass(frozen=True, slots=True)
class ProbeCandidateAction:
    """An authored probe considered by the policy, including rejection reasons."""

    record_id: str
    discriminates: tuple[str, ...]
    coverage: tuple[str, ...]
    selected: bool
    why_selected: str | None
    why_not_selected: str | None

    def __post_init__(self) -> None:
        if self.selected == (self.why_selected is None):
            raise JudgmentPolicyError("selected actions need why_selected; rejected actions need why_not_selected")
        if self.selected and self.why_not_selected is not None:
            raise JudgmentPolicyError("selected action cannot have why_not_selected")
        if not self.selected and self.why_not_selected is None:
            raise JudgmentPolicyError("rejected action needs why_not_selected")


@dataclass(frozen=True, slots=True)
class ProbePlan:
    """A minimal, authored next probe or an explicit abstention."""

    selected_probe_id: str | None
    candidate_actions: tuple[ProbeCandidateAction, ...]
    why_selected: str
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS

    @property
    def is_abstention(self) -> bool:
        return self.selected_probe_id is None


@dataclass(frozen=True, slots=True)
class EntryPolicyDecision:
    """Policy result after one entry answer, before a probe response."""

    entry_record_id: str
    facts: tuple[DecisionFact, ...]
    candidate_causes: tuple[CandidateCause, ...]
    probe_plan: ProbePlan
    next_action: Literal["probe", "independent_transfer", "abstain"]
    historical_context: tuple[HistoricalCandidateEvidence, ...] = ()
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS

    def __post_init__(self) -> None:
        if self.next_action == "independent_transfer" and self.candidate_causes:
            raise JudgmentPolicyError("a correct entry answer must not create cause candidates")
        if self.next_action == "probe" and not self.probe_plan.selected_probe_id:
            raise JudgmentPolicyError("probe action requires a selected probe")
        if self.next_action == "abstain" and not self.probe_plan.is_abstention:
            raise JudgmentPolicyError("abstain action cannot select a probe")


@dataclass(frozen=True, slots=True)
class ProbeEvidence:
    """A non-confirmatory evidence update for one candidate cause."""

    cause_id: str
    outcome: Literal["support", "refute", "insufficient"]
    evidence: str
    status: Literal["unconfirmed"] = _UNCONFIRMED
    is_ground_truth: bool = False

    def __post_init__(self) -> None:
        if self.outcome not in {"support", "refute", "insufficient"}:
            raise JudgmentPolicyError("probe evidence outcome is invalid")
        if self.status != _UNCONFIRMED or self.is_ground_truth:
            raise JudgmentPolicyError("probe evidence must never confirm a cause")


@dataclass(frozen=True, slots=True)
class TeachingPlan:
    """A directly linked authored teaching asset, or a reasoned abstention."""

    selected_asset_id: str | None
    target_cause_id: str | None
    why_selected: str
    history_used_for_tie_break: bool = False
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS

    @property
    def is_abstention(self) -> bool:
        return self.selected_asset_id is None


@dataclass(frozen=True, slots=True)
class TransferPlan:
    """An authored unseen, unassisted transfer item, or an abstention."""

    selected_transfer_id: str | None
    target_skill_ids: tuple[str, ...]
    independence_group: str | None
    excluded_independence_groups: tuple[str, ...]
    requires_no_hints: bool
    why_selected: str
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS

    @property
    def is_abstention(self) -> bool:
        return self.selected_transfer_id is None


@dataclass(frozen=True, slots=True)
class ProbeResolution:
    """Result after a selected probe; it remains below the confirmation bar."""

    probe_record_id: str
    facts: tuple[DecisionFact, ...]
    evidence_updates: tuple[ProbeEvidence, ...]
    teaching_plan: TeachingPlan
    transfer_plan: TransferPlan
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION
    calibration_status: str = CALIBRATION_STATUS


def diagnose_entry(
    records: Sequence[Mapping[str, Any]],
    *,
    entry_record_id: str,
    observation: EntryObservation,
    historical_context: Sequence[HistoricalCandidateEvidence] = (),
) -> EntryPolicyDecision:
    """Diagnose a single entry answer without writing learner state.

    A wrong answer produces two competing candidates only when a single
    authored probe can distinguish them.  If the pack does not contain such a
    probe, the policy preserves the facts and deliberately abstains instead of
    inventing a causal route.
    """

    history = _normalized_historical_context(historical_context)
    index = _index_records(records)
    entry = _record(index, entry_record_id)
    if entry.get("role") not in _ENTRY_ROLES:
        raise JudgmentPolicyError("entry_record_id must name an authored entry diagnostic")
    _require_option(entry, observation.selected_option, "selected option")
    _require_option(entry, observation.correct_option, "correct option")
    authored_correct = _option_from_record(entry, "correct_option")
    if authored_correct != observation.correct_option:
        raise JudgmentPolicyError("observation correct_option does not match authored record")

    facts = _entry_facts(entry_record_id, observation, entry)
    if observation.is_correct:
        return EntryPolicyDecision(
            entry_record_id=entry_record_id,
            facts=facts,
            candidate_causes=(),
            probe_plan=ProbePlan(
                selected_probe_id=None,
                candidate_actions=(),
                why_selected="首答正确；不生成错因或微课，改用未见、无提示的独立迁移题验证是否可更新状态。",
            ),
            next_action="independent_transfer",
            historical_context=history,
        )

    candidate_ids = _minimal_discriminable_candidate_ids(entry, _probe_records(index))
    if len(candidate_ids) < 2:
        # The entry itself can name only one cause.  Add no causal guess and
        # make the absence of an actionable discriminator explicit.
        plan = _select_probe_plan(_probe_records(index), ())
        return EntryPolicyDecision(
            entry_record_id=entry_record_id,
            facts=facts,
            candidate_causes=(),
            probe_plan=plan,
            next_action="abstain",
            historical_context=history,
        )

    evidence_ids = tuple(fact.fact_id for fact in facts)
    candidates = tuple(
        CandidateCause(
            cause_id=cause_id,
            status=_UNCONFIRMED,
            rank=rank,
            evidence_fact_ids=evidence_ids,
            rationale=_candidate_rationale(entry, observation, cause_id),
        )
        for rank, cause_id in enumerate(candidate_ids, start=1)
    )
    plan = _select_probe_plan(_probe_records(index), candidate_ids)
    return EntryPolicyDecision(
        entry_record_id=entry_record_id,
        facts=facts,
        candidate_causes=candidates,
        probe_plan=plan,
        next_action="probe" if plan.selected_probe_id else "abstain",
        historical_context=history,
    )


def resolve_probe(
    records: Sequence[Mapping[str, Any]],
    *,
    decision: EntryPolicyDecision,
    selected_option: str,
) -> ProbeResolution:
    """Interpret one selected probe and route teaching plus independent transfer.

    The function rejects attempts to resolve a correct-entry route or to answer
    an unselected probe.  It returns only ``support``, ``refute``, or
    ``insufficient`` evidence; no response can transition a cause to
    ``confirmed``.
    """

    if decision.next_action != "probe" or not decision.probe_plan.selected_probe_id:
        raise JudgmentPolicyError("probe resolution requires a decision with a selected probe")
    index = _index_records(records)
    probe = _record(index, decision.probe_plan.selected_probe_id)
    if probe.get("role") != _PROBE_ROLE:
        raise JudgmentPolicyError("selected probe is not an authored probe")
    selected = _option(selected_option, "selected_option")
    _require_option(probe, selected, "selected option")
    candidates = tuple(candidate.cause_id for candidate in decision.candidate_causes)
    discriminates = _string_tuple(probe.get("discriminates"), "probe discriminates")
    if not set(candidates).issubset(discriminates):
        raise JudgmentPolicyError("selected probe no longer covers decision candidates")

    facts = (
        DecisionFact(
            fact_id=f"probe.{probe['record_id']}.selected_option",
            kind="selected_option",
            value=selected,
            evidence="学习者在已选择的最小探查题上提交的选项。",
        ),
        DecisionFact(
            fact_id=f"probe.{probe['record_id']}.correctness",
            kind="correctness",
            value=selected == _option_from_record(probe, "correct_option"),
            evidence="由已验证的 authored probe 答案键确定。",
        ),
    )
    updates = _probe_updates(probe, selected, candidates)
    teaching = _select_teaching_plan(index, updates, decision.historical_context)
    used_groups = _used_independence_groups(index, decision.entry_record_id, probe["record_id"], teaching.selected_asset_id)
    entry = _record(index, decision.entry_record_id)
    transfer = _select_transfer_plan(
        index,
        target_skill_ids=_string_tuple(entry.get("target_skill_ids"), "entry target_skill_ids"),
        excluded_independence_groups=used_groups,
    )
    return ProbeResolution(
        probe_record_id=str(probe["record_id"]),
        facts=facts,
        evidence_updates=updates,
        teaching_plan=teaching,
        transfer_plan=transfer,
    )


def _index_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for raw in records:
        if not isinstance(raw, Mapping):
            raise JudgmentPolicyError("pack record must be a mapping")
        record_id = raw.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise JudgmentPolicyError("pack record_id must be a non-empty string")
        if record_id in index:
            raise JudgmentPolicyError(f"duplicate pack record_id: {record_id}")
        index[record_id] = raw
    return index


def _record(index: Mapping[str, Mapping[str, Any]], record_id: str) -> Mapping[str, Any]:
    try:
        return index[record_id]
    except KeyError as exc:
        raise JudgmentPolicyError(f"unknown authored record: {record_id}") from exc


def _option(value: object, label: str) -> str:
    if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
        raise JudgmentPolicyError(f"{label} must be one of A, B, C, D")
    return value.strip().upper()


def _option_from_record(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    return _option(value, f"record {key}")


def _require_option(record: Mapping[str, Any], option: str, label: str) -> None:
    options = record.get("options")
    if not isinstance(options, Mapping) or option not in options:
        raise JudgmentPolicyError(f"{label} is not available in authored record")


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not value:
        raise JudgmentPolicyError(f"{label} must be a non-empty sequence")
    strings = tuple(item for item in value if isinstance(item, str) and item.strip())
    if len(strings) != len(value) or len(set(strings)) != len(strings):
        raise JudgmentPolicyError(f"{label} must contain unique non-empty strings")
    return strings


def _normalized_historical_context(
    values: Sequence[HistoricalCandidateEvidence],
) -> tuple[HistoricalCandidateEvidence, ...]:
    """Keep one bounded, explicit summary per cause without inventing scores."""

    history: dict[str, HistoricalCandidateEvidence] = {}
    for value in values:
        if not isinstance(value, HistoricalCandidateEvidence):
            raise JudgmentPolicyError("historical context must contain HistoricalCandidateEvidence")
        if value.cause_id in history:
            raise JudgmentPolicyError("historical context must not repeat a cause")
        history[value.cause_id] = value
    return tuple(history[cause_id] for cause_id in sorted(history))


def _entry_facts(
    entry_record_id: str,
    observation: EntryObservation,
    entry: Mapping[str, Any],
) -> tuple[DecisionFact, ...]:
    distractor_map = entry.get("distractor_map")
    distractor_reason = None
    if isinstance(distractor_map, Mapping) and not observation.is_correct:
        reason = distractor_map.get(observation.selected_option)
        if isinstance(reason, str) and reason.strip():
            distractor_reason = reason.strip()
    return (
        DecisionFact(
            fact_id=f"entry.{entry_record_id}.selected_option",
            kind="selected_option",
            value=observation.selected_option,
            evidence="学习者在首答中提交的选项。",
        ),
        DecisionFact(
            fact_id=f"entry.{entry_record_id}.correctness",
            kind="correctness",
            value=observation.is_correct,
            evidence="由已验证的 authored entry 答案键确定。",
        ),
        DecisionFact(
            fact_id=f"entry.{entry_record_id}.confidence",
            kind="confidence",
            value=observation.confidence,
            evidence="学习者自报的作答信心，不能单独诊断错因。",
        ),
        DecisionFact(
            fact_id=f"entry.{entry_record_id}.elapsed_seconds",
            kind="elapsed_seconds",
            value=observation.elapsed_seconds,
            evidence="本次作答所记录的用时，不能单独诊断错因。",
        ),
        DecisionFact(
            fact_id=f"entry.{entry_record_id}.hint_count",
            kind="hint_count",
            value=observation.hint_count,
            evidence="首答前已使用帮助的次数；有帮助作答不属于独立验证。",
        ),
        DecisionFact(
            fact_id=f"entry.{entry_record_id}.distractor_reason",
            kind="distractor_reason",
            value=distractor_reason,
            evidence="作者为该错误选项提供的干扰项标签；它只用于形成候选。",
        ),
    )


def _probe_records(index: Mapping[str, Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(record for _, record in sorted(index.items()) if record.get("role") == _PROBE_ROLE)


def _minimal_discriminable_candidate_ids(
    entry: Mapping[str, Any], probes: Iterable[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Pick the smallest candidate pair covered by one authored probe.

    This does not rank the learner's psychology.  It makes the policy's
    operational requirement explicit: without two alternatives that one probe
    can discriminate, a causal teaching route must abstain.
    """

    entry_candidates = _string_tuple(entry.get("candidate_misconception_ids"), "entry candidate_misconception_ids")
    candidate_set = set(entry_candidates)
    choices: list[tuple[int, tuple[str, ...], str]] = []
    for probe in probes:
        discriminates = _string_tuple(probe.get("discriminates"), "probe discriminates")
        overlap = tuple(candidate for candidate in discriminates if candidate in candidate_set)
        if len(overlap) >= 2:
            # Preserve authored discriminates order for a stable ranked output;
            # prefer exactly two alternatives over an unnecessarily broad probe.
            choices.append((len(overlap), overlap, str(probe["record_id"])))
    if not choices:
        # A wrong entry still warrants competing *unconfirmed* candidates when
        # the authored entry names them.  The later planning step will abstain
        # if no probe covers both; it must not silently collapse to one cause.
        return entry_candidates[:2] if len(entry_candidates) >= 2 else ()
    _, selected, _ = min(choices, key=lambda row: (row[0], row[2]))
    return selected[:2]


def _candidate_rationale(entry: Mapping[str, Any], observation: EntryObservation, cause_id: str) -> str:
    record_id = str(entry["record_id"])
    reason = None
    distractor_map = entry.get("distractor_map")
    if isinstance(distractor_map, Mapping):
        raw = distractor_map.get(observation.selected_option)
        if isinstance(raw, str) and raw.strip():
            reason = raw.strip()
    qualifiers = []
    if observation.confidence == "low":
        qualifiers.append("低信心使单次错误不足以区分概念与注意力因素")
    if observation.hint_count:
        qualifiers.append("已有帮助，不能把本次作答作为独立证据")
    qualifier = "；".join(qualifiers) if qualifiers else "单次选项证据不足以确认原因"
    reason_text = _learner_reason_copy(reason)
    return f"{record_id} 首答错误，{reason_text}；{qualifier}，故 {cause_id} 仅为候选。"


def _learner_reason_copy(reason: str | None) -> str:
    """Translate authored distractor metadata before it enters learner copy."""

    copy = {
        "converse": "所选项把单向条件读成了反向关系",
        "reversed_implication": "所选项把条件箭头写反了",
        "affirming_consequent": "所选项从结果反推原因",
        "necessary_condition_misread": "所选项没有区分必要条件与可逆关系",
        "positive_example_not_counterexample": "所选项把一个正例当成了反例",
        "violates_rule": "所选项与题设规则不相容",
        "unsupported_premise": "所选项加入了题设没有给出的信息",
        "irrelevant_conclusion": "所选项没有回应题设条件关系",
    }
    return copy.get(reason or "", "本次选项与题设条件关系不一致")


def _select_probe_plan(
    probes: Sequence[Mapping[str, Any]], candidate_ids: tuple[str, ...],
) -> ProbePlan:
    wanted = set(candidate_ids)
    viable: list[tuple[int, str, Mapping[str, Any]]] = []
    probe_details: list[tuple[Mapping[str, Any], tuple[str, ...], bool]] = []
    for probe in sorted(probes, key=lambda record: str(record["record_id"])):
        discriminates = _string_tuple(probe.get("discriminates"), "probe discriminates")
        coverage = tuple(candidate for candidate in discriminates if candidate in wanted)
        covers_all = bool(wanted) and wanted.issubset(discriminates)
        if covers_all:
            viable.append((len(discriminates) - len(wanted), str(probe["record_id"]), probe))
        probe_details.append((probe, coverage, covers_all))
    selected_id: str | None = None
    if viable:
        _, selected_id, _ = min(viable, key=lambda row: (row[0], row[1]))

    actions: list[ProbeCandidateAction] = []
    for probe, coverage, covers_all in probe_details:
        record_id = str(probe["record_id"])
        discriminates = _string_tuple(probe.get("discriminates"), "probe discriminates")
        if record_id == selected_id:
            actions.append(
                ProbeCandidateAction(
                    record_id=record_id,
                    discriminates=discriminates,
                    coverage=coverage,
                    selected=True,
                    why_selected=(
                        f"单题覆盖当前候选 {', '.join(candidate_ids)}；"
                        f"额外区分数最少，故是最小探查。"
                    ),
                    why_not_selected=None,
                )
            )
            continue
        if not wanted:
            rejection = "没有至少两个可操作的候选错因；不发起探查。"
        elif covers_all:
            rejection = "也覆盖全部候选，但排序后不是额外区分最少、记录号最小的最小探查。"
        elif coverage:
            missing = ", ".join(candidate for candidate in candidate_ids if candidate not in coverage)
            rejection = f"只覆盖 {', '.join(coverage)}，未覆盖 {missing}。"
        else:
            rejection = "与当前候选错因没有重叠。"
        actions.append(
            ProbeCandidateAction(
                record_id=record_id,
                discriminates=discriminates,
                coverage=coverage,
                selected=False,
                why_selected=None,
                why_not_selected=rejection,
            )
        )
    if selected_id:
        why_selected = f"选择 {selected_id} 作为单题最小探查；政策未校准，结果只会支持、反驳或证据不足。"
    elif wanted:
        why_selected = "没有一题能同时区分当前候选；为避免伪精确诊断而暂不教学。"
    else:
        why_selected = "没有可由作者探查题区分的至少两个候选；为避免单因归因而暂不教学。"
    return ProbePlan(
        selected_probe_id=selected_id,
        candidate_actions=tuple(actions),
        why_selected=why_selected,
    )


def _probe_updates(
    probe: Mapping[str, Any],
    selected_option: str,
    candidate_ids: tuple[str, ...],
) -> tuple[ProbeEvidence, ...]:
    authored_map = probe.get("candidate_evidence_map")
    if isinstance(authored_map, Mapping):
        per_option = authored_map.get(selected_option)
        if not isinstance(per_option, Mapping):
            raise JudgmentPolicyError("authored probe evidence map has no selected option")
        outcomes: dict[str, Literal["support", "refute", "insufficient"]] = {}
        for cause_id in candidate_ids:
            raw = per_option.get(cause_id)
            if raw not in {"support", "refute", "insufficient"}:
                raise JudgmentPolicyError("authored probe evidence map has an invalid candidate outcome")
            outcomes[cause_id] = raw
        return tuple(
            ProbeEvidence(
                cause_id=cause_id,
                outcome=outcomes[cause_id],
                evidence=(
                    f"作者为 {probe['record_id']} 的选项 {selected_option} 明确指定了"
                    f"对 {cause_id} 的 {outcomes[cause_id]} 证据；"
                    "该更新仍是未确认候选，不是对学习者的事实判断。"
                ),
            )
            for cause_id in candidate_ids
        )

    # Backward-compatible protection for an older authored fixture.  All
    # current production-candidate probes are schema-required to use the
    # explicit map above; never infer their evidence route from label tokens.
    correct = _option_from_record(probe, "correct_option")
    if selected_option == correct:
        return tuple(
            ProbeEvidence(
                cause_id=cause_id,
                outcome="refute",
                evidence="在该候选的最小探查上选择了正确答案；这只反驳当前单次候选，不确认其不存在。",
            )
            for cause_id in candidate_ids
        )

    reason = _distractor_reason(probe, selected_option)
    supporting = _causes_supported_by_reason(reason, candidate_ids)
    return tuple(
        ProbeEvidence(
            cause_id=cause_id,
            outcome="support" if cause_id in supporting else "insufficient",
            evidence=(
                f"探查错误选项的作者标签为 {reason or '未标注'}；"
                "该信号只能支持或保留候选，不能确认错因。"
            ),
        )
        for cause_id in candidate_ids
    )


def _distractor_reason(record: Mapping[str, Any], selected_option: str) -> str | None:
    distractor_map = record.get("distractor_map")
    if not isinstance(distractor_map, Mapping):
        return None
    reason = distractor_map.get(selected_option)
    return reason.strip() if isinstance(reason, str) and reason.strip() else None


def _causes_supported_by_reason(reason: str | None, candidate_ids: tuple[str, ...]) -> frozenset[str]:
    """Use authored distractor labels conservatively; never support every cause."""

    text = (reason or "").lower()
    token_map = {
        "M-DIR": ("reverse", "converse", "biconditional", "condition"),
        "M-ROLE": ("necessary", "sufficient", "role", "violates_rule"),
        "M-INF": ("affirming", "negation", "inference", "consequent", "antecedent"),
        "M-READ": ("unsupported", "irrelevant", "contradicts_given", "ignores"),
    }
    supported = {
        cause_id
        for cause_id in candidate_ids
        if any(token in text for token in token_map.get(cause_id, ()))
    }
    if supported:
        return frozenset(supported)
    # An authored label unknown to this deterministic policy cannot establish a
    # cause.  Preserve insufficiency instead of guessing.
    return frozenset()


def _select_teaching_plan(
    index: Mapping[str, Mapping[str, Any]],
    updates: Sequence[ProbeEvidence],
    historical_context: Sequence[HistoricalCandidateEvidence],
) -> TeachingPlan:
    supported = tuple(update.cause_id for update in updates if update.outcome == "support")
    if not supported:
        return TeachingPlan(
            selected_asset_id=None,
            target_cause_id=None,
            why_selected="探查没有支持任何候选；不把一次正确或含混反应转换成教学归因。",
        )
    assets = tuple(
        record for _, record in sorted(index.items()) if record.get("role") == _TEACHING_ROLE
    )
    candidates: list[tuple[str, str, Mapping[str, Any]]] = []
    for asset in assets:
        targets = _string_tuple(asset.get("candidate_misconception_ids"), "teaching candidate_misconception_ids")
        for cause_id in supported:
            if cause_id in targets:
                candidates.append((cause_id, str(asset["record_id"]), asset))
    if not candidates:
        return TeachingPlan(
            selected_asset_id=None,
            target_cause_id=None,
            why_selected="探查只支持了没有关联作者教学资产的候选；为避免泛化讲解而暂不教学。",
        )
    history_by_cause = {item.cause_id: item for item in historical_context}
    current_supported = set(supported)
    has_current_tie = len(current_supported) > 1

    def selection_key(row: tuple[str, str, Mapping[str, Any]]) -> tuple[int, int, str]:
        cause_id, asset_id, _ = row
        prior = history_by_cause.get(cause_id)
        prior_supports = prior.supported_count if prior is not None else 0
        # Current support is always the admission criterion.  Prior observations
        # can only resolve an otherwise-current tie, never elevate an unsupported
        # cause over a supported one.
        return (-prior_supports if has_current_tie else 0, supported.index(cause_id), asset_id)

    cause_id, asset_id, _ = min(candidates, key=selection_key)
    history_used = has_current_tie and any(
        item.supported_count > 0 for item in historical_context if item.cause_id in current_supported
    )
    history_note = (
        "；当前探查同时支持多个候选，才用同一学习者既往探查观察作同分排序，"
        "既往观察本身不触发教学也不确认错因。"
        if history_used
        else ""
    )
    return TeachingPlan(
        selected_asset_id=asset_id,
        target_cause_id=cause_id,
        why_selected=(
            f"当前探查支持候选 {cause_id}，选择其关联的作者教学资产 {asset_id}；"
            f"候选仍未确认。{history_note}"
        ),
        history_used_for_tie_break=history_used,
    )


def _used_independence_groups(
    index: Mapping[str, Mapping[str, Any]],
    *record_ids: str | None,
) -> tuple[str, ...]:
    groups: list[str] = []
    for record_id in record_ids:
        if not record_id:
            continue
        record = _record(index, record_id)
        group = record.get("independence_group")
        if not isinstance(group, str) or not group.strip():
            raise JudgmentPolicyError("selected authored record requires independence_group")
        groups.append(group)
    return tuple(groups)


def _select_transfer_plan(
    index: Mapping[str, Mapping[str, Any]],
    *,
    target_skill_ids: tuple[str, ...],
    excluded_independence_groups: tuple[str, ...],
) -> TransferPlan:
    excluded = set(excluded_independence_groups)
    candidates: list[tuple[int, str, Mapping[str, Any]]] = []
    for record_id, record in sorted(index.items()):
        if record.get("role") != _TRANSFER_ROLE or record.get("requires_no_hints") is not True:
            continue
        group = record.get("independence_group")
        if not isinstance(group, str) or not group.strip() or group in excluded:
            continue
        skills = _string_tuple(record.get("target_skill_ids"), "transfer target_skill_ids")
        overlap = len(set(skills).intersection(target_skill_ids))
        if overlap:
            candidates.append((-overlap, record_id, record))
    if not candidates:
        return TransferPlan(
            selected_transfer_id=None,
            target_skill_ids=(),
            independence_group=None,
            excluded_independence_groups=excluded_independence_groups,
            requires_no_hints=True,
            why_selected="没有与目标技能重叠、且独立组未使用的无提示迁移题；暂不把非独立题计入验证。",
        )
    _, record_id, record = min(candidates, key=lambda row: (row[0], row[1]))
    skills = _string_tuple(record.get("target_skill_ids"), "transfer target_skill_ids")
    group = str(record["independence_group"])
    overlap = tuple(skill for skill in skills if skill in set(target_skill_ids))
    return TransferPlan(
        selected_transfer_id=record_id,
        target_skill_ids=overlap,
        independence_group=group,
        excluded_independence_groups=excluded_independence_groups,
        requires_no_hints=True,
        why_selected=(
            f"选择 {record_id}：覆盖目标技能 {', '.join(overlap)}，"
            f"独立组 {group} 不在已使用组中，且作者要求无提示。"
        ),
    )
