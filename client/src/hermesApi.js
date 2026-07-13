import {
  ASSISTANCE_ACTIONS,
  buildAssistanceCommand,
  isSupportedDossierClaimStatus,
  isSupportedDossierContinuation,
} from "./learningSupportAdapter.js";
import {
  buildCreateTodayPlanCommand,
  buildTaskCommand,
  normalizeReviewSchedule,
  normalizeTodayPlan,
  todayPlanId,
} from "./todayPlanAdapter.js";
import { createCommandId, createRunId, isRunId } from "./publicLearningId.js";
import {
  buildStudyPackAttempt,
  buildStudyPackCommand,
  buildStudyPackCreate,
  normalizeStudyPackAttemptResult,
  normalizeStudyPackCitation,
  normalizeStudyPackDetail,
  normalizeStudyPackLaunch,
  normalizeStudyPackList,
  studyPackAttemptPath,
  studyPackCitationPath,
  studyPackCommandPath,
  studyPackLaunchPath,
  studyPackPath,
  studyPackReceiptRequiresRefresh,
} from "./studyPackAdapter.js";
import {
  normalizeProductActivityBundle,
  productActivityListPath,
} from "./productActivityAdapter.js";
import { masteryCommitSummary, reviewCommitSummary } from "./learningResultAdapter.js";

export { createRunId };

export const PRODUCT_ACTIVITY_RELEASE_ID = "p031-data-analysis-v1";

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";
const REQUEST_TIMEOUT_MS = 5000;

export const HERMES_API_BASE = normalizeBaseUrl(
  import.meta.env?.VITE_HERMES_API_BASE || DEFAULT_BASE_URL,
);

