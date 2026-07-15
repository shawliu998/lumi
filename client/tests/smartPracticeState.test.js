import assert from "node:assert/strict";
import test from "node:test";

import {
  createSmartPracticeState,
  normalizeSmartPracticeQuestion,
  SMART_PRACTICE_TARGET,
  smartPracticeReducer,
} from "../src/smartPracticeState.js";

function question(ordinal) {
  return {
    question_id: `question-${ordinal}`,
    question_version_id: `question-${ordinal}@1`,
    prompt: `第 ${ordinal} 题题干`,
    options: [
      { id: "A", text: "选项 A" },
      { id: "B", text: "选项 B" },
    ],
    ordinal,
    total: SMART_PRACTICE_TARGET,
  };
}

function startedState(overrides = {}) {
  return smartPracticeReducer(createSmartPracticeState(), {
    type: "START_SUCCEEDED",
    payload: {
      session: {
        session_id: "session-1",
        answered_count: 0,
        target_count: 99,
        can_end_early: true,
      },
      question: question(1),
      ...overrides,
    },
  });
}

function answerQuestion(state, { correct = true, nextOrdinal, feedback = {}, summary } = {}) {
  let next = smartPracticeReducer(state, { type: "ANSWER_CHANGED", value: correct ? "A" : "B" });
  next = smartPracticeReducer(next, { type: "SUBMIT_REQUESTED" });
  return smartPracticeReducer(next, {
    type: "SUBMIT_SUCCEEDED",
    payload: {
      result: {
        correct,
        selected_option: correct ? "A" : "B",
        correct_option: "A",
        feedback: {
          level: correct ? "minimal" : "correction",
          key_principle: correct ? "判断正确。" : "先确定比较起点。",
          explanation: "完整解析内容。",
          ...feedback,
        },
      },
      ...(nextOrdinal ? { question: question(nextOrdinal) } : {}),
      ...(summary ? { summary } : {}),
    },
  });
}

test("the client keeps a fixed eight-question target and requires only an answer", () => {
  const state = startedState();
  assert.equal(state.phase, "question");
  assert.equal(state.targetCount, 8);
  assert.equal(state.answer, "");

  const withoutAnswer = smartPracticeReducer(state, { type: "SUBMIT_REQUESTED" });
  assert.equal(withoutAnswer.phase, "question");

  const withAnswer = smartPracticeReducer(
    smartPracticeReducer(state, { type: "ANSWER_CHANGED", value: "A" }),
    { type: "SUBMIT_REQUESTED" },
  );
  assert.equal(withAnswer.phase, "submitting");
});

test("an incorrect answer advances exactly one slot and never adds a question", () => {
  const state = answerQuestion(startedState(), { correct: false, nextOrdinal: 2 });
  assert.equal(state.phase, "feedback");
  assert.equal(state.answeredCount, 1);
  assert.equal(state.targetCount, 8);
  assert.equal(state.feedback.correct, false);

  const next = smartPracticeReducer(state, { type: "CONTINUE" });
  assert.equal(next.phase, "question");
  assert.equal(next.currentQuestion.ordinal, 2);
  assert.equal(next.answeredCount, 1);
});

