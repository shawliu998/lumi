export const SMART_PRACTICE_TARGET = 8;

const MAX_SUMMARY_PATTERNS = 2;

function firstText(...values) {
  const value = values.find((item) => typeof item === "string" && item.trim());
  return value?.trim() || "";
}

function normalizeOptions(value) {
  if (Array.isArray(value)) {
    return value
      .map((option, index) => {
        if (typeof option === "string") {
          return { id: String(index + 1), text: option };
        }
        const id = firstText(option?.id, option?.value, option?.key);
        const text = firstText(option?.text, option?.label, option?.content);
        return id && text ? { id, text } : null;
      })
      .filter(Boolean);
  }
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([id, text]) => ({ id: String(id), text: String(text || "").trim() }))
      .filter((option) => option.id && option.text);
  }
  return [];
}

export function normalizeSmartPracticeQuestion(value) {
  if (!value || typeof value !== "object") return null;
  const questionId = firstText(value.question_id, value.questionId, value.id);
  const questionVersionId = firstText(
    value.question_version_id,
    value.questionVersionId,
    value.version_id,
  );
  const prompt = firstText(value.prompt, value.stem, value.text);
  if (!questionId || !questionVersionId || !prompt) return null;
  return {
    questionId,
    questionVersionId,
    prompt,
    options: normalizeOptions(value.options),
    ordinal: Number.isInteger(value.ordinal) ? value.ordinal : null,
    eyebrow: firstText(value.eyebrow, value.type_label, value.typeLabel),
  };
}

function normalizeMicrotutorial(value) {
  if (typeof value === "string" && value.trim()) {
    return { title: "针对性讲解", body: value.trim(), points: [] };
  }
  if (!value || typeof value !== "object") return null;
  const body = firstText(value.body, value.content, value.message, value.prompt, value.principle);
  const rawPoints = Array.isArray(value.points)
    ? value.points
    : [value.worked_contrast, value.return_action];
  const points = rawPoints
    .filter((point) => typeof point === "string" && point.trim())
    .map((point) => point.trim());
  if (!body && points.length === 0) return null;
  return {
    title: firstText(value.title, value.label) || "针对性讲解",
    body,
    points,
  };
}

function normalizeProbe(value) {
  if (!value || typeof value !== "object") return null;
  const prompt = firstText(value.prompt, value.question, value.text);
  const options = normalizeOptions(value.options);
  if (!prompt || options.length === 0) return null;
  return {
    probeId: firstText(value.probe_id, value.probeId, value.asset_id, value.id),
    hypothesisId: firstText(value.hypothesis_id, value.hypothesisId),
    prompt,
    options,
  };
}

function normalizeFeedback(payload) {
  const result = payload?.result && typeof payload.result === "object" ? payload.result : {};
  const detail = result.feedback && typeof result.feedback === "object" ? result.feedback : {};
  const correct = typeof result.correct === "boolean" ? result.correct : null;
  return {
    correct,
    title: firstText(detail.title, detail.headline)
      || (correct === true ? "回答正确" : correct === false ? "这题暂未答对" : "本题已记录"),
    keyPrinciple: firstText(detail.key_principle, detail.keyPrinciple, detail.message),
    correctOption: firstText(result.correct_option, result.correctOption),
    selectedOption: firstText(result.selected_option, result.selectedOption),
    explanation: firstText(detail.explanation, result.explanation),
    microtutorial: normalizeMicrotutorial(detail.microtutorial),
    probe: normalizeProbe(detail.probe),
  };
}

function normalizeFact(value, index) {
  if (typeof value === "string" && value.trim()) {
    return { id: `fact-${index}`, label: "", value: value.trim() };
  }
  if (!value || typeof value !== "object") return null;
  const label = firstText(value.label, value.name, value.title);
  const factValue = firstText(value.value, value.detail, value.text);
  if (!label && !factValue) return null;
  return { id: firstText(value.id) || `fact-${index}`, label, value: factValue };
}