export class HermesApiError extends Error {
  constructor(message, { kind = "response", status = 0, code = "unknown", requestId = "" } = {}) {
    super(message);
    this.name = "HermesApiError";
    this.kind = kind;
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export async function fetchHealth() {
  const health = await request("/v1/health");
  if (
    health?.status !== "ok"
    || health?.service !== "hermes-local-sidecar"
    || health?.version !== "0.3.0"
    || health?.local_only !== true
  ) {
    throw new HermesApiError("本机服务返回了不受支持的健康状态。", {
      kind: "contract",
      code: "invalid_health_contract",
    });
  }
  return health;
}

const XINGCE_COVERAGE_UNSAFE_KEYS = new Set([
  "prompt",
  "options",
  "correct_option",
  "answer_labels",
  "answer_proof",
  "explanation_text",
  "misconception_dimensions",
  "content_requirements",
]);
const XINGCE_COVERAGE_MODULES = new Set([
  "verbal",
  "quantitative",
  "judgment",
  "data_analysis",
  "common_knowledge",
  "political_theory",
]);
const XINGCE_COVERAGE_FORMS = new Set(["text_mcq", "numeric_or_mcq", "visual_mcq", "material_mcq"]);

export async function fetchXingceCoverage() {
  const coverage = await request("/v1/xingce/coverage");
  if (!isValidXingceCoverageContract(coverage)) {
    throw new HermesApiError("行测范围状态格式不完整，未展示不可信的题型进度。", {
      kind: "contract",
      code: "invalid_xingce_coverage_contract",
    });
  }
  return coverage;
}

export function isValidXingceCoverageContract(coverage) {
  if (!coverage || typeof coverage !== "object" || containsUnsafeXingceCoverageKey(coverage)) return false;
  if (
    coverage.schema_version !== "lumi.xingce-coverage-catalog.v1"
    || coverage.local_only !== true
    || !coverage.summary
    || !Array.isArray(coverage.items)
  ) return false;
  const summary = coverage.summary;
  if (
    summary.schema_version !== "lumi.xingce-coverage-summary.v1"
    || typeof summary.taxonomy_version !== "string"
    || !Number.isInteger(summary.total_subtypes)
    || !Number.isInteger(summary.released_subtypes)
    || !Number.isInteger(summary.planned_subtypes)
    || typeof summary.is_complete !== "boolean"
    || !summary.modules
    || summary.total_subtypes !== coverage.items.length
    || summary.total_subtypes < 1
    || summary.released_subtypes + summary.planned_subtypes !== summary.total_subtypes
    || summary.is_complete !== (summary.released_subtypes === summary.total_subtypes)
  ) return false;
  const moduleEntries = Object.entries(summary.modules);
  if (moduleEntries.length !== XINGCE_COVERAGE_MODULES.size || moduleEntries.some(([id, module]) => (
    !XINGCE_COVERAGE_MODULES.has(id)
    || !module
    || typeof module.label !== "string"
    || !Number.isInteger(module.total)
    || !Number.isInteger(module.released)
    || module.total < 1
    || module.released < 0
    || module.released > module.total
  ))) return false;
  const seen = new Set();
  let released = 0;
  for (const item of coverage.items) {
    if (!item || typeof item !== "object" || seen.has(item.subtype_id)) return false;
    seen.add(item.subtype_id);
    if (
      typeof item.subtype_id !== "string"
      || !item.subtype_id.startsWith("xingce.")
      || !XINGCE_COVERAGE_MODULES.has(item.module_id)
      || typeof item.module_label !== "string"
      || typeof item.label !== "string"
      || !XINGCE_COVERAGE_FORMS.has(item.form)
      || !["available", "planned"].includes(item.availability)
      || !(item.launch === null || (typeof item.launch === "string" && item.launch.startsWith("/v1/")))
    ) return false;
    if (item.availability === "available") {
      released += 1;
      if (item.unavailable_reason !== null || !item.pack || typeof item.pack.pack_id !== "string" || typeof item.pack.pack_version !== "string" || item.launch === null) return false;
    } else if (item.launch !== null || item.unavailable_reason !== "reviewed_type_specific_pack_required" || "pack" in item) return false;
  }
  return released === summary.released_subtypes;
}

function containsUnsafeXingceCoverageKey(value) {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(containsUnsafeXingceCoverageKey);
  return Object.entries(value).some(([key, child]) => XINGCE_COVERAGE_UNSAFE_KEYS.has(key) || containsUnsafeXingceCoverageKey(child));
}

export async function fetchSkillReport() {
  const report = await request("/v1/skills/report");
  if (report?.policy !== "trace-summary-v1" || !Array.isArray(report?.items)) {
    throw new HermesApiError("技能报告格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_skill_report_contract",
    });
  }
  return report;
}

const JUDGMENT_UNSAFE_PUBLIC_KEYS = new Set([
  "correct_option",
  "answer_proof",
  "distractor_map",
  "selected_when",
  "formalization",
]);
const JUDGMENT_RECENT_STAGES = new Set([
  "awaiting_probe",
  "awaiting_transfer",
  "committing_transfer",
  "completed",
  "completed_no_error",
]);
const JUDGMENT_RESUMABLE_STAGES = new Set(["awaiting_probe", "awaiting_transfer"]);
const JUDGMENT_RECENT_SESSION_KEYS = new Set([
  "session_id",
  "stage",
  "updated_at",
  "event_count",
  "entry",
  "replay_available",
  "resume_available",
]);

export async function fetchJudgmentWorkspace() {
  const workspace = await request("/v1/judgment/workspace");
  if (!isValidJudgmentWorkspaceContract(workspace)) {
    throw new HermesApiError("判断推理工作台返回格式不完整，未展示任何替代题目。", {
      kind: "contract",
      code: "invalid_judgment_workspace_contract",
    });
  }
  return workspace;
}

export async function startJudgmentSession({
  entryRecordId,
  selectedOption,
  confidence,
  elapsedSeconds,
  rationale,
  commandId,
} = {}) {
  const body = judgmentAnswerBody({
    selectedOption,
    confidence,
    elapsedSeconds,
    commandId,
  });
  if (typeof entryRecordId !== "string" || !entryRecordId.trim()) {
    throw new HermesApiError("当前题目记录不可用。", { kind: "client", code: "invalid_judgment_entry" });
  }
  if (rationale !== undefined && (typeof rationale !== "string" || rationale.length > 1200)) {
    throw new HermesApiError("补充过程最多 1200 个字符。", { kind: "client", code: "invalid_judgment_rationale" });
  }
  const result = await request("/v1/judgment/sessions", {
    method: "POST",
    body: {
      entry_record_id: entryRecordId,
      ...body,
      ...(rationale?.trim() ? { rationale: rationale.trim() } : {}),
    },
  });
  assertJudgmentSessionResult(result, { expectedStages: ["awaiting_probe", "completed_no_error"] });
  return result;
}

export async function answerJudgmentProbe({
  session,
  selectedOption,
  confidence,
  elapsedSeconds,
  commandId,
} = {}) {
  assertJudgmentContinuation(session, "awaiting_probe");
  const body = judgmentAnswerBody({ selectedOption, confidence, elapsedSeconds, commandId });
  const result = await request(`/v1/judgment/sessions/${encodeURIComponent(session.session_id)}/probe`, {
    method: "POST",
    body: {
      expected_version: session.state_version,
      expected_stage: "awaiting_probe",
      ...body,
    },
  });
  assertJudgmentSessionResult(result, { expectedStages: ["awaiting_transfer"] });
  return result;
}

export async function answerJudgmentTransfer({
  session,
  selectedOption,
  confidence,
  elapsedSeconds,
  commandId,
} = {}) {
  assertJudgmentContinuation(session, "awaiting_transfer");
  const body = judgmentAnswerBody({ selectedOption, confidence, elapsedSeconds, commandId });
  const result = await request(`/v1/judgment/sessions/${encodeURIComponent(session.session_id)}/transfer`, {
    method: "POST",
    body: {
      expected_version: session.state_version,
      expected_stage: "awaiting_transfer",
      ...body,
    },
  });
  assertJudgmentSessionResult(result, { expectedStages: ["completed"] });
  return result;
}

export async function fetchJudgmentReplay(sessionId) {
  if (typeof sessionId !== "string" || !/^jr_[a-f0-9]{24,96}$/i.test(sessionId)) {
    throw new HermesApiError("学习记录编号不可用。", { kind: "client", code: "invalid_judgment_session_id" });
  }
  const replay = await request(`/v1/judgment/sessions/${encodeURIComponent(sessionId)}/replay`);
  if (
    replay?.schema_version !== "lumi.judgment-session.v1"
    || replay?.session_id !== sessionId
    || replay?.trace_verified !== true
    || !Number.isInteger(replay?.event_count)
    || !Array.isArray(replay?.timeline)
    || containsUnsafeJudgmentKey(replay)
  ) {
    throw new HermesApiError("证据回放格式不完整，未展示不可信记录。", {
      kind: "contract",
      code: "invalid_judgment_replay_contract",
    });
  }
  return replay;
}

export function latestJudgmentSessionFromReplay(replay) {
  const latest = replay?.timeline?.at?.(-1);
  const result = latest?.result;
  if (
    !latest
    || !Number.isInteger(latest.seq)
    || typeof latest.stage_after !== "string"
    || !JUDGMENT_RECENT_STAGES.has(latest.stage_after)
    || !result
    || result.session_id !== replay.session_id
    || result.stage !== latest.stage_after
  ) {
    throw new HermesApiError("本机回放不能安全恢复当前学习步骤。", {
      kind: "contract",
      code: "invalid_judgment_replay_resume",
    });
  }
  assertJudgmentSessionResult(result, {
    expectedStages: ["awaiting_probe", "awaiting_transfer", "completed", "completed_no_error"],
  });
  return result;
}

export function isValidJudgmentWorkspaceContract(workspace) {
  if (!workspace || typeof workspace !== "object" || containsUnsafeJudgmentKey(workspace)) return false;
  if (workspace.available === false) {
    return workspace.schema_version === "lumi.judgment-workspace.v1"
      && workspace.reason === "content_review_required"
      && typeof workspace.message === "string"
      && workspace.message.length > 0;
  }
  return workspace.available === true
    && workspace.schema_version === "lumi.judgment-session.v1"
    && typeof workspace?.pack?.pack_id === "string"
    && typeof workspace?.pack?.pack_version === "string"
    && workspace.next_step === "answer_entry"
    && workspace.privacy === "local_only"
    && Array.isArray(workspace.entry_items)
    && workspace.entry_items.length > 0
    && workspace.entry_items.every((item) => isValidJudgmentPublicRecord(item, ["entry_diagnostic", "routing_diagnostic"]))
    && Array.isArray(workspace.recent_sessions)
    && workspace.recent_sessions.length <= 6
    && workspace.recent_sessions.every(isValidJudgmentRecentSession)
    && new Set(workspace.recent_sessions.map((item) => item.session_id)).size === workspace.recent_sessions.length;
}

export function isValidJudgmentRecentSession(session) {
  if (!session || typeof session !== "object" || containsUnsafeJudgmentKey(session)) return false;
  if (
    Object.keys(session).length !== JUDGMENT_RECENT_SESSION_KEYS.size
    || Object.keys(session).some((key) => !JUDGMENT_RECENT_SESSION_KEYS.has(key))
  ) return false;
  if (
    !/^jr_[a-f0-9]{24,96}$/i.test(session.session_id || "")
    || !JUDGMENT_RECENT_STAGES.has(session.stage)
    || typeof session.updated_at !== "string"
    || session.updated_at.length < 20
    || !Number.isInteger(session.event_count)
    || session.event_count < 1
    || session.replay_available !== true
    || typeof session.resume_available !== "boolean"
    || session.resume_available !== JUDGMENT_RESUMABLE_STAGES.has(session.stage)
  ) return false;
  const entry = session.entry;
  return entry
    && typeof entry === "object"
    && Object.keys(entry).length === 2
    && typeof entry.record_id === "string"
    && typeof entry.title === "string";
}

export function isValidJudgmentPublicRecord(record, expectedRole) {
  if (!record || typeof record !== "object" || containsUnsafeJudgmentKey(record)) return false;
  const allowedRoles = Array.isArray(expectedRole) ? expectedRole : [expectedRole];
  return allowedRoles.includes(record.role)
    && typeof record.record_id === "string"
    && typeof record.title === "string"
    && typeof record.prompt === "string"
    && record.response_mode === "single_choice"
    && isJudgmentOptionCollection(record.options);
}

function judgmentAnswerBody({ selectedOption, confidence, elapsedSeconds, commandId } = {}) {
  const selected = String(selectedOption || "").trim().toUpperCase();
  const normalizedConfidence = String(confidence || "").trim().toLowerCase();
  if (!/^[A-D]$/.test(selected) || !["low", "medium", "high"].includes(normalizedConfidence)) {
    throw new HermesApiError("请选择答案和作答信心。", { kind: "client", code: "invalid_judgment_answer" });
  }
  const body = {
    selected_option: selected,
    confidence: normalizedConfidence,
    elapsed_seconds: Math.max(0, Math.min(Number(elapsedSeconds) || 0, 7200)),
  };
  if (commandId !== undefined) {
    if (typeof commandId !== "string" || !/^c_[A-P]{40}$/.test(commandId)) {
      throw new HermesApiError("本机命令编号不可用。", { kind: "client", code: "invalid_judgment_command_id" });
    }
    body.command_id = commandId;
  }
  return body;
}

function assertJudgmentContinuation(session, expectedStage) {
  if (
    !session
    || typeof session.session_id !== "string"
    || !Number.isInteger(session.state_version)
    || session.stage !== expectedStage
  ) {
    throw new HermesApiError("当前学习步骤已过期；请先重新读取本机记录。", {
      kind: "client",
      code: "invalid_judgment_continuation",
    });
  }
}

function assertJudgmentSessionResult(result, { expectedStages }) {
  if (
    !result
    || result.schema_version !== "lumi.judgment-session.v1"
    || typeof result.session_id !== "string"
    || !Number.isInteger(result.state_version)
    || !expectedStages.includes(result.stage)
    || containsUnsafeJudgmentKey(result)
  ) {
    throw new HermesApiError("本机服务返回了不一致的判断推理步骤。", {
      kind: "contract",
      code: "invalid_judgment_session_contract",
    });
  }
  if (result.stage === "awaiting_probe") {
    if (
      !isValidJudgmentPublicRecord(result.entry, ["entry_diagnostic", "routing_diagnostic"])
      || !isValidJudgmentPublicRecord(result.probe, "probe")
      || !Array.isArray(result.observed_facts)
      || !Array.isArray(result.candidate_causes)
      || !isValidJudgmentPolicy(result.policy)
    ) throw new HermesApiError("本机服务没有返回可解释的探查步骤。", { kind: "contract", code: "incomplete_judgment_diagnosis" });
  }
  if (result.stage === "awaiting_transfer") {
    if (
      !isValidJudgmentPublicRecord(result.probe, "probe")
      || !isValidJudgmentPublicRecord(result.transfer, "independent_transfer")
      || !result.teaching?.asset
      || !isValidJudgmentTeachingAsset(result.teaching.asset)
      || result.independence?.requires_no_hints !== true
    ) throw new HermesApiError("本机服务没有返回安全的教学和迁移步骤。", { kind: "contract", code: "incomplete_judgment_transfer" });
  }
  if (result.stage === "completed") {
    if (
      !isValidJudgmentPublicRecord(result.transfer, "independent_transfer")
      || typeof result.transfer.correct !== "boolean"
      || !Array.isArray(result.state_receipts)
      || !result.review_task
    ) throw new HermesApiError("本机服务没有返回状态收据或复习任务。", { kind: "contract", code: "incomplete_judgment_receipt" });
  }
}

function isValidJudgmentTeachingAsset(asset) {
  if (!asset || typeof asset !== "object" || containsUnsafeJudgmentKey(asset)) return false;
  return asset.role === "teaching_asset"
    && typeof asset.record_id === "string"
    && typeof asset.title === "string"
    && typeof asset.teaching_strategy === "string"
    && typeof asset.teaching_content === "string"
    && typeof asset.logic_rule === "string";
}

function isJudgmentOptionCollection(options) {
  if (Array.isArray(options)) {
    return options.length >= 2
      && options.every((option) => /^[A-D]$/.test(option?.label || "") && typeof option?.text === "string");
  }
  if (!options || typeof options !== "object") return false;
  const entries = Object.entries(options);
  return entries.length >= 2
    && entries.every(([label, text]) => /^[A-D]$/.test(label) && typeof text === "string");
}

function isValidJudgmentPolicy(policy) {
  return policy
    && typeof policy.policy_id === "string"
    && typeof policy.policy_version === "string"
    && typeof policy.why_selected === "string"
    && Array.isArray(policy.candidate_actions)
    && policy.candidate_actions.every((action) => (
      typeof action?.record_id === "string"
      && Array.isArray(action?.coverage)
      && typeof action?.selected === "boolean"
      && (action.selected
        ? (typeof action?.why_selected === "string" && action?.why_not_selected === null)
        : (action?.why_selected === null && typeof action?.why_not_selected === "string"))
    ));
}

function containsUnsafeJudgmentKey(value) {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(containsUnsafeJudgmentKey);
  return Object.entries(value).some(([key, child]) => JUDGMENT_UNSAFE_PUBLIC_KEYS.has(key) || containsUnsafeJudgmentKey(child));
}

export async function fetchProductActivityBundle({
  releaseId = PRODUCT_ACTIVITY_RELEASE_ID,
  requestImpl = request,
} = {}) {
  const [firstPayload, transferPayload] = await Promise.all([
    requestImpl(productActivityListPath({ releaseId, diagnosticRole: "first_answer" })),
    requestImpl(productActivityListPath({ releaseId, diagnosticRole: "independent_transfer" })),
  ]);
  try {
    return normalizeProductActivityBundle(firstPayload, transferPayload, { releaseId });
  } catch (error) {
    throw new HermesApiError("真题活动格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_product_activity_contract",
    });
  }
}