test("microtutorials and optional probes exist only when returned by the service", () => {
  const ordinary = answerQuestion(startedState(), { correct: false, nextOrdinal: 2 });
  assert.equal(ordinary.feedback.microtutorial, null);
  assert.equal(ordinary.feedback.probe, null);

  const withIntervention = answerQuestion(startedState(), {
    correct: false,
    feedback: {
      microtutorial: {
        title: "比较起点",
        principle: "增长率以基期量作分母。",
        worked_contrast: "从 400 增到 460，应计算 60 ÷ 400。",
        return_action: "先圈出变化前的数。",
      },
      probe: {
        probe_id: "probe-1",
        hypothesis_id: "hypothesis-1",
        prompt: "增长率的分母应选哪一个量？",
        options: [
          { id: "base", text: "基期量" },
          { id: "current", text: "现期量" },
        ],
      },
    },
  });
  assert.equal(withIntervention.feedback.microtutorial.title, "比较起点");
  assert.equal(withIntervention.feedback.microtutorial.points.length, 2);
  assert.equal(withIntervention.feedback.probe.hypothesisId, "hypothesis-1");

  const probeSelected = smartPracticeReducer(withIntervention, {
    type: "PROBE_ANSWER_CHANGED",
    value: "base",
  });
  const probeSubmitted = smartPracticeReducer(probeSelected, { type: "PROBE_SUBMIT_REQUESTED" });
  assert.equal(probeSubmitted.probeStatus, "submitting");
  assert.equal(probeSubmitted.answeredCount, 1);

  const probeSaved = smartPracticeReducer(probeSubmitted, {
    type: "PROBE_SUBMIT_SUCCEEDED",
    payload: {
      session: { answered_count: 2 },
      question: question(3),
      probe_result: {
        skipped: false,
        microtutorial: { principle: "增长率以基期量作分母。" },
      },
    },
  });
  assert.equal(probeSaved.answeredCount, 2);
  assert.equal(probeSaved.feedback.probe, null);
  assert.equal(probeSaved.feedback.microtutorial.body, "增长率以基期量作分母。");
  const afterSaved = smartPracticeReducer(probeSaved, { type: "CONTINUE" });
  assert.equal(afterSaved.currentQuestion.ordinal, 3);

  const skipRequested = smartPracticeReducer(withIntervention, {
    type: "PROBE_SUBMIT_REQUESTED",
    allowSkip: true,
  });
  const skipped = smartPracticeReducer(skipRequested, {
    type: "PROBE_SUBMIT_SUCCEEDED",
    payload: {
      session: { answered_count: 2 },
      question: question(3),
      probe_result: { skipped: true, microtutorial: null },
    },
  });
  assert.equal(skipped.answeredCount, 2);
  const afterSkip = smartPracticeReducer(skipped, { type: "CONTINUE" });
  assert.equal(afterSkip.phase, "question");
  assert.equal(afterSkip.currentQuestion.ordinal, 3);
});

test("the eighth answer always ends after its feedback and ignores an extra question", () => {
  let state = startedState();
  for (let ordinal = 1; ordinal <= 8; ordinal += 1) {
    state = answerQuestion(state, { correct: ordinal % 2 === 0, nextOrdinal: ordinal + 1 });
    assert.equal(state.answeredCount, ordinal);
    assert.equal(state.phase, "feedback");
    if (ordinal < 8) state = smartPracticeReducer(state, { type: "CONTINUE" });
  }

  assert.equal(state.nextQuestion, null);
  state = smartPracticeReducer(state, { type: "CONTINUE" });
  assert.equal(state.phase, "complete");
  assert.equal(state.answeredCount, 8);
  assert.equal(state.summary.facts[0].value, "8 / 8");
});

test("the client fails closed on unversioned questions and strips a final-slot probe", () => {
  assert.equal(normalizeSmartPracticeQuestion({ question_id: "q", prompt: "题目" }), null);

  let state = startedState();
  state = { ...state, answeredCount: 7, currentQuestion: question(8) };
  state = smartPracticeReducer(state, { type: "ANSWER_CHANGED", value: "B" });
  state = smartPracticeReducer(state, { type: "SUBMIT_REQUESTED" });
  state = smartPracticeReducer(state, {
    type: "SUBMIT_SUCCEEDED",
    payload: {
      result: {
        correct: false,
        feedback: {
          key_principle: "先核对条件。",
          probe: {
            hypothesis_id: "h-final",
            prompt: "不应出现的第九题位",
            options: [{ id: "A", text: "选项" }],
          },
        },
      },
    },
  });
  assert.equal(state.answeredCount, 8);
  assert.equal(state.feedback.probe, null);
  assert.equal(smartPracticeReducer(state, { type: "CONTINUE" }).phase, "complete");
});

test("group summary keeps facts and shows at most two possible patterns", () => {
  let state = startedState();
  for (let ordinal = 1; ordinal <= 8; ordinal += 1) {
    const summary = ordinal === 8
      ? {
          title: "本组完成",
          facts: [
            { id: "accuracy", label: "正确率", value: "6 / 8" },
            { id: "duration", label: "用时", value: "7 分 20 秒" },
          ],
          possible_patterns: [
            { id: "p1", title: "比较起点待确认", evidence: "两个独立题族出现相同错项。" },
            { id: "p2", title: "下降方向待确认", evidence: "一次下降题方向错误。" },
            { id: "p3", title: "不应展示的第三项", evidence: "超过产品上限。" },
          ],
        }
      : undefined;
    state = answerQuestion(state, { correct: ordinal <= 6, nextOrdinal: ordinal + 1, summary });
    if (ordinal < 8) state = smartPracticeReducer(state, { type: "CONTINUE" });
  }
  state = smartPracticeReducer(state, { type: "CONTINUE" });

  assert.deepEqual(state.summary.facts.map((fact) => fact.value), ["6 / 8", "7 分 20 秒"]);
  assert.deepEqual(state.summary.possiblePatterns.map((pattern) => pattern.id), ["p1", "p2"]);
  assert.equal(state.summary.correctCount, 6);
  assert.equal(state.summary.totalCount, 8);
  assert.equal(state.summary.primaryWeakness.title, "比较起点待确认");
  assert.equal(state.summary.wrongQuestions.length, 2);
  assert.equal(state.summary.wrongQuestions[0].selectedOption, "B");
  assert.equal(state.summary.wrongQuestions[0].correctOption, "A");
  assert.equal(state.summary.wrongQuestions[0].explanation, "完整解析内容。");
  assert.equal(state.summary.wrongQuestionsComplete, true);
});

