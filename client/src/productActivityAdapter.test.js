import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fetchProductActivityBundle } from "./hermesApi.js";
import {
  assertIndependentTransferBinding,
  normalizeProductActivity,
  normalizeProductActivityBundle,
} from "./productActivityAdapter.js";

const SIGNATURES = {
  first: "a".repeat(64),
  transfer: "b".repeat(64),
};

function activity({ id = "q_first", role = "first_answer", signature = SIGNATURES.first } = {}) {
  return {
    schema_version: "lumi.product-activity.v1",
    activity_id: id,
    release_id: "p031-data-analysis-v1",
    content_signature: signature,
    domain: "xingce",
    module: "资料分析",
    diagnostic_role: role,
    response_mode: "single_choice",
    material_text: "2024 年某指标为 120，同比增长 20%。",
    stem_text: "2023 年约为多少？",
    options: [
      { label: "A", text: "96" },
      { label: "B", text: "100" },
      { label: "C", text: "120" },
      { label: "D", text: "144" },
    ],
    source: {
      paper_title: "2024 年公务员录用考试《行测》题",
      year: 2024,
      question_no: 101,
      source_site: "local-source",
      source_url: "https://example.invalid/paper",
    },
    links: { self: `/v1/product-activities/${id}`, attempts: "/v1/attempts" },
  };
}

function listing(item) {
  return { count: 1, items: [item] };
}

test("safe projection normalizes only learner-visible activity fields", () => {
  const normalized = normalizeProductActivity(activity(), { expectedRole: "first_answer" });
  assert.equal(normalized.activityId, "q_first");
  assert.equal(normalized.contentSignature, SIGNATURES.first);
  assert.deepEqual(normalized.options.map((item) => item.label), ["A", "B", "C", "D"]);
  const serialized = JSON.stringify(normalized).toLowerCase();
  for (const forbidden of ["answer_labels", "correct_option", "explanation_text", "candidate_skills", "is_correct"]) {
    assert.doesNotMatch(serialized, new RegExp(forbidden));
  }
});

test("activity projection fails closed when any answer or scoring field leaks", () => {
  for (const privateField of [
    { answer_labels: "B" },
    { explanation_text: "解析" },
    { candidate_skills: [] },
    { scoring: { correct: "B" } },
  ]) {
    assert.throws(() => normalizeProductActivity({ ...activity(), ...privateField }), /private/);
  }
  const optionLeak = activity();
  optionLeak.options[1].is_correct = true;
  assert.throws(() => normalizeProductActivity(optionLeak), /private/);
});

test("bundle requires one first item and a genuinely different transfer item", () => {
  const transfer = activity({ id: "q_transfer", role: "independent_transfer", signature: SIGNATURES.transfer });
  const bundle = normalizeProductActivityBundle(listing(activity()), listing(transfer), { releaseId: "p031-data-analysis-v1" });
  assert.equal(bundle.firstAnswer.activityId, "q_first");
  assert.equal(bundle.independentTransfer.activityId, "q_transfer");
  assert.throws(
    () => normalizeProductActivityBundle(listing(activity()), listing(activity({ role: "independent_transfer" })), { releaseId: "p031-data-analysis-v1" }),
    /different item id/,
  );
});

test("transfer is writable only when server item id and content signature bind to projection", () => {
  const transfer = normalizeProductActivity(activity({ id: "q_transfer", role: "independent_transfer", signature: SIGNATURES.transfer }));
  const continuation = {
    teaching: {
      independent_verification_item: {
        item_id: "q_transfer",
        content_signature: SIGNATURES.transfer,
      },
    },
  };
  assert.equal(assertIndependentTransferBinding(continuation, transfer), transfer);
  assert.throws(() => assertIndependentTransferBinding({ teaching: {} }, transfer), /binding is missing/);
  assert.throws(() => assertIndependentTransferBinding({ teaching: { independent_verification_item: { ...continuation.teaching.independent_verification_item, item_id: "q_other" } } }, transfer), /item id mismatch/);
  assert.throws(() => assertIndependentTransferBinding({ teaching: { independent_verification_item: { ...continuation.teaching.independent_verification_item, content_signature: SIGNATURES.first } } }, transfer), /content signature mismatch/);
});

test("activity fetch uses an injectable local request interface and role-scoped paths", async () => {
  const paths = [];
  const requestImpl = async (path) => {
    paths.push(path);
    return path.includes("first_answer")
      ? listing(activity())
      : listing(activity({ id: "q_transfer", role: "independent_transfer", signature: SIGNATURES.transfer }));
  };
  const bundle = await fetchProductActivityBundle({ requestImpl });
  assert.equal(bundle.independentTransfer.activityId, "q_transfer");
  assert.deepEqual(paths.sort(), [
    "/v1/product-activities?release_id=p031-data-analysis-v1&diagnostic_role=first_answer",
    "/v1/product-activities?release_id=p031-data-analysis-v1&diagnostic_role=independent_transfer",
  ]);
});

test("real activity UI has no synthetic question fallback or pre-answer solution fields", () => {
  const app = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");
  const view = readFileSync(new URL("./ProductActivityViews.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(app, /某园区产值|13\.0%|growth-rate\.synthetic-01/);
  assert.match(app, /activityState\.bundle\.firstAnswer\.activityId/);
  assert.match(app, /候选 \/ 待验证/);
  assert.match(view, /activity\.materialText/);
  assert.match(view, /activity\.stemText/);
  assert.match(view, /activity\.options\.map/);
  assert.match(view, /补充作答过程（可选）/);
  assert.doesNotMatch(view, /activity\.(answer|explanation|correct)/);
});
