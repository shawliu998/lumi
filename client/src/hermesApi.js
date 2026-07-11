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
