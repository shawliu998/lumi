import { HermesApiError, request } from "./hermesApi.js";
import { isCommandId } from "./publicLearningId.js";

const SCHEMA = "lumi.xingce-adaptive-session.v1";
const SUBTYPE_ID = /^xingce\.(verbal|quantitative|judgment|data_analysis|common|political)\.[a-z_]+$/;
const SESSION_ID = /^xa_[a-f0-9]{36}$/i;
const STAGES = new Set(["awaiting_probe", "awaiting_transfer", "completed", "completed_no_error"]);
const RECORD_ROLES = new Set(["entry_diagnostic", "routing_diagnostic", "probe", "teaching_asset", "independent_transfer", "delayed_review"]);
const UNSAFE_KEYS = new Set([
  "correct_option",
  "answer_spec",
  "candidate_misconception_ids",
  "route_probe_ids",
  "candidate_evidence_map",
  "record_sha256",
  "scorer",
  "policy",
  "content_evidence",
  "human_review_gate",
  "artifacts",
]);

export async function fetchXingceAdaptiveWorkspace(subtypeId) {
  const payload = await request(workspacePath(subtypeId));
  if (!isValidXingceAdaptiveWorkspace(payload, { subtypeId })) {
    throw new HermesApiError("本机题型工作台返回了不可信的数据，未展示题目。", {
      kind: "contract",
      code: "invalid_xingce_adaptive_workspace",
    });
  }
  return payload;
}

export async function startXingceAdaptiveSession({
  subtypeId,
  entryRecordId,
  selectedResponse,
  confidence,
  elapsedSeconds,
  rationale,
  commandId,
} = {}) {
  if (!isRecordId(entryRecordId)) throw clientError("当前题目记录不可用。", "invalid_xingce_adaptive_entry");
  if (rationale !== undefined && (typeof rationale !== "string" || rationale.length > 1200)) {
    throw clientError("补充过程最多 1200 个字符。", "invalid_xingce_adaptive_rationale");
  }
  const payload = await request(sessionPath(subtypeId), {
    method: "POST",
    body: {
      entry_record_id: entryRecordId,
      ...answerBody({ selectedResponse, confidence, elapsedSeconds, commandId }),
      ...(rationale?.trim() ? { rationale: rationale.trim() } : {}),
    },
  });
  assertSessionResult(payload, { subtypeId, stages: ["awaiting_probe", "completed_no_error"] });
  return payload;
}

export async function answerXingceAdaptiveProbe({ subtypeId, session, selectedResponse, confidence, elapsedSeconds, commandId } = {}) {
  assertContinuation(session, "awaiting_probe");
  const payload = await request(`${sessionPath(subtypeId)}/${encodeURIComponent(session.session_id)}/probe`, {
    method: "POST",
    body: { expected_version: session.state_version, ...answerBody({ selectedResponse, confidence, elapsedSeconds, commandId }) },
  });
  assertSessionResult(payload, { subtypeId, stages: ["awaiting_transfer"] });
  return payload;
}

export async function answerXingceAdaptiveTransfer({ subtypeId, session, selectedResponse, confidence, elapsedSeconds, commandId } = {}) {
  assertContinuation(session, "awaiting_transfer");
  const payload = await request(`${sessionPath(subtypeId)}/${encodeURIComponent(session.session_id)}/transfer`, {
    method: "POST",
    body: { expected_version: session.state_version, ...answerBody({ selectedResponse, confidence, elapsedSeconds, commandId }) },
  });
  assertSessionResult(payload, { subtypeId, stages: ["completed"] });
  return payload;
}

export async function fetchXingceAdaptiveReplay({ subtypeId, sessionId } = {}) {
  if (!isSubtypeId(subtypeId) || !SESSION_ID.test(sessionId || "")) {
    throw clientError("本机学习记录编号不可用。", "invalid_xingce_adaptive_replay_id");
  }
  const payload = await request(`${sessionPath(subtypeId)}/${encodeURIComponent(sessionId)}/replay`);
  if (!isValidXingceAdaptiveReplay(payload, { sessionId })) {
    throw new HermesApiError("本机回放不完整，未恢复学习步骤。", { kind: "contract", code: "invalid_xingce_adaptive_replay" });
  }
  return payload;
}