export async function fetchStudyPackList() {
  return normalizeStudyPackList(await request("/v1/study-packs"));
}

export async function fetchStudyPack(packId) {
  return normalizeStudyPackDetail(
    await request(studyPackPath(packId)),
    { packId },
  );
}

export async function createStudyPack({ title, source, commandId } = {}) {
  const body = buildStudyPackCreate({ title, source, commandId });
  const created = normalizeStudyPackDetail(await request("/v1/study-packs", {
    method: "POST",
    body,
    timeoutMs: 15_000,
  }), { creation: true, title: body.title, sourceKind: body.source.kind });
  return studyPackReceiptRequiresRefresh(created) ? fetchStudyPack(created.packId) : created;
}

export async function commandStudyPack({ pack, action, commandId } = {}) {
  const body = buildStudyPackCommand({ pack, action, commandId });
  const result = normalizeStudyPackDetail(await request(studyPackCommandPath(pack.packId), {
    method: "POST",
    body,
    timeoutMs: 15_000,
  }), {
    packId: pack.packId,
    action,
    expectedVersion: pack.version,
    previousLifecycle: pack.lifecycle,
  });
  return studyPackReceiptRequiresRefresh(result) ? fetchStudyPack(pack.packId) : result;
}

export async function fetchStudyPackCitation({ packId, spanId, source } = {}) {
  const payload = await request(studyPackCitationPath(packId, spanId));
  return normalizeStudyPackCitation(payload, {
    packId,
    spanId,
    documentId: source?.documentId,
    sourceVersion: source?.version,
    normalizedSha256: source?.normalizedSha256,
  });
}

