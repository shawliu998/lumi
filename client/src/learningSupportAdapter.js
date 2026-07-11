export const ASSISTANCE_ACTIONS = [
  { ordinal: 1, action: "retry", label: "再试一次" },
  { ordinal: 2, action: "locate_evidence", label: "定位信息" },
  { ordinal: 3, action: "rule_hint", label: "规则提示" },
  { ordinal: 4, action: "analogous_example", label: "同类例子" },
  { ordinal: 5, action: "worked_step", label: "演示一步" },
  { ordinal: 6, action: "full_explanation", label: "完整说明" },
];

export const DOSSIER_CLAIM_STATUSES = Object.freeze([
  "unconfirmed_hypothesis",
  "supported_hypothesis",
  "refuted_hypothesis",
]);

const DOSSIER_CONTINUATION_POLICIES = Object.freeze({
  awaiting_probe: {
    learningStatuses: ["awaiting_probe"],
    actions: ["answer_targeted_probe"],
    requiresPromptInstance: true,
  },
  processing_probe: {
    learningStatuses: ["processing_probe_response"],
    actions: ["restart_attempt_after_processing_failure"],
    requiresRestartTarget: true,
  },
  awaiting_verification: {
    learningStatuses: ["awaiting_independent_verification"],
    actions: ["answer_independent_verification"],
    requiresPromptInstance: true,
  },
  processing_verification: {
    learningStatuses: ["processing_verification_response"],
    actions: ["restart_attempt_for_fresh_independent_verification"],
    requiresRestartTarget: true,
  },
  completed: {
    learningStatuses: [
      "remediated_by_independent_transfer",
      "needs_targeted_retry",
      "inconclusive_needs_fresh_independent_verification",
      "no_misconception_observed",
    ],
    actions: ["schedule_delayed_retention", "schedule_targeted_retry", "review_completed_attempt"],
  },
});

export function isSupportedDossierClaimStatus(value) {
  return DOSSIER_CLAIM_STATUSES.includes(value);
}

export function assertSupportedDossierClaimStatuses(payload) {
  const candidates = payload?.hypotheses;
  if (!Array.isArray(candidates) || candidates.some((item) => !isSupportedDossierClaimStatus(item?.claim_status))) {
    throw new TypeError("misconception dossier contains an unsupported claim_status");
  }
  return payload;
}

export function isSupportedDossierContinuation(payload) {
  const policy = DOSSIER_CONTINUATION_POLICIES[payload?.state];
  const nextAction = payload?.next_action;
  if (
    !policy
    || !policy.learningStatuses.includes(payload?.learning_status)
    || !nextAction
    || !policy.actions.includes(nextAction.action)
  ) return false;
  if (policy.requiresPromptInstance) {
    return typeof nextAction.prompt_instance_id === "string" && nextAction.prompt_instance_id.length > 0;
  }
  if (policy.requiresRestartTarget) {
    return nextAction.target === "/v1/attempts"
      && typeof nextAction.reason === "string"
      && nextAction.reason.length > 0;
  }
  return true;
}

export function assertSupportedDossierContinuation(payload) {
  if (!isSupportedDossierContinuation(payload)) {
    throw new TypeError("misconception dossier contains an unsupported state or next_action");
  }
  return payload;
}

export function createAssistanceState({ available = false } = {}) {
  return {
    status: available ? "ready" : "unavailable",
    items: [],
    error: null,
    pendingCommandId: null,
  };
}

export function appendAssistance(state, result) {
  const item = result.assistance;
  return {
    status: item.ordinal >= ASSISTANCE_ACTIONS.length ? "exhausted" : "ready",
    items: [...(state?.items || []), item],
    error: null,
    pendingCommandId: null,
  };
}

