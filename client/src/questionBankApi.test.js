import assert from "node:assert/strict";
import test from "node:test";

import {
  isValidQuestionBankAttempt,
  isValidQuestionBankList,
  isValidQuestionBankPapers,
  isValidQuestionBankQuestion,
  isValidQuestionBankStatus,
  questionBankAssetUrl,
} from "./questionBankApi.js";

const item = {
  question_id: "q_abc123",
  subtype_id: "xingce.verbal.logical_cloze",
  subtype_name: "逻辑填空",
  module_id: "verbal",
  paper_id: "paper_abc123",
  module: "言语理解与表达",
  year: 2025,
  region: "国考",
  exam_type: "国考",
  paper_title: "2025 年行测题",
  question_number: 1,
  question_type: "single",
  stem_preview: "请选择最恰当的一项。",
  has_material: false,
  option_count: 4,
};

test("question-bank status distinguishes a verified local export from honest unavailability", () => {
  assert.equal(isValidQuestionBankStatus({
    schema_version: "lumi.xingce-question-bank-status.v2",
    available: true,
    status: "available",
    export: {
      export_id: "lumi-xingce-cleaned17-v2",
      export_version: "cleaned17-v2",
      schema_version: "lumi.xingce-question-bank-export.v1",
      generated_at: "2026-07-14T00:00:00Z",
      counts: { total: 78179, ready: 77695, needs_review: 484 },
      access_counts: { direct_practice_ready: 68321, asset_gated: 9374 },
      subtypes: [{ subtype_id: "xingce.verbal.logical_cloze", name: "逻辑填空", ready_count: 100 }],
      facets: {
        years: [{ value: 2025, ready_count: 77695 }],
        regions: [{ value: "国考", ready_count: 77695 }],
        exam_types: [{ value: "国考", ready_count: 77695 }],
        modules: [
          { module_id: "verbal", name: "言语理解", ready_count: 28569 },
          { module_id: "unclassified", name: "未分类", ready_count: 49126 },
        ],
        knowledge_points: [
          { subtype_id: "xingce.verbal.logical_cloze", module_id: "verbal", name: "逻辑填空", ready_count: 3496 },
        ],
      },
      offline_assets: {
        schema_version: "lumi.xingce-question-assets-status.v1",
        available: true,
        status: "available",
        export_id: "lumi-xingce-assets-cleaned17-v2-local-assets-v1",
        export_version: "cleaned17-v2-local-assets-v1",
        counts: { flagged_asset_questions: 16999, attempt_unlocked: 7625, attempt_blocked: 9374 },
        implicit_network_fetch: false,
      },
    },
    practice_contract: { mode: "practice_only", writes_learner_state: false },
  }), true);
  assert.equal(isValidQuestionBankStatus({
    schema_version: "lumi.xingce-question-bank-status.v2",
    available: false,
    status: "unavailable",
    reason: "local_export_not_installed",
  }), true);
});

test("question lists and unanswered details fail closed on answer leakage", () => {
  const list = {
    schema_version: "lumi.xingce-question-bank-list.v2",
    items: [item],
    pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
    filters: { subtype_id: "", module_id: "", paper_id: "", year: null, region: "", exam_type: "", q: "" },
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
    attempt: { allowed: true, mode: "practice_only", writes_learner_state: false, asset_dependency_state: "not_required" },
  };
  assert.equal(isValidQuestionBankQuestion(detail), true);
  assert.equal(isValidQuestionBankQuestion({ ...detail, question: { ...detail.question, explanation: "答案依据" } }), false);
  const assetGated = {
    ...detail,
    question: { ...detail.question, stem: "", material: "", has_assets: true, asset_delivery: "not_bundled" },
    attempt: { ...detail.attempt, allowed: false, reason: "asset_not_bundled", asset_dependency_state: "required_remote" },
  };
  assert.equal(isValidQuestionBankQuestion(assetGated), true);
});

test("paper catalog requires exact, answer-safe whole-paper metadata", () => {
  const payload = {
    schema_version: "lumi.xingce-question-bank-paper-list.v1",
    items: [{
      paper_id: "paper_abc123",
      title: "2025 年国家公务员录用考试《行测》",
      year: 2025,
      region: "国考",
      exam_type: "国考",
      source_question_count: 130,
      ready_question_count: 130,
      asset_flagged_question_count: 6,
      all_collected_records_ready: true,
      sequence_status: "source_order_unique",
      paper_practice_available: true,
      official_completeness: "unknown",
      has_full_explanations: true,
    }],
    pagination: { page: 1, page_size: 24, total_items: 1, total_pages: 1 },
    filters: { year: 2025, region: "国考", exam_type: "国考", q: "" },
  };
  assert.equal(isValidQuestionBankPapers(payload), true);
  assert.equal(isValidQuestionBankPapers({ ...payload, items: [{ ...payload.items[0], answer: "A" }] }), false);
  assert.equal(isValidQuestionBankPapers({ ...payload, items: [{ ...payload.items[0], ready_question_count: 129 }] }), false);
  assert.equal(isValidQuestionBankPapers({ ...payload, items: [{ ...payload.items[0], sequence_status: "source_order_unavailable" }] }), false);
});

test("bundled assets use opaque loopback paths and reject source paths or URLs", () => {
  const asset = {
    asset_id: "asset_ab12",
    content_sha256: "a".repeat(64),
    media_type: "image/png",
    path: "/v1/xingce/question-bank/assets/asset_ab12",
    placements: [{ placement: "stem", option_label: "" }],
  };
  const detail = {
    schema_version: "lumi.xingce-question-bank-question.v1",
    question: {
      ...item,
      material: "",
      stem: "请根据图表选择。",
      options: [{ label: "A", text: "甲" }, { label: "B", text: "乙" }],
      has_assets: true,
      assets: [asset],
      asset_delivery: "bundled",
    },
    attempt: {
      allowed: true,
      mode: "practice_only",
      writes_learner_state: false,
      asset_dependency_state: "bundled_complete",
    },
  };
  assert.equal(isValidQuestionBankQuestion(detail), true);
  assert.match(questionBankAssetUrl(asset), /^http:\/\/127\.0\.0\.1:\d+\/v1\/xingce\/question-bank\/assets\/asset_ab12$/);
  assert.equal(isValidQuestionBankQuestion({
    ...detail,
    question: { ...detail.question, assets: [{ ...asset, path: "/Users/a1-6/source.png" }] },
  }), false);
  assert.equal(isValidQuestionBankQuestion({
    ...detail,
    question: { ...detail.question, assets: [{ ...asset, path: "https://example.com/source.png" }] },
  }), false);
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
    explanation_media_status: "not_required",
  };
  assert.equal(isValidQuestionBankAttempt(result), true);
  assert.equal(isValidQuestionBankAttempt({ ...result, learner_state_updated: true }), false);
});
