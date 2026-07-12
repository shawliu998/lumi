import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizeCompletedLearningResult,
  masteryCommitSummary,
  probeChoicesFromPrompt,
  probeEvidenceSummary,
  reviewCommitSummary,
} from "./learningResultAdapter.js";

const prompt = "已知现期量和增长率，你会用“现期量÷（1＋增长率）”还是“现期量×（1＋增长率）”？请选择。";

function continuation(overrides = {}) {
  return {
    state: "completed",
    teaching: { based_on: { probe_assessment: { assessments: [
      { evidence_direction: "insufficient_or_mixed" },
      { evidence_direction: "insufficient_or_mixed" },
    ] } } },
    verification: { provenance: { verification_attempt: {
      selected_option: "A", correct: false, independently_answered: true,
    } } },
    mastery_update: null,
    mastery_commit: {
      status: "withheld", reason_code: "failed_verification",
      skill_id: "xingce.data.base", previous_mastery: 0.3, new_mastery: 0.3, mastery_delta: 0,
    },
    reflection: { next_action: "schedule_targeted_retry" },
    review_schedule_commit: { status: "retry_required", code: "review_schedule_commit_failed", retryable: true },
    ...overrides,
  };
}

test("authored either-or probe becomes two explicit choices without inventing options", () => {
  assert.deepEqual(probeChoicesFromPrompt(prompt).map((item) => item.value), [
    "现期量÷（1＋增长率）", "现期量×（1＋增长率）",
  ]);
  assert.deepEqual(probeChoicesFromPrompt("请写出你的公式。"), []);
});

test("mixed probe evidence is explicitly presented as inconclusive", () => {
  const summary = probeEvidenceSummary(continuation());
  assert.equal(summary.status, "insufficient");
  assert.match(summary.detail, /候选.*不代表.*确认/);
});

test("failed independent transfer keeps both answers and explains withheld KT", () => {
  const result = normalizeCompletedLearningResult({
    attempt: { score: { passed: false, observations: [{ kind: "response", observation_id: "selected_option", value: "A" }] } },
    continuation: continuation(),
    firstActivity: { materialText: "首题材料", stemText: "首题题干" },
    transferActivity: { materialText: "迁移题材料", stemText: "迁移题题干" },
  });
  assert.deepEqual(result.initial, { material: "首题材料", title: "首题题干", answer: "A", correct: false });
  assert.deepEqual(result.transfer, { material: "迁移题材料", title: "迁移题题干", answer: "A", correct: false, independentlyAnswered: true });
  assert.equal(result.mastery.status, "withheld");
  assert.match(result.mastery.detail, /掌握状态保持不变/);
  assert.equal(result.review.status, "retry-required");
});

test("committed review receipt requires and presents real task details", () => {
  const summary = reviewCommitSummary({ status: "committed", created: true, task: {
    reason: "独立迁移未通过，安排短复习。", expected_duration_minutes: 6, success_criterion: "独立答对一题",
  } });
  assert.equal(summary.status, "committed");
  assert.match(summary.detail, /6 分钟.*独立答对一题/);
  assert.throws(() => reviewCommitSummary({ status: "mystery" }), /unsupported/);
});

test("mastery receipt distinguishes every withheld reason and rejects missing receipts", () => {
  const base = { status: "withheld", skill_id: "xingce.data.base", previous_mastery: 0.3, new_mastery: 0.3, mastery_delta: 0 };
  assert.match(masteryCommitSummary({ ...base, reason_code: "failed_verification" }).detail, /未通过/);
  assert.match(masteryCommitSummary({ ...base, reason_code: "assisted_verification" }).detail, /使用了帮助/);
  assert.match(masteryCommitSummary({ ...base, reason_code: "inconclusive_verification" }).detail, /证据不足/);
  assert.throws(() => masteryCommitSummary(null), /required/);
  assert.throws(() => masteryCommitSummary({ ...base, reason_code: "unknown" }), /unsupported/);
});
