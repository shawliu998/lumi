import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  buildCreateTodayPlanCommand,
  buildTaskCommand,
  classifyCreatePlanError,
  createOpaqueCommandId,
  isCreatePlanConflictCode,
  localDateString,
  normalizeReviewSchedule,
  normalizeTodayPlan,
} from "./todayPlanAdapter.js";

const HASH = "a".repeat(64);
const COMMAND_ID = `c_${"A".repeat(40)}`;

function evidenceRef(overrides = {}) {
  return {
    ref: `trace:run-contract:event:3:${HASH}#pointer=/output/score/passed`,
    kind: "trace_observation",
    source_type: "trace_event",
    run_id: "run-contract",
    event_seq: 3,
    event_hash: HASH,
    event_kind: "phase_completed",
    json_pointer: "/output/score/passed",
    semantic: "initial_answer_passed",
    subject_id: null,
    phase: "observe",
    claim_status: null,
    confirmation_status: null,
    ...overrides,
  };
}

function task(overrides = {}) {
  return {
    schema_version: "lumi.review-schedule.v1",
    task_id: "review-contract",
    source_key: "skill:contract",
    task_kind: "independent_retry",
    domain: "xingce",
    skill_id: "xingce.data.growth.compute-rate",
    reason: "最近一次单次学习证据未达到独立迁移标准，安排一次短复习。",
    expected_duration_minutes: 15,
    success_criterion: "在同题组独立复测中达到既定评分标准。",
    skip_consequence: "若跳过，任务保留在 ReviewSchedule，并按后续学习日公平轮候。",
    evidence_refs: [evidenceRef()],
    activity_ref: {
      fixture_id: "xingce.data-analysis.growth-rate.synthetic-01",
      fixture_content_sha256: HASH,
      availability: "launchable",
      novelty_status: "same_fixture_retest_not_novel_item",
      launch_method: "POST",
      launch_endpoint: "/v1/attempts",
      launch_schema_version: "hermes.attempt-session.v1",
    },
    cause_id: null,
    cause_label: null,
    cause_confirmation_status: null,
    definition_status: "authored_engineering_estimate_unvalidated",
    policy_offset_days: 1,
    base_due_on: "2026-07-11",
    initial_due_on: "2026-07-11",
    scheduling_adjustment: "on_policy_window",
    schedule_window: {
      policy_offset_days: 1,
      base_due_on: "2026-07-11",
      initial_due_on: "2026-07-11",
      scheduling_adjustment: "on_policy_window",
      calibration: "fixed_engineering_policy_unvalidated",
      exam_adjustment: "withhold_if_due_after_exam",
    },
    completion_semantics: null,
    state: "scheduled",
    due_on: "2026-07-11",
    version: 1,
    created_at: "2026-07-11T00:00:00+00:00",
    updated_at: "2026-07-11T00:00:00+00:00",
    ...overrides,
  };
}

function basis() {
  return {
    evidence_status: "recorded",
    inputs_used: ["daily_budget_minutes", "per_run_skill_evidence"],
    excluded_inputs: [
      "cohort_statistics",
      "peer_comparison",
      "population_effect",
      "authoritative_longitudinal_mastery",
      "learner_fatigue_signal",
    ],
    recent_evidence_counts_by_domain: { xingce: 1, shenlun: 0, interview: 0 },
    evidence_count_unit: "trace_backed_planning_evidence_record",
    workload_guardrail: {
      mode: "standard_load",
      eligible_evidence_count: 1,
      recent_evidence_count: 1,
      recent_attempt_count: 1,
      recent_failed_attempt_count: 1,
      max_non_accepted_tasks: 3,
      daily_budget_minutes: 60,
      overdue_catch_up_count: 0,
      withheld_activity_count: 0,
      withheld_exam_deadline_count: 0,
      event_timezone_offsets_minutes: [480],
      basis: "fixed_engineering_policy_not_population_calibrated",
    },
    exam_window: "not_provided",
    due_review_count: 1,
    selected_task_count: 1,
    future_review_task_count: 0,
    duration_policy: "fixed_estimate_not_population_calibrated",
    retention_window_policy: "engineering_default_plus_3_days_unvalidated",
    retry_window_policy: "engineering_default_plus_1_day_unvalidated",
    schedule_windows: {
      cause_probe_days: 1,
      independent_retry_days: 1,
      delayed_retention_days: 3,
      calibration: "fixed_engineering_policy_unvalidated",
      exam_adjustment: "withhold_if_due_after_exam",
    },
    task_definition_status: "authored_engineering_estimate_unvalidated",
  };
}

