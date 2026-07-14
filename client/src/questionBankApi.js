import { HERMES_API_BASE, HermesApiError, request } from "./hermesApi.js";
import { createCommandId, isCommandId } from "./publicLearningId.js";

const STATUS_SCHEMA = "lumi.xingce-question-bank-status.v1";
const LIST_SCHEMA = "lumi.xingce-question-bank-list.v1";
const QUESTION_SCHEMA = "lumi.xingce-question-bank-question.v1";
const ATTEMPT_SCHEMA = "lumi.xingce-question-bank-attempt.v1";
const FORBIDDEN_BEFORE_ATTEMPT = new Set([
  "answer",
  "answer_labels",
  "correct",
  "correct_option",
  "correct_option_id",
  "correct_option_ids",
  "explanation",
  "explanation_text",
  "is_correct",
]);

export async function fetchQuestionBankStatus() {
  const payload = await request("/v1/xingce/question-bank");
  if (!isValidQuestionBankStatus(payload)) {
    throw contractError("完整题库状态无法验证，未读取本机题目。", "invalid_question_bank_status");
  }
  return payload;
}

export async function searchQuestionBank({ subtypeId = "", query = "", page = 1, pageSize = 20 } = {}) {
  const normalizedPage = positiveInteger(page, "页码");
  const normalizedPageSize = positiveInteger(pageSize, "每页题数");
  if (normalizedPageSize > 100) throw clientError("每页最多读取 100 道题。", "invalid_question_bank_page_size");
  if (typeof query !== "string" || query.length > 100) throw clientError("搜索内容最多 100 个字符。", "invalid_question_bank_query");
  if (typeof subtypeId !== "string" || subtypeId.length > 100) throw clientError("题型筛选不可用。", "invalid_question_bank_subtype");
  const params = new URLSearchParams({ page: String(normalizedPage), page_size: String(normalizedPageSize) });
  if (subtypeId) params.set("subtype_id", subtypeId);
  if (query.trim()) params.set("q", query.trim());
  const payload = await request(`/v1/xingce/question-bank/questions?${params}`);
  if (!isValidQuestionBankList(payload)) {
    throw contractError("题目列表不完整，未展示可能泄露答案的数据。", "invalid_question_bank_list");
  }
  return payload;
}

export async function fetchQuestionBankQuestion(questionId) {
  assertQuestionId(questionId);
  const payload = await request(`/v1/xingce/question-bank/questions/${encodeURIComponent(questionId)}`);
  if (!isValidQuestionBankQuestion(payload)) {
    throw contractError("题目内容未通过本机合同校验。", "invalid_question_bank_question");
  }
  return payload;
}

export async function submitQuestionBankAttempt({
  questionId,
  selectedResponse,
  confidence,
  elapsedSeconds,
  commandId = createCommandId(),
} = {}) {
  assertQuestionId(questionId);
  if (typeof selectedResponse !== "string" || !selectedResponse.trim() || selectedResponse.length > 64) {
    throw clientError("请选择或填写有效答案。", "invalid_question_bank_response");
  }
  if (!["low", "medium", "high"].includes(confidence)) {
    throw clientError("请选择作答信心。", "invalid_question_bank_confidence");
  }
  if (!Number.isFinite(Number(elapsedSeconds)) || Number(elapsedSeconds) < 0 || Number(elapsedSeconds) > 7200) {
    throw clientError("作答用时不可用。", "invalid_question_bank_elapsed");
  }
  if (!isCommandId(commandId)) throw clientError("本机提交编号不可用。", "invalid_question_bank_command");
  const payload = await request(`/v1/xingce/question-bank/questions/${encodeURIComponent(questionId)}/attempts`, {
    method: "POST",
    body: {
      selected_response: selectedResponse.trim(),
      confidence,
      elapsed_seconds: Number(elapsedSeconds),
      command_id: commandId,
    },
  });
  if (!isValidQuestionBankAttempt(payload, { questionId, commandId })) {
    throw contractError("评分结果缺少练习边界或可信答案。", "invalid_question_bank_attempt");
  }
  return payload;
}

