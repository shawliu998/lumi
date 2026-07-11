import { createCommandId, isCommandId } from "./publicLearningId.js";

const TODAY_PLAN_KEYS = [
  "schema_version", "plan_id", "plan_date", "exam_date", "status", "version",
  "scheduler_policy_version", "basis", "empty_reason", "evidence_refs", "tasks",
  "mastery_write_capability", "created_at", "updated_at", "links", "event_stream",
];
const REVIEW_SCHEDULE_KEYS = [
  "schema_version", "count", "items", "authority", "mastery_write_capability",
  "population_evidence",
];
const TASK_KEYS = [
  "schema_version", "task_id", "source_key", "task_kind", "domain", "skill_id",
  "reason", "expected_duration_minutes", "success_criterion", "skip_consequence",
  "evidence_refs", "activity_ref", "cause_id", "cause_label",
  "cause_confirmation_status", "definition_status", "policy_offset_days", "base_due_on",
  "initial_due_on", "scheduling_adjustment", "schedule_window",
  "completion_semantics", "state", "due_on", "version", "created_at", "updated_at",
];
const EVIDENCE_KEYS = [
  "ref", "kind", "source_type", "run_id", "event_seq", "event_hash", "event_kind",
  "json_pointer", "semantic", "subject_id", "phase", "claim_status",
  "confirmation_status",
];
const ACTIVITY_KEYS = [
  "fixture_id", "fixture_content_sha256", "availability", "novelty_status", "launch_method",
  "launch_endpoint", "launch_schema_version",
];
const WINDOW_KEYS = [
  "policy_offset_days", "base_due_on", "initial_due_on", "scheduling_adjustment",
  "calibration", "exam_adjustment",
];
const BASIS_KEYS = [
  "evidence_status", "inputs_used", "excluded_inputs", "recent_evidence_counts_by_domain",
  "evidence_count_unit", "workload_guardrail", "exam_window", "due_review_count",
  "selected_task_count", "future_review_task_count", "duration_policy",
  "retention_window_policy", "retry_window_policy", "schedule_windows",
  "task_definition_status",
];
const WORKLOAD_KEYS = [
  "mode", "eligible_evidence_count", "recent_evidence_count", "recent_attempt_count",
  "recent_failed_attempt_count", "max_non_accepted_tasks",
  "daily_budget_minutes", "overdue_catch_up_count", "withheld_activity_count", "withheld_exam_deadline_count",
  "event_timezone_offsets_minutes", "basis",
];
const SCHEDULE_WINDOWS_KEYS = [
  "cause_probe_days", "independent_retry_days", "delayed_retention_days",
  "calibration", "exam_adjustment",
];

const TASK_KINDS = new Set(["independent_retry", "cause_probe", "delayed_retention"]);
const TASK_STATES = new Set(["scheduled", "accepted", "completed", "postponed", "skipped"]);
const CLAIM_STATUSES = new Set([
  "unconfirmed_hypothesis", "supported_hypothesis", "refuted_hypothesis",
]);
const PLAN_STATUSES = new Set(["empty", "active", "handled", "completed"]);
const EMPTY_REASONS = new Set([
  "no_recorded_evidence", "no_task_due_today", "task_due_after_exam",
  "activity_unavailable", "no_task_within_guardrail", "no_pending_review_tasks",
]);
const ACTIONS = new Set(["accept", "complete", "postpone", "skip"]);
const ACTIONS_BY_STATE = {
  scheduled: new Set(["accept", "postpone", "skip"]),
  accepted: new Set(["complete", "postpone", "skip"]),
  completed: new Set(),
  postponed: new Set(),
  skipped: new Set(),
};
const CREATE_PLAN_CONFLICT_CODES = new Set([
  "historical_plan_read_only",
  "stale_schedule_version",
  "command_conflict",
  "plan_date_mismatch",
]);
const EVIDENCE_KINDS = new Set([
  "trace_observation", "trace_skill_evidence", "candidate_cause", "trace_terminal",
]);
const CURRENT_FIXTURE_ID = "xingce.data-analysis.growth-rate.synthetic-01";
const SHA256 = /^[0-9a-f]{64}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const SAFE_ID = /^[A-Za-z0-9_.:-]{1,96}$/;

export class TodayPlanContractError extends TypeError {
  constructor(path, message) {
    super(`TodayPlan contract error at ${path}: ${message}`);
    this.name = "TodayPlanContractError";
  }
}