function todayPlan(overrides = {}) {
  return {
    schema_version: "lumi.today-plan.v1",
    plan_id: "today-2026-07-11",
    plan_date: "2026-07-11",
    exam_date: null,
    status: "active",
    version: 1,
    scheduler_policy_version: "lumi.deterministic-scheduler.v1",
    basis: basis(),
    empty_reason: null,
    evidence_refs: [evidenceRef().ref],
    tasks: [{ ...task(), ordinal: 1 }],
    mastery_write_capability: false,
    created_at: "2026-07-11T00:00:00+00:00",
    updated_at: "2026-07-11T00:00:00+00:00",
    links: {
      self: "/v1/today-plans/today-2026-07-11",
      replay: "/v1/today-plans/today-2026-07-11/replay",
      review_schedule: "/v1/review-schedule",
    },
    event_stream: {
      stream_type: "today_plan",
      stream_id: "today-2026-07-11",
      version: 1,
      trace_verified: true,
      projection_verified: true,
    },
    ...overrides,
  };
}

function reviewSchedule(overrides = {}) {
  return {
    schema_version: "lumi.review-schedule.v1",
    count: 1,
    items: [task()],
    authority: "independent_review_schedule_projection",
    mastery_write_capability: false,
    population_evidence: "unavailable",
    ...overrides,
  };
}

test("strict adapters accept the exact P0.2 TodayPlan and ReviewSchedule contracts", () => {
  const normalizedPlan = normalizeTodayPlan(todayPlan());
  const normalizedSchedule = normalizeReviewSchedule(reviewSchedule());
  assert.equal(normalizedPlan.planId, "today-2026-07-11");
  assert.equal(normalizedPlan.tasks[0].durationCalibration, "未校准工程估算");
  assert.equal(normalizedPlan.tasks[0].launchable, true);
  assert.equal(normalizedPlan.tasks[0].activityRef.noveltyStatus, "same_fixture_retest_not_novel_item");
  assert.equal(normalizedPlan.tasks[0].policyOffsetDays, 1);
  assert.equal(normalizedPlan.tasks[0].schedulingAdjustment, "on_policy_window");
  assert.equal(normalizedPlan.basis.workloadGuardrail.overdueCatchUpCount, 0);
  assert.equal(normalizedPlan.basis.workloadGuardrail.eligibleEvidenceCount, 1);
  assert.equal(normalizedPlan.basis.workloadGuardrail.recentEvidenceCount, 1);
  assert.equal(normalizedPlan.basis.workloadGuardrail.maxNonAcceptedTasks, 3);
  assert.equal(normalizedSchedule.items[0].state, "scheduled");
  assert.equal(normalizedSchedule.masteryWriteCapability, false);
});

test("completed ReviewSchedule evidence has its own honest no-pending-review empty reason", () => {
  const payload = todayPlan({
    status: "empty",
    empty_reason: "no_pending_review_tasks",
    evidence_refs: [],
    tasks: [],
    basis: {
      ...basis(),
      selected_task_count: 0,
      future_review_task_count: 0,
      workload_guardrail: {
        ...basis().workload_guardrail,
        overdue_catch_up_count: 0,
      },
    },
  });
  const normalized = normalizeTodayPlan(payload);
  assert.equal(normalized.emptyReason, "no_pending_review_tasks");
  assert.equal(normalized.basis.workloadGuardrail.overdueCatchUpCount, 0);
});