export function latestXingceAdaptiveSessionFromReplay(replay) {
  if (!isValidXingceAdaptiveReplay(replay, { sessionId: replay?.session_id })) {
    throw clientError("本机回放不能安全恢复当前学习步骤。", "invalid_xingce_adaptive_replay_resume");
  }
  const latest = replay.timeline.at(-1);
  const result = latest?.result;
  if (!result || result.stage !== latest.stage_after || !STAGES.has(result.stage)) {
    throw clientError("本机回放不能安全恢复当前学习步骤。", "invalid_xingce_adaptive_replay_resume");
  }
  assertSessionResult(result, { subtypeId: result?.pack?.subtype_id, stages: [...STAGES], allowPackOmission: true });
  return result;
}

export function isValidXingceAdaptiveWorkspace(workspace, { subtypeId } = {}) {
  if (!isSubtypeId(subtypeId) || !isSafe(workspace) || workspace?.schema_version !== SCHEMA || workspace?.available !== true || workspace?.local_only !== true) return false;
  const pack = workspace.pack;
  if (!pack || Object.keys(pack).length !== 5 || pack.subtype_id !== subtypeId || !isSafePack(pack)) return false;
  return Array.isArray(workspace.entry_items)
    && workspace.entry_items.length > 0
    && workspace.entry_items.every((record) => isValidXingceAdaptiveRecord(record, ["entry_diagnostic", "routing_diagnostic"]));
}

export function isValidXingceAdaptiveRecord(record, expectedRoles = RECORD_ROLES) {
  if (!isSafe(record) || !record || typeof record !== "object") return false;
  const roles = expectedRoles instanceof Set ? expectedRoles : new Set(expectedRoles);
  if (!roles.has(record.role) || !RECORD_ROLES.has(record.role) || !isRecordId(record.record_id) || !nonempty(record.title)) return false;
  if (record.role === "teaching_asset") {
    return exactKeys(record, ["record_id", "role", "title", "teaching_content"]) && nonempty(record.teaching_content);
  }
  if (!exactKeys(record, record.response_mode === "single_choice"
    ? ["record_id", "role", "title", "prompt", "response_mode", "options"]
    : ["record_id", "role", "title", "prompt", "response_mode"])) return false;
  if (!nonempty(record.prompt) || !["single_choice", "numeric"].includes(record.response_mode)) return false;
  if (record.response_mode === "numeric") return record.options === undefined;
  return Array.isArray(record.options)
    && record.options.length >= 2
    && record.options.every((option) => option && exactKeys(option, ["label", "text"]) && /^[A-Z]{1,4}$/.test(option.label || "") && nonempty(option.text));
}

export function isValidXingceAdaptiveReplay(replay, { sessionId } = {}) {
  if (!isSafe(replay) || !SESSION_ID.test(sessionId || "") || replay?.schema_version !== SCHEMA || replay?.session_id !== sessionId || replay?.trace_verified !== true || !Array.isArray(replay?.timeline) || replay.timeline.length < 1) return false;
  return replay.timeline.every((event, index) => (
    event && exactKeys(event, ["seq", "kind", "stage_after", "result"])
    && event.seq === index + 1
    && typeof event.kind === "string"
    && ["awaiting_probe", "awaiting_transfer", "committing_transfer", "completed", "completed_no_error"].includes(event.stage_after)
    && event.result && event.result.schema_version === SCHEMA
  ));
}

export function isValidXingceAdaptiveSessionResult(result, { subtypeId, stages = [...STAGES] } = {}) {
  try {
    assertSessionResult(result, { subtypeId, stages, allowPackOmission: !subtypeId });
    return true;
  } catch {
    return false;
  }
}