function contract(path, condition, message) {
  if (!condition) throw new TodayPlanContractError(path, message);
}

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, expected, path) {
  contract(path, plainObject(value), "expected an object");
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  contract(path, actual.length === required.length, "contains missing or unknown fields");
  contract(path, actual.every((key, index) => key === required[index]), "contains missing or unknown fields");
}

function optionalOrdinalKeys(value, path, allowOrdinal) {
  const expected = allowOrdinal ? [...TASK_KEYS, "ordinal"] : TASK_KEYS;
  exactKeys(value, expected, path);
}

function text(value, path, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  contract(path, typeof value === "string" && value.length > 0, "expected non-empty text");
  return value;
}

function integer(value, path, { min = 0, max = Number.MAX_SAFE_INTEGER } = {}) {
  contract(path, Number.isInteger(value) && value >= min && value <= max, `expected an integer in [${min}, ${max}]`);
  return value;
}

function boolean(value, path) {
  contract(path, typeof value === "boolean", "expected a boolean");
  return value;
}

function isoDate(value, path, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  contract(path, typeof value === "string" && ISO_DATE.test(value), "expected YYYY-MM-DD");
  const parsed = new Date(`${value}T00:00:00Z`);
  contract(path, !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value, "expected a real calendar date");
  return value;
}

function isoTimestamp(value, path) {
  text(value, path);
  contract(path, !Number.isNaN(new Date(value).getTime()), "expected an ISO timestamp");
  return value;
}

function safeIdentifier(value, path) {
  contract(path, typeof value === "string" && SAFE_ID.test(value), "expected a bounded public identifier");
  return value;
}

function stringArray(value, path) {
  contract(path, Array.isArray(value) && value.every((item) => typeof item === "string" && item.length > 0), "expected a text array");
  return [...value];
}

function normalizeEvidenceRef(value, path) {
  exactKeys(value, EVIDENCE_KEYS, path);
  text(value.ref, `${path}.ref`);
  contract(`${path}.kind`, EVIDENCE_KINDS.has(value.kind), "unsupported evidence kind");
  contract(`${path}.source_type`, value.source_type === "trace_event", "must cite a trace event");
  safeIdentifier(value.run_id, `${path}.run_id`);
  integer(value.event_seq, `${path}.event_seq`, { min: 1 });
  contract(`${path}.event_hash`, typeof value.event_hash === "string" && SHA256.test(value.event_hash), "expected a SHA-256 hash");
  text(value.event_kind, `${path}.event_kind`);
  contract(`${path}.json_pointer`, typeof value.json_pointer === "string" && value.json_pointer.startsWith("/"), "expected a JSON pointer");
  text(value.semantic, `${path}.semantic`);
  if (value.kind === "candidate_cause") {
    text(value.subject_id, `${path}.subject_id`);
    contract(`${path}.claim_status`, CLAIM_STATUSES.has(value.claim_status), "candidate claim must remain a hypothesis");
    contract(`${path}.confirmation_status`, value.confirmation_status === "unconfirmed", "candidate cause cannot be confirmed");
  } else {
    contract(`${path}.subject_id`, value.subject_id === null, "non-cause evidence cannot carry subject_id");
    contract(`${path}.claim_status`, value.claim_status === null, "non-cause evidence cannot carry a claim");
    contract(`${path}.confirmation_status`, value.confirmation_status === null, "non-cause evidence cannot carry confirmation");
  }
  contract(`${path}.phase`, value.phase === null || typeof value.phase === "string", "phase must be text or null");
  return {
    ref: value.ref,
    kind: value.kind,
    sourceType: value.source_type,
    runId: value.run_id,
    eventSeq: value.event_seq,
    eventHash: value.event_hash,
    eventKind: value.event_kind,
    jsonPointer: value.json_pointer,
    semantic: value.semantic,
    subjectId: value.subject_id,
    phase: value.phase,
    claimStatus: value.claim_status,
    confirmationStatus: value.confirmation_status,
    causeStatusCopy: value.kind === "candidate_cause" ? "候选 / 未确认" : null,
  };
}