test("overdue catch-up exposes the missed fixed window and never pretends the actual due date is +1/+3", () => {
  const overdue = task({
    task_kind: "delayed_retention",
    policy_offset_days: 3,
    base_due_on: "2026-07-10",
    initial_due_on: "2026-07-11",
    scheduling_adjustment: "overdue_catch_up",
    schedule_window: {
      policy_offset_days: 3,
      base_due_on: "2026-07-10",
      initial_due_on: "2026-07-11",
      scheduling_adjustment: "overdue_catch_up",
      calibration: "fixed_engineering_policy_unvalidated",
      exam_adjustment: "withhold_if_due_after_exam",
    },
  });
  const normalized = normalizeReviewSchedule(reviewSchedule({ items: [overdue] })).items[0];
  assert.equal(normalized.baseDueOn, "2026-07-10");
  assert.equal(normalized.initialDueOn, "2026-07-11");
  assert.match(normalized.scheduleTruthCopy, /固定.*\+3 天窗口已错过/);
  assert.match(normalized.scheduleTruthCopy, /逾期补排/);
  assert.match(normalized.scheduleTruthCopy, /不代表仍按 \+3 天执行/);
});

test("legacy base/applied offsets and inconsistent scheduling truth fail closed", () => {
  assert.throws(() => normalizeReviewSchedule(reviewSchedule({ items: [task({
    schedule_window: { ...task().schedule_window, base_offset_days: 1 },
  })] })), /contract/i);
  assert.throws(() => normalizeReviewSchedule(reviewSchedule({ items: [task({
    initial_due_on: "2026-07-12",
    scheduling_adjustment: "on_policy_window",
    schedule_window: {
      ...task().schedule_window,
      initial_due_on: "2026-07-12",
      scheduling_adjustment: "on_policy_window",
    },
  })] })), /contract/i);
});

test("candidate causes remain candidate / unconfirmed without a probability surface", () => {
  const causeEvidence = evidenceRef({
    ref: `trace:run-contract:event:5:${HASH}#pointer=/assessments/0/claim_status`,
    kind: "candidate_cause",
    event_seq: 5,
    event_kind: "probe_assessed",
    json_pointer: "/assessments/0/claim_status",
    semantic: "candidate_claim_status",
    subject_id: "ratio-growth-confusion",
    phase: null,
    claim_status: "supported_hypothesis",
    confirmation_status: "unconfirmed",
  });
  const causeTask = task({
    task_kind: "cause_probe",
    cause_id: "ratio-growth-confusion",
    cause_label: "把倍数关系直接当作增长率",
    cause_confirmation_status: "unconfirmed",
    evidence_refs: [causeEvidence],
  });
  const normalized = normalizeReviewSchedule(reviewSchedule({ items: [causeTask] }));
  assert.equal(normalized.items[0].causeStatusCopy, "候选 / 未确认");
  assert.equal("probability" in normalized.items[0], false);
  assert.equal("rankingProbability" in normalized.items[0], false);
  assert.equal(normalized.items[0].evidenceRefs[0].causeStatusCopy, "候选 / 未确认");
});

test("unknown and fabricated planning fields fail closed at every contract level", () => {
  const attacks = [
    todayPlan({ predicted_gain: 18 }),
    todayPlan({ mastery: 0.9 }),
    todayPlan({ tasks: [{ ...todayPlan().tasks[0], fatigue: "high" }] }),
    todayPlan({ tasks: [{ ...todayPlan().tasks[0], activity_ref: { ...task().activity_ref, peer_rate: 0.8 } }] }),
    todayPlan({ tasks: [{ ...todayPlan().tasks[0], evidence_refs: [{ ...evidenceRef(), forgetting_probability: 0.4 }] }] }),
    todayPlan({ basis: { ...basis(), invented_metric: 7 } }),
  ];
  for (const payload of attacks) {
    assert.throws(() => normalizeTodayPlan(payload), /contract/i);
  }
  assert.throws(
    () => normalizeReviewSchedule(reviewSchedule({ cohort_mastery: 0.8 })),
    /contract/i,
  );
  const currentWorkload = basis().workload_guardrail;
  const { max_non_accepted_tasks: _removed, ...legacyWorkload } = currentWorkload;
  assert.throws(
    () => normalizeTodayPlan(todayPlan({
      basis: {
        ...basis(),
        workload_guardrail: { ...legacyWorkload, max_new_tasks: 3 },
      },
    })),
    /workload_guardrail.*missing|unknown fields/i,
  );
});