export async function launchStudyPackItem(item) {
  const expected = {
    artifactId: item?.artifactId,
    artifactVersion: item?.artifactVersion,
    packId: item?.packId,
    scorer: item?.content?.scorer || item?.scorer,
  };
  return normalizeStudyPackLaunch(
    await request(studyPackLaunchPath(item.artifactId)),
    expected,
  );
}

export async function attemptStudyPackItem({ launch, learnerAnswer, commandId } = {}) {
  const body = buildStudyPackAttempt({ launch, learnerAnswer, commandId });
  const payload = await request(studyPackAttemptPath(launch.artifactId), {
    method: "POST",
    body,
  });
  const result = normalizeStudyPackAttemptResult(payload, { launch });
  if (!studyPackReceiptRequiresRefresh(result)) return result;
  const refreshedPack = await fetchStudyPack(launch.packId);
  if (refreshedPack.version < result.packVersion) {
    throw new HermesApiError("学习包最新版本与重放记录不一致。", {
      kind: "contract",
      code: "invalid_study_pack_replay_projection",
    });
  }
  return { ...result, refreshedPack };
}

export async function fetchReviewSchedule() {
  const schedule = await request("/v1/review-schedule");
  try {
    return normalizeReviewSchedule(schedule);
  } catch (error) {
    throw new HermesApiError("复习安排格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_review_schedule_contract",
    });
  }
}

