from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .store import open_sqlite_connection, redact, retry_sqlite_locked


SCHEDULER_POLICY_VERSION = "lumi.deterministic-scheduler.v1"
SCHEDULE_SCHEMA_VERSION = "lumi.review-schedule.v1"
TODAY_PLAN_SCHEMA_VERSION = "lumi.today-plan.v1"
ACTIVITY_NOVELTY_STATUS = "same_fixture_retest_not_novel_item"
_ACTIVITY_REF_KEYS = frozenset(
    {
        "fixture_id",
        "fixture_content_sha256",
        "availability",
        "launch_method",
        "launch_endpoint",
        "launch_schema_version",
        "novelty_status",
    }
)

_SUCCESS_CRITERIA = {
    "cause_probe": (
        "在无提示的同题组独立复测中作答，并用证据支持或反驳该候选错因；"
        "本任务只记录同题组复测，不构成未见平行题上的迁移验证。"
    ),
    "delayed_retention": (
        "在无提示的同题组独立复测中再次达到既定评分标准；"
        "本任务只记录同题组复测，不构成未见平行题上的迁移验证。"
    ),
    "independent_retry": (
        "在无提示的同题组独立复测中达到既定评分标准；"
        "本任务只记录同题组复测，不构成未见平行题上的迁移验证。"
    ),
}
_SKIP_CONSEQUENCES = {
    "cause_probe": (
        "若跳过，该错因仍保持未确认；任务保留在 ReviewSchedule，"
        "并按后续学习日公平轮候。"
    ),
    "delayed_retention": (
        "若跳过，本次延迟保持仍未验证；任务保留在 ReviewSchedule，"
        "并按后续学习日公平轮候。"
    ),
    "independent_retry": (
        "若跳过，这条未通过证据不会消失；任务保留在 ReviewSchedule，"
        "并按后续学习日公平轮候。"
    ),
}

_TASK_STATES = frozenset(
    {"scheduled", "accepted", "completed", "postponed", "skipped"}
)
_TRANSITIONS = {
    "scheduled": frozenset({"accept", "postpone", "skip"}),
    "accepted": frozenset({"complete", "postpone", "skip"}),
    "completed": frozenset(),
    "postponed": frozenset({"resurface"}),
    "skipped": frozenset({"resurface"}),
}
_EVIDENCE_KINDS = frozenset(
    {
        "trace_observation",
        "trace_skill_evidence",
        "candidate_cause",
        "trace_terminal",
    }
)
_CLAIM_STATUSES = frozenset(
    {"unconfirmed_hypothesis", "supported_hypothesis", "refuted_hypothesis"}
)
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
_NATIONAL_ID_PATTERN = re.compile(r"\d{17}[0-9Xx]")
_PUBLIC_RUN_ID_PATTERN = re.compile(r"r_[A-P]{40}")
_PUBLIC_COMMAND_ID_PATTERN = re.compile(r"c_[A-P]{40}")
_SECRET_PATTERN = re.compile(
    r"(?:"
    r"sk[-_](?:live[-_])?[A-Za-z0-9_-]{16,}|"
    r"[rsp]k_live_[A-Za-z0-9]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"AIzaSy[A-Za-z0-9_-]{20,}|"
    r"npm_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r")",
    re.IGNORECASE,
)


class ScheduleError(RuntimeError):
    pass


class ScheduleNotFound(ScheduleError):
    pass