export function questionBankAssetUrl(asset) {
  if (!validQuestionAsset(asset)) {
    throw contractError("离线图片地址未通过本机合同校验。", "invalid_question_bank_asset");
  }
  return `${HERMES_API_BASE}${asset.path}`;
}

export function isValidQuestionBankStatus(payload) {
  if (!plainObject(payload) || payload.schema_version !== STATUS_SCHEMA || typeof payload.available !== "boolean") return false;
  if (!payload.available) {
    return payload.status === "unavailable" && nonempty(payload.reason) && payload.export === undefined;
  }
  const value = payload.export;
  return payload.status === "available"
    && plainObject(value)
    && nonempty(value.export_id)
    && nonempty(value.export_version)
    && nonempty(value.schema_version)
    && nonempty(value.generated_at)
    && validCounts(value.counts)
    && validAccessCounts(value.access_counts, value.counts.ready)
    && Array.isArray(value.subtypes)
    && value.subtypes.every((row) => plainObject(row)
      && nonempty(row.subtype_id)
      && nonempty(row.name)
      && Number.isInteger(row.ready_count)
      && row.ready_count >= 0)
    && validOfflineAssetStatus(value.offline_assets)
    && payload.practice_contract?.mode === "practice_only"
    && payload.practice_contract?.writes_learner_state === false;
}

export function isValidQuestionBankList(payload) {
  if (!plainObject(payload) || payload.schema_version !== LIST_SCHEMA || containsForbidden(payload)) return false;
  const pagination = payload.pagination;
  return Array.isArray(payload.items)
    && payload.items.every(validListItem)
    && plainObject(pagination)
    && ["page", "page_size", "total_items", "total_pages"].every((key) => Number.isInteger(pagination[key]) && pagination[key] >= (key === "page" || key === "page_size" ? 1 : 0))
    && plainObject(payload.filters)
    && typeof payload.filters.subtype_id === "string"
    && typeof payload.filters.q === "string";
}

export function isValidQuestionBankQuestion(payload) {
  if (!plainObject(payload) || payload.schema_version !== QUESTION_SCHEMA || containsForbidden(payload)) return false;
  const question = payload.question;
  const attempt = payload.attempt;
  return validListItem(question)
    && typeof question.material === "string"
    && typeof question.stem === "string"
    && (attempt?.allowed
      ? (nonempty(question.stem) || nonempty(question.material))
      : question.has_assets === true && question.asset_delivery === "not_bundled")
    && Array.isArray(question.options)
    && question.options.length >= 2
    && question.options.every((option) => plainObject(option) && /^[A-Z]{1,4}$/.test(option.label || "") && nonempty(option.text))
    && Array.isArray(question.assets)
    && question.assets.every(validQuestionAsset)
    && typeof question.has_assets === "boolean"
    && ["not_required", "not_bundled", "bundled"].includes(question.asset_delivery)
    && plainObject(attempt)
    && typeof attempt.allowed === "boolean"
    && attempt.mode === "practice_only"
    && attempt.writes_learner_state === false
    && nonempty(attempt.asset_dependency_state)
    && (attempt.allowed ? attempt.reason === undefined : attempt.reason === "asset_not_bundled")
    && (question.asset_delivery === "bundled" ? attempt.allowed && question.assets.length > 0 : true)
    && (question.asset_delivery === "not_bundled" ? !attempt.allowed && question.assets.length === 0 : true)
    && (question.asset_delivery === "not_required" ? question.assets.length === 0 : true);
}

export function isValidQuestionBankAttempt(payload, { questionId = payload?.question_id, commandId = payload?.command_id } = {}) {
  return plainObject(payload)
    && payload.schema_version === ATTEMPT_SCHEMA
    && payload.question_id === questionId
    && payload.command_id === commandId
    && nonempty(payload.attempt_id)
    && typeof payload.correct === "boolean"
    && nonempty(payload.selected_response)
    && nonempty(payload.answer)
    && typeof payload.explanation === "string"
    && ["low", "medium", "high"].includes(payload.confidence)
    && Number.isFinite(payload.elapsed_seconds)
    && payload.elapsed_seconds >= 0
    && payload.evidence_proposal_only === true
    && payload.learner_state_updated === false
    && nonempty(payload.created_at)
    && typeof payload.idempotent_replay === "boolean"
    && ["not_required", "text_only"].includes(payload.explanation_media_status);
}