export async function fetchTodayPlan({ now = new Date() } = {}) {
  const planId = todayPlanId(now);
  const plan = await request(`/v1/today-plans/${encodeURIComponent(planId)}`);
  try {
    return normalizeTodayPlan(plan);
  } catch (error) {
    throw new HermesApiError("今日计划格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_today_plan_contract",
    });
  }
}

export async function createTodayPlan({
  now = new Date(),
  examDate,
  dailyBudgetMinutes,
  commandId,
} = {}) {
  const body = buildCreateTodayPlanCommand({
    now,
    examDate,
    dailyBudgetMinutes,
    commandId,
  });
  const plan = await request("/v1/today-plans", { method: "POST", body });
  try {
    return normalizeTodayPlan(plan);
  } catch (error) {
    throw new HermesApiError("本机服务返回了不一致的今日计划。", {
      kind: "contract",
      code: "invalid_today_plan_contract",
    });
  }
}

export async function commandTodayPlanTask({
  plan,
  task,
  action,
  postponeUntil,
  commandId,
} = {}) {
  const body = buildTaskCommand({ plan, task, action, postponeUntil, commandId });
  const result = await request(
    `/v1/today-plans/${encodeURIComponent(plan.planId)}/tasks/${encodeURIComponent(task.id)}/commands`,
    { method: "POST", body },
  );
  try {
    return normalizeTodayPlan(result);
  } catch (error) {
    throw new HermesApiError("任务操作后的计划格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_today_plan_contract",
    });
  }
}