class ScheduleVersionConflict(ScheduleError):
    def __init__(self, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"schedule version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class ScheduleTaskVersionConflict(ScheduleError):
    def __init__(self, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"review task version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class ScheduleHistoricalPlan(ScheduleError):
    pass


class ScheduleBudgetBelowAcceptedCommitment(ScheduleError):
    def __init__(self, required_minutes: int) -> None:
        super().__init__(
            f"daily budget must be at least {required_minutes} minutes for accepted commitments"
        )
        self.required_minutes = required_minutes


class ScheduleCommandConflict(ScheduleError):
    pass


class ScheduleTransitionError(ScheduleError):
    pass


class ScheduleValidationError(ScheduleError):
    pass


@dataclass(frozen=True, slots=True)
class ActivityRef:
    fixture_id: str
    fixture_content_sha256: str
    availability: str
    launch_method: str = "POST"
    launch_endpoint: str = "/v1/attempts"
    launch_schema_version: str = "hermes.attempt-session.v1"
    novelty_status: str = ACTIVITY_NOVELTY_STATUS

    def __post_init__(self) -> None:
        if not self.fixture_id or len(self.fixture_id) > 200:
            raise ScheduleValidationError("activity fixture_id is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", self.fixture_content_sha256) is None:
            raise ScheduleValidationError("activity fixture hash is invalid")
        if self.availability not in {"launchable", "activity_unavailable"}:
            raise ScheduleValidationError("activity availability is invalid")
        if (
            self.launch_method != "POST"
            or self.launch_endpoint != "/v1/attempts"
            or self.launch_schema_version != "hermes.attempt-session.v1"
        ):
            raise ScheduleValidationError("activity launch contract is unsupported")
        if self.novelty_status != ACTIVITY_NOVELTY_STATUS:
            raise ScheduleValidationError("activity novelty contract is unsupported")


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    ref: str
    kind: str
    source_type: str
    run_id: str
    event_seq: int
    event_hash: str
    event_kind: str
    json_pointer: str
    semantic: str
    subject_id: str | None = None
    phase: str | None = None
    claim_status: str | None = None
    confirmation_status: str | None = None

    def __post_init__(self) -> None:
        if not self.ref or len(self.ref) > 512:
            raise ScheduleValidationError("evidence ref must be a short non-empty identifier")
        if self.kind not in _EVIDENCE_KINDS:
            raise ScheduleValidationError("unsupported scheduling evidence kind")
        if self.source_type != "trace_event":
            raise ScheduleValidationError("scheduling evidence must reference a trace event")
        if not valid_stored_run_identifier(self.run_id):
            raise ScheduleValidationError("evidence run_id is invalid")
        if isinstance(self.event_seq, bool) or not isinstance(self.event_seq, int) or self.event_seq < 1:
            raise ScheduleValidationError("evidence event_seq must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", self.event_hash) is None:
            raise ScheduleValidationError("evidence event_hash is invalid")
        if not self.event_kind or len(self.event_kind) > 80:
            raise ScheduleValidationError("evidence event_kind is invalid")
        if (
            not self.json_pointer.startswith("/")
            or len(self.json_pointer) > 240
            or any(ord(character) < 32 for character in self.json_pointer)
        ):
            raise ScheduleValidationError("evidence json_pointer is invalid")
        if self.semantic not in {
            "verification_effective",
            "initial_answer_passed",
            "candidate_hypothesis",
            "candidate_claim_status",
            "terminal_completed",
        }:
            raise ScheduleValidationError("evidence semantic is unsupported")
        semantic_contracts = {
            "verification_effective": (
                "trace_skill_evidence",
                "phase_completed",
                "update",
                r"/output/evidence/verification_effective",
            ),
            "initial_answer_passed": (
                "trace_observation",
                "phase_completed",
                "observe",
                r"/output/score/passed",
            ),
            "candidate_hypothesis": (
                "candidate_cause",
                "phase_completed",
                "diagnose",
                r"/output/diagnosis/hypotheses/\d+/status",
            ),
            "candidate_claim_status": (
                "candidate_cause",
                "probe_assessed",
                None,
                r"/assessments/\d+/claim_status",
            ),
            "terminal_completed": (
                "trace_terminal",
                "phase_completed",
                "reflect",
                r"/state_after/status",
            ),
        }
        expected_kind, expected_event_kind, expected_phase, pointer_pattern = (
            semantic_contracts[self.semantic]
        )
        if (
            self.kind != expected_kind
            or self.event_kind != expected_event_kind
            or self.phase != expected_phase
            or re.fullmatch(pointer_pattern, self.json_pointer) is None
        ):
            raise ScheduleValidationError(
                "evidence semantic is not bound to its authored trace location"
            )
        canonical_ref = (
            f"trace:{self.run_id}:event:{self.event_seq}:{self.event_hash}"
            f"#pointer={self.json_pointer}"
        )
        if self.ref != canonical_ref:
            raise ScheduleValidationError("evidence ref does not match its structured fields")
        if self.kind == "candidate_cause":
            if not self.subject_id or len(self.subject_id) > 160:
                raise ScheduleValidationError("candidate cause subject_id is invalid")
            if self.claim_status not in _CLAIM_STATUSES:
                raise ScheduleValidationError("candidate cause must retain its hypothesis status")
            if self.confirmation_status != "unconfirmed":
                raise ScheduleValidationError("candidate cause cannot be represented as confirmed")
            if self.semantic not in {
                "candidate_hypothesis",
                "candidate_claim_status",
            }:
                raise ScheduleValidationError("candidate cause semantic is invalid")
        elif self.kind == "trace_terminal":
            if self.subject_id is not None:
                raise ScheduleValidationError("terminal evidence cannot carry subject_id")
            if self.semantic != "terminal_completed":
                raise ScheduleValidationError("terminal evidence semantic is invalid")
            if self.claim_status is not None or self.confirmation_status is not None:
                raise ScheduleValidationError("terminal evidence cannot carry a cause claim")
        elif self.kind == "trace_observation":
            if self.semantic != "initial_answer_passed":
                raise ScheduleValidationError("observation evidence semantic is invalid")
            if (
                self.subject_id is not None
                or self.claim_status is not None
                or self.confirmation_status is not None
            ):
                raise ScheduleValidationError("observation evidence cannot carry a cause claim")
        elif self.claim_status is not None or self.confirmation_status is not None:
            raise ScheduleValidationError("skill evidence cannot carry a cause confirmation claim")
        elif self.subject_id is not None:
            raise ScheduleValidationError("skill evidence cannot carry subject_id")
        elif self.semantic != "verification_effective":
            raise ScheduleValidationError("skill evidence semantic is invalid")


@dataclass(frozen=True, slots=True)
class PlanningEvidence:
    evidence_ref: EvidenceRef
    supporting_refs: tuple[EvidenceRef, ...]
    occurred_at: str
    occurred_on: str
    timezone_offset_minutes: int
    domain: str
    skill_id: str
    verification_effective: bool | None
    attempt_failed: bool
    cause_id: str | None = None
    cause_label: str | None = None
    activity_ref: ActivityRef | None = None

    def __post_init__(self) -> None:
        occurred_at = _parse_datetime(self.occurred_at)
        occurred_on = _parse_date(self.occurred_on, "planning evidence occurred_on")
        if (
            isinstance(self.timezone_offset_minutes, bool)
            or not isinstance(self.timezone_offset_minutes, int)
            or not -720 <= self.timezone_offset_minutes <= 840
        ):
            raise ScheduleValidationError("planning timezone offset is invalid")
        local_time = occurred_at + timedelta(minutes=self.timezone_offset_minutes)
        if local_time.date() != occurred_on:
            raise ScheduleValidationError(
                "planning evidence local date does not match event time and offset"
            )
        refs = (self.evidence_ref, *self.supporting_refs)
        if any(ref.run_id != self.evidence_ref.run_id for ref in refs):
            raise ScheduleValidationError("planning evidence refs must belong to one run")
        if not any(ref.kind == "trace_terminal" for ref in refs):
            raise ScheduleValidationError("planning evidence requires completed-run provenance")
        if self.domain not in {"xingce", "shenlun", "interview"}:
            raise ScheduleValidationError("planning evidence has an unsupported domain")
        if not self.skill_id or len(self.skill_id) > 160:
            raise ScheduleValidationError("planning evidence requires a bounded skill identifier")
        if self.evidence_ref.kind == "candidate_cause":
            if not self.cause_id or len(self.cause_id) > 160:
                raise ScheduleValidationError("candidate-cause evidence requires cause_id")
            if not self.cause_label or len(self.cause_label) > 240:
                raise ScheduleValidationError("candidate-cause evidence requires authored label")
        elif self.cause_id is not None or self.cause_label is not None:
            raise ScheduleValidationError("only candidate-cause evidence may carry cause_id")
        if self.activity_ref is None:
            raise ScheduleValidationError("planning evidence requires immutable activity_ref")


@dataclass(frozen=True, slots=True)
class ScheduleTaskSpec:
    source_key: str
    task_kind: str
    domain: str
    skill_id: str
    reason: str
    expected_duration_minutes: int
    success_criterion: str
    skip_consequence: str
    evidence_refs: tuple[EvidenceRef, ...]
    activity_ref: ActivityRef
    policy_offset_days: int
    base_due_on: str
    scheduling_adjustment: str
    due_on: str
    cause_id: str | None = None
    cause_label: str | None = None
    cause_confirmation_status: str | None = None

    def __post_init__(self) -> None:
        if not self.source_key or len(self.source_key) > 240:
            raise ScheduleValidationError("task source key is invalid")
        if self.task_kind not in {"independent_retry", "cause_probe", "delayed_retention"}:
            raise ScheduleValidationError("task kind is invalid")
        if self.domain not in {"xingce", "shenlun", "interview"}:
            raise ScheduleValidationError("task domain is invalid")
        if not self.skill_id or len(self.skill_id) > 160:
            raise ScheduleValidationError("task skill_id is invalid")
        if not 1 <= self.expected_duration_minutes <= 60:
            raise ScheduleValidationError("task duration must be in [1, 60]")
        if not self.reason or not self.success_criterion or not self.skip_consequence:
            raise ScheduleValidationError("task explanation fields cannot be empty")
        if not self.evidence_refs:
            raise ScheduleValidationError("every scheduled task must cite recorded evidence")
        base_due = _parse_date(self.base_due_on, "task base_due_on")
        actual_due = _parse_date(self.due_on, "task due_on")
        expected_offset = 3 if self.task_kind == "delayed_retention" else 1
        if self.policy_offset_days != expected_offset:
            raise ScheduleValidationError("task policy offset does not match task kind")
        if actual_due < base_due:
            raise ScheduleValidationError("task due date cannot precede its policy window")
        expected_adjustment = (
            "overdue_catch_up" if actual_due > base_due else "on_policy_window"
        )
        if self.scheduling_adjustment != expected_adjustment:
            raise ScheduleValidationError("task scheduling adjustment is inconsistent")
        if self.activity_ref.availability != "launchable":
            raise ScheduleValidationError("scheduled task activity must be launchable")
        if self.task_kind == "cause_probe":
            if (
                not self.cause_id
                or not self.cause_label
                or self.cause_confirmation_status != "unconfirmed"
            ):
                raise ScheduleValidationError("cause probes must remain explicitly unconfirmed")
        elif (
            self.cause_id is not None
            or self.cause_label is not None
            or self.cause_confirmation_status is not None
        ):
            raise ScheduleValidationError("independent retry cannot carry a cause claim")


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    policy_version: str
    candidate_tasks: tuple[ScheduleTaskSpec, ...]
    evidence_status: str
    inputs_used: tuple[str, ...]
    excluded_inputs: tuple[str, ...]
    evidence_counts_by_domain: dict[str, int]
    workload_guardrail: dict[str, Any]
    exam_window: str


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    stream_type: str
    stream_id: str
    seq: int
    occurred_at: str
    kind: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


def build_scheduler_decision(
    evidence: Iterable[PlanningEvidence],
    *,
    plan_date: str,
    exam_date: str | None,
    daily_budget_minutes: int,
) -> SchedulerDecision:
    """Build a deterministic, evidence-bounded scheduling proposal.

    The function intentionally has no mastery-state input and no population or
    peer-data input. It consumes only recorded per-run evidence. Review tasks
    already due are merged transactionally by :class:`ScheduleStore`.
    """

    day = _parse_date(plan_date, "plan_date")
    exam = _parse_date(exam_date, "exam_date") if exam_date is not None else None
    if exam is not None and exam < day:
        raise ScheduleValidationError("exam_date cannot be before plan_date")
    if isinstance(daily_budget_minutes, bool) or not isinstance(daily_budget_minutes, int):
        raise ScheduleValidationError("daily_budget_minutes must be an integer")
    if not 5 <= daily_budget_minutes <= 240:
        raise ScheduleValidationError("daily_budget_minutes must be in [5, 240]")

    eligible: list[PlanningEvidence] = []
    recent: list[PlanningEvidence] = []
    for item in evidence:
        occurred = _parse_date(item.occurred_on, "planning evidence occurred_on")
        age_days = (day - occurred).days
        if age_days >= 0:
            eligible.append(item)
        if 0 <= age_days <= 14:
            recent.append(item)
    eligible.sort(key=lambda item: (item.occurred_at, item.evidence_ref.ref), reverse=True)
    recent.sort(key=lambda item: (item.occurred_at, item.evidence_ref.ref), reverse=True)

    evidence_counts_by_domain = {
        domain: 0 for domain in ("xingce", "shenlun", "interview")
    }
    run_refs: set[str] = set()
    failed_refs: set[str] = set()
    for item in recent:
        evidence_counts_by_domain[item.domain] += 1
        run_ref = item.evidence_ref.run_id
        run_refs.add(run_ref)
        if item.attempt_failed:
            failed_refs.add(run_ref)

    failed_count = len(failed_refs)
    recent_attempt_count = len(run_refs)
    if failed_count >= 3:
        max_non_accepted_tasks = 1
        mode = "recovery_load"
    elif failed_count >= 2:
        max_non_accepted_tasks = 2
        mode = "reduced_load"
    else:
        max_non_accepted_tasks = 3
        mode = "standard_load"

    if exam is None:
        exam_window = "not_provided"
    else:
        days = (exam - day).days
        exam_window = "near" if days <= 14 else "normal"

    candidates: list[tuple[tuple[Any, ...], ScheduleTaskSpec]] = []
    seen_sources: set[str] = set()
    withheld_activity_runs: set[str] = set()
    withheld_exam_deadline_runs: set[str] = set()
    cause_by_run = {
        item.evidence_ref.run_id: item
        for item in reversed(eligible)
        if item.evidence_ref.kind == "candidate_cause"
        and item.evidence_ref.claim_status != "refuted_hypothesis"
    }
    for item in eligible:
        if item.activity_ref is None or item.activity_ref.availability != "launchable":
            withheld_activity_runs.add(item.evidence_ref.run_id)
            continue
        evidence_day = _parse_date(item.occurred_on, "planning evidence occurred_on")

        def scheduled_due(
            offset_days: int,
        ) -> tuple[str, str, str] | None:
            base_target = evidence_day + timedelta(days=offset_days)
            target = max(day, base_target)
            if exam is not None and target > exam:
                return None
            adjustment = (
                "overdue_catch_up" if target > base_target else "on_policy_window"
            )
            return target.isoformat(), base_target.isoformat(), adjustment

        if item.evidence_ref.kind == "candidate_cause":
            if item.evidence_ref.claim_status == "refuted_hypothesis":
                continue
            source_key = "cause:" + _fingerprint(
                {
                    "policy_version": SCHEDULER_POLICY_VERSION,
                    "evidence": asdict(item.evidence_ref),
                    "cause_id": item.cause_id,
                }
            )
            due = scheduled_due(1)
            if due is None:
                withheld_exam_deadline_runs.add(item.evidence_ref.run_id)
                continue
            due_on, base_due_on, scheduling_adjustment = due
            spec = ScheduleTaskSpec(
                source_key=source_key,
                task_kind="cause_probe",
                domain=item.domain,
                skill_id=item.skill_id,
                reason=(
                    f"用定向题复核候选错因“{item.cause_label}”；它仍是未确认假设，"
                    "不能当作已经查明的原因。"
                    + (
                        " 原固定未校准 +1 天窗口已错过；今天仅作逾期补排。"
                        if scheduling_adjustment == "overdue_catch_up"
                        else ""
                    )
                ),
                expected_duration_minutes=12,
                success_criterion=_SUCCESS_CRITERIA["cause_probe"],
                skip_consequence=_SKIP_CONSEQUENCES["cause_probe"],
                evidence_refs=_unique_evidence_refs(
                    (item.evidence_ref, *item.supporting_refs)
                ),
                activity_ref=item.activity_ref,
                policy_offset_days=1,
                base_due_on=base_due_on,
                scheduling_adjustment=scheduling_adjustment,
                due_on=due_on,
                cause_id=item.cause_id,
                cause_label=item.cause_label,
                cause_confirmation_status="unconfirmed",
            )
            priority = (
                1,
                evidence_counts_by_domain[item.domain],
                -_datetime_sort_value(item.occurred_at),
                source_key,
            )
        else:
            source_key = "skill:" + _fingerprint(
                {
                    "policy_version": SCHEDULER_POLICY_VERSION,
                    "evidence": asdict(item.evidence_ref),
                    "skill_id": item.skill_id,
                }
            )
            if item.verification_effective is True and not item.attempt_failed:
                related_cause = cause_by_run.get(item.evidence_ref.run_id)
                due = scheduled_due(3)
                if due is None:
                    withheld_exam_deadline_runs.add(item.evidence_ref.run_id)
                    continue
                due_on, base_due_on, scheduling_adjustment = due
                spec = ScheduleTaskSpec(
                    source_key=source_key,
                    task_kind="delayed_retention",
                    domain=item.domain,
                    skill_id=item.skill_id,
                    reason=(
                        "已有一次独立迁移通过证据；"
                        + (
                            f"本轮候选错因“{related_cause.cause_label}”仍未确认；"
                            if related_cause is not None
                            else ""
                        )
                        + (
                            "原固定未校准 +3 天窗口已错过；今天仅作逾期补排，"
                            "不代表仍按 +3 天执行。"
                            if scheduling_adjustment == "overdue_catch_up"
                            else "按固定未校准 +3 天窗口安排延迟保持复核。"
                        )
                    ),
                    expected_duration_minutes=10,
                    success_criterion=_SUCCESS_CRITERIA["delayed_retention"],
                    skip_consequence=_SKIP_CONSEQUENCES["delayed_retention"],
                    evidence_refs=_unique_evidence_refs(
                        (
                            item.evidence_ref,
                            *item.supporting_refs,
                            related_cause.evidence_ref,
                            *related_cause.supporting_refs,
                        )
                        if related_cause is not None
                        else (item.evidence_ref, *item.supporting_refs)
                    ),
                    activity_ref=item.activity_ref,
                    policy_offset_days=3,
                    base_due_on=base_due_on,
                    scheduling_adjustment=scheduling_adjustment,
                    due_on=due_on,
                )
                priority = (
                    0,
                    evidence_counts_by_domain[item.domain],
                    -_datetime_sort_value(item.occurred_at),
                    source_key,
                )
            else:
                due = scheduled_due(1)
                if due is None:
                    withheld_exam_deadline_runs.add(item.evidence_ref.run_id)
                    continue
                due_on, base_due_on, scheduling_adjustment = due
                spec = ScheduleTaskSpec(
                    source_key=source_key,
                    task_kind="independent_retry",
                    domain=item.domain,
                    skill_id=item.skill_id,
                    reason=(
                        "最近一次单次学习证据未达到独立迁移标准，安排一次短复习。"
                        + (
                            " 原固定未校准 +1 天窗口已错过；今天仅作逾期补排。"
                            if scheduling_adjustment == "overdue_catch_up"
                            else ""
                        )
                    ),
                    expected_duration_minutes=15,
                    success_criterion=_SUCCESS_CRITERIA["independent_retry"],
                    skip_consequence=_SKIP_CONSEQUENCES["independent_retry"],
                    evidence_refs=_unique_evidence_refs(
                        (item.evidence_ref, *item.supporting_refs)
                    ),
                    activity_ref=item.activity_ref,
                    policy_offset_days=1,
                    base_due_on=base_due_on,
                    scheduling_adjustment=scheduling_adjustment,
                    due_on=due_on,
                )
                priority = (
                    2,
                    evidence_counts_by_domain[item.domain],
                    -_datetime_sort_value(item.occurred_at),
                    source_key,
                )
        if source_key not in seen_sources:
            seen_sources.add(source_key)
            candidates.append((priority, spec))

    candidates.sort(key=lambda item: item[0])
    selected_items: list[ScheduleTaskSpec] = []
    selected_run_refs: set[str] = set()
    for _, spec in candidates:
        run_ref = spec.evidence_refs[0].run_id
        if run_ref in selected_run_refs:
            continue
        selected_run_refs.add(run_ref)
        selected_items.append(spec)
    selected = tuple(selected_items)
    withheld_activity_count = len(withheld_activity_runs)
    withheld_exam_deadline_count = len(
        withheld_exam_deadline_runs - selected_run_refs
    )
    overdue_catch_up_count = sum(
        task.scheduling_adjustment == "overdue_catch_up" for task in selected
    )
    evidence_status = "recorded" if eligible else "unavailable"
    inputs_used = ["daily_budget_minutes"]
    if any(item.evidence_ref.kind == "trace_skill_evidence" for item in eligible):
        inputs_used.append("per_run_skill_evidence")
    if any(item.evidence_ref.kind == "candidate_cause" for item in eligible):
        inputs_used.append("candidate_causes")
    if recent:
        inputs_used.extend(
            [
                "recent_evidence_counts_by_domain",
                "workload_and_failed_attempt_guardrail",
            ]
        )
    if eligible:
        inputs_used.append("event_local_date_with_recorded_utc_offset")
    if exam is not None:
        inputs_used.append("exam_date")
    return SchedulerDecision(
        policy_version=SCHEDULER_POLICY_VERSION,
        candidate_tasks=selected,
        evidence_status=evidence_status,
        inputs_used=tuple(inputs_used),
        excluded_inputs=(
            "cohort_statistics",
            "peer_comparison",
            "population_effect",
            "authoritative_longitudinal_mastery",
            "learner_fatigue_signal",
        ),
        evidence_counts_by_domain=evidence_counts_by_domain,
        workload_guardrail={
            "mode": mode,
            "recent_attempt_count": recent_attempt_count,
            "recent_failed_attempt_count": failed_count,
            "eligible_evidence_count": len(eligible),
            "recent_evidence_count": len(recent),
            "max_non_accepted_tasks": max_non_accepted_tasks,
            "daily_budget_minutes": daily_budget_minutes,
            "withheld_activity_count": withheld_activity_count,
            "withheld_exam_deadline_count": withheld_exam_deadline_count,
            "overdue_catch_up_count": overdue_catch_up_count,
            "event_timezone_offsets_minutes": sorted(
                {item.timezone_offset_minutes for item in eligible}
            ),
            "basis": "fixed_engineering_policy_not_population_calibrated",
        },
        exam_window=exam_window,
    )


class ScheduleStore:
    """Independent ReviewSchedule and TodayPlan projections plus event streams."""

    def __init__(
        self,
        path: str | Path,
        *,
        planning_timezone: tzinfo = timezone.utc,
    ) -> None:
        self.path = str(path)
        if not isinstance(planning_timezone, tzinfo):
            raise ScheduleValidationError("planning_timezone must be tzinfo")
        self._planning_timezone = planning_timezone
        self._connection = open_sqlite_connection(self.path)
        retry_sqlite_locked(self._create_schema)

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_schedule_tasks (
                task_id TEXT PRIMARY KEY,
                source_key TEXT NOT NULL UNIQUE,
                task_kind TEXT NOT NULL,
                domain TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                expected_duration_minutes INTEGER NOT NULL,
                success_criterion TEXT NOT NULL,
                skip_consequence TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL,
                activity_ref_json TEXT NOT NULL,
                cause_id TEXT,
                cause_label TEXT,
                cause_confirmation_status TEXT,
                definition_status TEXT NOT NULL,
                policy_offset_days INTEGER NOT NULL,
                base_due_on TEXT NOT NULL,
                initial_due_on TEXT NOT NULL,
                scheduling_adjustment TEXT NOT NULL,
                completion_semantics TEXT,
                state TEXT NOT NULL,
                due_on TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS review_schedule_due_idx
                ON review_schedule_tasks(state, due_on, task_id);
            CREATE TRIGGER IF NOT EXISTS review_schedule_definition_immutable
            BEFORE UPDATE ON review_schedule_tasks
            WHEN NEW.task_id IS NOT OLD.task_id
              OR NEW.source_key IS NOT OLD.source_key
              OR NEW.task_kind IS NOT OLD.task_kind
              OR NEW.domain IS NOT OLD.domain
              OR NEW.skill_id IS NOT OLD.skill_id
              OR NEW.reason IS NOT OLD.reason
              OR NEW.expected_duration_minutes IS NOT OLD.expected_duration_minutes
              OR NEW.success_criterion IS NOT OLD.success_criterion
              OR NEW.skip_consequence IS NOT OLD.skip_consequence
              OR NEW.evidence_refs_json IS NOT OLD.evidence_refs_json
              OR NEW.activity_ref_json IS NOT OLD.activity_ref_json
              OR NEW.cause_id IS NOT OLD.cause_id
              OR NEW.cause_label IS NOT OLD.cause_label
              OR NEW.cause_confirmation_status IS NOT OLD.cause_confirmation_status
              OR NEW.definition_status IS NOT OLD.definition_status
              OR NEW.created_at IS NOT OLD.created_at
            BEGIN
                SELECT RAISE(ABORT, 'review task definition is immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS review_schedule_no_delete
            BEFORE DELETE ON review_schedule_tasks BEGIN
                SELECT RAISE(ABORT, 'review schedule tasks cannot be deleted');
            END;

            CREATE TABLE IF NOT EXISTS today_plans (
                plan_id TEXT PRIMARY KEY,
                plan_date TEXT NOT NULL UNIQUE,
                exam_date TEXT,
                status TEXT NOT NULL,
                version INTEGER NOT NULL CHECK(version > 0),
                scheduler_policy_version TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                basis_json TEXT NOT NULL,
                empty_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS today_plan_tasks (
                plan_id TEXT NOT NULL REFERENCES today_plans(plan_id),
                task_id TEXT NOT NULL REFERENCES review_schedule_tasks(task_id),
                ordinal INTEGER NOT NULL CHECK(ordinal > 0),
                state TEXT NOT NULL,
                task_snapshot_json TEXT NOT NULL,
                PRIMARY KEY(plan_id, task_id),
                UNIQUE(plan_id, ordinal)
            );
            CREATE TRIGGER IF NOT EXISTS today_plan_context_immutable
            BEFORE UPDATE ON today_plans
            WHEN NEW.plan_id IS NOT OLD.plan_id
              OR NEW.plan_date IS NOT OLD.plan_date
              OR NEW.exam_date IS NOT OLD.exam_date
              OR NEW.scheduler_policy_version IS NOT OLD.scheduler_policy_version
              OR NEW.input_digest IS NOT OLD.input_digest
              OR NEW.basis_json IS NOT OLD.basis_json
              OR NEW.empty_reason IS NOT OLD.empty_reason
              OR NEW.created_at IS NOT OLD.created_at
            BEGIN
                SELECT RAISE(ABORT, 'TodayPlan context is immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS today_plans_no_delete
            BEFORE DELETE ON today_plans BEGIN
                SELECT RAISE(ABORT, 'TodayPlans cannot be deleted');
            END;
            CREATE TRIGGER IF NOT EXISTS today_plan_membership_immutable
            BEFORE UPDATE ON today_plan_tasks
            WHEN NEW.plan_id IS NOT OLD.plan_id
              OR NEW.task_id IS NOT OLD.task_id
              OR NEW.ordinal IS NOT OLD.ordinal
            BEGIN
                SELECT RAISE(ABORT, 'TodayPlan task membership is immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS today_plan_tasks_no_delete
            BEFORE DELETE ON today_plan_tasks BEGIN
                SELECT RAISE(ABORT, 'TodayPlan task membership cannot be deleted');
            END;

            CREATE TABLE IF NOT EXISTS schedule_events (
                stream_type TEXT NOT NULL,
                stream_id TEXT NOT NULL,
                seq INTEGER NOT NULL CHECK(seq > 0),
                occurred_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                PRIMARY KEY(stream_type, stream_id, seq)
            );
            CREATE INDEX IF NOT EXISTS schedule_events_kind_idx
                ON schedule_events(stream_type, stream_id, kind, seq);
            CREATE TRIGGER IF NOT EXISTS schedule_events_no_update
            BEFORE UPDATE ON schedule_events BEGIN
                SELECT RAISE(ABORT, 'schedule_events is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS schedule_events_no_delete
            BEFORE DELETE ON schedule_events BEGIN
                SELECT RAISE(ABORT, 'schedule_events is append-only');
            END;

            CREATE TABLE IF NOT EXISTS schedule_command_results (
                command_id TEXT PRIMARY KEY,
                request_fingerprint TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS schedule_command_results_no_update
            BEFORE UPDATE ON schedule_command_results BEGIN
                SELECT RAISE(ABORT, 'schedule command results are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS schedule_command_results_no_delete
            BEFORE DELETE ON schedule_command_results BEGIN
                SELECT RAISE(ABORT, 'schedule command results are immutable');
            END;

            CREATE TABLE IF NOT EXISTS schedule_migrations (
                migration_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                task_ids_json TEXT NOT NULL,
                plan_ids_json TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS schedule_migrations_no_update
            BEFORE UPDATE ON schedule_migrations BEGIN
                SELECT RAISE(ABORT, 'schedule migrations are append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS schedule_migrations_no_delete
            BEFORE DELETE ON schedule_migrations BEGIN
                SELECT RAISE(ABORT, 'schedule migrations are append-only');
            END;
            """
        )
        connection = self._connection
        required_review_columns = {
            "policy_offset_days",
            "base_due_on",
            "initial_due_on",
            "scheduling_adjustment",
        }

        def migration_needed() -> bool:
            review_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(review_schedule_tasks)"
                ).fetchall()
            }
            if not required_review_columns.issubset(review_columns):
                return True
            for row in connection.execute(
                """
                SELECT task_kind, policy_offset_days, base_due_on,
                       initial_due_on, scheduling_adjustment,
                       activity_ref_json, success_criterion, skip_consequence
                FROM review_schedule_tasks
                """
            ).fetchall():
                task_kind = str(row["task_kind"])
                if task_kind not in {
                    "cause_probe",
                    "independent_retry",
                    "delayed_retention",
                }:
                    return True
                expected_offset = 3 if task_kind == "delayed_retention" else 1
                try:
                    base_due = _parse_date(
                        str(row["base_due_on"]), "stored task base_due_on"
                    )
                    initial_due = _parse_date(
                        str(row["initial_due_on"]), "stored task initial_due_on"
                    )
                except ScheduleValidationError:
                    return True
                expected_adjustment = (
                    "overdue_catch_up"
                    if initial_due > base_due
                    else "on_policy_window"
                )
                if (
                    row["policy_offset_days"] != expected_offset
                    or initial_due < base_due
                    or row["scheduling_adjustment"] != expected_adjustment
                ):
                    return True
                try:
                    activity = json.loads(row["activity_ref_json"])
                except (TypeError, json.JSONDecodeError):
                    return True
                if (
                    not isinstance(activity, dict)
                    or set(activity) != _ACTIVITY_REF_KEYS
                    or activity.get("novelty_status") != ACTIVITY_NOVELTY_STATUS
                    or row["success_criterion"] != _SUCCESS_CRITERIA[task_kind]
                    or row["skip_consequence"] != _SKIP_CONSEQUENCES[task_kind]
                ):
                    return True
            plan_task_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(today_plan_tasks)"
                ).fetchall()
            }
            if "task_snapshot_json" not in plan_task_columns:
                return True
            if connection.execute(
                """
                SELECT 1 FROM today_plan_tasks
                WHERE task_snapshot_json IS NULL OR trim(task_snapshot_json) = ''
                LIMIT 1
                """
            ).fetchone() is not None:
                return True
            for row in connection.execute(
                "SELECT basis_json FROM today_plans"
            ).fetchall():
                try:
                    basis = json.loads(row["basis_json"])
                except (TypeError, json.JSONDecodeError):
                    return True
                guardrail = basis.get("workload_guardrail") if isinstance(basis, dict) else None
                if (
                    not isinstance(guardrail, dict)
                    or "max_non_accepted_tasks" not in guardrail
                    or "max_new_tasks" in guardrail
                ):
                    return True
            return connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'trigger'
                  AND name = 'review_schedule_definition_immutable_v2'
                """
            ).fetchone() is None

        if not migration_needed():
            return

        connection.execute("BEGIN IMMEDIATE")
        try:
            if not migration_needed():
                connection.execute("COMMIT")
                return
            # A process may have stopped after adding one column but before its
            # backfill. Drop the v2 guard while the whole migration is repaired
            # atomically, then recreate it before commit.
            review_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(review_schedule_tasks)"
                ).fetchall()
            }
            additions = {
                "policy_offset_days": "INTEGER",
                "base_due_on": "TEXT",
                "initial_due_on": "TEXT",
                "scheduling_adjustment": "TEXT",
            }
            for column, column_type in additions.items():
                if column not in review_columns:
                    connection.execute(
                        f"ALTER TABLE review_schedule_tasks ADD COLUMN {column} {column_type}"
                    )

            migration_rows = connection.execute(
                """
                SELECT task_id, task_kind, due_on, policy_offset_days,
                       base_due_on, initial_due_on, scheduling_adjustment
                FROM review_schedule_tasks
                """
            ).fetchall()
            repairs: list[tuple[int, str, str, str, str]] = []
            for row in migration_rows:
                task_kind = str(row["task_kind"])
                if task_kind not in {
                    "cause_probe",
                    "independent_retry",
                    "delayed_retention",
                }:
                    raise ScheduleError("stored review task has an unsupported kind")
                due_on = _parse_date(str(row["due_on"]), "stored task due_on")
                expected_offset = 3 if task_kind == "delayed_retention" else 1
                try:
                    base_due = _parse_date(
                        str(row["base_due_on"]), "stored task base_due_on"
                    )
                except ScheduleValidationError:
                    base_due = due_on
                try:
                    initial_due = _parse_date(
                        str(row["initial_due_on"]), "stored task initial_due_on"
                    )
                except ScheduleValidationError:
                    initial_due = due_on
                if initial_due < base_due:
                    initial_due = max(base_due, due_on)
                adjustment = (
                    "overdue_catch_up"
                    if initial_due > base_due
                    else "on_policy_window"
                )
                repaired = (
                    expected_offset,
                    base_due.isoformat(),
                    initial_due.isoformat(),
                    adjustment,
                    str(row["task_id"]),
                )
                stored = (
                    row["policy_offset_days"],
                    row["base_due_on"],
                    row["initial_due_on"],
                    row["scheduling_adjustment"],
                    str(row["task_id"]),
                )
                if stored != repaired:
                    repairs.append(repaired)

            if repairs:
                connection.execute(
                    "DROP TRIGGER IF EXISTS review_schedule_definition_immutable_v2"
                )
                connection.executemany(
                    """
                    UPDATE review_schedule_tasks
                    SET policy_offset_days = ?, base_due_on = ?,
                        initial_due_on = ?, scheduling_adjustment = ?
                    WHERE task_id = ?
                    """,
                    repairs,
                )

            connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS review_schedule_definition_immutable_v2
                BEFORE UPDATE ON review_schedule_tasks
                WHEN NEW.policy_offset_days IS NOT OLD.policy_offset_days
                  OR NEW.base_due_on IS NOT OLD.base_due_on
                  OR NEW.initial_due_on IS NOT OLD.initial_due_on
                  OR NEW.scheduling_adjustment IS NOT OLD.scheduling_adjustment
                BEGIN
                    SELECT RAISE(ABORT, 'review task schedule window is immutable');
                END
                """
            )

            # Development builds may already contain the initial P0.2 table
            # shape. Keep each TodayPlan as a historical task snapshot.
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(today_plan_tasks)"
                ).fetchall()
            }
            if "task_snapshot_json" not in columns:
                connection.execute(
                    "ALTER TABLE today_plan_tasks ADD COLUMN task_snapshot_json TEXT"
                )
            rows = connection.execute(
                """
                SELECT p.plan_id, p.task_id, p.task_snapshot_json, r.*
                FROM today_plan_tasks p
                JOIN review_schedule_tasks r ON r.task_id = p.task_id
                WHERE p.task_snapshot_json IS NULL OR trim(p.task_snapshot_json) = ''
                """
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE today_plan_tasks SET task_snapshot_json = ?
                    WHERE plan_id = ? AND task_id = ?
                    """,
                    (
                        _canonical_json(_task_from_row(row)),
                        str(row["plan_id"]),
                        str(row["task_id"]),
                    ),
                )
            missing_snapshot = connection.execute(
                """
                SELECT 1 FROM today_plan_tasks
                WHERE task_snapshot_json IS NULL OR trim(task_snapshot_json) = ''
                LIMIT 1
                """
            ).fetchone()
            if missing_snapshot is not None:
                raise ScheduleError("TodayPlan task snapshot migration is incomplete")

            definition_rows = connection.execute(
                "SELECT * FROM review_schedule_tasks ORDER BY task_id"
            ).fetchall()
            legacy_definitions: list[tuple[sqlite3.Row, dict[str, Any]]] = []
            for row in definition_rows:
                task_kind = str(row["task_kind"])
                try:
                    raw_activity = json.loads(row["activity_ref_json"])
                except (TypeError, json.JSONDecodeError):
                    raise ScheduleError(
                        "stored review task activity contract is invalid"
                    ) from None
                if not isinstance(raw_activity, dict):
                    raise ScheduleError(
                        "stored review task activity contract is invalid"
                    )
                if (
                    set(raw_activity) != _ACTIVITY_REF_KEYS
                    or raw_activity.get("novelty_status")
                    != ACTIVITY_NOVELTY_STATUS
                    or row["success_criterion"] != _SUCCESS_CRITERIA[task_kind]
                    or row["skip_consequence"] != _SKIP_CONSEQUENCES[task_kind]
                ):
                    legacy_definitions.append((row, raw_activity))

            if legacy_definitions:
                occurred_at = _utc_now()
                source_contracts = [
                    {
                        "task_id": str(row["task_id"]),
                        "task_kind": str(row["task_kind"]),
                        "version": int(row["version"]),
                        "activity_ref": activity,
                        "success_criterion": str(row["success_criterion"]),
                        "skip_consequence": str(row["skip_consequence"]),
                    }
                    for row, activity in legacy_definitions
                ]
                source_digest = _fingerprint(source_contracts)
                migration_id = "migration-" + _fingerprint(
                    {
                        "kind": "pre_release_schedule_contract_v2",
                        "source_digest": source_digest,
                    }
                )[:24]
                connection.execute(
                    "DROP TRIGGER IF EXISTS review_schedule_definition_immutable"
                )
                migrated_task_ids: list[str] = []
                for row, raw_activity in legacy_definitions:
                    if set(raw_activity) - _ACTIVITY_REF_KEYS:
                        raise ScheduleError(
                            "legacy review task activity contains unknown fields"
                        )
                    activity = ActivityRef(
                        fixture_id=str(raw_activity.get("fixture_id", "")),
                        fixture_content_sha256=str(
                            raw_activity.get("fixture_content_sha256", "")
                        ),
                        availability=str(raw_activity.get("availability", "")),
                        launch_method=str(raw_activity.get("launch_method", "POST")),
                        launch_endpoint=str(
                            raw_activity.get("launch_endpoint", "/v1/attempts")
                        ),
                        launch_schema_version=str(
                            raw_activity.get(
                                "launch_schema_version",
                                "hermes.attempt-session.v1",
                            )
                        ),
                        novelty_status=ACTIVITY_NOVELTY_STATUS,
                    )
                    task_id = str(row["task_id"])
                    task_kind = str(row["task_kind"])
                    connection.execute(
                        """
                        UPDATE review_schedule_tasks
                        SET success_criterion = ?, skip_consequence = ?,
                            activity_ref_json = ?, version = version + 1,
                            updated_at = ?
                        WHERE task_id = ?
                        """,
                        (
                            _SUCCESS_CRITERIA[task_kind],
                            _SKIP_CONSEQUENCES[task_kind],
                            _canonical_json(asdict(activity)),
                            occurred_at,
                            task_id,
                        ),
                    )
                    migrated_task_ids.append(task_id)

                connection.execute(
                    """
                    CREATE TRIGGER review_schedule_definition_immutable
                    BEFORE UPDATE ON review_schedule_tasks
                    WHEN NEW.task_id IS NOT OLD.task_id
                      OR NEW.source_key IS NOT OLD.source_key
                      OR NEW.task_kind IS NOT OLD.task_kind
                      OR NEW.domain IS NOT OLD.domain
                      OR NEW.skill_id IS NOT OLD.skill_id
                      OR NEW.reason IS NOT OLD.reason
                      OR NEW.expected_duration_minutes IS NOT OLD.expected_duration_minutes
                      OR NEW.success_criterion IS NOT OLD.success_criterion
                      OR NEW.skip_consequence IS NOT OLD.skip_consequence
                      OR NEW.evidence_refs_json IS NOT OLD.evidence_refs_json
                      OR NEW.activity_ref_json IS NOT OLD.activity_ref_json
                      OR NEW.cause_id IS NOT OLD.cause_id
                      OR NEW.cause_label IS NOT OLD.cause_label
                      OR NEW.cause_confirmation_status IS NOT OLD.cause_confirmation_status
                      OR NEW.definition_status IS NOT OLD.definition_status
                      OR NEW.created_at IS NOT OLD.created_at
                    BEGIN
                        SELECT RAISE(ABORT, 'review task definition is immutable');
                    END
                    """
                )

                placeholders = ",".join("?" for _ in migrated_task_ids)
                membership_rows = connection.execute(
                    f"""
                    SELECT plan_id, task_id, task_snapshot_json
                    FROM today_plan_tasks
                    WHERE task_id IN ({placeholders})
                    ORDER BY plan_id, task_id
                    """,
                    migrated_task_ids,
                ).fetchall()
                migrated_plan_ids: set[str] = set()
                task_versions = {
                    str(row["task_id"]): int(row["version"])
                    for row in connection.execute(
                        f"""
                        SELECT task_id, version FROM review_schedule_tasks
                        WHERE task_id IN ({placeholders})
                        """,
                        migrated_task_ids,
                    ).fetchall()
                }
                task_definitions = {
                    str(row["task_id"]): _task_from_row(row)
                    for row in connection.execute(
                        f"""
                        SELECT * FROM review_schedule_tasks
                        WHERE task_id IN ({placeholders})
                        """,
                        migrated_task_ids,
                    ).fetchall()
                }
                for row in membership_rows:
                    try:
                        snapshot = json.loads(row["task_snapshot_json"])
                    except (TypeError, json.JSONDecodeError):
                        raise ScheduleError(
                            "legacy TodayPlan task snapshot is invalid"
                        ) from None
                    if not isinstance(snapshot, dict):
                        raise ScheduleError(
                            "legacy TodayPlan task snapshot is invalid"
                        )
                    task_id = str(row["task_id"])
                    definition = task_definitions[task_id]
                    snapshot["success_criterion"] = definition[
                        "success_criterion"
                    ]
                    snapshot["skip_consequence"] = definition["skip_consequence"]
                    snapshot["activity_ref"] = definition["activity_ref"]
                    snapshot["version"] = int(snapshot.get("version", 0)) + 1
                    snapshot["updated_at"] = occurred_at
                    connection.execute(
                        """
                        UPDATE today_plan_tasks SET task_snapshot_json = ?
                        WHERE plan_id = ? AND task_id = ?
                        """,
                        (
                            _canonical_json(snapshot),
                            str(row["plan_id"]),
                            task_id,
                        ),
                    )
                    migrated_plan_ids.add(str(row["plan_id"]))

                for plan_id in sorted(migrated_plan_ids):
                    connection.execute(
                        """
                        UPDATE today_plans
                        SET version = version + 1, updated_at = ?
                        WHERE plan_id = ?
                        """,
                        (occurred_at, plan_id),
                    )

                for task_id in migrated_task_ids:
                    task = task_definitions[task_id]
                    if task["version"] != task_versions[task_id]:
                        raise ScheduleError("migrated review task version is inconsistent")
                    self._validate_task_provenance(task)
                    self._append_event(
                        "review_task",
                        task_id,
                        "task_contract_migrated",
                        {
                            "schema_version": SCHEDULE_SCHEMA_VERSION,
                            "migration_id": migration_id,
                            "source_contract_digest": source_digest,
                            "task_after": task,
                        },
                        occurred_at,
                    )
                for plan_id in sorted(migrated_plan_ids):
                    plan_after = self._load_plan_in_transaction(plan_id)
                    self._append_event(
                        "today_plan",
                        plan_id,
                        "today_plan_contract_migrated",
                        {
                            "schema_version": TODAY_PLAN_SCHEMA_VERSION,
                            "migration_id": migration_id,
                            "source_contract_digest": source_digest,
                            "plan_after": plan_after,
                        },
                        occurred_at,
                    )
                connection.execute(
                    """
                    INSERT INTO schedule_migrations
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        migration_id,
                        "pre_release_schedule_contract_v2",
                        occurred_at,
                        source_digest,
                        _canonical_json(sorted(migrated_task_ids)),
                        _canonical_json(sorted(migrated_plan_ids)),
                    ),
                )

            legacy_basis_rows: list[tuple[sqlite3.Row, dict[str, Any]]] = []
            for row in connection.execute(
                "SELECT plan_id, basis_json, version FROM today_plans ORDER BY plan_id"
            ).fetchall():
                try:
                    basis = json.loads(row["basis_json"])
                except (TypeError, json.JSONDecodeError):
                    raise ScheduleError("stored TodayPlan basis is invalid") from None
                guardrail = basis.get("workload_guardrail") if isinstance(basis, dict) else None
                if not isinstance(guardrail, dict):
                    raise ScheduleError("stored TodayPlan workload guardrail is invalid")
                if (
                    "max_non_accepted_tasks" not in guardrail
                    or "max_new_tasks" in guardrail
                ):
                    legacy_basis_rows.append((row, basis))

            if legacy_basis_rows:
                occurred_at = _utc_now()
                source_basis = [
                    {
                        "plan_id": str(row["plan_id"]),
                        "version": int(row["version"]),
                        "basis": basis,
                    }
                    for row, basis in legacy_basis_rows
                ]
                source_digest = _fingerprint(source_basis)
                migration_id = "migration-" + _fingerprint(
                    {
                        "kind": "pre_release_workload_limit_contract_v2",
                        "source_digest": source_digest,
                    }
                )[:24]
                connection.execute(
                    "DROP TRIGGER IF EXISTS today_plan_context_immutable"
                )
                migrated_plan_ids: list[str] = []
                for row, basis in legacy_basis_rows:
                    guardrail = dict(basis["workload_guardrail"])
                    legacy_limit = guardrail.pop("max_new_tasks", None)
                    current_limit = guardrail.get("max_non_accepted_tasks")
                    limit = current_limit if current_limit is not None else legacy_limit
                    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 3:
                        raise ScheduleError(
                            "stored TodayPlan presentation limit is invalid"
                        )
                    guardrail["max_non_accepted_tasks"] = limit
                    basis["workload_guardrail"] = guardrail
                    plan_id = str(row["plan_id"])
                    connection.execute(
                        """
                        UPDATE today_plans
                        SET basis_json = ?, version = version + 1, updated_at = ?
                        WHERE plan_id = ?
                        """,
                        (_canonical_json(basis), occurred_at, plan_id),
                    )
                    migrated_plan_ids.append(plan_id)

                connection.execute(
                    """
                    CREATE TRIGGER today_plan_context_immutable
                    BEFORE UPDATE ON today_plans
                    WHEN NEW.plan_id IS NOT OLD.plan_id
                      OR NEW.plan_date IS NOT OLD.plan_date
                      OR NEW.exam_date IS NOT OLD.exam_date
                      OR NEW.scheduler_policy_version IS NOT OLD.scheduler_policy_version
                      OR NEW.input_digest IS NOT OLD.input_digest
                      OR NEW.basis_json IS NOT OLD.basis_json
                      OR NEW.empty_reason IS NOT OLD.empty_reason
                      OR NEW.created_at IS NOT OLD.created_at
                    BEGIN
                        SELECT RAISE(ABORT, 'TodayPlan context is immutable');
                    END
                    """
                )
                for plan_id in migrated_plan_ids:
                    plan_after = self._load_plan_in_transaction(plan_id)
                    self._append_event(
                        "today_plan",
                        plan_id,
                        "today_plan_workload_contract_migrated",
                        {
                            "schema_version": TODAY_PLAN_SCHEMA_VERSION,
                            "migration_id": migration_id,
                            "source_contract_digest": source_digest,
                            "plan_after": plan_after,
                        },
                        occurred_at,
                    )
                connection.execute(
                    """
                    INSERT INTO schedule_migrations
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        migration_id,
                        "pre_release_workload_limit_contract_v2",
                        occurred_at,
                        source_digest,
                        _canonical_json([]),
                        _canonical_json(sorted(migrated_plan_ids)),
                    ),
                )
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _validate_task_provenance(self, task: Mapping[str, Any]) -> None:
        try:
            refs = tuple(
                item if isinstance(item, EvidenceRef) else EvidenceRef(**item)
                for item in task["evidence_refs"]
            )
        except (KeyError, TypeError, ScheduleValidationError) as exc:
            raise ScheduleError("review task evidence contract is invalid") from exc
        if not refs:
            raise ScheduleError("review task has no trace evidence")
        if len({ref.ref for ref in refs}) != len(refs):
            raise ScheduleError("review task contains duplicate evidence refs")
        run_ids = {ref.run_id for ref in refs}
        if len(run_ids) != 1:
            raise ScheduleError("review task evidence crosses learner runs")
        events = self._verified_trace_events(next(iter(run_ids)))
        terminal_seen = False
        terminal_state: dict[str, Any] | None = None
        terminal_sequences: list[int] = []
        evidence_sequences: list[int] = []
        verification_values: list[Any] = []
        verification_events: list[tuple[EvidenceRef, dict[str, Any]]] = []
        observation_values: list[bool] = []
        observation_events: list[EvidenceRef] = []
        candidate_claim_refs: list[EvidenceRef] = []
        candidate_subjects: set[str] = set()
        for ref in refs:
            event = events.get(ref.event_seq)
            if (
                event is None
                or str(event["event_hash"]) != ref.event_hash
                or str(event["kind"]) != ref.event_kind
            ):
                raise ScheduleError("review task evidence event identity is invalid")
            payload = json.loads(event["payload_json"])
            if ref.phase is not None and payload.get("phase") != ref.phase:
                raise ScheduleError("review task evidence phase is invalid")
            value = _json_pointer_value(payload, ref.json_pointer)
            if ref.semantic == "terminal_completed":
                if value != "completed":
                    raise ScheduleError("review task source run is not completed")
                state_after = payload.get("state_after")
                if not isinstance(state_after, dict):
                    raise ScheduleError("review task terminal state is invalid")
                if terminal_state is not None and terminal_state != state_after:
                    raise ScheduleError("review task terminal evidence is inconsistent")
                terminal_state = state_after
                terminal_seen = True
                terminal_sequences.append(ref.event_seq)
            elif ref.semantic == "verification_effective":
                if value is not None and not isinstance(value, bool):
                    raise ScheduleError("verification evidence has an invalid value")
                verification_values.append(value)
                verification_events.append((ref, payload))
                evidence_sequences.append(ref.event_seq)
            elif ref.semantic == "initial_answer_passed":
                if not isinstance(value, bool):
                    raise ScheduleError("initial-answer evidence has an invalid value")
                observation_values.append(value)
                observation_events.append(ref)
                evidence_sequences.append(ref.event_seq)
            else:
                if value != ref.claim_status:
                    raise ScheduleError("candidate claim status does not match trace evidence")
                parent_pointer = ref.json_pointer.rsplit("/", 1)[0]
                parent = _json_pointer_value(payload, parent_pointer)
                if (
                    not isinstance(parent, dict)
                    or parent.get("cause_id") != ref.subject_id
                ):
                    raise ScheduleError("candidate evidence does not match its cause")
                candidate_subjects.add(str(ref.subject_id))
                if ref.semantic == "candidate_claim_status":
                    candidate_claim_refs.append(ref)
                evidence_sequences.append(ref.event_seq)
        if not terminal_seen:
            raise ScheduleError("review task lacks completed-run provenance")
        if terminal_state is None:
            raise ScheduleError("review task terminal state is unavailable")
        if evidence_sequences and min(terminal_sequences) <= max(evidence_sequences):
            raise ScheduleError("completed-run evidence precedes its scheduling evidence")
        if terminal_sequences != [max(events)]:
            raise ScheduleError("completed-run evidence is not the latest trace event")
        observe_sequences = [
            seq
            for seq, event in events.items()
            if str(event["kind"]) == "phase_completed"
            and json.loads(event["payload_json"]).get("phase") == "observe"
        ]
        if observation_events and (
            len(observation_events) != 1
            or not observe_sequences
            or observation_events[0].event_seq != max(observe_sequences)
        ):
            raise ScheduleError("initial-answer evidence is not the latest observe event")
        committed_updates = [
            seq
            for seq, event in events.items()
            if str(event["kind"]) == "phase_completed"
            and json.loads(event["payload_json"]).get("phase") == "update"
            and json.loads(event["payload_json"])
            .get("output", {})
            .get("commit_status")
            == "committed"
        ]
        for ref, payload in verification_events:
            output = payload.get("output", {})
            if (
                output.get("commit_status") != "committed"
                or output.get("skill_id") != task.get("skill_id")
                or not committed_updates
                or ref.event_seq != max(committed_updates)
            ):
                raise ScheduleError(
                    "verification evidence is not the latest committed update for its skill"
                )
        latest_assessment_by_cause: dict[str, tuple[int, str]] = {}
        for seq, event in events.items():
            if str(event["kind"]) != "probe_assessed":
                continue
            payload = json.loads(event["payload_json"])
            for assessment in payload.get("assessments", []):
                if not isinstance(assessment, dict):
                    continue
                cause_id = assessment.get("cause_id")
                claim_status = assessment.get("claim_status")
                if isinstance(cause_id, str) and isinstance(claim_status, str):
                    latest_assessment_by_cause[cause_id] = (seq, claim_status)
        for ref in candidate_claim_refs:
            latest = latest_assessment_by_cause.get(str(ref.subject_id))
            if (
                latest is None
                or latest != (ref.event_seq, ref.claim_status)
                or ref.claim_status == "refuted_hypothesis"
            ):
                raise ScheduleError(
                    "candidate evidence is not the latest non-refuted assessment"
                )
        task_kind = task.get("task_kind")
        if task_kind == "delayed_retention" and True not in verification_values:
            raise ScheduleError("delayed retention lacks successful transfer evidence")
        if task_kind == "independent_retry" and (
            not verification_values or all(value is True for value in verification_values)
        ):
            raise ScheduleError("independent retry lacks failed transfer evidence")
        if task_kind == "cause_probe":
            cause_id = task.get("cause_id")
            if not isinstance(cause_id, str) or cause_id not in candidate_subjects:
                raise ScheduleError("cause probe lacks matching candidate evidence")
            if not any(
                ref.subject_id == cause_id for ref in candidate_claim_refs
            ):
                raise ScheduleError("cause probe lacks a current probe assessment")
        if candidate_subjects and observation_values != [False]:
            raise ScheduleError("candidate-cause scheduling lacks an observed first-answer error")

        activity = task.get("activity_ref")
        if isinstance(activity, ActivityRef):
            activity = asdict(activity)
        if not isinstance(activity, dict) or set(activity) != _ACTIVITY_REF_KEYS:
            raise ScheduleError("review task activity provenance is invalid")
        try:
            ActivityRef(**activity)
        except (TypeError, ScheduleValidationError) as exc:
            raise ScheduleError("review task activity contract is invalid") from exc
        content_hash = activity.get("fixture_content_sha256")
        row = self._connection.execute(
            "SELECT kind, content_json FROM content_snapshots WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if row is None or str(row["kind"]) != "domain_fixture":
            raise ScheduleError("review task fixture snapshot is unavailable")
        try:
            content = json.loads(row["content_json"])
        except json.JSONDecodeError:
            raise ScheduleError("review task fixture snapshot is invalid") from None
        if (
            hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
            != content_hash
            or content.get("fixture_id") != activity.get("fixture_id")
        ):
            raise ScheduleError("review task fixture snapshot failed integrity validation")
        context = terminal_state.get("context")
        if (
            not isinstance(context, dict)
            or context.get("scenario") != "attempt"
            or context.get("evidence_origin") != "human_local_interactive"
            or context.get("fixture_id") != activity.get("fixture_id")
            or context.get("fixture_content_sha256") != content_hash
        ):
            raise ScheduleError("review task trace is not a human local attempt for its activity")
        if task.get("domain") != terminal_state.get("domain") or task.get(
            "domain"
        ) != content.get("domain"):
            raise ScheduleError("review task domain does not match its source fixture")
        authored_skills = {
            item.get("skill_id")
            for item in content.get("skills", [])
            if isinstance(item, dict) and isinstance(item.get("skill_id"), str)
        }
        if task.get("skill_id") not in authored_skills:
            raise ScheduleError("review task skill does not belong to its source fixture")
        authored_causes = {
            item.get("cause_id"): item.get("label")
            for item in content.get("diagnosis", {}).get("candidate_causes", [])
            if isinstance(item, dict)
            and isinstance(item.get("cause_id"), str)
            and isinstance(item.get("label"), str)
        }
        if any(subject not in authored_causes for subject in candidate_subjects):
            raise ScheduleError("review task candidate cause is not authored by its fixture")
        cause_id = task.get("cause_id")
        if cause_id is not None and (
            cause_id not in authored_causes
            or task.get("cause_label") != authored_causes[cause_id]
        ):
            raise ScheduleError("review task cause label does not match its source fixture")

    def _verified_trace_events(self, run_id: str) -> dict[int, sqlite3.Row]:
        try:
            rows = self._connection.execute(
                "SELECT * FROM trace_events WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        except sqlite3.OperationalError:
            raise ScheduleError("review task source trace is unavailable") from None
        if not rows:
            raise ScheduleError("review task source trace is unavailable")
        previous_hash = "GENESIS"
        verified: dict[int, sqlite3.Row] = {}
        for row in rows:
            encoded = str(row["payload_json"])
            expected = _trace_event_hash(
                str(row["run_id"]),
                int(row["seq"]),
                str(row["occurred_at"]),
                str(row["kind"]),
                encoded,
                previous_hash,
            )
            if (
                str(row["previous_hash"]) != previous_hash
                or str(row["event_hash"]) != expected
            ):
                raise ScheduleError("review task source trace failed hash verification")
            verified[int(row["seq"])] = row
            previous_hash = str(row["event_hash"])
        return verified

    def _validate_plan_response_provenance(self, response: Mapping[str, Any]) -> None:
        tasks = response.get("tasks")
        if not isinstance(tasks, list):
            raise ScheduleError("stored TodayPlan receipt is invalid")
        for task in tasks:
            if not isinstance(task, dict):
                raise ScheduleError("stored TodayPlan task receipt is invalid")
            self._validate_task_provenance(task)

    def _validate_planning_evidence(self, item: PlanningEvidence) -> None:
        task_kind = (
            "cause_probe"
            if item.evidence_ref.kind == "candidate_cause"
            else (
                "delayed_retention"
                if item.verification_effective is True and not item.attempt_failed
                else "independent_retry"
            )
        )
        self._validate_task_provenance(
            {
                "task_kind": task_kind,
                "domain": item.domain,
                "skill_id": item.skill_id,
                "cause_id": item.cause_id,
                "cause_label": item.cause_label,
                "evidence_refs": (item.evidence_ref, *item.supporting_refs),
                "activity_ref": item.activity_ref,
            }
        )
        events = self._verified_trace_events(item.evidence_ref.run_id)
        source = events.get(item.evidence_ref.event_seq)
        if source is None or str(source["occurred_at"]) != item.occurred_at:
            raise ScheduleError("planning evidence time does not match its trace event")
        parsed = datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ScheduleError("planning evidence event time lacks timezone")
        local = parsed.astimezone(self._planning_timezone)
        offset = local.utcoffset()
        if offset is None:
            raise ScheduleError("planning timezone offset is unavailable")
        expected_offset = int(offset.total_seconds() // 60)
        if (
            item.timezone_offset_minutes != expected_offset
            or item.occurred_on != local.date().isoformat()
        ):
            raise ScheduleError("planning evidence local date basis is invalid")
        source_payload = json.loads(source["payload_json"])
        source_value = _json_pointer_value(
            source_payload, item.evidence_ref.json_pointer
        )
        refs = (item.evidence_ref, *item.supporting_refs)
        if item.evidence_ref.kind == "trace_skill_evidence":
            if (
                item.verification_effective is not source_value
                or item.attempt_failed != (source_value is not True)
            ):
                raise ScheduleError("planning transfer fields do not match trace evidence")
        else:
            observations = []
            for ref in refs:
                if ref.semantic != "initial_answer_passed":
                    continue
                event = events.get(ref.event_seq)
                if event is None:
                    raise ScheduleError("planning observation evidence is unavailable")
                observations.append(
                    _json_pointer_value(
                        json.loads(event["payload_json"]), ref.json_pointer
                    )
                )
            if (
                item.verification_effective is not None
                or observations != [False]
                or item.attempt_failed is not True
                or item.cause_id != item.evidence_ref.subject_id
            ):
                raise ScheduleError("planning cause fields do not match trace evidence")

    def create_today_plan(
        self,
        *,
        plan_date: str,
        exam_date: str | None,
        daily_budget_minutes: int,
        expected_version: int,
        command_id: str,
        evidence: Sequence[PlanningEvidence],
    ) -> dict[str, Any]:
        day = _parse_date(plan_date, "plan_date")
        if expected_version != 0:
            raise ScheduleValidationError("a new TodayPlan requires expected_version 0")
        if not _valid_command_id(command_id):
            raise ScheduleValidationError("command_id is invalid")
        evidence_items = tuple(evidence)
        if len({item.evidence_ref.ref for item in evidence_items}) != len(
            evidence_items
        ):
            raise ScheduleValidationError("duplicate planning evidence is not allowed")
        for item in evidence_items:
            self._validate_planning_evidence(item)
        decision = build_scheduler_decision(
            evidence_items,
            plan_date=plan_date,
            exam_date=exam_date,
            daily_budget_minutes=daily_budget_minutes,
        )
        for spec in decision.candidate_tasks:
            self._validate_task_provenance(
                {
                    "task_kind": spec.task_kind,
                    "domain": spec.domain,
                    "skill_id": spec.skill_id,
                    "cause_id": spec.cause_id,
                    "cause_label": spec.cause_label,
                    "evidence_refs": spec.evidence_refs,
                    "activity_ref": spec.activity_ref,
                }
            )
        plan_id = f"today-{plan_date}"
        request = _create_plan_request(
            plan_id=plan_id,
            plan_date=plan_date,
            exam_date=exam_date,
            daily_budget_minutes=daily_budget_minutes,
            expected_version=expected_version,
            command_id=command_id,
        )
        fingerprint = _fingerprint(request)
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._command_replay(command_id, fingerprint)
            if replay is not None:
                self._validate_plan_response_provenance(replay)
                connection.execute("COMMIT")
                return replay
            latest_plan_row = connection.execute(
                "SELECT MAX(plan_date) AS latest_plan_date FROM today_plans"
            ).fetchone()
            latest_plan_date = latest_plan_row["latest_plan_date"]
            if latest_plan_date is not None and plan_date < str(latest_plan_date):
                raise ScheduleHistoricalPlan(
                    "an older TodayPlan cannot be created after a newer local date plan"
                )
            existing = connection.execute(
                "SELECT version FROM today_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if existing is not None:
                raise ScheduleVersionConflict(expected_version, int(existing["version"]))

            occurred_at = _utc_now()
            due_rows = connection.execute(
                """
                SELECT r.*,
                    (
                        SELECT COUNT(*)
                        FROM today_plan_tasks membership
                        WHERE membership.task_id = r.task_id
                    ) AS presentation_count,
                    (
                        SELECT MAX(plan.plan_date)
                        FROM today_plan_tasks membership
                        JOIN today_plans plan ON plan.plan_id = membership.plan_id
                        WHERE membership.task_id = r.task_id
                    ) AS last_presented_on
                FROM review_schedule_tasks r
                WHERE r.state != 'completed' AND r.due_on <= ?
                ORDER BY
                    CASE WHEN r.state = 'accepted' THEN 0 ELSE 1 END,
                    r.due_on,
                    presentation_count,
                    CASE WHEN last_presented_on IS NULL THEN 0 ELSE 1 END,
                    last_presented_on,
                    r.task_id
                """,
                (plan_date,),
            ).fetchall()
            accepted_required_minutes = sum(
                int(row["expected_duration_minutes"])
                for row in due_rows
                if str(row["state"]) == "accepted"
            )
            if accepted_required_minutes > daily_budget_minutes:
                raise ScheduleBudgetBelowAcceptedCommitment(
                    accepted_required_minutes
                )
            due_tasks: list[dict[str, Any]] = []
            for row in due_rows:
                task = _task_from_row(row)
                self._validate_task_provenance(task)
                if task["state"] in {"skipped", "postponed"}:
                    task["state"] = "scheduled"
                    task["version"] += 1
                    task["updated_at"] = occurred_at
                    self._update_task_projection(task)
                    self._append_event(
                        "review_task",
                        task["task_id"],
                        "task_resurfaced",
                        {
                            "schema_version": SCHEDULE_SCHEMA_VERSION,
                            "cause": "due_review",
                            "causation_command_id": command_id,
                            "task_after": task,
                        },
                        occurred_at,
                    )
                due_tasks.append(task)

            accepted_tasks = [
                task for task in due_tasks if task["state"] == "accepted"
            ]
            budget_remaining = daily_budget_minutes - accepted_required_minutes
            selected: list[dict[str, Any]] = list(accepted_tasks)
            presentation_limit = int(
                decision.workload_guardrail["max_non_accepted_tasks"]
            )
            non_accepted_selected_count = 0
            for task in due_tasks:
                if task["state"] == "accepted":
                    continue
                if non_accepted_selected_count >= presentation_limit:
                    break
                duration = int(task["expected_duration_minutes"])
                if duration <= budget_remaining:
                    selected.append(task)
                    budget_remaining -= duration
                    non_accepted_selected_count += 1

            future_task_count = 0
            for spec in decision.candidate_tasks:
                existing_task = connection.execute(
                    "SELECT * FROM review_schedule_tasks WHERE source_key = ?",
                    (spec.source_key,),
                ).fetchone()
                if existing_task is not None:
                    task = _task_from_row(existing_task)
                    if (
                        task["state"] != "completed"
                        and task["due_on"] <= plan_date
                        and all(item["task_id"] != task["task_id"] for item in selected)
                        and non_accepted_selected_count < presentation_limit
                        and int(task["expected_duration_minutes"]) <= budget_remaining
                    ):
                        selected.append(task)
                        budget_remaining -= int(task["expected_duration_minutes"])
                        non_accepted_selected_count += 1
                    elif task["state"] != "completed" and task["due_on"] > plan_date:
                        future_task_count += 1
                    continue
                task = _task_from_spec(spec, due_on=spec.due_on, occurred_at=occurred_at)
                self._validate_task_provenance(task)
                self._insert_task_projection(task)
                self._append_event(
                    "review_task",
                    task["task_id"],
                    "task_created",
                    {
                        "schema_version": SCHEDULE_SCHEMA_VERSION,
                        "causation_command_id": command_id,
                        "task_after": task,
                    },
                    occurred_at,
                )
                if task["due_on"] <= plan_date:
                    if (
                        non_accepted_selected_count < presentation_limit
                        and spec.expected_duration_minutes <= budget_remaining
                    ):
                        selected.append(task)
                        budget_remaining -= spec.expected_duration_minutes
                        non_accepted_selected_count += 1
                else:
                    future_task_count += 1

            active_review_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS active_count,
                    SUM(CASE WHEN scheduling_adjustment = 'overdue_catch_up'
                             THEN 1 ELSE 0 END) AS overdue_count
                FROM review_schedule_tasks
                WHERE state != 'completed'
                """
            ).fetchone()
            active_review_count = int(active_review_row["active_count"])
            active_overdue_catch_up_count = int(
                active_review_row["overdue_count"] or 0
            )
            workload_guardrail = dict(decision.workload_guardrail)
            # The decision is rebuilt from immutable trace evidence every day,
            # but existing task definitions are immutable. Report the actual
            # active ReviewSchedule backlog, not a recomputed or completed spec.
            workload_guardrail["overdue_catch_up_count"] = (
                active_overdue_catch_up_count
            )
            basis = {
                "evidence_status": (
                    "recorded" if selected else decision.evidence_status
                ),
                "inputs_used": (
                    list(decision.inputs_used)
                    + (["due_reviews"] if due_tasks else [])
                ),
                "excluded_inputs": list(decision.excluded_inputs),
                "recent_evidence_counts_by_domain": decision.evidence_counts_by_domain,
                "evidence_count_unit": "trace_backed_planning_evidence_record",
                "workload_guardrail": workload_guardrail,
                "exam_window": decision.exam_window,
                "due_review_count": len(due_tasks),
                "selected_task_count": len(selected),
                "future_review_task_count": future_task_count,
                "duration_policy": "fixed_estimate_not_population_calibrated",
                "retention_window_policy": "engineering_default_plus_3_days_unvalidated",
                "retry_window_policy": "engineering_default_plus_1_day_unvalidated",
                "schedule_windows": {
                    "cause_probe_days": 1,
                    "independent_retry_days": 1,
                    "delayed_retention_days": 3,
                    "calibration": "fixed_engineering_policy_unvalidated",
                    "exam_adjustment": "withhold_if_due_after_exam",
                },
                "task_definition_status": "authored_engineering_estimate_unvalidated",
            }
            empty_reason = None
            if not selected:
                if decision.evidence_status == "unavailable" and not due_tasks:
                    empty_reason = "no_recorded_evidence"
                elif future_task_count:
                    empty_reason = "no_task_due_today"
                elif decision.workload_guardrail.get(
                    "withheld_exam_deadline_count", 0
                ):
                    empty_reason = "task_due_after_exam"
                elif decision.workload_guardrail.get("withheld_activity_count", 0):
                    empty_reason = "activity_unavailable"
                elif active_review_count == 0:
                    empty_reason = "no_pending_review_tasks"
                else:
                    empty_reason = "no_task_within_guardrail"
            input_digest = _fingerprint(
                {
                    "decision": _decision_dict(decision),
                    "due_task_ids": [task["task_id"] for task in due_tasks],
                }
            )
            status = "empty" if not selected else "active"
            connection.execute(
                """
                INSERT INTO today_plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    plan_date,
                    exam_date,
                    status,
                    1,
                    decision.policy_version,
                    input_digest,
                    _canonical_json(basis),
                    empty_reason,
                    occurred_at,
                    occurred_at,
                ),
            )
            for ordinal, task in enumerate(selected, start=1):
                connection.execute(
                    """
                    INSERT INTO today_plan_tasks
                    (plan_id, task_id, ordinal, state, task_snapshot_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        task["task_id"],
                        ordinal,
                        task["state"],
                        _canonical_json(task),
                    ),
                )
            response = self._load_plan_in_transaction(plan_id)
            self._append_event(
                "today_plan",
                plan_id,
                "today_plan_created",
                {
                    "schema_version": TODAY_PLAN_SCHEMA_VERSION,
                    "causation_command_id": command_id,
                    "plan_after": response,
                },
                occurred_at,
            )
            response["event_stream"] = self._stream_metadata("today_plan", plan_id)
            self._record_command(command_id, fingerprint, response, occurred_at)
            connection.execute("COMMIT")
            return response
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def replay_create_today_plan_command(
        self,
        *,
        plan_date: str,
        exam_date: str | None,
        daily_budget_minutes: int,
        expected_version: int,
        command_id: str,
    ) -> dict[str, Any] | None:
        """Return an exact prior receipt before applying a new-day date guard."""

        plan_id = f"today-{plan_date}"
        request = _create_plan_request(
            plan_id=plan_id,
            plan_date=plan_date,
            exam_date=exam_date,
            daily_budget_minutes=daily_budget_minutes,
            expected_version=expected_version,
            command_id=command_id,
        )
        replay = self._command_replay(command_id, _fingerprint(request))
        if replay is not None:
            self._validate_plan_response_provenance(replay)
        return replay

    def transition_task(
        self,
        *,
        plan_id: str,
        task_id: str,
        action: str,
        action_date: str,
        expected_version: int,
        expected_task_version: int,
        command_id: str,
        postpone_until: str | None = None,
    ) -> dict[str, Any]:
        effective_day = _parse_date(action_date, "action_date")
        if action not in {"accept", "complete", "postpone", "skip", "resurface"}:
            raise ScheduleValidationError("unsupported schedule action")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ScheduleValidationError("expected_version must be a positive integer")
        if (
            isinstance(expected_task_version, bool)
            or not isinstance(expected_task_version, int)
            or expected_task_version < 1
        ):
            raise ScheduleValidationError(
                "expected_task_version must be a positive integer"
            )
        if not _valid_command_id(command_id):
            raise ScheduleValidationError("command_id is invalid")
        if action == "postpone":
            if postpone_until is None:
                raise ScheduleValidationError("postpone requires postpone_until")
            resume_day = _parse_date(postpone_until, "postpone_until")
        elif postpone_until is not None:
            raise ScheduleValidationError("postpone_until is only valid for postpone")
        request = {
            "operation": "transition_task",
            "plan_id": plan_id,
            "task_id": task_id,
            "action": action,
            "expected_version": expected_version,
            "expected_task_version": expected_task_version,
            "command_id": command_id,
            "postpone_until": postpone_until,
        }
        fingerprint = _fingerprint(request)
        connection = self._connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            replay = self._command_replay(command_id, fingerprint)
            if replay is not None:
                self._validate_plan_response_provenance(replay)
                connection.execute("COMMIT")
                return replay
            if action == "postpone" and resume_day <= effective_day:
                raise ScheduleValidationError("postpone_until must be after action_date")
            plan_row = connection.execute(
                "SELECT * FROM today_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if plan_row is None:
                raise ScheduleNotFound("TodayPlan does not exist")
            stored_plan_date = _parse_date(str(plan_row["plan_date"]), "plan_date")
            latest_plan_date_row = connection.execute(
                "SELECT MAX(plan_date) AS latest_plan_date FROM today_plans"
            ).fetchone()
            latest_plan_date = str(latest_plan_date_row["latest_plan_date"])
            if (
                effective_day != stored_plan_date
                or stored_plan_date.isoformat() != latest_plan_date
            ):
                raise ScheduleHistoricalPlan(
                    "historical TodayPlans are read-only; use the current local date plan"
                )
            actual_version = int(plan_row["version"])
            if actual_version != expected_version:
                raise ScheduleVersionConflict(expected_version, actual_version)
            mapping = connection.execute(
                """
                SELECT state, task_snapshot_json FROM today_plan_tasks
                WHERE plan_id = ? AND task_id = ?
                """,
                (plan_id, task_id),
            ).fetchone()
            task_row = connection.execute(
                "SELECT * FROM review_schedule_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if mapping is None or task_row is None:
                raise ScheduleNotFound("task is not part of the TodayPlan")
            task = _task_from_row(task_row)
            actual_task_version = int(task["version"])
            try:
                membership_snapshot = json.loads(mapping["task_snapshot_json"])
            except (TypeError, json.JSONDecodeError):
                raise ScheduleError("TodayPlan task snapshot is invalid") from None
            membership_task_version = (
                membership_snapshot.get("version")
                if isinstance(membership_snapshot, dict)
                else None
            )
            if (
                expected_task_version != actual_task_version
                or membership_task_version != actual_task_version
                or str(mapping["state"]) != str(task["state"])
            ):
                raise ScheduleTaskVersionConflict(
                    expected_task_version, actual_task_version
                )
            current_state = str(task["state"])
            if action not in _TRANSITIONS[current_state]:
                raise ScheduleTransitionError(
                    f"action {action} is not allowed from state {current_state}"
                )
            if action == "resurface" and effective_day < _parse_date(task["due_on"], "due_on"):
                raise ScheduleTransitionError("task cannot resurface before its due date")

            next_state = {
                "accept": "accepted",
                "complete": "completed",
                "postpone": "postponed",
                "skip": "skipped",
                "resurface": "scheduled",
            }[action]
            task["state"] = next_state
            task["version"] += 1
            task["updated_at"] = _utc_now()
            if action == "complete":
                task["completion_semantics"] = "user_marked_not_learning_evidence"
            if action == "postpone":
                task["due_on"] = str(postpone_until)
            elif action == "skip":
                task["due_on"] = (effective_day + timedelta(days=1)).isoformat()
            elif action == "resurface":
                task["due_on"] = action_date
            self._update_task_projection(task)
            connection.execute(
                """
                UPDATE today_plan_tasks SET state = ?, task_snapshot_json = ?
                WHERE plan_id = ? AND task_id = ?
                """,
                (next_state, _canonical_json(task), plan_id, task_id),
            )

            mapping_states = [
                str(row[0])
                for row in connection.execute(
                    "SELECT state FROM today_plan_tasks WHERE plan_id = ? ORDER BY ordinal",
                    (plan_id,),
                ).fetchall()
            ]
            if mapping_states and all(state == "completed" for state in mapping_states):
                plan_status = "completed"
            elif mapping_states and all(
                state in {"completed", "postponed", "skipped"} for state in mapping_states
            ):
                plan_status = "handled"
            else:
                plan_status = "active"
            new_version = actual_version + 1
            connection.execute(
                "UPDATE today_plans SET status = ?, version = ?, updated_at = ? WHERE plan_id = ?",
                (plan_status, new_version, task["updated_at"], plan_id),
            )
            task_event_payload: dict[str, Any] = {
                "schema_version": SCHEDULE_SCHEMA_VERSION,
                "action": action,
                "action_date": action_date,
                "causation_command_id": command_id,
                "completion_semantics": (
                    "user_marked_not_learning_evidence" if action == "complete" else None
                ),
                "mastery_write_capability": False,
                "task_after": task,
            }
            self._append_event(
                "review_task",
                task_id,
                {
                    "accept": "task_accepted",
                    "complete": "task_completed",
                    "postpone": "task_postponed",
                    "skip": "task_skipped",
                    "resurface": "task_resurfaced",
                }[action],
                task_event_payload,
                task["updated_at"],
            )
            response = self._load_plan_in_transaction(plan_id)
            self._append_event(
                "today_plan",
                plan_id,
                "today_plan_task_transitioned",
                {
                    "schema_version": TODAY_PLAN_SCHEMA_VERSION,
                    "action": action,
                    "action_date": action_date,
                    "causation_command_id": command_id,
                    "task_after": task,
                    "plan_after": response,
                },
                task["updated_at"],
            )
            response["event_stream"] = self._stream_metadata("today_plan", plan_id)
            self._record_command(command_id, fingerprint, response, task["updated_at"])
            connection.execute("COMMIT")
            return response
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def load_plan(self, plan_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT 1 FROM today_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if row is None:
            raise ScheduleNotFound("TodayPlan does not exist")
        result = self._load_plan_in_transaction(plan_id)
        result["event_stream"] = self._stream_metadata("today_plan", plan_id)
        return result

    def review_schedule(self) -> dict[str, Any]:
        rows = self._connection.execute(
            "SELECT * FROM review_schedule_tasks ORDER BY due_on, task_id"
        ).fetchall()
        items = [_task_from_row(row) for row in rows]
        for item in items:
            self._validate_task_provenance(item)
        return {
            "schema_version": SCHEDULE_SCHEMA_VERSION,
            "count": len(rows),
            "items": items,
            "authority": "independent_review_schedule_projection",
            "mastery_write_capability": False,
            "population_evidence": "unavailable",
        }

    def events(self, stream_type: str, stream_id: str) -> list[ScheduleEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM schedule_events
            WHERE stream_type = ? AND stream_id = ? ORDER BY seq
            """,
            (stream_type, stream_id),
        ).fetchall()
        return [
            ScheduleEvent(
                stream_type=str(row["stream_type"]),
                stream_id=str(row["stream_id"]),
                seq=int(row["seq"]),
                occurred_at=str(row["occurred_at"]),
                kind=str(row["kind"]),
                payload=json.loads(row["payload_json"]),
                previous_hash=str(row["previous_hash"]),
                event_hash=str(row["event_hash"]),
            )
            for row in rows
        ]

    def verify(self, stream_type: str, stream_id: str) -> bool:
        previous_hash = "GENESIS"
        for event in self.events(stream_type, stream_id):
            encoded = _canonical_json(event.payload)
            expected = _schedule_event_hash(
                event.stream_type,
                event.stream_id,
                event.seq,
                event.occurred_at,
                event.kind,
                encoded,
                previous_hash,
            )
            if event.previous_hash != previous_hash or event.event_hash != expected:
                return False
            previous_hash = event.event_hash
        return True

    def replay(self, stream_type: str, stream_id: str) -> dict[str, Any]:
        events = self.events(stream_type, stream_id)
        if not events:
            raise ScheduleNotFound("schedule event stream does not exist")
        if not self.verify(stream_type, stream_id):
            raise ScheduleError("schedule event hash verification failed")
        frames = []
        for event in events:
            state = (
                event.payload.get("plan_after")
                if stream_type == "today_plan"
                else event.payload.get("task_after")
            )
            if state is not None:
                frames.append(
                    {"seq": event.seq, "kind": event.kind, "state": state}
                )
        if not frames or not self._projection_matches(stream_type, stream_id, frames[-1]["state"]):
            raise ScheduleError("schedule replay does not match the stored projection")
        return {
            "schema_version": "lumi.schedule-replay.v1",
            "stream_type": stream_type,
            "stream_id": stream_id,
            "trace_verified": True,
            "projection_verified": True,
            "frame_count": len(frames),
            "frames": frames,
        }

    def _load_plan_in_transaction(self, plan_id: str) -> dict[str, Any]:
        plan = self._connection.execute(
            "SELECT * FROM today_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if plan is None:
            raise ScheduleNotFound("TodayPlan does not exist")
        task_rows = self._connection.execute(
            """
            SELECT task_id, ordinal, state AS plan_task_state, task_snapshot_json
            FROM today_plan_tasks
            WHERE plan_id = ? ORDER BY ordinal
            """,
            (plan_id,),
        ).fetchall()
        tasks = []
        for row in task_rows:
            try:
                task = json.loads(row["task_snapshot_json"])
            except (TypeError, json.JSONDecodeError):
                raise ScheduleError("TodayPlan task snapshot is invalid") from None
            if (
                not isinstance(task, dict)
                or task.get("task_id") != str(row["task_id"])
            ):
                raise ScheduleError("TodayPlan task snapshot does not match membership")
            task["state"] = str(row["plan_task_state"])
            task["ordinal"] = int(row["ordinal"])
            self._validate_task_provenance(task)
            tasks.append(task)
        basis = json.loads(plan["basis_json"])
        evidence_refs = sorted(
            {
                ref["ref"]
                for task in tasks
                for ref in task["evidence_refs"]
            }
        )
        return {
            "schema_version": TODAY_PLAN_SCHEMA_VERSION,
            "plan_id": str(plan["plan_id"]),
            "plan_date": str(plan["plan_date"]),
            "exam_date": plan["exam_date"],
            "status": str(plan["status"]),
            "version": int(plan["version"]),
            "scheduler_policy_version": str(plan["scheduler_policy_version"]),
            "basis": basis,
            "empty_reason": plan["empty_reason"],
            "evidence_refs": evidence_refs,
            "tasks": tasks,
            "mastery_write_capability": False,
            "created_at": str(plan["created_at"]),
            "updated_at": str(plan["updated_at"]),
            "links": {
                "self": f"/v1/today-plans/{plan_id}",
                "replay": f"/v1/today-plans/{plan_id}/replay",
                "review_schedule": "/v1/review-schedule",
            },
        }

    def _insert_task_projection(self, task: Mapping[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO review_schedule_tasks (
                task_id, source_key, task_kind, domain, skill_id, reason,
                expected_duration_minutes, success_criterion, skip_consequence,
                evidence_refs_json, activity_ref_json, cause_id, cause_label,
                cause_confirmation_status, definition_status,
                policy_offset_days, base_due_on, initial_due_on, scheduling_adjustment,
                completion_semantics, state, due_on, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["task_id"],
                task["source_key"],
                task["task_kind"],
                task["domain"],
                task["skill_id"],
                task["reason"],
                task["expected_duration_minutes"],
                task["success_criterion"],
                task["skip_consequence"],
                _canonical_json(task["evidence_refs"]),
                _canonical_json(task["activity_ref"]),
                task["cause_id"],
                task["cause_label"],
                task["cause_confirmation_status"],
                task["definition_status"],
                task["policy_offset_days"],
                task["base_due_on"],
                task["initial_due_on"],
                task["scheduling_adjustment"],
                task["completion_semantics"],
                task["state"],
                task["due_on"],
                task["version"],
                task["created_at"],
                task["updated_at"],
            ),
        )

    def _update_task_projection(self, task: Mapping[str, Any]) -> None:
        self._connection.execute(
            """
            UPDATE review_schedule_tasks
            SET state = ?, due_on = ?, version = ?, completion_semantics = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (
                task["state"],
                task["due_on"],
                task["version"],
                task["completion_semantics"],
                task["updated_at"],
                task["task_id"],
            ),
        )

    def _append_event(
        self,
        stream_type: str,
        stream_id: str,
        kind: str,
        payload: Mapping[str, Any],
        occurred_at: str,
    ) -> ScheduleEvent:
        safe_payload = redact(dict(payload))
        encoded = _canonical_json(safe_payload)
        row = self._connection.execute(
            """
            SELECT seq, event_hash FROM schedule_events
            WHERE stream_type = ? AND stream_id = ? ORDER BY seq DESC LIMIT 1
            """,
            (stream_type, stream_id),
        ).fetchone()
        seq = int(row["seq"]) + 1 if row else 1
        previous_hash = str(row["event_hash"]) if row else "GENESIS"
        event_hash = _schedule_event_hash(
            stream_type, stream_id, seq, occurred_at, kind, encoded, previous_hash
        )
        self._connection.execute(
            "INSERT INTO schedule_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stream_type,
                stream_id,
                seq,
                occurred_at,
                kind,
                encoded,
                previous_hash,
                event_hash,
            ),
        )
        return ScheduleEvent(
            stream_type,
            stream_id,
            seq,
            occurred_at,
            kind,
            safe_payload,
            previous_hash,
            event_hash,
        )

    def _stream_metadata(self, stream_type: str, stream_id: str) -> dict[str, Any]:
        events = self.events(stream_type, stream_id)
        latest_state = None
        if events:
            latest_state = (
                events[-1].payload.get("plan_after")
                if stream_type == "today_plan"
                else events[-1].payload.get("task_after")
            )
        return {
            "stream_type": stream_type,
            "stream_id": stream_id,
            "version": events[-1].seq if events else 0,
            "trace_verified": self.verify(stream_type, stream_id),
            "projection_verified": (
                self._projection_matches(stream_type, stream_id, latest_state)
                if latest_state is not None
                else False
            ),
        }

    def _projection_matches(
        self, stream_type: str, stream_id: str, replayed_state: Any
    ) -> bool:
        if not isinstance(replayed_state, dict):
            return False
        if stream_type == "today_plan":
            try:
                projected = self._load_plan_in_transaction(stream_id)
            except ScheduleNotFound:
                return False
        elif stream_type == "review_task":
            row = self._connection.execute(
                "SELECT * FROM review_schedule_tasks WHERE task_id = ?", (stream_id,)
            ).fetchone()
            if row is None:
                return False
            projected = _task_from_row(row)
            self._validate_task_provenance(projected)
        else:
            return False
        return _canonical_json(projected) == _canonical_json(replayed_state)

    def _command_replay(self, command_id: str, fingerprint: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT request_fingerprint, response_json FROM schedule_command_results WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_fingerprint"]) != fingerprint:
            raise ScheduleCommandConflict(
                "command_id was already used for a different schedule command"
            )
        response = json.loads(row["response_json"])
        if _response_uses_superseded_schedule_contract(response):
            raise ScheduleCommandConflict(
                "command receipt uses a superseded pre-release schedule contract; reload the current plan"
            )
        return response

    def _record_command(
        self, command_id: str, fingerprint: str, response: Mapping[str, Any], created_at: str
    ) -> None:
        self._connection.execute(
            "INSERT INTO schedule_command_results VALUES (?, ?, ?, ?)",
            (command_id, fingerprint, _canonical_json(response), created_at),
        )


def _decision_dict(decision: SchedulerDecision) -> dict[str, Any]:
    return {
        "policy_version": decision.policy_version,
        "candidate_tasks": [
            {
                **asdict(task),
                "evidence_refs": [asdict(ref) for ref in task.evidence_refs],
            }
            for task in decision.candidate_tasks
        ],
        "evidence_status": decision.evidence_status,
        "inputs_used": list(decision.inputs_used),
        "excluded_inputs": list(decision.excluded_inputs),
        "evidence_counts_by_domain": decision.evidence_counts_by_domain,
        "workload_guardrail": decision.workload_guardrail,
        "exam_window": decision.exam_window,
    }


def _create_plan_request(
    *,
    plan_id: str,
    plan_date: str,
    exam_date: str | None,
    daily_budget_minutes: int,
    expected_version: int,
    command_id: str,
) -> dict[str, Any]:
    return {
        "operation": "create_today_plan",
        "plan_id": plan_id,
        "plan_date": plan_date,
        "exam_date": exam_date,
        "daily_budget_minutes": daily_budget_minutes,
        "expected_version": expected_version,
        "command_id": command_id,
    }


def _task_from_spec(
    spec: ScheduleTaskSpec, *, due_on: str, occurred_at: str
) -> dict[str, Any]:
    if due_on != spec.due_on:
        raise ScheduleError("task projection due date does not match its scheduler spec")
    task_id = "review-" + hashlib.sha256(spec.source_key.encode("utf-8")).hexdigest()[:24]
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "task_id": task_id,
        "source_key": spec.source_key,
        "task_kind": spec.task_kind,
        "domain": spec.domain,
        "skill_id": spec.skill_id,
        "reason": spec.reason,
        "expected_duration_minutes": spec.expected_duration_minutes,
        "success_criterion": spec.success_criterion,
        "skip_consequence": spec.skip_consequence,
        "evidence_refs": [asdict(ref) for ref in spec.evidence_refs],
        "activity_ref": asdict(spec.activity_ref),
        "cause_id": spec.cause_id,
        "cause_label": spec.cause_label,
        "cause_confirmation_status": spec.cause_confirmation_status,
        "definition_status": "authored_engineering_estimate_unvalidated",
        "policy_offset_days": spec.policy_offset_days,
        "base_due_on": spec.base_due_on,
        "initial_due_on": due_on,
        "scheduling_adjustment": spec.scheduling_adjustment,
        "schedule_window": _task_schedule_window(
            spec.task_kind,
            policy_offset_days=spec.policy_offset_days,
            base_due_on=spec.base_due_on,
            initial_due_on=due_on,
            scheduling_adjustment=spec.scheduling_adjustment,
        ),
        "completion_semantics": None,
        "state": "scheduled",
        "due_on": due_on,
        "version": 1,
        "created_at": occurred_at,
        "updated_at": occurred_at,
    }


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    state = str(row["state"])
    if state not in _TASK_STATES:
        raise ScheduleError("stored review task has an unsupported state")
    return {
        "schema_version": SCHEDULE_SCHEMA_VERSION,
        "task_id": str(row["task_id"]),
        "source_key": str(row["source_key"]),
        "task_kind": str(row["task_kind"]),
        "domain": str(row["domain"]),
        "skill_id": str(row["skill_id"]),
        "reason": str(row["reason"]),
        "expected_duration_minutes": int(row["expected_duration_minutes"]),
        "success_criterion": str(row["success_criterion"]),
        "skip_consequence": str(row["skip_consequence"]),
        "evidence_refs": json.loads(row["evidence_refs_json"]),
        "activity_ref": json.loads(row["activity_ref_json"]),
        "cause_id": row["cause_id"],
        "cause_label": row["cause_label"],
        "cause_confirmation_status": row["cause_confirmation_status"],
        "definition_status": str(row["definition_status"]),
        "policy_offset_days": int(row["policy_offset_days"]),
        "base_due_on": str(row["base_due_on"]),
        "initial_due_on": str(row["initial_due_on"]),
        "scheduling_adjustment": str(row["scheduling_adjustment"]),
        "schedule_window": _task_schedule_window(
            str(row["task_kind"]),
            policy_offset_days=int(row["policy_offset_days"]),
            base_due_on=str(row["base_due_on"]),
            initial_due_on=str(row["initial_due_on"]),
            scheduling_adjustment=str(row["scheduling_adjustment"]),
        ),
        "completion_semantics": row["completion_semantics"],
        "state": state,
        "due_on": str(row["due_on"]),
        "version": int(row["version"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _valid_command_id(value: Any) -> bool:
    return valid_public_command_identifier(value)


def valid_public_run_identifier(value: Any) -> bool:
    """Return whether ``value`` is a new-write public run identifier.

    The deliberately narrow opaque alphabet prevents learner-provided PII or
    credentials from becoming durable SQLite keys. Existing safe legacy keys
    remain readable through :func:`valid_stored_run_identifier` only.
    """

    return isinstance(value, str) and _PUBLIC_RUN_ID_PATTERN.fullmatch(value) is not None


def valid_public_command_identifier(value: Any) -> bool:
    """Return whether ``value`` is a new-write idempotency command identifier."""

    return (
        isinstance(value, str)
        and _PUBLIC_COMMAND_ID_PATTERN.fullmatch(value) is not None
    )


def valid_public_identifier(value: Any) -> bool:
    """Validate a safe legacy identifier for read compatibility only."""

    if not isinstance(value, str) or not value or len(value) > 96:
        return False
    if not all(
        character.isascii() and (character.isalnum() or character in "_.:-")
        for character in value
    ) or re.search(r"[A-Za-z]", value) is None:
        return False
    normalized = re.sub(r"[_.:-]", "", value)
    return (
        _PHONE_PATTERN.search(normalized) is None
        and _NATIONAL_ID_PATTERN.search(normalized) is None
        and _SECRET_PATTERN.search(value) is None
    )


def valid_stored_run_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    ) or valid_public_run_identifier(value) or valid_public_identifier(value)


def _task_schedule_window(
    task_kind: str,
    *,
    policy_offset_days: int,
    base_due_on: str,
    initial_due_on: str,
    scheduling_adjustment: str,
) -> dict[str, Any]:
    offsets = {
        "cause_probe": 1,
        "independent_retry": 1,
        "delayed_retention": 3,
    }
    if task_kind not in offsets:
        raise ScheduleError("stored review task has an unsupported kind")
    if policy_offset_days != offsets[task_kind]:
        raise ScheduleError("stored review task has an inconsistent policy offset")
    base_due = _parse_date(base_due_on, "stored task base_due_on")
    initial_due = _parse_date(initial_due_on, "stored task initial_due_on")
    if initial_due < base_due:
        raise ScheduleError("stored review task precedes its policy window")
    expected_adjustment = (
        "overdue_catch_up" if initial_due > base_due else "on_policy_window"
    )
    if scheduling_adjustment != expected_adjustment:
        raise ScheduleError("stored review task has an inconsistent scheduling adjustment")
    return {
        "policy_offset_days": policy_offset_days,
        "base_due_on": base_due_on,
        "initial_due_on": initial_due_on,
        "scheduling_adjustment": scheduling_adjustment,
        "calibration": "fixed_engineering_policy_unvalidated",
        "exam_adjustment": "withhold_if_due_after_exam",
    }


def _unique_evidence_refs(
    refs: Iterable[EvidenceRef],
) -> tuple[EvidenceRef, ...]:
    unique: list[EvidenceRef] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.ref not in seen:
            seen.add(ref.ref)
            unique.append(ref)
    return tuple(unique)


def _response_uses_superseded_schedule_contract(response: Any) -> bool:
    if not isinstance(response, dict):
        return True
    tasks = response.get("tasks")
    if not isinstance(tasks, list):
        return True
    basis = response.get("basis")
    guardrail = basis.get("workload_guardrail") if isinstance(basis, dict) else None
    if (
        not isinstance(guardrail, dict)
        or "max_non_accepted_tasks" not in guardrail
        or "max_new_tasks" in guardrail
    ):
        return True
    for task in tasks:
        if not isinstance(task, dict):
            return True
        task_kind = task.get("task_kind")
        activity = task.get("activity_ref")
        if (
            task_kind not in _SUCCESS_CRITERIA
            or not isinstance(activity, dict)
            or set(activity) != _ACTIVITY_REF_KEYS
            or activity.get("novelty_status") != ACTIVITY_NOVELTY_STATUS
            or task.get("success_criterion") != _SUCCESS_CRITERIA[task_kind]
            or task.get("skip_consequence") != _SKIP_CONSEQUENCES[task_kind]
        ):
            return True
    return False


def _parse_date(value: str, field: str) -> date:
    if not isinstance(value, str):
        raise ScheduleValidationError(f"{field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ScheduleValidationError(f"{field} must be an ISO date") from None
    if parsed.isoformat() != value:
        raise ScheduleValidationError(f"{field} must use YYYY-MM-DD")
    return parsed


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ScheduleValidationError("occurred_at must be an ISO datetime") from None
    if parsed.tzinfo is None:
        raise ScheduleValidationError("occurred_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _datetime_sort_value(value: str) -> float:
    return _parse_datetime(value).timestamp()


def _json_pointer_value(document: Any, pointer: str) -> Any:
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ScheduleError("review task evidence pointer cannot be resolved")
    return current


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _schedule_event_hash(
    stream_type: str,
    stream_id: str,
    seq: int,
    occurred_at: str,
    kind: str,
    encoded: str,
    previous_hash: str,
) -> str:
    canonical = "\x1f".join(
        (stream_type, stream_id, str(seq), occurred_at, kind, encoded, previous_hash)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _trace_event_hash(
    run_id: str,
    seq: int,
    occurred_at: str,
    kind: str,
    encoded: str,
    previous_hash: str,
) -> str:
    canonical = "\x1f".join(
        (run_id, str(seq), occurred_at, kind, encoded, previous_hash)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