function normalizePattern(value, index) {
  if (typeof value === "string" && value.trim()) {
    return { id: `pattern-${index}`, title: value.trim(), evidence: "" };
  }
  if (!value || typeof value !== "object") return null;
  const title = firstText(value.title, value.label, value.name);
  if (!title) return null;
  return {
    id: firstText(value.id, value.signature_id, value.signatureId) || `pattern-${index}`,
    title,
    evidence: firstText(value.evidence, value.detail, value.description),
  };
}

function normalizeWrongQuestion(value, index) {
  if (!value || typeof value !== "object") return null;
  const questionId = firstText(value.question_id, value.questionId, value.id);
  const prompt = firstText(value.prompt, value.stem, value.question);
  if (!questionId || !prompt) return null;
  const ordinalValue = Number(value.ordinal);
  return {
    id: questionId,
    questionVersionId: firstText(value.question_version_id, value.questionVersionId),
    ordinal: Number.isInteger(ordinalValue) && ordinalValue > 0 ? ordinalValue : index + 1,
    prompt,
    selectedOption: firstText(value.selected_option, value.selectedOption, value.answer),
    correctOption: firstText(value.correct_option, value.correctOption),
    keyPrinciple: firstText(value.key_principle, value.keyPrinciple),
    explanation: firstText(value.explanation),
  };
}

function wrongQuestionFromAttempt(attempt, index) {
  if (attempt?.correct !== false) return null;
  return normalizeWrongQuestion({
    question_id: attempt.questionId,
    question_version_id: attempt.questionVersionId,
    ordinal: attempt.ordinal,
    prompt: attempt.prompt,
    selected_option: attempt.selectedOption,
    correct_option: attempt.correctOption,
    key_principle: attempt.keyPrinciple,
    explanation: attempt.explanation,
  }, index);
}

function integerFromFact(facts, id) {
  const fact = facts.find((item) => item.id === id);
  const match = fact?.value?.match(/\d+/u);
  return match ? Number(match[0]) : null;
}

function derivedSummary(attempts, resumedCount = 0) {
  const scored = attempts.filter((attempt) => typeof attempt.correct === "boolean");
  const correct = scored.filter((attempt) => attempt.correct).length;
  const wrongQuestions = attempts.map(wrongQuestionFromAttempt).filter(Boolean);
  const facts = [
    {
      id: "answered",
      label: "完成题数",
      value: `${Math.min(SMART_PRACTICE_TARGET, resumedCount + attempts.length)} / ${SMART_PRACTICE_TARGET}`,
    },
  ];
  if (scored.length > 0) {
    facts.push(
      { id: "correct", label: "答对", value: `${correct} 题` },
      { id: "scored", label: "已判分", value: `${scored.length} 题` },
    );
  }
  return {
    title: "本组练习完成",
    message: "这里只汇总本组可观察到的作答事实。",
    facts,
    possiblePatterns: [],
    correctCount: resumedCount === 0 ? correct : null,
    totalCount: resumedCount + attempts.length,
    scoredCount: scored.length,
    primaryWeakness: null,
    wrongQuestions,
    wrongQuestionsComplete: resumedCount === 0,
  };
}

function normalizeSummary(value, attempts, resumedCount = 0) {
  const fallback = derivedSummary(attempts, resumedCount);
  if (!value || typeof value !== "object") return fallback;
  const factsValue = Array.isArray(value.facts) ? value.facts : [];
  const patternsValue = Array.isArray(value.possible_patterns)
    ? value.possible_patterns
    : Array.isArray(value.possiblePatterns)
      ? value.possiblePatterns
      : Array.isArray(value.patterns)
        ? value.patterns
        : [];
  const facts = factsValue.map(normalizeFact).filter(Boolean);
  const possiblePatterns = patternsValue
    .map(normalizePattern)
    .filter(Boolean)
    .slice(0, MAX_SUMMARY_PATTERNS);
  const rawWrongQuestions = Array.isArray(value.wrong_questions)
    ? value.wrong_questions
    : Array.isArray(value.wrongQuestions)
      ? value.wrongQuestions
      : null;
  const wrongQuestions = rawWrongQuestions === null
    ? fallback.wrongQuestions
    : rawWrongQuestions.map(normalizeWrongQuestion).filter(Boolean);
  const normalizedFacts = facts.length > 0 ? facts : fallback.facts;
  const correctCount = integerFromFact(normalizedFacts, "correct") ?? fallback.correctCount;
  const totalCount = integerFromFact(normalizedFacts, "answered") ?? fallback.totalCount;
  return {
    title: firstText(value.title, value.heading) || fallback.title,
    message: firstText(value.message, value.description) || fallback.message,
    facts: normalizedFacts,
    possiblePatterns,
    correctCount,
    totalCount,
    scoredCount: Number.isInteger(value.scored_count) ? value.scored_count : fallback.scoredCount,
    primaryWeakness: possiblePatterns[0] || null,
    wrongQuestions,
    wrongQuestionsComplete: rawWrongQuestions !== null || resumedCount === 0,
  };
}

