import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidJudgmentPublicRecord,
  isValidJudgmentRecentSession,
  isValidJudgmentWorkspaceContract,
  latestJudgmentSessionFromReplay,
} from "./hermesApi.js";

const entry = {
  record_id: "D01",
  role: "entry_diagnostic",
  title: "条件方向",
  prompt: "只有完成登记，才能领取工作牌。",
  response_mode: "single_choice",
  options: { A: "登记", B: "领取", C: "不知道", D: "都不是" },
};

const recent = {
  session_id: "jr_1234567890abcdef1234567890abcdef123456",
  stage: "completed_no_error",
  updated_at: "2026-07-13T04:45:24.500474+00:00",
  event_count: 1,
  entry: { record_id: "D01", title: "条件方向" },
  replay_available: true,
  resume_available: false,
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
    recent_sessions: [],
    next_step: "answer_entry",
    privacy: "local_only",
  }), true);
  assert.equal(isValidJudgmentWorkspaceContract({
    schema_version: "lumi.judgment-session.v1",
    available: true,
    pack: { pack_id: "lumi-conditional", pack_version: "0.1" },
    entry_items: [entry, { ...entry, record_id: "D02", role: "routing_diagnostic", title: "推理有效性" }],
    recent_sessions: [recent],
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
    recent_sessions: [],
    next_step: "answer_entry",
    privacy: "local_only",
  }), false);
});

test("recent-session index exposes no answer data and only resumes incomplete work", () => {
  assert.equal(isValidJudgmentRecentSession(recent), true);
  assert.equal(isValidJudgmentRecentSession({ ...recent, selected_option: "A" }), false);
  assert.equal(isValidJudgmentRecentSession({ ...recent, resume_available: true }), false);
  assert.equal(isValidJudgmentRecentSession({ ...recent, stage: "awaiting_probe", resume_available: true }), true);
});

test("a deliberate replay read can restore only the matching public local receipt", () => {
  const replay = {
    schema_version: "lumi.judgment-session.v1",
    session_id: recent.session_id,
    trace_verified: true,
    event_count: 1,
    timeline: [{
      seq: 1,
      kind: "judgment_entry_submitted",
      occurred_at: recent.updated_at,
      stage_after: "completed_no_error",
      result: {
        schema_version: "lumi.judgment-session.v1",
        session_id: recent.session_id,
        state_version: 1,
        stage: "completed_no_error",
      },
    }],
  };
  assert.equal(latestJudgmentSessionFromReplay(replay).stage, "completed_no_error");
  assert.throws(
    () => latestJudgmentSessionFromReplay({ ...replay, timeline: [{ ...replay.timeline[0], stage_after: "awaiting_probe" }] }),
    /不能安全恢复/,
  );
});