function normalizeActivityRef(value, path) {
  exactKeys(value, ACTIVITY_KEYS, path);
  text(value.fixture_id, `${path}.fixture_id`);
  contract(`${path}.fixture_content_sha256`, typeof value.fixture_content_sha256 === "string" && SHA256.test(value.fixture_content_sha256), "expected a fixture SHA-256 hash");
  contract(`${path}.availability`, ["launchable", "activity_unavailable"].includes(value.availability), "unsupported availability");
  contract(`${path}.novelty_status`, value.novelty_status === "same_fixture_retest_not_novel_item", "unsupported novelty status");
  contract(`${path}.launch_method`, value.launch_method === "POST", "unsupported launch method");
  contract(`${path}.launch_endpoint`, value.launch_endpoint === "/v1/attempts", "unsupported launch endpoint");
  contract(`${path}.launch_schema_version`, value.launch_schema_version === "hermes.attempt-session.v1", "unsupported launch schema");
  return {
    fixtureId: value.fixture_id,
    fixtureContentSha256: value.fixture_content_sha256,
    availability: value.availability,
    noveltyStatus: value.novelty_status,
    launchMethod: value.launch_method,
    launchEndpoint: value.launch_endpoint,
    launchSchemaVersion: value.launch_schema_version,
  };
}

function normalizeScheduleWindow(value, path) {
  exactKeys(value, WINDOW_KEYS, path);
  const policyOffsetDays = integer(value.policy_offset_days, `${path}.policy_offset_days`, { min: 1, max: 3 });
  const baseDueOn = isoDate(value.base_due_on, `${path}.base_due_on`);
  const initialDueOn = isoDate(value.initial_due_on, `${path}.initial_due_on`);
  contract(`${path}.scheduling_adjustment`, ["on_policy_window", "overdue_catch_up"].includes(value.scheduling_adjustment), "unsupported scheduling adjustment");
  contract(`${path}.calibration`, value.calibration === "fixed_engineering_policy_unvalidated", "unsupported calibration label");
  contract(`${path}.exam_adjustment`, value.exam_adjustment === "withhold_if_due_after_exam", "unsupported exam adjustment");
  return {
    policyOffsetDays,
    baseDueOn,
    initialDueOn,
    schedulingAdjustment: value.scheduling_adjustment,
    calibration: value.calibration,
    examAdjustment: value.exam_adjustment,
  };
}