test("a resumed group reports authoritative totals without inventing missing wrong-question detail", () => {
  let state = startedState({
    session: {
      session_id: "session-resumed",
      answered_count: 7,
      target_count: 8,
      can_end_early: true,
    },
    question: question(8),
  });
  state = answerQuestion(state, {
    correct: false,
    summary: {
      facts: [
        { id: "answered", label: "完成题数", value: "8 / 8" },
        { id: "correct", label: "答对", value: "5 题" },
      ],
    },
  });
  state = smartPracticeReducer(state, { type: "CONTINUE" });

  assert.equal(state.summary.correctCount, 5);
  assert.equal(state.summary.totalCount, 8);
  assert.equal(state.summary.scoreBreakdownComplete, false);
  assert.equal(state.summary.wrongQuestions.length, 1);
  assert.equal(state.summary.wrongQuestionsComplete, false);

  let missingServerSummary = startedState({
    session: { session_id: "session-resumed-2", answered_count: 7, target_count: 8 },
    question: question(8),
  });
  missingServerSummary = answerQuestion(missingServerSummary, { correct: false });
  missingServerSummary = smartPracticeReducer(missingServerSummary, { type: "CONTINUE" });
  assert.equal(missingServerSummary.summary.correctCount, null);
});

test("a session interrupted at an optional probe resumes without creating a new group", () => {
  const state = smartPracticeReducer(createSmartPracticeState(), {
    type: "START_SUCCEEDED",
    payload: {
      resumed: true,
      session: {
        session_id: "session-pending-probe",
        answered_count: 3,
        target_count: 8,
      },
      pending_probe: {
        probe_id: "probe-pending",
        hypothesis_id: "hypothesis-pending",
        prompt: "这一步应先确认哪个量？",
        options: {
          A: "基期量",
          B: "现期量",
        },
      },
    },
  });

  assert.equal(state.phase, "feedback");
  assert.equal(state.sessionId, "session-pending-probe");
  assert.equal(state.answeredCount, 3);
  assert.equal(state.resumedCount, 3);
  assert.equal(state.currentQuestion, null);
  assert.equal(state.feedback.probe.hypothesisId, "hypothesis-pending");
});

test("starting the next group clears terminal state and preserves the fixed-eight contract", () => {
  let state = startedState();
  for (let ordinal = 1; ordinal <= 8; ordinal += 1) {
    state = answerQuestion(state, { correct: true, nextOrdinal: ordinal + 1 });
    if (ordinal < 8) state = smartPracticeReducer(state, { type: "CONTINUE" });
  }
  state = smartPracticeReducer(state, { type: "CONTINUE" });
  assert.equal(state.phase, "complete");

  state = smartPracticeReducer(state, { type: "START_REQUESTED" });
  state = smartPracticeReducer(state, {
    type: "START_SUCCEEDED",
    payload: { session: { session_id: "session-2", answered_count: 0 }, question: question(1) },
  });
  assert.equal(state.phase, "question");
  assert.equal(state.sessionId, "session-2");
  assert.equal(state.targetCount, 8);
  assert.equal(state.attempts.length, 0);
  assert.equal(state.summary, null);
});

test("duplicate submit results cannot increment progress twice", () => {
  let state = smartPracticeReducer(startedState(), { type: "ANSWER_CHANGED", value: "A" });
  state = smartPracticeReducer(state, { type: "SUBMIT_REQUESTED" });
  const payload = {
    result: { correct: true, feedback: { key_principle: "判断正确。" } },
    question: question(2),
  };
  state = smartPracticeReducer(state, { type: "SUBMIT_SUCCEEDED", payload });
  state = smartPracticeReducer(state, { type: "SUBMIT_SUCCEEDED", payload });
  assert.equal(state.answeredCount, 1);
  assert.equal(state.attempts.length, 1);
});
