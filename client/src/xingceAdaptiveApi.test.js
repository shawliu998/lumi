import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidXingceAdaptiveRecord,
  isValidXingceAdaptiveReplay,
  isValidXingceAdaptiveSessionResult,
  isValidXingceAdaptiveWorkspace,
  latestXingceAdaptiveSessionFromReplay,
} from "./xingceAdaptiveApi.js";

const subtypeId = "xingce.verbal.logical_cloze";
const sessionId = `xa_${"a".repeat(36)}`;
const entry = {
  record_id: "D01",
  role: "entry_diagnostic",
  title: "逻辑填空",
  prompt: "结论必须以数据为____。",
  response_mode: "single_choice",
  options: [{ label: "A", text: "依据" }, { label: "B", text: "结果" }],
};
const probe = {
  record_id: "P01",
  role: "probe",
  title: "最小探查",
  prompt: "不是为了限制，____为了协作。",
  response_mode: "single_choice",
  options: [{ label: "A", text: "而是" }, { label: "B", text: "因此" }],
};
const transfer = {
  record_id: "V01",
  role: "independent_transfer",
  title: "无提示迁移",
  prompt: "先确定范围，____比较结果。",
  response_mode: "single_choice",
  options: [{ label: "A", text: "然后" }, { label: "B", text: "即使" }],
};
const tableMaterial = {
  kind: "table", title: "季度服务量", columns: ["季度", "服务量（件）"],
  rows: [["一季度", 120], ["二季度", 180]], scope_note: "单位：件；范围：本市样例。",
};
const diagramMaterial = {
  kind: "diagram", title: "点阵序列", alt_text: "第一图一个实心圆，第二图两个实心圆。",
  panels: [{ label: "图一", tokens: ["●"] }, { label: "图二", tokens: ["●", "●"] }],
};
const causes = [
  { cause_id: "M-SC", label: "候选：忽略词义或搭配约束", status: "unconfirmed", rank: 1 },
  { cause_id: "M-CR", label: "候选：误判上下文逻辑关系", status: "unconfirmed", rank: 2 },
];

test("generic Xingce workspace accepts only a reviewed public projection bound to its subtype", () => {
  const workspace = {
    schema_version: "lumi.xingce-adaptive-session.v1",
    available: true,
    local_only: true,
    pack: { pack_id: "lumi-logical-cloze", pack_version: "0.1.0", subtype_id: subtypeId, module_id: "verbal", form: "text_mcq" },
    entry_items: [entry],
  };
  assert.equal(isValidXingceAdaptiveWorkspace(workspace, { subtypeId }), true);
  const reviewedTable = {
    ...workspace,
    pack: { pack_id: "lumi-table-material", pack_version: "0.1.0", subtype_id: "xingce.data.table_material", module_id: "data_analysis", form: "material_mcq" },
    entry_items: [{ ...entry, source_material: tableMaterial }],
  };
  assert.equal(isValidXingceAdaptiveWorkspace(reviewedTable, { subtypeId: "xingce.data.table_material" }), true);
  assert.equal(isValidXingceAdaptiveWorkspace({ ...workspace, pack: { ...workspace.pack, subtype_id: "xingce.verbal.main_idea" } }, { subtypeId }), false);
  assert.equal(isValidXingceAdaptiveWorkspace({ ...workspace, entry_items: [{ ...entry, correct_option: "A" }] }, { subtypeId }), false);
});

test("generic records support both public choice and numeric forms but never scorer fields", () => {
  assert.equal(isValidXingceAdaptiveRecord(entry, ["entry_diagnostic"]), true);
  assert.equal(isValidXingceAdaptiveRecord({ record_id: "D02", role: "entry_diagnostic", title: "数字推理", prompt: "1，2，3，____", response_mode: "numeric" }, ["entry_diagnostic"]), true);
  assert.equal(isValidXingceAdaptiveRecord({ ...entry, answer_spec: { target: 12 } }, ["entry_diagnostic"]), false);
  assert.equal(isValidXingceAdaptiveRecord({ ...entry, source_material: tableMaterial }, ["entry_diagnostic"]), true);
  assert.equal(isValidXingceAdaptiveRecord({ ...entry, source_material: diagramMaterial }, ["entry_diagnostic"]), true);
  assert.equal(isValidXingceAdaptiveRecord({ ...entry, source_material: { ...tableMaterial, answer_key: "A" } }, ["entry_diagnostic"]), false);
});

test("candidate labels are learner-visible hypotheses while internal routing remains rejected", () => {
  const awaitingProbe = {
    schema_version: "lumi.xingce-adaptive-session.v1",
    session_id: sessionId,
    state_version: 1,
    stage: "awaiting_probe",
    entry: { ...entry, selected_response: "B", correct: false, confidence: "medium", elapsed_seconds: 12 },
    candidate_causes: causes,
    probe,
    next_step: "answer_probe",
  };
  assert.equal(isValidXingceAdaptiveSessionResult(awaitingProbe, { subtypeId, stages: ["awaiting_probe"] }), true);
  assert.equal(isValidXingceAdaptiveSessionResult({ ...awaitingProbe, candidate_causes: [{ ...causes[0], route_probe_ids: ["P01"] }, causes[1]] }, { subtypeId, stages: ["awaiting_probe"] }), false);
});

test("replay restores only public, trace-verified generic learning states", () => {
  const completed = {
    schema_version: "lumi.xingce-adaptive-session.v1",
    session_id: sessionId,
    state_version: 4,
    stage: "completed",
    transfer: { ...transfer, selected_response: "A", correct: true },
    state_update: {
      eligible: true,
      reason: "unseen_unassisted_transfer_passed",
      receipts: [{ skill_id: "xingce.verbal.logical_cloze.context_relation", state_version: 1, state_delta: { commit_status: "committed" } }],
    },
    review_task: {
      task_id: "xrt_a1",
      kind: "delayed_retention",
      due_on: "2026-07-16",
      source_session_id: sessionId,
      item_selector: { pack_id: "lumi-logical-cloze", record_id: "R01" },
      success_criterion: "无提示作答",
      skip_consequence: "不提高掌握状态。",
    },
    next_step: "delayed_review",
  };
  const replay = {
    schema_version: "lumi.xingce-adaptive-session.v1",
    session_id: sessionId,
    trace_verified: true,
    timeline: [
      { seq: 1, kind: "xingce_adaptive_entry", stage_after: "awaiting_probe", result: { schema_version: "lumi.xingce-adaptive-session.v1" } },
      { seq: 2, kind: "xingce_adaptive_probe", stage_after: "awaiting_transfer", result: { schema_version: "lumi.xingce-adaptive-session.v1" } },
      { seq: 3, kind: "xingce_adaptive_transfer", stage_after: "committing_transfer", result: { schema_version: "lumi.xingce-adaptive-session.v1" } },
      { seq: 4, kind: "xingce_adaptive_receipt", stage_after: "completed", result: completed },
    ],
  };
  assert.equal(isValidXingceAdaptiveReplay(replay, { sessionId }), true);
  assert.equal(latestXingceAdaptiveSessionFromReplay(replay).stage, "completed");
  assert.equal(isValidXingceAdaptiveReplay({ ...replay, timeline: [...replay.timeline.slice(0, -1), { ...replay.timeline.at(-1), result: { ...completed, correct_option: "A" } }] }, { sessionId }), false);
});