function normalizeTask(value, path, { allowOrdinal = false } = {}) {
  optionalOrdinalKeys(value, path, allowOrdinal);
  contract(`${path}.schema_version`, value.schema_version === "lumi.review-schedule.v1", "unsupported schema version");
  safeIdentifier(value.task_id, `${path}.task_id`);
  text(value.source_key, `${path}.source_key`);
  contract(`${path}.task_kind`, TASK_KINDS.has(value.task_kind), "unsupported task kind");
  contract(`${path}.domain`, ["xingce", "shenlun", "interview"].includes(value.domain), "unsupported domain");
  text(value.skill_id, `${path}.skill_id`);
  text(value.reason, `${path}.reason`);
  integer(value.expected_duration_minutes, `${path}.expected_duration_minutes`, { min: 1, max: 60 });
  text(value.success_criterion, `${path}.success_criterion`);
  text(value.skip_consequence, `${path}.skip_consequence`);
  contract(`${path}.evidence_refs`, Array.isArray(value.evidence_refs) && value.evidence_refs.length > 0, "requires structured evidence refs");
  const evidenceRefs = value.evidence_refs.map((item, index) => normalizeEvidenceRef(item, `${path}.evidence_refs[${index}]`));
  const activityRef = normalizeActivityRef(value.activity_ref, `${path}.activity_ref`);
  if (value.task_kind === "cause_probe") {
    text(value.cause_id, `${path}.cause_id`);
    text(value.cause_label, `${path}.cause_label`);
    contract(`${path}.cause_confirmation_status`, value.cause_confirmation_status === "unconfirmed", "candidate cause must remain unconfirmed");
  } else {
    contract(`${path}.cause_id`, value.cause_id === null, "non-cause task cannot carry cause_id");
    contract(`${path}.cause_label`, value.cause_label === null, "non-cause task cannot carry cause_label");
    contract(`${path}.cause_confirmation_status`, value.cause_confirmation_status === null, "non-cause task cannot carry cause confirmation");
  }
  contract(`${path}.definition_status`, value.definition_status === "authored_engineering_estimate_unvalidated", "unsupported definition status");
  const policyOffsetDays = integer(value.policy_offset_days, `${path}.policy_offset_days`, { min: 1, max: 3 });
  const expectedPolicyOffset = value.task_kind === "delayed_retention" ? 3 : 1;
  contract(`${path}.policy_offset_days`, policyOffsetDays === expectedPolicyOffset, "policy offset does not match task kind");
  const baseDueOn = isoDate(value.base_due_on, `${path}.base_due_on`);
  const initialDueOn = isoDate(value.initial_due_on, `${path}.initial_due_on`);
  contract(`${path}.initial_due_on`, initialDueOn >= baseDueOn, "initial due date cannot precede the fixed-window base date");
  const expectedAdjustment = initialDueOn > baseDueOn ? "overdue_catch_up" : "on_policy_window";
  contract(`${path}.scheduling_adjustment`, value.scheduling_adjustment === expectedAdjustment, "scheduling adjustment is inconsistent with fixed-window dates");
  const scheduleWindow = normalizeScheduleWindow(value.schedule_window, `${path}.schedule_window`);
  contract(`${path}.schedule_window`, scheduleWindow.policyOffsetDays === policyOffsetDays, "nested policy offset mismatch");
  contract(`${path}.schedule_window`, scheduleWindow.baseDueOn === baseDueOn, "nested base due date mismatch");
  contract(`${path}.schedule_window`, scheduleWindow.initialDueOn === initialDueOn, "nested initial due date mismatch");
  contract(`${path}.schedule_window`, scheduleWindow.schedulingAdjustment === value.scheduling_adjustment, "nested scheduling adjustment mismatch");
  contract(`${path}.state`, TASK_STATES.has(value.state), "unsupported task state");
  if (value.state === "completed") {
    contract(`${path}.completion_semantics`, value.completion_semantics === "user_marked_not_learning_evidence", "completion cannot become learning evidence");
  } else {
    contract(`${path}.completion_semantics`, value.completion_semantics === null, "completion semantics must be null before completion");
  }
  isoDate(value.due_on, `${path}.due_on`);
  integer(value.version, `${path}.version`, { min: 1 });
  isoTimestamp(value.created_at, `${path}.created_at`);
  isoTimestamp(value.updated_at, `${path}.updated_at`);
  if (allowOrdinal) integer(value.ordinal, `${path}.ordinal`, { min: 1 });
  const launchable = activityRef.availability === "launchable"
    && activityRef.fixtureId === CURRENT_FIXTURE_ID;
  const scheduleTruthCopy = value.scheduling_adjustment === "overdue_catch_up"
    ? `固定未校准 +${policyOffsetDays} 天窗口已错过；${initialDueOn} 为逾期补排日，不代表仍按 +${policyOffsetDays} 天执行。`
    : `固定未校准 +${policyOffsetDays} 天窗口；基准到期日与首次排入日均为 ${baseDueOn}。`;
  return {
    id: value.task_id,
    sourceKey: value.source_key,
    taskKind: value.task_kind,
    domain: value.domain,
    skillId: value.skill_id,
    reason: value.reason,
    expectedDurationMinutes: value.expected_duration_minutes,
    durationCalibration: "未校准工程估算",
    successCriterion: value.success_criterion,
    skipConsequence: value.skip_consequence,
    evidenceRefs,
    activityRef,
    causeId: value.cause_id,
    causeLabel: value.cause_label,
    causeConfirmationStatus: value.cause_confirmation_status,
    causeStatusCopy: value.task_kind === "cause_probe" ? "候选 / 未确认" : null,
    definitionStatus: value.definition_status,
    policyOffsetDays,
    baseDueOn,
    initialDueOn,
    schedulingAdjustment: value.scheduling_adjustment,
    scheduleTruthCopy,
    scheduleWindow,
    completionSemantics: value.completion_semantics,
    state: value.state,
    dueOn: value.due_on,
    version: value.version,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    ordinal: allowOrdinal ? value.ordinal : null,
    launchable,
  };
}