export async function submitAttempt({ fixtureId, response, confidence, responseTimeSeconds, runId } = {}) {
  if (!fixtureId || !String(response).trim() || !Number.isFinite(confidence)) {
    throw new HermesApiError("作答内容不完整。", {
      kind: "client",
      code: "invalid_attempt_input",
    });
  }
  const resolvedRunId = runId || createRunId();
  if (!isRunId(resolvedRunId)) {
    throw new HermesApiError("运行编号不符合本机学习记录合同。", {
      kind: "client",
      code: "invalid_run_id",
    });
  }
  const attempt = await request("/v1/attempts", {
    method: "POST",
    body: {
      fixture_id: fixtureId,
      response: String(response).trim(),
      confidence,
      response_time_seconds: Math.max(0, Math.min(Number(responseTimeSeconds) || 0, 7200)),
      run_id: resolvedRunId,
    },
  });
  if (
    attempt?.schema_version !== "hermes.attempt-session.v1"
    || attempt?.run_id !== resolvedRunId
    || !isRunId(attempt?.run_id)
    || attempt?.state !== "awaiting_probe"
    || !Number.isInteger(attempt?.state_version)
    || attempt?.diagnosis?.semantics !== "ranked_unconfirmed_hypotheses"
    || !attempt?.probe?.prompt
    || !attempt?.probe?.prompt_instance_id
    || !attempt?.links?.respond
    || !attempt?.links?.assist
    || !attempt?.links?.misconception
  ) {
    throw new HermesApiError("本次首答未返回可继续的探查状态。", {
      kind: "contract",
      code: "invalid_attempt_contract",
    });
  }
  return { attempt };
}

