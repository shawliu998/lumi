import { SMART_PRACTICE_SCOPES } from "./practiceScopes.js";

const KNOWN_SCOPE_IDS = new Set(SMART_PRACTICE_SCOPES.map((scope) => scope.scopeId));
const WRONG_STATES = new Set(["needs_review", "resolved"]);
const SESSION_STATES = new Set(["active", "completed", "ended_early"]);
const HYPOTHESIS_STATES = new Set([
  "evidence_insufficient",
  "repeated_error_observed",
  "awaiting_disambiguation",
  "supported_hypothesis",
  "awaiting_transfer_validation",
  "weakened_by_transfer",
  "persistent_or_recurrent",
  "resolved_after_validation",
  "hypothesis_withdrawn",
  "voided",
]);

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function nonNegativeInteger(value) {
  return Number.isInteger(value) && value >= 0;
}

function nullableMetric(value) {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function requireOverall(value) {
  if (
    !isObject(value)
    || !nonNegativeInteger(value.session_count)
    || !nonNegativeInteger(value.completed_session_count)
    || !nonNegativeInteger(value.scored_attempt_count)
    || !nonNegativeInteger(value.correct_count)
    || !nonNegativeInteger(value.incorrect_count)
    || !nullableMetric(value.accuracy)
    || !nonNegativeInteger(value.independent_attempt_count)
    || !nonNegativeInteger(value.ignored_non_independent_attempt_count)
    || !nonNegativeInteger(value.recorded_response_time_count)
    || !nullableMetric(value.average_response_time_seconds)
  ) {
    throw new TypeError("Invalid practice profile overall metrics");
  }
  return value;
}

function requireModule(value) {
  if (
    !isObject(value)
    || !text(value.module_id)
    || !text(value.module_label)
    || !isObject(value.facts)
    || !isObject(value.independent_evidence)
    || !nonNegativeInteger(value.ignored_non_independent_count)
    || !text(value.evidence_status)
    || !Array.isArray(value.reason_codes)
  ) {
    throw new TypeError("Invalid practice profile module");
  }
  const factMetrics = value.facts;
  const independent = value.independent_evidence;
  if (
    !nonNegativeInteger(factMetrics.attempt_count)
    || !nonNegativeInteger(factMetrics.correct_count)
    || !nonNegativeInteger(factMetrics.incorrect_count)
    || !nullableMetric(factMetrics.accuracy)
    || !nonNegativeInteger(factMetrics.recorded_response_time_count)
    || !nullableMetric(factMetrics.average_response_time_seconds)
    || !nonNegativeInteger(independent.attempt_count)
    || !nonNegativeInteger(independent.correct_count)
    || !nonNegativeInteger(independent.incorrect_count)
    || !nullableMetric(independent.accuracy)
    || !nonNegativeInteger(independent.distinct_family_count)
    || !nonNegativeInteger(independent.verified_transfer_count)
  ) {
    throw new TypeError("Invalid practice module metrics");
  }
  return value;
}

function normalizeHypothesis(value) {
  if (
    !isObject(value)
    || !text(value.hypothesis_id)
    || !text(value.signature_label)
    || !HYPOTHESIS_STATES.has(value.status)
    || !Array.isArray(value.cause_candidates)
    || !value.cause_candidates.every((candidate) => isObject(candidate) && text(candidate.label))
    || !nonNegativeInteger(value.independent_family_count)
  ) {
    throw new TypeError("Invalid reversible error hypothesis");
  }
  return {
    ...value,
    hypothesis_id: text(value.hypothesis_id),
    signature_label: text(value.signature_label),
    cause_candidates: value.cause_candidates.map((candidate) => ({
      ...candidate,
      label: text(candidate.label),
    })),
  };
}

export function normalizePracticeProfile(payload, { embedded = false } = {}) {
  if (
    !isObject(payload)
    || (!embedded && payload.schema_version !== "lumi.practice-profile.v1")
    || !isObject(payload.overall)
    || !Array.isArray(payload.modules)
    || !Array.isArray(payload.error_hypotheses)
    || !payload.evidence_policy
  ) {
    throw new TypeError("Invalid practice profile contract");
  }
  requireOverall(payload.overall);
  payload.modules.forEach(requireModule);
  return {
    ...payload,
    error_hypotheses: payload.error_hypotheses.map(normalizeHypothesis),
  };
}

export function normalizeWrongQuestion(value) {
  if (
    !isObject(value)
    || !text(value.question_ref?.question_id)
    || !text(value.question_ref?.question_version_id)
    || !text(value.module_id)
    || !text(value.module_label)
    || !WRONG_STATES.has(value.review_state)
    || !text(value.question?.prompt)
    || !isObject(value.answer_review)
    || !isObject(value.attempts)
    || !nonNegativeInteger(value.attempts.total_count)
    || !nonNegativeInteger(value.attempts.wrong_count)
    || !nonNegativeInteger(value.attempts.independent_wrong_count)
    || !Array.isArray(value.diagnosis_hypotheses)
  ) {
    throw new TypeError("Invalid wrong-question record");
  }
  return {
    id: value.question_ref.question_id,
    questionVersionId: value.question_ref.question_version_id,
    moduleId: value.module_id,
    moduleLabel: value.module_label,
    reviewState: value.review_state,
    prompt: value.question.prompt,
    responseMode: text(value.question.response_mode),
    options: isObject(value.question.options) ? value.question.options : {},
    correctOption: text(value.answer_review.correct_option),
    keyPrinciple: text(value.answer_review.key_principle),
    explanation: text(value.answer_review.explanation),
    totalAttempts: value.attempts.total_count,
    wrongAttempts: value.attempts.wrong_count,
    independentWrongAttempts: value.attempts.independent_wrong_count,
    lastSelectedOption: text(value.attempts.last_selected_option),
    lastWrongAt: text(value.attempts.last_wrong_at),
    diagnosisHypotheses: value.diagnosis_hypotheses.map(normalizeHypothesis),
  };
}

export function normalizeWrongQuestionBook(payload) {
  if (
    payload?.schema_version !== "lumi.wrong-question-book.v1"
    || !nonNegativeInteger(payload.total)
    || !nonNegativeInteger(payload.count)
    || !Array.isArray(payload.items)
    || payload.count !== payload.items.length
  ) {
    throw new TypeError("Invalid wrong-question book contract");
  }
  return { ...payload, items: payload.items.map(normalizeWrongQuestion) };
}

export function normalizePracticeOverview(payload) {
  if (
    payload?.schema_version !== "lumi.practice-overview.v1"
    || !Array.isArray(payload.recent_sessions)
    || !Array.isArray(payload.wrong_question_preview)
    || !isObject(payload.recommendation?.decision)
    || !Array.isArray(payload.recommendation.decision.reason_codes)
    || !Array.isArray(payload.recommendation.decision.evidence_refs)
  ) {
    throw new TypeError("Invalid practice overview contract");
  }
  const profile = normalizePracticeProfile(payload.profile, { embedded: true });
  const requestedScopeId = text(payload.recommendation.decision.recommended_scope_id);
  const recentSessions = payload.recent_sessions
    .map((session) => {
      const scopeId = text(session?.scope_id);
      const sessionId = text(session?.session_id);
      if (
        !isObject(session)
        || !sessionId
        || !KNOWN_SCOPE_IDS.has(scopeId)
        || !SESSION_STATES.has(session.status)
        || !nonNegativeInteger(session.answered_count)
        || session.target_count !== 8
        || session.answered_count > session.target_count
        || (session.status === "active" && session.answered_count >= session.target_count)
        || (session.status === "completed" && session.answered_count !== session.target_count)
      ) {
        return null;
      }
      const questionAttemptCount = nonNegativeInteger(session.question_attempt_count)
        && session.question_attempt_count <= session.answered_count
        ? session.question_attempt_count
        : null;
      const probeOrSkipCount = nonNegativeInteger(session.probe_or_skip_count)
        && session.probe_or_skip_count <= session.answered_count
        && (questionAttemptCount === null
          || session.probe_or_skip_count + questionAttemptCount === session.answered_count)
        ? session.probe_or_skip_count
        : null;
      return {
        sessionId,
        scopeId,
        status: session.status,
        answeredCount: session.answered_count,
        targetCount: session.target_count,
        questionAttemptCount,
        probeOrSkipCount,
        correctCount: questionAttemptCount !== null
          && nonNegativeInteger(session.correct_count)
          && session.correct_count <= questionAttemptCount
          ? session.correct_count
          : null,
        accuracy: nullableMetric(session.accuracy) ? session.accuracy : null,
        title: text(session.title),
        moduleLabel: text(session.module_label),
        startedAt: text(session.started_at),
      };
    })
    .filter(Boolean);
  const resumable = recentSessions.find((session) => (
    session.status === "active" && session.answeredCount < session.targetCount
  ));
  const activeSession = resumable ? {
    sessionId: resumable.sessionId,
    scopeId: resumable.scopeId,
    answeredCount: resumable.answeredCount,
    targetCount: resumable.targetCount,
    title: resumable.title,
    moduleLabel: resumable.moduleLabel,
    startedAt: resumable.startedAt,
  } : null;
  return {
    ...payload,
    profile,
    wrongQuestionPreview: payload.wrong_question_preview.map(normalizeWrongQuestion),
    recommendedScopeId: KNOWN_SCOPE_IDS.has(requestedScopeId) ? requestedScopeId : "",
    recentSessions,
    activeSession,
  };
}

export function normalizePracticeHistory(payload) {
  if (
    payload?.schema_version !== "lumi.practice-history.v1"
    || !nonNegativeInteger(payload.total)
    || !nonNegativeInteger(payload.count)
    || !Array.isArray(payload.items)
    || payload.count !== payload.items.length
  ) {
    throw new TypeError("Invalid practice history contract");
  }
  return payload;
}

export function normalizePracticeSessionReport(payload) {
  if (
    payload?.schema_version !== "lumi.practice-session-report.v1"
    || !isObject(payload.session)
    || !isObject(payload.metrics)
    || !Array.isArray(payload.module_breakdown)
    || !Array.isArray(payload.error_hypotheses)
    || !isObject(payload.recommendation)
    || !isObject(payload.audit)
  ) {
    throw new TypeError("Invalid practice session report contract");
  }
  return {
    ...payload,
    error_hypotheses: payload.error_hypotheses.map(normalizeHypothesis),
  };
}

export function isKnownPracticeScope(scopeId) {
  return KNOWN_SCOPE_IDS.has(scopeId);
}