export function createSmartPracticeState() {
  return {
    phase: "idle",
    sessionId: "",
    title: "智能刷题",
    moduleLabel: "行测",
    targetCount: SMART_PRACTICE_TARGET,
    answeredCount: 0,
    currentQuestion: null,
    nextQuestion: null,
    answer: "",
    feedback: null,
    serverSummary: null,
    summary: null,
    attempts: [],
    resumedCount: 0,
    probeAnswer: "",
    probeStatus: "idle",
    probeError: "",
    error: "",
    retryKind: "",
  };
}

function startSucceeded(state, payload) {
  const session = payload?.session && typeof payload.session === "object" ? payload.session : {};
  const question = normalizeSmartPracticeQuestion(payload?.question);
  const pendingProbe = normalizeProbe(payload?.pending_probe);
  const sessionId = firstText(session.session_id, session.sessionId, payload?.session_id);
  if (!sessionId || (!question && !pendingProbe)) {
    return {
      ...state,
      phase: "error",
      error: "本机服务没有返回可继续的题目或探查。",
      retryKind: "start",
    };
  }
  const resumedCount = Math.min(
    SMART_PRACTICE_TARGET,
    Math.max(0, Number.isInteger(session.answered_count) ? session.answered_count : 0),
  );
  return {
    ...createSmartPracticeState(),
    phase: question ? "question" : "feedback",
    sessionId,
    title: firstText(payload?.title, session.title) || state.title,
    moduleLabel: firstText(payload?.module_label, payload?.moduleLabel, session.module_label) || state.moduleLabel,
    answeredCount: resumedCount,
    resumedCount,
    currentQuestion: question,
    feedback: pendingProbe
      ? {
          correct: null,
          title: "继续未完成本组",
          keyPrinciple: "上次在可选探查处中断；提交或跳过后即可继续刷题。",
          correctOption: "",
          selectedOption: "",
          explanation: "",
          microtutorial: null,
          probe: pendingProbe,
        }
      : null,
  };
}

function submitSucceeded(state, payload) {
  if (state.phase !== "submitting" || !state.currentQuestion) return state;
  const normalizedFeedback = normalizeFeedback(payload);
  const answeredCount = Math.min(SMART_PRACTICE_TARGET, state.answeredCount + 1);
  const feedback = answeredCount >= SMART_PRACTICE_TARGET
    ? { ...normalizedFeedback, probe: null }
    : normalizedFeedback;
  const attempts = [
    ...state.attempts,
    {
      questionId: state.currentQuestion.questionId,
      questionVersionId: state.currentQuestion.questionVersionId,
      ordinal: state.currentQuestion.ordinal || answeredCount,
      prompt: state.currentQuestion.prompt,
      selectedOption: normalizedFeedback.selectedOption || state.answer,
      correctOption: normalizedFeedback.correctOption,
      correct: feedback.correct,
      keyPrinciple: normalizedFeedback.keyPrinciple,
      explanation: normalizedFeedback.explanation,
    },
  ];
  return {
    ...state,
    phase: "feedback",
    answeredCount,
    nextQuestion: answeredCount < SMART_PRACTICE_TARGET
      ? normalizeSmartPracticeQuestion(payload?.question)
      : null,
    feedback,
    serverSummary: payload?.summary || null,
    attempts,
    probeAnswer: "",
    probeStatus: "idle",
    probeError: "",
    error: "",
    retryKind: "",
  };
}