export async function continueAttempt({ session, phase, response, confidence, responseTimeSeconds } = {}) {
  const expectedState = phase === "probe" ? "awaiting_probe" : "awaiting_verification";
  const promptInstanceId = phase === "probe"
    ? session?.probe?.prompt_instance_id
    : session?.verification?.prompt_instance_id;
  if (
    !session?.run_id
    || session?.state !== expectedState
    || !Number.isInteger(session?.state_version)
    || !promptInstanceId
    || !String(response).trim()
    || !Number.isFinite(confidence)
  ) {
    throw new HermesApiError("当前步骤缺少可继续的作答状态。", {
      kind: "client",
      code: "invalid_continuation_input",
    });
  }
  const continuation = await requestLink(session.links?.respond, {
    method: "POST",
    body: {
      phase,
      expected_version: session.state_version,
      expected_state: expectedState,
      prompt_instance_id: promptInstanceId,
      response: String(response).trim(),
      confidence,
      response_time_seconds: Math.max(0, Math.min(Number(responseTimeSeconds) || 0, 7200)),
    },
  });
  const nextState = phase === "probe" ? "awaiting_verification" : "completed";
  if (
    continuation?.schema_version !== "hermes.attempt-continuation-result.v1"
    || continuation?.run_id !== session.run_id
    || continuation?.accepted_phase !== phase
    || continuation?.state !== nextState
    || !Number.isInteger(continuation?.state_version)
    || !continuation?.trace_verified
  ) {
    throw new HermesApiError("本机服务返回了不一致的训练步骤。", {
      kind: "contract",
      code: "invalid_continuation_contract",
    });
  }
  if (phase === "probe") {
    if (!continuation?.teaching?.prompt || !continuation?.verification?.prompt || !continuation?.verification?.prompt_instance_id) {
      throw new HermesApiError("探查结果缺少教学或独立验证题。", {
        kind: "contract",
        code: "incomplete_probe_result",
      });
    }
    return { continuation };
  }
  if (!continuation?.reflection) {
    throw new HermesApiError("独立验证结果缺少复盘记录。", {
      kind: "contract",
      code: "incomplete_verification_result",
    });
  }
  try {
    masteryCommitSummary(continuation.mastery_commit);
    reviewCommitSummary(continuation.review_schedule_commit);
    if (
      continuation.mastery_commit.status === "committed" && !continuation.mastery_update
      || continuation.mastery_commit.status === "withheld" && continuation.mastery_update !== null
    ) throw new TypeError("mastery projection disagrees with commit receipt");
  } catch {
    throw new HermesApiError("独立验证结果缺少可信的 KT 或复习写入回执。", {
      kind: "contract",
      code: "invalid_learning_commit_receipt",
    });
  }
  const [trace, replay] = await Promise.all([
    requestLink(continuation.links?.trace),
    requestLink(continuation.links?.replay),
  ]);
  return { continuation, trace, replay };
}

export async function requestNextAssistance({ session, elapsedTimeSeconds, commandId } = {}) {
  const promptInstanceId = session?.probe?.prompt_instance_id;
  if (
    !session?.run_id
    || session?.state !== "awaiting_probe"
    || !Number.isInteger(session?.state_version)
    || !promptInstanceId
    || !session?.links?.assist
  ) {
    throw new HermesApiError("当前探查题没有可写入的帮助状态。", {
      kind: "client",
      code: "assistance_unavailable",
    });
  }
  const result = await requestLink(session.links?.assist, {
    method: "POST",
    body: buildAssistanceCommand({
      session,
      elapsedTimeSeconds,
      commandId: commandId || createCommandId(),
    }),
  });
  const assistance = result?.assistance;
  const expectedAssistance = ASSISTANCE_ACTIONS[Number(assistance?.ordinal) - 1];
  if (
    result?.schema_version !== "hermes.assistance-result.v1"
    || result?.run_id !== session.run_id
    || result?.state !== "awaiting_probe"
    || !Number.isInteger(result?.state_version)
    || result.state_version <= session.state_version
    || result?.prompt_instance_id !== promptInstanceId
    || !Number.isInteger(assistance?.ordinal)
    || assistance.ordinal < 1
    || assistance.ordinal > 6
    || !assistance?.title
    || !assistance?.content
    || !assistance?.policy_version
    || assistance?.action !== expectedAssistance?.action
    || !Number.isFinite(Number(assistance?.diagnostic_evidence_weight))
    || assistance?.calibration_status !== "engineering_policy_unvalidated"
    || assistance?.independence_effect !== "discounts_probe_evidence"
    || result?.remaining_levels !== 6 - assistance.ordinal
    || result?.trace_verified !== true
  ) {
    throw new HermesApiError("本机服务返回了不一致的帮助事件。", {
      kind: "contract",
      code: "invalid_assistance_contract",
    });
  }
  return { ...result, assistance };
}