function validOfflineAssetStatus(value) {
  if (!plainObject(value) || value.schema_version !== "lumi.xingce-question-assets-status.v1" || typeof value.available !== "boolean") return false;
  if (!value.available) return value.status === "unavailable" && nonempty(value.reason);
  const counts = value.counts;
  return value.status === "available"
    && nonempty(value.export_id)
    && nonempty(value.export_version)
    && value.implicit_network_fetch === false
    && plainObject(counts)
    && Number.isInteger(counts.flagged_asset_questions)
    && Number.isInteger(counts.attempt_unlocked)
    && Number.isInteger(counts.attempt_blocked)
    && counts.attempt_unlocked >= 0
    && counts.attempt_blocked >= 0
    && counts.attempt_unlocked + counts.attempt_blocked === counts.flagged_asset_questions;
}

function validQuestionAsset(asset) {
  return plainObject(asset)
    && /^[A-Za-z0-9._:-]{1,128}$/.test(asset.asset_id || "")
    && /^[0-9a-f]{64}$/.test(asset.content_sha256 || "")
    && ["image/png", "image/jpeg", "image/gif", "image/webp"].includes(asset.media_type)
    && /^\/v1\/xingce\/question-bank\/assets\/[A-Za-z0-9._:-]{1,128}$/.test(asset.path || "")
    && Array.isArray(asset.placements)
    && asset.placements.length >= 1
    && asset.placements.every((placement) => plainObject(placement)
      && ["material", "stem", "requirement", "option"].includes(placement.placement)
      && typeof placement.option_label === "string"
      && (placement.placement === "option" ? /^[A-Z]{1,4}$/.test(placement.option_label) : placement.option_label === ""));
}

function validListItem(row) {
  return plainObject(row)
    && /^q_[a-zA-Z0-9]+$/.test(row.question_id || "")
    && nonempty(row.subtype_id)
    && nonempty(row.subtype_name)
    && typeof row.module === "string"
    && (row.year === null || Number.isInteger(row.year))
    && typeof row.region === "string"
    && nonempty(row.paper_title)
    && (row.question_number === null || Number.isInteger(row.question_number))
    && nonempty(row.question_type)
    && nonempty(row.stem_preview)
    && typeof row.has_material === "boolean"
    && Number.isInteger(row.option_count)
    && row.option_count >= 0;
}

function validAccessCounts(value, ready) {
  return plainObject(value)
    && Number.isInteger(value.direct_practice_ready)
    && Number.isInteger(value.asset_gated)
    && value.direct_practice_ready >= 0
    && value.asset_gated >= 0
    && value.direct_practice_ready + value.asset_gated === ready;
}

function validCounts(value) {
  return plainObject(value)
    && Number.isInteger(value.total)
    && Number.isInteger(value.ready)
    && Number.isInteger(value.needs_review)
    && value.total >= 1
    && value.ready >= 1
    && value.needs_review >= 0
    && value.ready + value.needs_review === value.total;
}

function containsForbidden(value) {
  if (Array.isArray(value)) return value.some(containsForbidden);
  if (!plainObject(value)) return false;
  return Object.entries(value).some(([key, child]) => FORBIDDEN_BEFORE_ATTEMPT.has(key) || containsForbidden(child));
}

function assertQuestionId(value) {
  if (typeof value !== "string" || !/^q_[a-zA-Z0-9]+$/.test(value)) {
    throw clientError("题目编号不可用。", "invalid_question_bank_question_id");
  }
}

function positiveInteger(value, label) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1) throw clientError(`${label}不可用。`, "invalid_question_bank_pagination");
  return number;
}

function plainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonempty(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function contractError(message, code) {
  return new HermesApiError(message, { kind: "contract", code });
}

function clientError(message, code) {
  return new HermesApiError(message, { kind: "client", code });
}