function continueFromFeedback(state) {
  if (state.phase !== "feedback") return state;
  if (state.answeredCount >= SMART_PRACTICE_TARGET) {
    return {
      ...state,
      phase: "complete",
      currentQuestion: null,
      nextQuestion: null,
      answer: "",
      summary: normalizeSummary(state.serverSummary, state.attempts, state.resumedCount),
    };
  }
  if (!state.nextQuestion) {
    return {
      ...state,
      phase: "error",
      error: "本机服务没有返回下一题，本组进度已经保留。",
      retryKind: "continue",
    };
  }
  return {
    ...state,
    phase: "question",
    currentQuestion: state.nextQuestion,
    nextQuestion: null,
    answer: "",
    feedback: null,
    serverSummary: null,
    probeAnswer: "",
    probeStatus: "idle",
    probeError: "",
  };
}

function probeSucceeded(state, payload) {
  if (state.phase !== "feedback" || !state.feedback?.probe) return state;
  const session = payload?.session && typeof payload.session === "object" ? payload.session : {};
  const serverCount = Number.isInteger(session.answered_count) ? session.answered_count : null;
  const answeredCount = Math.min(
    SMART_PRACTICE_TARGET,
    Math.max(state.answeredCount, serverCount ?? state.answeredCount + 1),
  );
  const tutorial = normalizeMicrotutorial(payload?.probe_result?.microtutorial);
  return {
    ...state,
    answeredCount,
    nextQuestion: answeredCount < SMART_PRACTICE_TARGET
      ? normalizeSmartPracticeQuestion(payload?.question)
      : null,
    feedback: {
      ...state.feedback,
      probe: null,
      microtutorial: tutorial || state.feedback.microtutorial,
    },
    serverSummary: payload?.summary || state.serverSummary,
    probeAnswer: "",
    probeStatus: "submitted",
    probeError: "",
  };
}

export function smartPracticeReducer(state, action) {
  switch (action.type) {
    case "START_REQUESTED":
      return { ...createSmartPracticeState(), phase: "starting" };
    case "START_SUCCEEDED":
      return startSucceeded(state, action.payload);
    case "START_FAILED":
      return {
        ...state,
        phase: "error",
        error: firstText(action.error?.message, action.error) || "暂时无法开始本组练习。",
        retryKind: "start",
      };
    case "ANSWER_CHANGED":
      return state.phase === "question" ? { ...state, answer: String(action.value || "") } : state;
    case "SUBMIT_REQUESTED":
      return state.phase === "question" && state.answer.trim()
        ? { ...state, phase: "submitting", error: "", retryKind: "" }
        : state;
    case "SUBMIT_SUCCEEDED":
      return submitSucceeded(state, action.payload);
    case "SUBMIT_FAILED":
      return {
        ...state,
        phase: "error",
        error: firstText(action.error?.message, action.error) || "这次作答还没有保存。",
        retryKind: "submit",
      };
    case "CONTINUE":
      return continueFromFeedback(state);
    case "RETRY_SUBMIT":
      return state.phase === "error" && state.retryKind === "submit"
        ? { ...state, phase: "question", error: "", retryKind: "" }
        : state;
    case "PROBE_ANSWER_CHANGED":
      return state.phase === "feedback"
        ? { ...state, probeAnswer: String(action.value || ""), probeError: "" }
        : state;
    case "PROBE_SUBMIT_REQUESTED":
      return state.phase === "feedback" && (state.probeAnswer.trim() || action.allowSkip)
        ? { ...state, probeStatus: "submitting", probeError: "" }
        : state;
    case "PROBE_SUBMIT_FAILED":
      return state.phase === "feedback"
        ? {
            ...state,
            probeStatus: "idle",
            probeError: firstText(action.error?.message, action.error) || "探查未保存，不影响继续刷题。",
          }
        : state;
    case "PROBE_SUBMIT_SUCCEEDED":
      return probeSucceeded(state, action.payload);
    default:
      return state;
  }
}
