import {
  createSmartPracticeStartBody,
  validateSmartPracticeCapabilities,
} from "./practiceScopes";
import {
  isKnownPracticeScope,
  normalizePracticeHistory,
  normalizePracticeOverview,
  normalizePracticeProfile,
  normalizePracticeSessionReport,
  normalizeWrongQuestionBook,
} from "./practiceInsights";

const DEFAULT_BASE_URL = "http://127.0.0.1:8765";
const REQUEST_TIMEOUT_MS = 5000;

export const HERMES_API_BASE = normalizeBaseUrl(
  import.meta.env.VITE_HERMES_API_BASE || DEFAULT_BASE_URL,
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
    || health?.local_only !== true
  ) {
    throw new HermesApiError("本机服务返回了不受支持的健康状态。", {
      kind: "contract",
      code: "invalid_health_contract",
    });
  }
  return health;
}

export async function fetchCapabilities() {
  const capabilities = await request("/v1/capabilities");
  try {
    validateSmartPracticeCapabilities(capabilities);
  } catch {
    throw new HermesApiError("本机服务不支持当前 Core-320 题库。", {
      kind: "contract",
      code: "invalid_core320_capabilities",
    });
  }
  return capabilities;
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

function normalizeReadModel(payload, normalizer, message, code) {
  try {
    return normalizer(payload);
  } catch {
    throw new HermesApiError(message, { kind: "contract", code });
  }
}

export async function fetchPracticeOverview() {
  const payload = await request("/v1/practice/overview");
  return normalizeReadModel(
    payload,
    normalizePracticeOverview,
    "本机学习概览格式与客户端不兼容。",
    "invalid_practice_overview_contract",
  );
}

export async function fetchPracticeProfile() {
  const payload = await request("/v1/practice/profile");
  return normalizeReadModel(
    payload,
    normalizePracticeProfile,
    "本机学习档案格式与客户端不兼容。",
    "invalid_practice_profile_contract",
  );
}

export async function fetchWrongQuestionBook({
  limit = 30,
  offset = 0,
  state = "needs_review",
  moduleId = "",
} = {}) {
  if (
    !Number.isInteger(limit)
    || limit < 1
    || limit > 100
    || !Number.isInteger(offset)
    || offset < 0
    || !["needs_review", "resolved", "all"].includes(state)
  ) {
    throw new HermesApiError("错题本筛选条件无效。", {
      kind: "client",
      code: "invalid_wrong_question_query",
    });
  }
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    state,
  });
  if (moduleId) query.set("module_id", String(moduleId));
  const payload = await request(`/v1/practice/wrong-questions?${query}`);
  return normalizeReadModel(
    payload,
    normalizeWrongQuestionBook,
    "本机错题本格式与客户端不兼容。",
    "invalid_wrong_question_book_contract",
  );
}

export async function fetchPracticeHistory({
  limit = 30,
  offset = 0,
  scopeId = "",
  status = "",
} = {}) {
  if (
    !Number.isInteger(limit)
    || limit < 1
    || limit > 100
    || !Number.isInteger(offset)
    || offset < 0
    || (scopeId && !isKnownPracticeScope(scopeId))
    || (status && !["active", "completed", "ended_early"].includes(status))
  ) {
    throw new HermesApiError("练习历史筛选条件无效。", {
      kind: "client",
      code: "invalid_practice_history_query",
    });
  }
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (scopeId) query.set("scope_id", scopeId);
  if (status) query.set("status", status);
  const payload = await request(`/v1/practice/history?${query}`);
  return normalizeReadModel(
    payload,
    normalizePracticeHistory,
    "本机练习历史格式与客户端不兼容。",
    "invalid_practice_history_contract",
  );
}

export async function fetchPracticeSessionReport(sessionId) {
  assertPracticeSessionId(sessionId);
  const payload = await request(`/v1/practice-sessions/${encodeURIComponent(sessionId)}/report`);
  return normalizeReadModel(
    payload,
    normalizePracticeSessionReport,
    "本组练习报告格式与客户端不兼容。",
    "invalid_practice_session_report_contract",
  );
}

export async function fetchPracticeCatalog() {
  const catalog = await request("/v1/scenarios?domain=xingce&mode=success");
  if (
    catalog?.policy !== "safe-practice-catalog-v1"
    || !Array.isArray(catalog?.items)
    || catalog.items.some((item) => !item?.fixture_id || !item?.prompt || !item?.domain)
  ) {
    throw new HermesApiError("练习题目录格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_practice_catalog_contract",
    });
  }
  return catalog;
}

export async function fetchLessonCatalog() {
  const catalog = await request("/v1/lessons");
  if (
    catalog?.schema_version !== "hermes.lesson-catalog.v1"
    || catalog?.policy !== "auditable-lesson-catalog-v1"
    || !Array.isArray(catalog?.items)
    || catalog.items.some((item) => (
      !item?.lesson_id
      || !item?.title
      || !Number.isFinite(item?.estimated_minutes)
      || !Number.isInteger(item?.practice_count)
      || !item?.links?.self
    ))
  ) {
    throw new HermesApiError("教程目录格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_lesson_catalog_contract",
    });
  }
  return catalog;
}