function normalizeBasis(value, path) {
  exactKeys(value, BASIS_KEYS, path);
  contract(`${path}.evidence_status`, ["recorded", "unavailable"].includes(value.evidence_status), "unsupported evidence status");
  const inputsUsed = stringArray(value.inputs_used, `${path}.inputs_used`);
  const excludedInputs = stringArray(value.excluded_inputs, `${path}.excluded_inputs`);
  exactKeys(value.recent_evidence_counts_by_domain, ["xingce", "shenlun", "interview"], `${path}.recent_evidence_counts_by_domain`);
  const evidenceCountsByDomain = Object.fromEntries(Object.entries(value.recent_evidence_counts_by_domain).map(([key, count]) => [key, integer(count, `${path}.recent_evidence_counts_by_domain.${key}`)]));
  contract(`${path}.evidence_count_unit`, value.evidence_count_unit === "trace_backed_planning_evidence_record", "unsupported evidence unit");
  exactKeys(value.workload_guardrail, WORKLOAD_KEYS, `${path}.workload_guardrail`);
  contract(`${path}.workload_guardrail.mode`, ["standard_load", "reduced_load", "recovery_load"].includes(value.workload_guardrail.mode), "unsupported workload mode");
  contract(`${path}.workload_guardrail.event_timezone_offsets_minutes`, Array.isArray(value.workload_guardrail.event_timezone_offsets_minutes), "expected timezone offsets array");
  const workloadGuardrail = {
    mode: value.workload_guardrail.mode,
    eligibleEvidenceCount: integer(value.workload_guardrail.eligible_evidence_count, `${path}.workload_guardrail.eligible_evidence_count`),
    recentEvidenceCount: integer(value.workload_guardrail.recent_evidence_count, `${path}.workload_guardrail.recent_evidence_count`),
    recentAttemptCount: integer(value.workload_guardrail.recent_attempt_count, `${path}.workload_guardrail.recent_attempt_count`),
    recentFailedAttemptCount: integer(value.workload_guardrail.recent_failed_attempt_count, `${path}.workload_guardrail.recent_failed_attempt_count`),
    maxNonAcceptedTasks: integer(value.workload_guardrail.max_non_accepted_tasks, `${path}.workload_guardrail.max_non_accepted_tasks`, { min: 1, max: 3 }),
    dailyBudgetMinutes: integer(value.workload_guardrail.daily_budget_minutes, `${path}.workload_guardrail.daily_budget_minutes`, { min: 5, max: 240 }),
    overdueCatchUpCount: integer(value.workload_guardrail.overdue_catch_up_count, `${path}.workload_guardrail.overdue_catch_up_count`),
    withheldActivityCount: integer(value.workload_guardrail.withheld_activity_count, `${path}.workload_guardrail.withheld_activity_count`),
    withheldExamDeadlineCount: integer(value.workload_guardrail.withheld_exam_deadline_count, `${path}.workload_guardrail.withheld_exam_deadline_count`),
    eventTimezoneOffsetsMinutes: value.workload_guardrail.event_timezone_offsets_minutes.map((item, index) => integer(item, `${path}.workload_guardrail.event_timezone_offsets_minutes[${index}]`, { min: -720, max: 840 })),
    basis: value.workload_guardrail.basis,
  };
  contract(`${path}.workload_guardrail.basis`, value.workload_guardrail.basis === "fixed_engineering_policy_not_population_calibrated", "unsupported workload basis");
  contract(`${path}.exam_window`, ["not_provided", "near", "normal"].includes(value.exam_window), "unsupported exam window");
  const dueReviewCount = integer(value.due_review_count, `${path}.due_review_count`);
  const selectedTaskCount = integer(value.selected_task_count, `${path}.selected_task_count`);
  const futureReviewTaskCount = integer(value.future_review_task_count, `${path}.future_review_task_count`);
  contract(`${path}.duration_policy`, value.duration_policy === "fixed_estimate_not_population_calibrated", "unsupported duration policy");
  contract(`${path}.retention_window_policy`, value.retention_window_policy === "engineering_default_plus_3_days_unvalidated", "unsupported retention window policy");
  contract(`${path}.retry_window_policy`, value.retry_window_policy === "engineering_default_plus_1_day_unvalidated", "unsupported retry window policy");
  exactKeys(value.schedule_windows, SCHEDULE_WINDOWS_KEYS, `${path}.schedule_windows`);
  contract(`${path}.schedule_windows.cause_probe_days`, value.schedule_windows.cause_probe_days === 1, "unsupported cause window");
  contract(`${path}.schedule_windows.independent_retry_days`, value.schedule_windows.independent_retry_days === 1, "unsupported retry window");
  contract(`${path}.schedule_windows.delayed_retention_days`, value.schedule_windows.delayed_retention_days === 3, "unsupported retention window");
  contract(`${path}.schedule_windows.calibration`, value.schedule_windows.calibration === "fixed_engineering_policy_unvalidated", "unsupported schedule calibration");
  contract(`${path}.schedule_windows.exam_adjustment`, value.schedule_windows.exam_adjustment === "withhold_if_due_after_exam", "unsupported schedule exam adjustment");
  contract(`${path}.task_definition_status`, value.task_definition_status === "authored_engineering_estimate_unvalidated", "unsupported task definition status");
  return {
    evidenceStatus: value.evidence_status,
    inputsUsed,
    excludedInputs,
    evidenceCountsByDomain,
    workloadGuardrail,
    examWindow: value.exam_window,
    dueReviewCount,
    selectedTaskCount,
    futureReviewTaskCount,
    durationPolicy: value.duration_policy,
    retentionWindowPolicy: value.retention_window_policy,
    retryWindowPolicy: value.retry_window_policy,
  };
}

