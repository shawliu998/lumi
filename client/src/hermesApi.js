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

export { createRunId };

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
    || health?.version !== "0.2.0"
    || health?.local_only !== true
  ) {
    throw new HermesApiError("本机服务返回了不受支持的健康状态。", {
      kind: "contract",
      code: "invalid_health_contract",
    });
  }
  return health;
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
  if (!continuation?.mastery_update || !continuation?.reflection) {
    throw new HermesApiError("独立验证结果缺少掌握变化或复盘记录。", {
      kind: "contract",
      code: "incomplete_verification_result",
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

async function request(path, { method = "GET", body } = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