export function createAssistanceCommandId() {
  if (globalThis.crypto?.randomUUID) return `assist-${globalThis.crypto.randomUUID()}`;
  return `assist-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function buildAssistanceCommand({ session, elapsedTimeSeconds, commandId }) {
  return {
    phase: "probe",
    expected_version: session.state_version,
    expected_state: "awaiting_probe",
    prompt_instance_id: session.probe.prompt_instance_id,
    action: "next",
    elapsed_time_seconds: Math.max(0, Math.min(Number(elapsedTimeSeconds) || 0, 7200)),
    command_id: commandId,
  };
}

const CAUSE_COPY = {
  "ratio-growth-confusion": {
    label: "把倍数关系直接当作增长率",
    subtype: "资料分析 · 增长率表达",
  },
  "denominator-current-base-confusion": {
    label: "增长率分母误用现期量",
    subtype: "资料分析 · 增长率分母",
  },
  "increment-rate-confusion": {
    label: "把增长量当作增长率",
    subtype: "资料分析 · 增长量与增长率",
  },
};

const EVIDENCE_COPY = {
  engineering_prior: "规则库先验",
  learner_history: "既往作答特征",
  attempt_feature_likelihood: "本次作答特征匹配",
};

const OBSERVATION_EVIDENCE_COPY = {
  "learner selection": "学习者选择",
  "exact option comparison": "选项精确比对",
};

function causeCopy(candidate) {
  return CAUSE_COPY[candidate?.cause_id] || {
    label: candidate?.label || candidate?.claim || "待进一步辨析的具体线索",
    subtype: candidate?.subtype || "题型子类待服务说明",
  };
}

function evidenceCopy(reference) {
  if (typeof reference === "string") return EVIDENCE_COPY[reference] || reference;
  if (reference?.kind === "initial_response_pattern") {
    return `首答作答特征${reference?.event?.seq ? `（事件 ${reference.event.seq}）` : ""}`;
  }
  if (reference?.kind === "targeted_probe_assessment") {
    return `定向探查评估${reference?.assessment_event?.seq ? `（事件 ${reference.assessment_event.seq}）` : ""}`;
  }
  return reference?.label || reference?.summary || reference?.evidence_id || reference?.id || reference?.kind || "未命名证据引用";
}

function normalizeCandidate(candidate, index, defaultLearningStatus = "unavailable") {
  const copy = causeCopy(candidate);
  const probability = Number(candidate?.probability ?? candidate?.ranking_probability);
  const supporting = candidate?.supporting_evidence_refs
    || candidate?.supporting_evidence
    || candidate?.evidence
    || [];
  const refuting = candidate?.refuting_evidence_refs
    || candidate?.refuting_evidence
    || [];
  return {
    id: candidate?.cause_id || candidate?.claim_id || `candidate-${index + 1}`,
    rank: Number(candidate?.rank) || index + 1,
    label: copy.label,
    subtype: copy.subtype,
    probability: Number.isFinite(probability) ? probability : null,
    claimStatus: candidate.claim_status,
    learningStatus: candidate?.learning_status || defaultLearningStatus,
    supportingEvidence: supporting.map(evidenceCopy),
    refutingEvidence: refuting.map(evidenceCopy),
  };
}

export function normalizeMisconceptionDossier(payload) {
  assertSupportedDossierClaimStatuses(payload);
  assertSupportedDossierContinuation(payload);
  const candidates = payload?.hypotheses || [];
  const observationPayload = payload?.observations || {};
  const observations = [
    {
      id: "score",
      label: "首答评分",
      value: observationPayload?.score?.passed
        ? `通过 · ${observationPayload.score.score}/${observationPayload.score.max_score}`
        : `未通过 · ${observationPayload?.score?.score ?? "—"}/${observationPayload?.score?.max_score ?? "—"}`,
      source: observationPayload?.event?.seq ? `本机事件 ${observationPayload.event.seq}` : "本机事件轨迹",
    },
    ...(observationPayload?.items || []).map((item, index) => ({
      id: item?.observation_id || `observation-${index + 1}`,
      label: item?.kind === "score" ? "评分观察" : item?.kind === "distractor_pattern" ? "干扰项特征" : "作答观察",
      value: typeof item?.value === "boolean" ? (item.value ? "是" : "否") : String(item?.value ?? "已记录"),
      source: OBSERVATION_EVIDENCE_COPY[item?.evidence]
        || (typeof item?.evidence === "string" && item.evidence.startsWith("selected option ") ? `选择了 ${item.evidence.slice(-1)} 选项` : item?.evidence)
        || "本机评分适配器",
    })),
  ];
  const rankedHypotheses = candidates.map((item, index) => normalizeCandidate(item, index, payload.learning_status));
  const learningStatus = payload?.learning_status || payload?.status || "unconfirmed";
  const requiresRestart = ["processing_probe", "processing_verification"].includes(payload.state);
  return {
    source: "sidecar_dossier",
    persistence: "event_sourced",
    runId: payload.run_id,
    skill: payload?.module ? String(payload.module).replaceAll("/", " · ") : "资料分析 · 增长率与基期量",
    observations,
    rankedHypotheses,
    status: learningStatus,
    serviceState: payload.state,
    statusCopy: "尚未确认",
    nextProbe: requiresRestart ? null : (payload?.probe?.prompt || "等待后续探查安排"),
    canConfirm: false,
    cohortEvidence: payload?.cohort_evidence || { status: "unavailable", sample_size: 0 },
    sourceTraceVersion: Number(payload?.provenance?.source_trace_version) || 0,
    nextAction: payload.next_action,
    requiresRestart,
  };
}