export function normalizeTodayPlan(payload) {
  exactKeys(payload, TODAY_PLAN_KEYS, "plan");
  contract("plan.schema_version", payload.schema_version === "lumi.today-plan.v1", "unsupported schema version");
  safeIdentifier(payload.plan_id, "plan.plan_id");
  isoDate(payload.plan_date, "plan.plan_date");
  isoDate(payload.exam_date, "plan.exam_date", { nullable: true });
  contract("plan.status", PLAN_STATUSES.has(payload.status), "unsupported plan status");
  integer(payload.version, "plan.version", { min: 1 });
  contract("plan.scheduler_policy_version", payload.scheduler_policy_version === "lumi.deterministic-scheduler.v1", "unsupported scheduler policy");
  const normalizedBasis = normalizeBasis(payload.basis, "plan.basis");
  contract("plan.empty_reason", payload.empty_reason === null || EMPTY_REASONS.has(payload.empty_reason), "unsupported empty reason");
  const evidenceRefs = stringArray(payload.evidence_refs, "plan.evidence_refs");
  contract("plan.tasks", Array.isArray(payload.tasks), "expected tasks array");
  const tasks = payload.tasks.map((item, index) => normalizeTask(item, `plan.tasks[${index}]`, { allowOrdinal: true }));
  contract("plan.mastery_write_capability", payload.mastery_write_capability === false, "schedule actions cannot write mastery");
  if (payload.status === "empty") {
    contract("plan.tasks", tasks.length === 0 && payload.empty_reason !== null, "empty plan must have an empty reason and no tasks");
  } else {
    contract("plan.tasks", tasks.length > 0 && payload.empty_reason === null, "non-empty plan requires tasks and no empty reason");
  }
  isoTimestamp(payload.created_at, "plan.created_at");
  isoTimestamp(payload.updated_at, "plan.updated_at");
  exactKeys(payload.links, ["self", "replay", "review_schedule"], "plan.links");
  contract("plan.links.self", payload.links.self === `/v1/today-plans/${encodeURIComponent(payload.plan_id)}`, "unsafe self link");
  contract("plan.links.replay", payload.links.replay === `/v1/today-plans/${encodeURIComponent(payload.plan_id)}/replay`, "unsafe replay link");
  contract("plan.links.review_schedule", payload.links.review_schedule === "/v1/review-schedule", "unsafe schedule link");
  exactKeys(payload.event_stream, ["stream_type", "stream_id", "version", "trace_verified", "projection_verified"], "plan.event_stream");
  contract("plan.event_stream.stream_type", payload.event_stream.stream_type === "today_plan", "unsupported stream type");
  contract("plan.event_stream.stream_id", payload.event_stream.stream_id === payload.plan_id, "stream id mismatch");
  integer(payload.event_stream.version, "plan.event_stream.version", { min: 1 });
  contract("plan.event_stream.trace_verified", payload.event_stream.trace_verified === true, "schedule trace is not verified");
  contract("plan.event_stream.projection_verified", payload.event_stream.projection_verified === true, "schedule projection is not verified");
  return {
    planId: payload.plan_id,
    planDate: payload.plan_date,
    examDate: payload.exam_date,
    status: payload.status,
    version: payload.version,
    schedulerPolicyVersion: payload.scheduler_policy_version,
    basis: normalizedBasis,
    emptyReason: payload.empty_reason,
    evidenceRefs,
    tasks,
    masteryWriteCapability: false,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
    links: { self: payload.links.self, replay: payload.links.replay, reviewSchedule: payload.links.review_schedule },
    eventStream: {
      streamType: payload.event_stream.stream_type,
      streamId: payload.event_stream.stream_id,
      version: payload.event_stream.version,
      traceVerified: true,
      projectionVerified: true,
    },
  };
}