test("invalid availability, claim confirmation, completion semantics, and plan status fail closed", () => {
  assert.throws(
    () => normalizeReviewSchedule(reviewSchedule({ items: [task({ activity_ref: { ...task().activity_ref, availability: "withheld" } })] })),
    /contract/i,
  );
  assert.throws(
    () => normalizeReviewSchedule(reviewSchedule({ items: [task({
      task_kind: "cause_probe",
      cause_id: "ratio-growth-confusion",
      cause_label: "把倍数关系直接当作增长率",
      cause_confirmation_status: "confirmed",
    })] })),
    /contract/i,
  );
  assert.throws(
    () => normalizeReviewSchedule(reviewSchedule({ items: [task({ state: "completed", completion_semantics: "learning_evidence" })] })),
    /contract/i,
  );
  assert.throws(() => normalizeTodayPlan(todayPlan({ status: "mastered" })), /contract/i);
});

test("activity novelty status is required and rejects any claim of a novel item", () => {
  const activity = task().activity_ref;
  const { novelty_status: _missing, ...missingNovelty } = activity;
  assert.throws(
    () => normalizeReviewSchedule(reviewSchedule({ items: [task({ activity_ref: missingNovelty })] })),
    /activity_ref.*missing|unknown fields/i,
  );
  assert.throws(
    () => normalizeReviewSchedule(reviewSchedule({ items: [task({ activity_ref: { ...activity, novelty_status: "novel_parallel_item" } })] })),
    /novelty/i,
  );
});

test("plan creation uses only the injected local date, optional exam date, bounded budget, version zero, and opaque command id", () => {
  const now = new Date(2026, 6, 11, 23, 45, 0);
  assert.equal(localDateString(now), "2026-07-11");
  assert.deepEqual(buildCreateTodayPlanCommand({
    now,
    examDate: "2026-08-10",
    dailyBudgetMinutes: 60,
    commandId: COMMAND_ID,
  }), {
    plan_date: "2026-07-11",
    exam_date: "2026-08-10",
    daily_budget_minutes: 60,
    expected_version: 0,
    command_id: COMMAND_ID,
  });
  assert.throws(() => buildCreateTodayPlanCommand({ now, dailyBudgetMinutes: 4, commandId: COMMAND_ID }), /5.*240/);
  assert.throws(() => buildCreateTodayPlanCommand({ now, dailyBudgetMinutes: 241, commandId: COMMAND_ID }), /5.*240/);
  assert.throws(() => buildCreateTodayPlanCommand({ now, examDate: "2026-7-12", dailyBudgetMinutes: 30, commandId: COMMAND_ID }), /exam/i);
});

test("create-plan conflicts include a stale-clock historical plan and exclude task-only conflicts", () => {
  for (const code of ["historical_plan_read_only", "stale_schedule_version", "command_conflict", "plan_date_mismatch"]) {
    assert.equal(isCreatePlanConflictCode(code), true, code);
  }
  assert.equal(isCreatePlanConflictCode("stale_task_version"), false);
  assert.equal(isCreatePlanConflictCode("unknown"), false);
  const appSource = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
  assert.match(appSource, /error\?\.code === "historical_plan_read_only"/);
  assert.match(appSource, /本机日期或计划状态已变化；已重新读取本机当前计划/);
});