export async function fetchMisconceptionDossier(runId) {
  if (!runId) {
    throw new HermesApiError("缺少错因档案运行编号。", {
      kind: "client",
      code: "invalid_dossier_input",
    });
  }
  const dossier = await requestLink(`/v1/misconceptions/${encodeURIComponent(runId)}`);
  if (!isValidMisconceptionDossierContract(dossier, runId)) {
    throw new HermesApiError("本机服务返回了不一致的错因档案。", {
      kind: "contract",
      code: "invalid_dossier_contract",
    });
  }
  return dossier;
}

export function isValidMisconceptionDossierContract(dossier, runId) {
  return !(
    dossier?.schema_version !== "hermes.misconception-dossier.v1"
    || dossier?.run_id !== runId
    || !dossier?.observations
    || !Array.isArray(dossier?.observations?.items)
    || !Array.isArray(dossier?.hypotheses)
    || !dossier?.learning_status
    || dossier?.hypothesis_semantics !== "ranked_candidates_never_causal_ground_truth"
    || dossier?.cohort_evidence?.status !== "unavailable"
    || dossier?.cohort_evidence?.sample_size !== 0
    || dossier?.provenance?.trace_verified !== true
    || !isSupportedDossierContinuation(dossier)
    || dossier.hypotheses.some((item) => {
      const supporting = item?.supporting_evidence;
      const refuting = item?.refuting_evidence;
      const rankingFactors = item?.ranking_factors;
      const prior = item?.prior;
      return !isSupportedDossierClaimStatus(item?.claim_status)
        || !Array.isArray(supporting)
        || !Array.isArray(refuting)
        || !Array.isArray(rankingFactors)
        || rankingFactors.includes("cohort_prior")
        || prior?.kind !== "engineering_prior"
        || prior?.sample_size !== 0
        || prior?.population_calibrated !== false;
    })
  );
}

function normalizeBaseUrl(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(parsed.hostname)) {
    throw new Error("VITE_HERMES_API_BASE must use an HTTP loopback address");
  }
  parsed.pathname = parsed.pathname.replace(/\/$/, "");
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/$/, "");
}

function requestLink(link, options) {
  if (typeof link !== "string" || !link.startsWith("/v1/")) {
    throw new HermesApiError("本机服务返回了不安全的轨迹链接。", {
      kind: "contract",
      code: "invalid_local_link",
    });
  }
  return request(link, options);
}

async function request(path, { method = "GET", body, timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const requestId = createRequestId();
  try {
    const response = await fetch(`${HERMES_API_BASE}${path}`, {
      method,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-Request-ID": requestId,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const payload = await parsePayload(response);
    if (!response.ok) {
      const error = payload?.error || {};
      throw new HermesApiError(error.message || `本机服务返回 ${response.status}。`, {
        kind: "response",
        status: response.status,
        code: error.code || "http_error",
        requestId: error.request_id || response.headers.get("X-Request-ID") || requestId,
      });
    }
    return payload;
  } catch (error) {
    if (error instanceof HermesApiError) throw error;
    const timedOut = error?.name === "AbortError";
    throw new HermesApiError(timedOut ? "连接本机服务超时。" : "无法连接本机服务。", {
      kind: "unavailable",
      code: timedOut ? "request_timeout" : "service_unavailable",
      requestId,
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

async function parsePayload(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new HermesApiError("本机服务返回了无法读取的数据。", {
      kind: "contract",
      status: response.status,
      code: "invalid_json_response",
      requestId: response.headers.get("X-Request-ID") || "",
    });
  }
}

function createRequestId() {
  if (globalThis.crypto?.randomUUID) return `client-${globalThis.crypto.randomUUID()}`;
  return `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