export function normalizeReviewSchedule(payload) {
  exactKeys(payload, REVIEW_SCHEDULE_KEYS, "reviewSchedule");
  contract("reviewSchedule.schema_version", payload.schema_version === "lumi.review-schedule.v1", "unsupported schema version");
  integer(payload.count, "reviewSchedule.count");
  contract("reviewSchedule.items", Array.isArray(payload.items) && payload.items.length === payload.count, "count does not match items");
  const items = payload.items.map((item, index) => normalizeTask(item, `reviewSchedule.items[${index}]`));
  contract("reviewSchedule.authority", payload.authority === "independent_review_schedule_projection", "unsupported authority");
  contract("reviewSchedule.mastery_write_capability", payload.mastery_write_capability === false, "schedule cannot write mastery");
  contract("reviewSchedule.population_evidence", payload.population_evidence === "unavailable", "population evidence must remain unavailable");
  return {
    count: payload.count,
    items,
    authority: payload.authority,
    masteryWriteCapability: false,
    populationEvidence: "unavailable",
  };
}

export function localDateString(now = new Date()) {
  contract("clientClock", now instanceof Date && !Number.isNaN(now.getTime()), "expected a valid local Date");
  const year = String(now.getFullYear()).padStart(4, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function resolveClientNow() {
  const injected = import.meta.env?.DEV && typeof globalThis.location?.search === "string"
    ? new URLSearchParams(globalThis.location.search).get("qa-date")
    : null;
  if (injected && ISO_DATE.test(injected)) {
    const [year, month, day] = injected.split("-").map(Number);
    const candidate = new Date(year, month - 1, day, 12, 0, 0);
    if (localDateString(candidate) === injected) return candidate;
  }
  return new Date();
}

export function todayPlanId(now = new Date()) {
  return `today-${localDateString(now)}`;
}

export function isCreatePlanConflictCode(code) {
  return CREATE_PLAN_CONFLICT_CODES.has(code);
}

export function classifyCreatePlanError(error) {
  const code = error?.code;
  if (error?.status !== 409) return "error";
  if (code === "budget_below_accepted_commitment") return "retry_with_higher_budget";
  if (isCreatePlanConflictCode(code)) return "refresh";
  return "error";
}

export function createOpaqueCommandId() {
  return createCommandId();
}

function commandId(value) {
  contract("command.command_id", isCommandId(value), "invalid opaque command id");
  return value;
}

export function buildCreateTodayPlanCommand({
  now = new Date(),
  examDate,
  dailyBudgetMinutes,
  commandId: opaqueCommandId = createOpaqueCommandId(),
} = {}) {
  const planDate = localDateString(now);
  integer(dailyBudgetMinutes, "command.daily_budget_minutes", { min: 5, max: 240 });
  const body = {
    plan_date: planDate,
    daily_budget_minutes: dailyBudgetMinutes,
    expected_version: 0,
    command_id: commandId(opaqueCommandId),
  };
  if (examDate !== undefined && examDate !== null && examDate !== "") {
    isoDate(examDate, "command.exam_date");
    contract("command.exam_date", examDate >= planDate, "exam date cannot precede the local plan date");
    body.exam_date = examDate;
  }
  return body;
}

export function buildTaskCommand({
  plan,
  task,
  action,
  postponeUntil,
  commandId: opaqueCommandId = createOpaqueCommandId(),
} = {}) {
  contract("command.action", ACTIONS.has(action), "unsupported action");
  contract("command.action", ACTIONS_BY_STATE[task?.state]?.has(action), "action is not allowed from the current task state");
  integer(plan?.version, "command.expected_version", { min: 1 });
  integer(task?.version, "command.expected_task_version", { min: 1 });
  const body = {
    action,
    expected_version: plan.version,
    expected_task_version: task.version,
    command_id: commandId(opaqueCommandId),
  };
  if (action === "postpone") {
    isoDate(postponeUntil, "command.postpone_until");
    contract("command.postpone_until", postponeUntil > plan.planDate, "postpone date must be after the local plan date");
    body.postpone_until = postponeUntil;
  } else {
    contract("command.postpone_until", postponeUntil === undefined || postponeUntil === null || postponeUntil === "", "postpone_until is only valid for postpone");
  }
  return body;
}
