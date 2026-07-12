import test from "node:test";
import assert from "node:assert/strict";
import {
  candidateStatusCopy,
  judgmentFormReadiness,
  reviewTaskCopy,
  stageProgress,
} from "./judgmentWorkspaceAdapter.js";

test("judgment form remains disabled until a learner deliberately supplies answer and confidence", () => {
  assert.deepEqual(judgmentFormReadiness({}), { ready: false, reason: "请选择一个答案后再提交。" });
  assert.deepEqual(judgmentFormReadiness({ selectedOption: "B" }), { ready: false, reason: "请选择作答信心后再提交。" });
  assert.equal(judgmentFormReadiness({ selectedOption: "B", confidence: "medium" }).ready, true);
  assert.equal(judgmentFormReadiness({ selectedOption: "B", confidence: "medium", inFlight: true }).ready, false);
});

test("candidate and review copy preserve uncertainty and explicit skip consequence", () => {
  assert.equal(candidateStatusCopy("supported"), "有支持证据，仍待后续验证");
  assert.match(candidateStatusCopy("unconfirmed"), /未确认/);
  assert.deepEqual(reviewTaskCopy({
    kind: "delayed_retention",
    due_on: "2026-07-15",
    success_criterion: "独立作答",
    skip_consequence: "不会自动提高掌握状态。",
  }), {
    title: "延后保持性复习",
    dueOn: "2026-07-15",
    criterion: "独立作答",
    consequence: "不会自动提高掌握状态。",
  });
  assert.equal(stageProgress("awaiting_transfer"), 4);
});
