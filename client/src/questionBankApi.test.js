import assert from "node:assert/strict";
import test from "node:test";

import {
  isValidQuestionBankAttempt,
  isValidQuestionBankList,
  isValidQuestionBankQuestion,
  isValidQuestionBankStatus,
} from "./questionBankApi.js";

const item = {
  question_id: "q_abc123",
  subtype_id: "xingce.verbal.logical_cloze",
  subtype_name: "逻辑填空",
  module: "言语理解与表达",
  year: 2025,
  region: "国考",
  paper_title: "2025 年行测题",
  question_number: 1,
  question_type: "single",
  stem_preview: "请选择最恰当的一项。",
  has_material: false,
  option_count: 4,
};

test("question-bank status distinguishes a verified local export from honest unavailability", () => {
  assert.equal(isValidQuestionBankStatus({
    schema_version: "lumi.xingce-question-bank-status.v1",
    available: true,
    status: "available",
    export: {
      export_id: "lumi-xingce-full-20260617-cleaned17-v1",
      export_version: "1",
      schema_version: "lumi.xingce-question-bank-export.v1",
      generated_at: "2026-07-14T00:00:00Z",
      counts: { total: 78179, ready: 77704, needs_review: 475 },
      access_counts: { direct_practice_ready: 60703, asset_gated: 17001 },
      subtypes: [{ subtype_id: "xingce.verbal.logical_cloze", name: "逻辑填空", ready_count: 100 }],
    },
    practice_contract: { mode: "practice_only", writes_learner_state: false },
  }), true);
  assert.equal(isValidQuestionBankStatus({
    schema_version: "lumi.xingce-question-bank-status.v1",
    available: false,
    status: "unavailable",
    reason: "local_export_not_installed",
  }), true);
});

test("question lists and unanswered details fail closed on answer leakage", () => {
  const list = {
    schema_version: "lumi.xingce-question-bank-list.v1",
    items: [item],
    pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
    filters: { subtype_id: "", q: "" },
  };
  assert.equal(isValidQuestionBankList(list), true);
  assert.equal(isValidQuestionBankList({ ...list, items: [{ ...item, answer: "A" }] }), false);

  const detail = {
    schema_version: "lumi.xingce-question-bank-question.v1",
    question: {
      ...item,
      material: "",
      stem: "请选择最恰当的一项。",
      options: [
        { label: "A", text: "甲" },
        { label: "B", text: "乙" },
      ],
      has_assets: false,
      assets: [],
      asset_delivery: "not_required",
    },
    attempt: { allowed: true, mode: "practice_only", writes_learner_state: false },
  };
  assert.equal(isValidQuestionBankQuestion(detail), true);
  assert.equal(isValidQuestionBankQuestion({ ...detail, question: { ...detail.question, explanation: "答案依据" } }), false);
  const assetGated = {
    ...detail,
    question: { ...detail.question, stem: "", material: "", has_assets: true, asset_delivery: "not_bundled" },
    attempt: { ...detail.attempt, allowed: false, reason: "asset_not_bundled" },
  };
  assert.equal(isValidQuestionBankQuestion(assetGated), true);
});

test("scored practice is explicit evidence-only and never claims a learner-state write", () => {
  const result = {
    schema_version: "lumi.xingce-question-bank-attempt.v1",
    attempt_id: "qba_abc123",
    command_id: `c_${"A".repeat(40)}`,
    question_id: "q_abc123",
    correct: true,
    selected_response: "A",
    answer: "A",
    explanation: "根据语境选择甲。",
    confidence: "high",
    elapsed_seconds: 12,
    evidence_proposal_only: true,
    learner_state_updated: false,
    created_at: "2026-07-14T00:00:00Z",
    idempotent_replay: false,
  };
  assert.equal(isValidQuestionBankAttempt(result), true);
  assert.equal(isValidQuestionBankAttempt({ ...result, learner_state_updated: true }), false);
});