test("accepted-commitment budget conflict keeps create retryable without a planning refresh", () => {
  assert.equal(classifyCreatePlanError({ status: 409, code: "budget_below_accepted_commitment" }), "retry_with_higher_budget");
  assert.equal(classifyCreatePlanError({ status: 409, code: "historical_plan_read_only" }), "refresh");
  assert.equal(classifyCreatePlanError({ status: 409, code: "stale_schedule_version" }), "refresh");
  assert.equal(classifyCreatePlanError({ status: 400, code: "budget_below_accepted_commitment" }), "error");
  assert.equal(classifyCreatePlanError({ status: 409, code: "unknown" }), "error");

  const appSource = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
  const viewsSource = readFileSync(new URL("./TodayPlanViews.jsx", import.meta.url), "utf8");
  assert.match(appSource, /budget_below_accepted_commitment/);
  assert.match(appSource, /请提高今日可用时间后重试/);
  assert.match(appSource, /本次请求没有创建或修改计划/);
  assert.match(viewsSource, /已接受任务全部优先展示且不计入此上限/);
  assert.match(viewsSource, /剩余预算最多再排/);
  assert.match(viewsSource, /尚未接受的任务/);
  assert.match(viewsSource, /今日计划/);
  assert.doesNotMatch(viewsSource, /非 accepted 任务|Today 最多|Today 中|Today 展示/);
});

test("task commands contain only action, both optimistic versions, opaque id, and postpone date when required", () => {
  const plan = normalizeTodayPlan(todayPlan());
  const taskItem = plan.tasks[0];
  assert.deepEqual(buildTaskCommand({
    plan,
    task: taskItem,
    action: "accept",
    commandId: COMMAND_ID,
  }), {
    action: "accept",
    expected_version: 1,
    expected_task_version: 1,
    command_id: COMMAND_ID,
  });
  assert.deepEqual(buildTaskCommand({
    plan,
    task: taskItem,
    action: "postpone",
    postponeUntil: "2026-07-12",
    commandId: COMMAND_ID,
  }).postpone_until, "2026-07-12");
  assert.throws(() => buildTaskCommand({ plan, task: taskItem, action: "resurface", commandId: COMMAND_ID }), /action/i);
  assert.throws(() => buildTaskCommand({ plan, task: taskItem, action: "accept", postponeUntil: "2026-07-12", commandId: COMMAND_ID }), /postpone/i);
  assert.throws(() => buildTaskCommand({ plan, task: taskItem, action: "postpone", commandId: COMMAND_ID }), /postpone/i);
});

test("command ids require Web Crypto and expose no timestamp or semantic payload", () => {
  const value = createOpaqueCommandId();
  assert.match(value, /^c_[A-P]{40}$/);
  assert.doesNotMatch(value, /plan|task|accept|complete|postpone|skip|\d{13}/i);
  for (const invalid of [
    "59678fb4-b3ee-4caa-bbb2-2ae95ba15b9c",
    "create-plan-command",
    `sk_live_${"A".repeat(32)}`,
    `ghp_${"A".repeat(32)}`,
  ]) {
    assert.throws(() => buildCreateTodayPlanCommand({ now: new Date(2026, 6, 11), dailyBudgetMinutes: 60, commandId: invalid }), /command/i);
  }
});

test("skip and postpone copy preserves fair rotation without promising same-day display", () => {
  const appSource = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
  const viewsSource = readFileSync(new URL("./TodayPlanViews.jsx", import.meta.url), "utf8");
  const copy = `${appSource}\n${viewsSource}`;
  assert.match(copy, /保留在 ReviewSchedule，并按后续学习日公平轮候/);
  assert.match(copy, /最早恢复到期日/);
  assert.match(copy, /预算、公平轮转与已接受承诺/);
  assert.match(copy, /同题组独立复测/);
  assert.match(copy, /不构成未见平行题上的迁移验证/);
  assert.doesNotMatch(copy, /无提示的新题|未见新题/);
  assert.doesNotMatch(copy, /下一学习日自动重新出现|下一学习日；无需手动重新浮现|到期后会在下一学习日/);
});