export async function fetchLesson(lessonId) {
  if (!lessonId || !/^[A-Za-z0-9._:-]+$/.test(String(lessonId))) {
    throw new HermesApiError("教程标识无效。", {
      kind: "client",
      code: "invalid_lesson_id",
    });
  }
  const detail = await request(`/v1/lessons/${encodeURIComponent(lessonId)}`);
  const lesson = detail?.lesson;
  if (
    detail?.schema_version !== "hermes.lesson-detail.v1"
    || detail?.policy !== "auditable-lesson-catalog-v1"
    || lesson?.lesson_id !== lessonId
    || !lesson?.method_card
    || !lesson?.worked_example
    || !Array.isArray(lesson?.practice_items)
    || !lesson?.completion_policy
  ) {
    throw new HermesApiError("教程内容格式与客户端不兼容。", {
      kind: "contract",
      code: "invalid_lesson_detail_contract",
    });
  }
  return lesson;
}

function assertPracticeSessionId(sessionId) {
  if (!sessionId || !/^[A-Za-z0-9._:-]+$/.test(String(sessionId))) {
    throw new HermesApiError("练习会话标识无效。", {
      kind: "client",
      code: "invalid_practice_session_id",
    });
  }
}

function validateSmartPracticePayload(payload, { requireContinuable = false } = {}) {
  const hasQuestion = Boolean(
    payload?.question?.question_id && payload?.question?.question_version_id,
  );
  const hasPendingProbe = Boolean(
    payload?.pending_probe?.hypothesis_id
    && payload.pending_probe.prompt
    && payload.pending_probe.options
    && (Array.isArray(payload.pending_probe.options)
      ? payload.pending_probe.options.length > 0
      : Object.keys(payload.pending_probe.options).length > 0),
  );
  if (
    payload?.schema_version !== "lumi.practice-session.v2"
    || !payload?.session?.session_id
    || payload.session.target_count !== 8
    || !Number.isInteger(payload.session.answered_count)
    || (requireContinuable && !hasQuestion && !hasPendingProbe)
  ) {
    throw new HermesApiError("本机服务返回了不兼容的 8 题练习状态。", {
      kind: "contract",
      code: "invalid_smart_practice_contract",
    });
  }
  return payload;
}

export async function startSmartPracticeSession({ scopeId } = {}) {
  const payload = await request("/v1/practice-sessions", {
    method: "POST",
    body: createSmartPracticeStartBody(scopeId),
  });
  return validateSmartPracticePayload(payload, { requireContinuable: true });
}

export async function submitSmartPracticeAnswer({
  sessionId,
  questionId,
  questionVersionId,
  answer,
  responseTimeSeconds,
} = {}) {
  assertPracticeSessionId(sessionId);
  if (!questionId || !questionVersionId || !String(answer || "").trim()) {
    throw new HermesApiError("请选择答案后再提交。", {
      kind: "client",
      code: "invalid_smart_practice_answer",
    });
  }
  const payload = await request(`/v1/practice-sessions/${encodeURIComponent(sessionId)}/answers`, {
    method: "POST",
    body: {
      question_id: String(questionId),
      question_version_id: String(questionVersionId),
      answer: String(answer).trim(),
      response_time_seconds: Math.max(0, Math.min(Number(responseTimeSeconds) || 0, 7200)),
    },
  });
  return validateSmartPracticePayload(payload);
}

export async function submitSmartPracticeProbe({ sessionId, hypothesisId, answer } = {}) {
  assertPracticeSessionId(sessionId);
  if (!hypothesisId || !String(answer || "").trim()) {
    throw new HermesApiError("探查结果不完整。", {
      kind: "client",
      code: "invalid_smart_practice_probe",
    });
  }
  const payload = await request(`/v1/practice-sessions/${encodeURIComponent(sessionId)}/probes`, {
    method: "POST",
    body: {
      hypothesis_id: String(hypothesisId),
      answer: String(answer).trim(),
    },
  });
  return validateSmartPracticePayload(payload);
}

export async function endSmartPracticeSession({ sessionId, reason } = {}) {
  assertPracticeSessionId(sessionId);
  const payload = await request(`/v1/practice-sessions/${encodeURIComponent(sessionId)}/end`, {
    method: "POST",
    body: reason ? { reason: String(reason).slice(0, 120) } : {},
  });
  return validateSmartPracticePayload(payload);
}

export async function submitAttempt({ fixtureId, response, confidence, responseTimeSeconds, runId } = {}) {
  if (!fixtureId || !String(response).trim() || !Number.isFinite(confidence)) {
    throw new HermesApiError("作答内容不完整。", {
      kind: "client",
      code: "invalid_attempt_input",
    });
  }
  const attempt = await request("/v1/attempts", {
    method: "POST",
    body: {
      fixture_id: fixtureId,
      response: String(response).trim(),
      confidence,
      response_time_seconds: Math.max(0, Math.min(Number(responseTimeSeconds) || 0, 7200)),
      run_id: runId || createRunId(),
    },
  });
  if (
    attempt?.schema_version !== "hermes.attempt-session.v1"
    || !attempt?.run_id
    || attempt?.state !== "awaiting_probe"
    || !Number.isInteger(attempt?.state_version)
    || attempt?.diagnosis?.semantics !== "ranked_unconfirmed_hypotheses"
    || !attempt?.probe?.prompt
    || !attempt?.links?.respond
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
  if (
    !session?.run_id
    || session?.state !== expectedState
    || !Number.isInteger(session?.state_version)
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
    if (!continuation?.teaching?.prompt || !continuation?.verification?.prompt) {
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

function createRunId() {
  return `mac-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function createRequestId() {
  if (globalThis.crypto?.randomUUID) return `client-${globalThis.crypto.randomUUID()}`;
  return `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