function assertSessionResult(result, { subtypeId, stages, allowPackOmission = false }) {
  if (!isSafe(result) || result?.schema_version !== SCHEMA || !SESSION_ID.test(result?.session_id || "") || !Number.isInteger(result?.state_version) || result.state_version < 1 || !stages.includes(result.stage)) {
    throw new HermesApiError("本机服务返回了不一致的行测学习步骤。", { kind: "contract", code: "invalid_xingce_adaptive_session" });
  }
  if (result.stage === "awaiting_probe") {
    if (!isObservedRecord(result.entry, ["entry_diagnostic", "routing_diagnostic"]) || !isValidXingceAdaptiveRecord(result.probe, ["probe"]) || !validCandidates(result.candidate_causes) || result.next_step !== "answer_probe") failResult("诊断步骤缺少可解释的本机证据。");
  }
  if (result.stage === "awaiting_transfer") {
    if (!isObservedRecord(result.probe, ["probe"]) || !isValidXingceAdaptiveRecord(result.transfer, ["independent_transfer"]) || !(result.teaching === null || isValidXingceAdaptiveRecord(result.teaching, ["teaching_asset"])) || result.next_step !== "answer_transfer") failResult("教学或迁移步骤不完整。");
  }
  if (result.stage === "completed") {
    if (!isCompletedTransfer(result.transfer) || !isStateUpdate(result.state_update) || !isReviewTask(result.review_task) || !["delayed_review", "independent_retry"].includes(result.next_step)) failResult("状态收据或复习任务不完整。");
  }
  if (result.stage === "completed_no_error") {
    if (!isObservedRecord(result.entry, ["entry_diagnostic", "routing_diagnostic"]) || result.entry.correct !== true || result.next_step !== "review_or_stop") failResult("无错分支不完整。");
  }
  if (!allowPackOmission && !isSubtypeId(subtypeId)) failResult("题型绑定不可用。");
}

function isObservedRecord(record, roles) {
  if (!record || typeof record !== "object" || !isSafe(record)) return false;
  const baseKeys = record.response_mode === "single_choice"
    ? ["record_id", "role", "title", "prompt", "response_mode", "options"]
    : ["record_id", "role", "title", "prompt", "response_mode"];
  const observedKeys = [...baseKeys, "selected_response", "correct"];
  if (record.role === "entry_diagnostic" || record.role === "routing_diagnostic") observedKeys.push("confidence", "elapsed_seconds");
  if (record.role === "probe") observedKeys.push("evidence_updates");
  const publicRecord = Object.fromEntries(baseKeys.filter((key) => key in record).map((key) => [key, record[key]]));
  return exactKeys(record, observedKeys)
    && isValidXingceAdaptiveRecord(publicRecord, roles)
    && validResponse(record.selected_response)
    && typeof record.correct === "boolean"
    && (record.confidence === undefined || validConfidence(record.confidence))
    && (record.elapsed_seconds === undefined || validElapsed(record.elapsed_seconds))
    && (record.evidence_updates === undefined || validEvidenceUpdates(record.evidence_updates));
}

function isCompletedTransfer(record) {
  return isObservedRecord(record, ["independent_transfer"]);
}

function validCandidates(rows) {
  return Array.isArray(rows) && rows.length >= 2 && rows.every((row, index) => (
    row && exactKeys(row, ["cause_id", "label", "status", "rank"])
    && isRecordId(row.cause_id)
    && nonempty(row.label)
    && row.status === "unconfirmed"
    && row.rank === index + 1
  ));
}

function validEvidenceUpdates(rows) {
  return Array.isArray(rows) && rows.length >= 1 && rows.every((row) => (
    row && exactKeys(row, ["cause_id", "label", "outcome", "status"])
    && isRecordId(row.cause_id)
    && nonempty(row.label)
    && ["support", "refute", "insufficient"].includes(row.outcome)
    && ["supported", "refuted", "unconfirmed"].includes(row.status)
  ));
}

function isStateUpdate(value) {
  return value && exactKeys(value, ["eligible", "reason", "receipts"])
    && typeof value.eligible === "boolean"
    && typeof value.reason === "string"
    && Array.isArray(value.receipts)
    && value.receipts.every((receipt) => receipt && exactKeys(receipt, ["skill_id", "state_version", "state_delta"])
      && isRecordId(receipt.skill_id)
      && Number.isInteger(receipt.state_version)
      && receipt.state_version >= 1
      && receipt.state_delta && receipt.state_delta.commit_status && typeof receipt.state_delta.commit_status === "string");
}

