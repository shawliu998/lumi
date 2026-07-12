import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidJudgmentPublicRecord,
  isValidJudgmentWorkspaceContract,
} from "./hermesApi.js";

const entry = {
  record_id: "D01",
  role: "entry_diagnostic",
  title: "条件方向",
  prompt: "只有完成登记，才能领取工作牌。",
  response_mode: "single_choice",
  options: { A: "登记", B: "领取", C: "不知道", D: "都不是" },
};

test("judgment workspace accepts only an honest review gate or public local entry projection", () => {
  assert.equal(isValidJudgmentWorkspaceContract({
    schema_version: "lumi.judgment-workspace.v1",
    available: false,
    reason: "content_review_required",
    message: "尚待逻辑与编辑/权属审核。",
  }), true);
  assert.equal(isValidJudgmentWorkspaceContract({
    schema_version: "lumi.judgment-session.v1",
    available: true,
    pack: { pack_id: "lumi-conditional", pack_version: "0.1" },
    entry_items: [entry],
    next_step: "answer_entry",
    privacy: "local_only",
  }), true);
  assert.equal(isValidJudgmentWorkspaceContract({
    schema_version: "lumi.judgment-session.v1",
    available: true,
    pack: { pack_id: "lumi-conditional", pack_version: "0.1" },
    entry_items: [entry, { ...entry, record_id: "D02", role: "routing_diagnostic", title: "推理有效性" }],
    next_step: "answer_entry",
    privacy: "local_only",
  }), true);
});

test("judgment workspace refuses answer keys and internal route metadata before rendering", () => {
  assert.equal(isValidJudgmentPublicRecord({ ...entry, correct_option: "A" }, "entry_diagnostic"), false);
  assert.equal(isValidJudgmentPublicRecord({ ...entry, formalization: "B -> A" }, "entry_diagnostic"), false);
  assert.equal(isValidJudgmentWorkspaceContract({
    schema_version: "lumi.judgment-session.v1",
    available: true,
    pack: { pack_id: "lumi-conditional", pack_version: "0.1" },
    entry_items: [{ ...entry, distractor_map: { B: "reverse" } }],
    next_step: "answer_entry",
    privacy: "local_only",
  }), false);
});