function isReviewTask(value) {
  return value && exactKeys(value, ["task_id", "kind", "due_on", "source_session_id", "item_selector", "success_criterion", "skip_consequence"])
    && isRecordId(value.task_id)
    && ["delayed_retention", "independent_retry"].includes(value.kind)
    && /^\d{4}-\d{2}-\d{2}$/.test(value.due_on || "")
    && SESSION_ID.test(value.source_session_id || "")
    && value.item_selector && exactKeys(value.item_selector, ["pack_id", "record_id"])
    && nonempty(value.item_selector.pack_id)
    && isRecordId(value.item_selector.record_id)
    && nonempty(value.success_criterion)
    && nonempty(value.skip_consequence);
}

function answerBody({ selectedResponse, confidence, elapsedSeconds, commandId } = {}) {
  if (!validResponse(selectedResponse) || !validConfidence(confidence) || !validElapsed(elapsedSeconds) || !isCommandId(commandId)) {
    throw clientError("请填写有效答案、作答信心与本机命令编号。", "invalid_xingce_adaptive_answer");
  }
  return {
    selected_response: selectedResponse.trim(),
    confidence: confidence.trim().toLowerCase(),
    elapsed_seconds: Math.max(0, Math.min(Number(elapsedSeconds), 7200)),
    command_id: commandId,
  };
}

function assertContinuation(session, expectedStage) {
  if (!session || !SESSION_ID.test(session.session_id || "") || !Number.isInteger(session.state_version) || session.stage !== expectedStage) {
    throw clientError("当前学习步骤已过期；请重新读取本机记录。", "invalid_xingce_adaptive_continuation");
  }
}

function workspacePath(subtypeId) {
  if (!isSubtypeId(subtypeId)) throw clientError("行测子型编号不可用。", "invalid_xingce_adaptive_subtype");
  return `/v1/xingce/adaptive/${encodeURIComponent(subtypeId)}/workspace`;
}

function sessionPath(subtypeId) {
  if (!isSubtypeId(subtypeId)) throw clientError("行测子型编号不可用。", "invalid_xingce_adaptive_subtype");
  return `/v1/xingce/adaptive/${encodeURIComponent(subtypeId)}/sessions`;
}

function isSafe(value) {
  if (!value || typeof value !== "object") return true;
  if (Array.isArray(value)) return value.every(isSafe);
  return Object.entries(value).every(([key, child]) => !UNSAFE_KEYS.has(key) && isSafe(child));
}

function isSafePack(pack) {
  return exactKeys(pack, ["pack_id", "pack_version", "subtype_id", "module_id", "form"])
    && nonempty(pack.pack_id)
    && nonempty(pack.pack_version)
    && isSubtypeId(pack.subtype_id)
    && ["verbal", "quantitative", "judgment", "data_analysis", "common_knowledge", "political_theory"].includes(pack.module_id)
    && ["text_mcq", "numeric_or_mcq", "visual_mcq", "material_mcq"].includes(pack.form);
}

function isSubtypeId(value) { return typeof value === "string" && SUBTYPE_ID.test(value); }
function isRecordId(value) { return typeof value === "string" && /^[A-Za-z][A-Za-z0-9_.:-]{0,120}$/.test(value); }
function validResponse(value) { return typeof value === "string" && value.trim().length >= 1 && value.trim().length <= 200; }
function validConfidence(value) { return typeof value === "string" && ["low", "medium", "high"].includes(value.trim().toLowerCase()); }
function validElapsed(value) { return Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 7200; }
function nonempty(value) { return typeof value === "string" && value.trim().length > 0; }
function exactKeys(value, keys) { return value && typeof value === "object" && Object.keys(value).length === keys.length && Object.keys(value).every((key) => keys.includes(key)); }
function clientError(message, code) { return new HermesApiError(message, { kind: "client", code }); }
function failResult(message) { throw new HermesApiError(message, { kind: "contract", code: "invalid_xingce_adaptive_session" }); }
