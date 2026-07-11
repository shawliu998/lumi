import { createCommandId, isCommandId } from "./publicLearningId.js";

const PACK_ID = /^p_[A-P]{40}$/;
const DOCUMENT_ID = /^d_[A-P]{40}$/;
const SPAN_ID = /^s_[A-P]{40}$/;
const ARTIFACT_ID = /^a_[A-P]{40}$/;
const ATTEMPT_ID = /^t_[A-P]{40}$/;
const DECISION_ID = /^v_[A-P]{40}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const LIFECYCLES = new Set(["draft", "review", "published", "quarantined"]);
const ARTIFACT_TYPES = new Set([
  "study_pack.one_page_notes",
  "study_pack.knowledge_card",
  "study_pack.practice_item",
  "study_pack.review_task",
]);
const ITEM_KINDS = new Set(["cloze_exact_v1", "normalized_exact_v1"]);
const HUMAN_ORIGIN = "human_local_interactive";
const ACTIVITY_KIND = "within_pack_practice";

const LIST_KEYS = ["schema_version", "count", "items"];
const LIST_ITEM_KEYS = ["pack_id", "title", "lifecycle", "version", "created_at", "updated_at", "links"];
const DETAIL_KEYS = [
  "schema_version", "pack_id", "title", "lifecycle", "version", "source",
  "artifact_set_digest", "artifact_counts", "artifacts", "candidate_skill_links",
  "review", "quarantine_reason", "generator", "learning_projection_writes",
  "created_at", "updated_at", "links",
];
const SOURCE_KEYS = [
  "document_id", "source_version", "input_kind", "media_type", "original_sha256",
  "normalized_sha256", "byte_count", "locator_count", "codepoint_count", "parser_name",
  "parser_version", "normalization_name", "normalization_version", "extraction_state", "warning_codes",
];
const ARTIFACT_KEYS = [
  "artifact_id", "pack_id", "artifact_version", "artifact_type", "lifecycle",
  "content_digest", "generator_id", "generator_metadata", "content",
];
const GENERATOR_METADATA_KEYS = [
  "generator_id", "mode", "model_calls", "network_calls", "ocr_calls", "source_normalized_sha256",
];
const CITATION_REF_KEYS = ["field_pointer", "span_ref"];
const REVIEW_KEYS = ["accepted", "decision_count", "accepted_count", "decision_refs", "reason_codes"];
const DECISION_KEYS = [
  "decision_id", "artifact_id", "artifact_version", "artifact_digest", "verifier_id", "accepted", "reason_codes",
];
const SKILL_LINK_KEYS = [
  "artifact_id", "label", "skill_id", "status", "taxonomy_version", "taxonomy_digest",
];
const PROJECTION_KEYS = ["kt", "misconception", "today_plan", "review_schedule"];

export class StudyPackContractError extends Error {
  constructor(message, code = "invalid_study_pack_contract") {
    super(message);
    this.name = "StudyPackContractError";
    this.kind = "contract";
    this.code = code;
  }
}

function fail(path, message, code) {
  throw new StudyPackContractError(`${path}: ${message}`, code);
}

function object(value, path) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(path, "expected object");
  return value;
}

function exactKeys(value, keys, path, { optional = [] } = {}) {
  object(value, path);
  const actual = Object.keys(value).sort();
  const allowed = [...keys, ...optional];
  const unknown = actual.filter((key) => !allowed.includes(key));
  const missing = keys.filter((key) => !(key in value));
  if (unknown.length || missing.length) {
    fail(path, `closed object mismatch${missing.length ? `; missing ${missing.join(", ")}` : ""}${unknown.length ? `; unknown ${unknown.join(", ")}` : ""}`);
  }
}

function text(value, path, { max = 20_000, empty = false } = {}) {
  if (typeof value !== "string" || (!empty && !value.trim()) || value.length > max) fail(path, "invalid text");
  return value;
}

function integer(value, path, { min = 0, max = Number.MAX_SAFE_INTEGER } = {}) {
  if (!Number.isInteger(value) || value < min || value > max) fail(path, "invalid integer");
  return value;
}

function finite(value, path, { min = 0, max = Number.MAX_VALUE } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) fail(path, "invalid number");
  return value;
}

function identifier(value, pattern, path) {
  if (typeof value !== "string" || !pattern.test(value)) fail(path, "invalid public identifier");
  return value;
}

function hash(value, path, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || !SHA256.test(value)) fail(path, "invalid SHA-256");
  return value;
}

function timestamp(value, path) {
  text(value, path, { max: 80 });
  if (Number.isNaN(Date.parse(value))) fail(path, "invalid timestamp");
  return value;
}

function stringArray(value, path, { maxItems = 200 } = {}) {
  if (!Array.isArray(value) || value.length > maxItems) fail(path, "invalid string array");
  return value.map((item, index) => text(item, `${path}[${index}]`, { max: 500, empty: false }));
}

function relativeLink(value, expected, path) {
  if (value !== expected) fail(path, "unsafe or mismatched local link");
  return value;
}

function normalizeProjectionWrites(value, path) {
  exactKeys(value, PROJECTION_KEYS, path);
  for (const key of PROJECTION_KEYS) {
    if (value[key] !== false) fail(`${path}.${key}`, "Study Pack cannot write shared learning projections");
  }
  return Object.freeze({ kt: false, misconception: false, todayPlan: false, reviewSchedule: false });
}

function normalizeCitationRefs(value, path, expectedPointers) {
  if (!Array.isArray(value) || value.length === 0 || value.length > 100) fail(path, "citations must be a non-empty bounded array");
  const normalized = value.map((citation, index) => {
    const itemPath = `${path}[${index}]`;
    exactKeys(citation, CITATION_REF_KEYS, itemPath);
    return {
      fieldPointer: text(citation.field_pointer, `${itemPath}.field_pointer`, { max: 300 }),
      spanId: identifier(citation.span_ref, SPAN_ID, `${itemPath}.span_ref`),
    };
  });
  const pointers = normalized.map((item) => item.fieldPointer);
  if (new Set(pointers).size !== pointers.length) fail(path, "duplicate citation field pointer");
  if (
    pointers.length !== expectedPointers.length
    || expectedPointers.some((pointer) => !pointers.includes(pointer))
  ) fail(path, "citation field pointers do not exactly cover the public content");
  return normalized;
}

function normalizeArtifactContent(artifact, path) {
  const content = artifact.content;
  object(content, `${path}.content`);
  if (artifact.artifact_type === "study_pack.one_page_notes") {
    exactKeys(content, ["schema_version", "title", "claims", "citations"], `${path}.content`);
    const claims = stringArray(content.claims, `${path}.content.claims`, { maxItems: 30 });
    if (!claims.length) fail(`${path}.content.claims`, "note requires claims");
    return {
      schemaVersion: text(content.schema_version, `${path}.content.schema_version`, { max: 100 }),
      title: text(content.title, `${path}.content.title`, { max: 200 }),
      claims,
      citations: normalizeCitationRefs(
        content.citations,
        `${path}.content.citations`,
        claims.map((_, index) => `/claims/${index}`),
      ),
    };
  }
  if (artifact.artifact_type === "study_pack.knowledge_card") {
    exactKeys(content, ["schema_version", "question", "answer", "citations"], `${path}.content`);
    return {
      schemaVersion: text(content.schema_version, `${path}.content.schema_version`, { max: 100 }),
      question: text(content.question, `${path}.content.question`, { max: 2_000 }),
      answer: text(content.answer, `${path}.content.answer`, { max: 2_000 }),
      citations: normalizeCitationRefs(content.citations, `${path}.content.citations`, ["/answer"]),
    };
  }
  if (artifact.artifact_type === "study_pack.practice_item") {
    exactKeys(content, ["schema_version", "item_kind", "prompt", "scorer"], `${path}.content`);
    if (!ITEM_KINDS.has(content.item_kind)) fail(`${path}.content.item_kind`, "unsupported practice item kind");
    exactKeys(content.scorer, ["kind", "version"], `${path}.content.scorer`);
    if (content.scorer.kind !== content.item_kind) fail(`${path}.content.scorer.kind`, "scorer kind mismatch");
    text(content.scorer.version, `${path}.content.scorer.version`, { max: 40 });
    return {
      schemaVersion: text(content.schema_version, `${path}.content.schema_version`, { max: 100 }),
      itemKind: content.item_kind,
      prompt: text(content.prompt, `${path}.content.prompt`, { max: 4_000 }),
      scorer: { kind: content.scorer.kind, version: content.scorer.version },
    };
  }
  if (artifact.artifact_type === "study_pack.review_task") {
    exactKeys(content, ["schema_version", "instruction", "citations", "scope", "schedule_write_capability"], `${path}.content`);
    if (content.scope !== "pack_local_only") fail(`${path}.content.scope`, "review task must remain pack-local");
    if (content.schedule_write_capability !== false) fail(`${path}.content.schedule_write_capability`, "review task cannot write ReviewSchedule");
    return {
      schemaVersion: text(content.schema_version, `${path}.content.schema_version`, { max: 100 }),
      instruction: text(content.instruction, `${path}.content.instruction`, { max: 2_500 }),
      citations: normalizeCitationRefs(content.citations, `${path}.content.citations`, ["/instruction"]),
      scope: "pack_local_only",
      scheduleWriteCapability: false,
    };
  }
  fail(`${path}.artifact_type`, "unsupported artifact type");
}

function normalizeArtifact(value, path, packId) {
  const practice = value?.artifact_type === "study_pack.practice_item";
  exactKeys(value, ARTIFACT_KEYS, path, { optional: practice ? ["links"] : [] });
  identifier(value.artifact_id, ARTIFACT_ID, `${path}.artifact_id`);
  if (value.pack_id !== packId) fail(`${path}.pack_id`, "artifact pack mismatch");
  integer(value.artifact_version, `${path}.artifact_version`, { min: 1 });
  if (!ARTIFACT_TYPES.has(value.artifact_type)) fail(`${path}.artifact_type`, "unsupported artifact type");
  if (!LIFECYCLES.has(value.lifecycle)) fail(`${path}.lifecycle`, "unsupported artifact lifecycle");
  hash(value.content_digest, `${path}.content_digest`);
  text(value.generator_id, `${path}.generator_id`, { max: 100 });
  exactKeys(value.generator_metadata, GENERATOR_METADATA_KEYS, `${path}.generator_metadata`);
  if (value.generator_metadata.generator_id !== value.generator_id) fail(`${path}.generator_metadata.generator_id`, "generator mismatch");
  text(value.generator_metadata.mode, `${path}.generator_metadata.mode`, { max: 100 });
  for (const key of ["model_calls", "network_calls", "ocr_calls"]) {
    if (value.generator_metadata[key] !== 0) fail(`${path}.generator_metadata.${key}`, "local extractive generator must not use this capability");
  }
  hash(value.generator_metadata.source_normalized_sha256, `${path}.generator_metadata.source_normalized_sha256`);
  if (practice) {
    exactKeys(value.links, ["launch"], `${path}.links`);
    relativeLink(value.links.launch, studyPackLaunchPath(value.artifact_id), `${path}.links.launch`);
  }
  return {
    artifactId: value.artifact_id,
    packId,
    artifactVersion: value.artifact_version,
    type: value.artifact_type,
    lifecycle: value.lifecycle,
    contentDigest: value.content_digest,
    generatorId: value.generator_id,
    content: normalizeArtifactContent(value, path),
    launchPath: practice ? value.links.launch : null,
  };
}

function validateArtifactCounts(counts, artifacts, lifecycle, path) {
  exactKeys(counts, [...ARTIFACT_TYPES], path);
  for (const type of ARTIFACT_TYPES) integer(counts[type], `${path}.${type}`, { max: 5 });
  const actual = Object.fromEntries([...ARTIFACT_TYPES].map((type) => [type, artifacts.filter((item) => item.type === type).length]));
  for (const type of ARTIFACT_TYPES) {
    if (counts[type] !== actual[type]) fail(`${path}.${type}`, "artifact count mismatch");
  }
  if (lifecycle !== "quarantined") {
    if (actual["study_pack.one_page_notes"] !== 1) fail(path, "requires exactly one note");
    if (actual["study_pack.knowledge_card"] < 3 || actual["study_pack.knowledge_card"] > 5) fail(path, "requires three to five cards");
    if (actual["study_pack.practice_item"] !== 3) fail(path, "requires exactly three practice items");
    if (actual["study_pack.review_task"] !== 1) fail(path, "requires exactly one pack-local review task");
  }
  return Object.freeze({
    notes: actual["study_pack.one_page_notes"],
    cards: actual["study_pack.knowledge_card"],
    practice: actual["study_pack.practice_item"],
    reviewTasks: actual["study_pack.review_task"],
    total: artifacts.length,
  });
}

export function studyPackPath(packId) {
  identifier(packId, PACK_ID, "pack_id");
  return `/v1/study-packs/${encodeURIComponent(packId)}`;
}

export function studyPackCommandPath(packId) {
  return `${studyPackPath(packId)}/commands`;
}

export function studyPackCitationPath(packId, spanId) {
  identifier(spanId, SPAN_ID, "span_id");
  return `${studyPackPath(packId)}/citations/${encodeURIComponent(spanId)}`;
}

export function studyPackLaunchPath(artifactId) {
  identifier(artifactId, ARTIFACT_ID, "artifact_id");
  return `/v1/study-pack-items/${encodeURIComponent(artifactId)}/launch`;
}

export function studyPackAttemptPath(artifactId) {
  identifier(artifactId, ARTIFACT_ID, "artifact_id");
  return `/v1/study-pack-items/${encodeURIComponent(artifactId)}/attempts`;
}

export function normalizeStudyPackList(payload) {
  exactKeys(payload, LIST_KEYS, "studyPackList");
  if (payload.schema_version !== "lumi.study-pack-list.v1") fail("studyPackList.schema_version", "unsupported schema version");
  integer(payload.count, "studyPackList.count");
  if (!Array.isArray(payload.items) || payload.items.length !== payload.count) fail("studyPackList.items", "count mismatch");
  const items = payload.items.map((item, index) => {
    const path = `studyPackList.items[${index}]`;
    exactKeys(item, LIST_ITEM_KEYS, path);
    identifier(item.pack_id, PACK_ID, `${path}.pack_id`);
    if (!LIFECYCLES.has(item.lifecycle)) fail(`${path}.lifecycle`, "unsupported lifecycle");
    exactKeys(item.links, ["self"], `${path}.links`);
    relativeLink(item.links.self, studyPackPath(item.pack_id), `${path}.links.self`);
    return {
      packId: item.pack_id,
      title: text(item.title, `${path}.title`, { max: 200 }),
      lifecycle: item.lifecycle,
      version: integer(item.version, `${path}.version`, { min: 1 }),
      createdAt: timestamp(item.created_at, `${path}.created_at`),
      updatedAt: timestamp(item.updated_at, `${path}.updated_at`),
    };
  });
  if (new Set(items.map((item) => item.packId)).size !== items.length) fail("studyPackList.items", "duplicate pack identifier");
  return items;
}

function validateDetailRequestContext(payload, expected) {
  if (!expected) fail("studyPack.expected_context", "request context is required");
  if (expected.packId !== undefined && payload.pack_id !== expected.packId) fail("studyPack.pack_id", "response does not match requested pack");
  if (expected.title !== undefined && payload.title !== expected.title.trim()) fail("studyPack.title", "response does not match requested title");
  if (expected.sourceKind !== undefined && payload.source?.input_kind !== expected.sourceKind) fail("studyPack.source.input_kind", "response does not match requested source kind");
  if (expected.action !== undefined) {
    integer(expected.expectedVersion, "studyPack.expected_context.expected_version", { min: 1 });
    if (payload.version !== expected.expectedVersion + 1) fail("studyPack.version", "command response version did not advance exactly once");
    const allowed = expected.action === "request_review"
      ? new Set(["review", "quarantined"])
      : expected.action === "publish"
        ? new Set(["published"])
        : new Set();
    if (!allowed.has(payload.lifecycle)) fail("studyPack.lifecycle", "invalid command lifecycle transition");
    const requiredPrevious = expected.action === "request_review" ? "draft" : "review";
    if (expected.previousLifecycle !== requiredPrevious) fail("studyPack.expected_context.lifecycle", "command was not valid from the original lifecycle");
  }
  if (expected.creation === true) {
    if (payload.version !== 1 || !["draft", "quarantined"].includes(payload.lifecycle)) fail("studyPack", "invalid creation projection");
  }
}

export function normalizeStudyPackDetail(payload, expected) {
  exactKeys(payload, DETAIL_KEYS, "studyPack", { optional: ["idempotent_replay"] });
  if (payload.schema_version !== "lumi.study-pack-detail.v1") fail("studyPack.schema_version", "unsupported schema version");
  validateDetailRequestContext(payload, expected);
  const packId = identifier(payload.pack_id, PACK_ID, "studyPack.pack_id");
  if (!LIFECYCLES.has(payload.lifecycle)) fail("studyPack.lifecycle", "unsupported lifecycle");
  exactKeys(payload.source, SOURCE_KEYS, "studyPack.source");
  identifier(payload.source.document_id, DOCUMENT_ID, "studyPack.source.document_id");
  integer(payload.source.source_version, "studyPack.source.source_version", { min: 1 });
  if (!["pasted_text", "text_pdf"].includes(payload.source.input_kind)) fail("studyPack.source.input_kind", "unsupported source kind");
  const expectedMedia = payload.source.input_kind === "text_pdf" ? "application/pdf" : "text/plain;charset=utf-8";
  if (payload.source.media_type !== expectedMedia) fail("studyPack.source.media_type", "media type mismatch");
  hash(payload.source.original_sha256, "studyPack.source.original_sha256");
  hash(payload.source.normalized_sha256, "studyPack.source.normalized_sha256");
  integer(payload.source.byte_count, "studyPack.source.byte_count");
  integer(payload.source.locator_count, "studyPack.source.locator_count", { min: 1, max: 120 });
  integer(payload.source.codepoint_count, "studyPack.source.codepoint_count", { min: 1, max: 250_000 });
  for (const key of ["parser_name", "parser_version", "normalization_name", "normalization_version"]) {
    text(payload.source[key], `studyPack.source.${key}`, { max: 100 });
  }
  if (!["accepted", "accepted_with_warnings"].includes(payload.source.extraction_state)) fail("studyPack.source.extraction_state", "unsupported extraction state");
  const warningCodes = stringArray(payload.source.warning_codes, "studyPack.source.warning_codes");
  hash(payload.artifact_set_digest, "studyPack.artifact_set_digest", { nullable: payload.lifecycle === "quarantined" });
  if (!Array.isArray(payload.artifacts) || payload.artifacts.length > 10) fail("studyPack.artifacts", "invalid artifact array");
  const artifacts = payload.artifacts.map((item, index) => normalizeArtifact(item, `studyPack.artifacts[${index}]`, packId));
  if (new Set(artifacts.map((item) => item.artifactId)).size !== artifacts.length) fail("studyPack.artifacts", "duplicate artifact identifier");
  for (const artifact of artifacts) {
    if (artifact.lifecycle !== payload.lifecycle) fail("studyPack.artifacts", "artifact lifecycle does not match pack lifecycle");
  }
  const artifactCounts = validateArtifactCounts(payload.artifact_counts, artifacts, payload.lifecycle, "studyPack.artifact_counts");
  if (!Array.isArray(payload.candidate_skill_links)) fail("studyPack.candidate_skill_links", "invalid candidate links");
  const candidateSkillLinks = payload.candidate_skill_links.map((link, index) => {
    const path = `studyPack.candidate_skill_links[${index}]`;
    exactKeys(link, SKILL_LINK_KEYS, path);
    identifier(link.artifact_id, ARTIFACT_ID, `${path}.artifact_id`);
    if (!artifacts.some((artifact) => artifact.artifactId === link.artifact_id)) fail(`${path}.artifact_id`, "candidate link does not bind a pack artifact");
    text(link.label, `${path}.label`, { max: 300 });
    if (link.skill_id !== null) text(link.skill_id, `${path}.skill_id`, { max: 300 });
    if (link.status !== "unconfirmed_candidate") fail(`${path}.status`, "candidate skill cannot be confirmed by Study Pack");
    if (link.taxonomy_version !== null) text(link.taxonomy_version, `${path}.taxonomy_version`, { max: 100 });
    hash(link.taxonomy_digest, `${path}.taxonomy_digest`, { nullable: true });
    if ((link.skill_id === null) !== (link.taxonomy_version === null) || (link.skill_id === null) !== (link.taxonomy_digest === null)) {
      fail(path, "candidate taxonomy binding is incomplete");
    }
    return {
      artifactId: link.artifact_id,
      label: link.label,
      skillId: link.skill_id,
      status: "unconfirmed_candidate",
      taxonomyVersion: link.taxonomy_version,
    };
  });
  const candidateKeys = candidateSkillLinks.map((link) => `${link.artifactId}\u0000${link.label}\u0000${link.skillId || ""}`);
  if (new Set(candidateKeys).size !== candidateKeys.length) fail("studyPack.candidate_skill_links", "duplicate candidate link");
  exactKeys(payload.review, REVIEW_KEYS, "studyPack.review");
  if (typeof payload.review.accepted !== "boolean") fail("studyPack.review.accepted", "invalid review status");
  integer(payload.review.decision_count, "studyPack.review.decision_count");
  integer(payload.review.accepted_count, "studyPack.review.accepted_count");
  if (!Array.isArray(payload.review.decision_refs) || payload.review.decision_refs.length !== payload.review.decision_count) fail("studyPack.review.decision_refs", "decision count mismatch");
  const decisions = payload.review.decision_refs.map((decision, index) => {
    const path = `studyPack.review.decision_refs[${index}]`;
    exactKeys(decision, DECISION_KEYS, path);
    identifier(decision.decision_id, DECISION_ID, `${path}.decision_id`);
    identifier(decision.artifact_id, ARTIFACT_ID, `${path}.artifact_id`);
    integer(decision.artifact_version, `${path}.artifact_version`, { min: 1 });
    hash(decision.artifact_digest, `${path}.artifact_digest`);
    text(decision.verifier_id, `${path}.verifier_id`, { max: 100 });
    if (typeof decision.accepted !== "boolean") fail(`${path}.accepted`, "invalid decision");
    const boundArtifact = artifacts.find((artifact) => artifact.artifactId === decision.artifact_id);
    if (
      !boundArtifact
      || boundArtifact.artifactVersion !== decision.artifact_version
      || boundArtifact.contentDigest !== decision.artifact_digest
    ) fail(path, "verifier decision does not exactly bind an artifact version and digest");
    return {
      decisionId: decision.decision_id,
      artifactId: decision.artifact_id,
      accepted: decision.accepted,
      reasonCodes: stringArray(decision.reason_codes, `${path}.reason_codes`),
    };
  });
  if (new Set(decisions.map((item) => item.decisionId)).size !== decisions.length) fail("studyPack.review.decision_refs", "duplicate verifier decision identifier");
  if (new Set(decisions.map((item) => item.artifactId)).size !== decisions.length) fail("studyPack.review.decision_refs", "duplicate verifier decision artifact binding");
  const actualAcceptedCount = decisions.filter((item) => item.accepted).length;
  if (payload.review.accepted_count !== actualAcceptedCount) fail("studyPack.review.accepted_count", "accepted count mismatch");
  const actualReviewAccepted = decisions.length > 0 && actualAcceptedCount === decisions.length;
  if (payload.review.accepted !== actualReviewAccepted) fail("studyPack.review.accepted", "accepted summary mismatch");
  if (["review", "published"].includes(payload.lifecycle)) {
    if (decisions.length !== artifacts.length || !actualReviewAccepted) fail("studyPack.review", "review and published packs require one accepted decision per artifact");
  }
  if (payload.lifecycle === "draft" && (decisions.length !== 0 || payload.review.accepted_count !== 0)) fail("studyPack.review", "draft cannot carry verifier decisions");
  const reviewReasonCodes = stringArray(payload.review.reason_codes, "studyPack.review.reason_codes");
  if (payload.quarantine_reason !== null) text(payload.quarantine_reason, "studyPack.quarantine_reason", { max: 200 });
  if (payload.lifecycle === "quarantined" && !payload.quarantine_reason) fail("studyPack.quarantine_reason", "quarantined pack requires a reason");
  exactKeys(payload.generator, ["id", "model_calls", "network_calls", "ocr_calls"], "studyPack.generator");
  text(payload.generator.id, "studyPack.generator.id", { max: 100 });
  for (const key of ["model_calls", "network_calls", "ocr_calls"]) {
    if (payload.generator[key] !== 0) fail(`studyPack.generator.${key}`, "unsupported generator capability");
  }
  normalizeProjectionWrites(payload.learning_projection_writes, "studyPack.learning_projection_writes");
  exactKeys(payload.links, ["self", "commands", "replay"], "studyPack.links");
  relativeLink(payload.links.self, studyPackPath(packId), "studyPack.links.self");
  relativeLink(payload.links.commands, studyPackCommandPath(packId), "studyPack.links.commands");
  relativeLink(payload.links.replay, `${studyPackPath(packId)}/replay`, "studyPack.links.replay");
  if ("idempotent_replay" in payload && typeof payload.idempotent_replay !== "boolean") fail("studyPack.idempotent_replay", "invalid replay marker");
  return {
    packId,
    title: text(payload.title, "studyPack.title", { max: 200 }),
    lifecycle: payload.lifecycle,
    version: integer(payload.version, "studyPack.version", { min: 1 }),
    source: {
      documentId: payload.source.document_id,
      version: payload.source.source_version,
      kind: payload.source.input_kind,
      mediaType: payload.source.media_type,
      byteCount: payload.source.byte_count,
      locatorCount: payload.source.locator_count,
      codepointCount: payload.source.codepoint_count,
      parserName: payload.source.parser_name,
      normalizedSha256: payload.source.normalized_sha256,
      extractionState: payload.source.extraction_state,
      warningCodes,
    },
    artifactCounts,
    artifacts,
    candidateSkillLinks,
    review: {
      accepted: payload.review.accepted,
      decisionCount: payload.review.decision_count,
      acceptedCount: payload.review.accepted_count,
      decisions,
      reasonCodes: reviewReasonCodes,
    },
    quarantineReason: payload.quarantine_reason,
    generatorId: payload.generator.id,
    createdAt: timestamp(payload.created_at, "studyPack.created_at"),
    updatedAt: timestamp(payload.updated_at, "studyPack.updated_at"),
    idempotentReplay: payload.idempotent_replay === true,
  };
}

export function buildStudyPackCreate({ title, source, commandId = createCommandId() } = {}) {
  const normalizedTitle = typeof title === "string" ? title.trim() : "";
  if (!normalizedTitle || normalizedTitle.length > 200) fail("create.title", "title is required and must be at most 200 characters", "invalid_create_input");
  if (!isCommandId(commandId)) fail("create.command_id", "invalid opaque command id", "invalid_command_id");
  object(source, "create.source");
  if (source.kind === "pasted_text") {
    exactKeys(source, ["kind", "text"], "create.source");
    const sourceText = text(source.text, "create.source.text", { max: 512 * 1024 });
    if (new TextEncoder().encode(sourceText).byteLength > 512 * 1024) fail("create.source.text", "UTF-8 text exceeds 512 KiB", "source_too_large");
    return { title: normalizedTitle, source: { kind: "pasted_text", text: sourceText }, command_id: commandId };
  }
  if (source.kind === "text_pdf") {
    exactKeys(source, ["kind", "pdf_base64"], "create.source");
    text(source.pdf_base64, "create.source.pdf_base64", { max: 12 * 1024 * 1024 });
    return { title: normalizedTitle, source: { kind: "text_pdf", pdf_base64: source.pdf_base64 }, command_id: commandId };
  }
  fail("create.source.kind", "only pasted text or one PDF is accepted", "invalid_source_body");
}

export function buildStudyPackCommand({ pack, action, commandId = createCommandId() } = {}) {
  if (!pack || !PACK_ID.test(pack.packId || "")) fail("command.pack", "invalid pack", "invalid_command_input");
  if (!["request_review", "publish"].includes(action)) fail("command.action", "unsupported action", "invalid_command_input");
  integer(pack.version, "command.expected_version", { min: 1 });
  if (!isCommandId(commandId)) fail("command.command_id", "invalid opaque command id", "invalid_command_id");
  return { action, expected_version: pack.version, command_id: commandId };
}

export function buildStudyPackAttempt({ launch, learnerAnswer, commandId = createCommandId() } = {}) {
  const answer = typeof learnerAnswer === "string" ? learnerAnswer.trim() : "";
  if (!answer || answer.length > 10_000) fail("attempt.learner_answer", "a real typed answer is required", "invalid_attempt_input");
  if (!launch || launch.evidenceOrigin !== HUMAN_ORIGIN) fail("attempt.evidence_origin", "only human local interactive launches can be submitted", "evaluation_fixture_rejected");
  if (!isCommandId(commandId)) fail("attempt.command_id", "invalid opaque command id", "invalid_command_id");
  return {
    learner_answer: answer,
    expected_pack_version: integer(launch.packVersion, "attempt.expected_pack_version", { min: 1 }),
    expected_artifact_version: integer(launch.artifactVersion, "attempt.expected_artifact_version", { min: 1 }),
    command_id: commandId,
  };
}

export function arrayBufferToBase64(buffer) {
  if (!(buffer instanceof ArrayBuffer)) fail("pdf", "expected ArrayBuffer", "invalid_pdf_file");
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength > 8 * 1024 * 1024) fail("pdf", "PDF exceeds 8 MiB", "source_too_large");
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  if (typeof globalThis.btoa === "function") return globalThis.btoa(binary);
  return Buffer.from(bytes).toString("base64");
}

export async function pdfFileToSource(file) {
  if (!file || typeof file.arrayBuffer !== "function") fail("pdf", "choose one PDF file", "invalid_pdf_file");
  const name = typeof file.name === "string" ? file.name : "";
  if (file.type !== "application/pdf" && !name.toLowerCase().endsWith(".pdf")) fail("pdf", "only PDF files are accepted", "invalid_pdf_file");
  if (!Number.isFinite(file.size) || file.size <= 0) fail("pdf", "PDF is empty", "invalid_pdf_file");
  if (file.size > 8 * 1024 * 1024) fail("pdf", "PDF exceeds 8 MiB", "source_too_large");
  return { kind: "text_pdf", pdf_base64: arrayBufferToBase64(await file.arrayBuffer()) };
}

function rejectEvaluationOrigin(origin, path) {
  if (origin === "evaluation_fixture") {
    fail(path, "evaluation fixture data cannot become a production learning record", "evaluation_fixture_rejected");
  }
  if (origin !== HUMAN_ORIGIN) fail(path, "unsupported evidence origin", "invalid_evidence_origin");
}

export function normalizeStudyPackLaunch(payload, expected) {
  exactKeys(payload, [
    "schema_version", "pack_id", "pack_version", "artifact_id", "artifact_version",
    "item_kind", "prompt", "scorer", "activity_kind", "evidence_origin", "links",
  ], "launch");
  rejectEvaluationOrigin(payload.evidence_origin, "launch.evidence_origin");
  if (payload.schema_version !== "lumi.study-pack-launch.v1") fail("launch.schema_version", "unsupported schema version");
  const packId = identifier(payload.pack_id, PACK_ID, "launch.pack_id");
  const artifactId = identifier(payload.artifact_id, ARTIFACT_ID, "launch.artifact_id");
  if (!expected || artifactId !== expected.artifactId) fail("launch.artifact_id", "response does not match requested artifact");
  if (expected.packId !== undefined && packId !== expected.packId) fail("launch.pack_id", "response does not match the artifact pack");
  if (expected.artifactVersion !== undefined && payload.artifact_version !== expected.artifactVersion) fail("launch.artifact_version", "response does not match the artifact version");
  if (!ITEM_KINDS.has(payload.item_kind)) fail("launch.item_kind", "unsupported item kind");
  if (payload.activity_kind !== ACTIVITY_KIND) fail("launch.activity_kind", "unsupported activity kind");
  exactKeys(payload.scorer, ["kind", "version"], "launch.scorer");
  if (payload.scorer.kind !== payload.item_kind) fail("launch.scorer.kind", "scorer kind mismatch");
  text(payload.scorer.version, "launch.scorer.version", { max: 40 });
  if (
    expected.scorer
    && (payload.scorer.kind !== expected.scorer.kind || payload.scorer.version !== expected.scorer.version)
  ) fail("launch.scorer", "response scorer does not match the published artifact");
  exactKeys(payload.links, ["pack", "attempts"], "launch.links");
  relativeLink(payload.links.pack, studyPackPath(packId), "launch.links.pack");
  relativeLink(payload.links.attempts, studyPackAttemptPath(artifactId), "launch.links.attempts");
  return Object.freeze({
    packId,
    packVersion: integer(payload.pack_version, "launch.pack_version", { min: 1 }),
    artifactId,
    artifactVersion: integer(payload.artifact_version, "launch.artifact_version", { min: 1 }),
    itemKind: payload.item_kind,
    prompt: text(payload.prompt, "launch.prompt", { max: 4_000 }),
    scorer: Object.freeze({ kind: payload.scorer.kind, version: payload.scorer.version }),
    activityKind: ACTIVITY_KIND,
    evidenceOrigin: HUMAN_ORIGIN,
  });
}

export function createActivePracticeProjection(launch) {
  if (!launch || launch.evidenceOrigin !== HUMAN_ORIGIN) fail("practice", "invalid active launch", "evaluation_fixture_rejected");
  return Object.freeze({
    packId: launch.packId,
    artifactId: launch.artifactId,
    prompt: launch.prompt,
    itemKind: launch.itemKind,
    evidenceOrigin: HUMAN_ORIGIN,
  });
}

export function summarizePracticeResults(results, expectedArtifactIds) {
  if (!Array.isArray(expectedArtifactIds) || expectedArtifactIds.length !== 3) fail("practice.expected_artifacts", "completion requires exactly three expected artifacts", "invalid_practice_completion");
  expectedArtifactIds.forEach((artifactId, index) => identifier(artifactId, ARTIFACT_ID, `practice.expected_artifacts[${index}]`));
  if (new Set(expectedArtifactIds).size !== 3) fail("practice.expected_artifacts", "expected practice artifacts must be distinct", "invalid_practice_completion");
  if (!Array.isArray(results) || results.length !== 3) fail("practice.results", "completion requires exactly three accepted attempts", "invalid_practice_completion");
  const rows = results.map((result, index) => {
    if (!result || result.evidenceOrigin !== HUMAN_ORIGIN || typeof result.correct !== "boolean") {
      fail(`practice.results[${index}]`, "completion accepts only human local interactive results", "evaluation_fixture_rejected");
    }
    if (result.artifactId !== expectedArtifactIds[index]) fail(`practice.results[${index}].artifactId`, "result does not match expected practice order", "invalid_practice_completion");
    identifier(result.attemptId, ATTEMPT_ID, `practice.results[${index}].attemptId`);
    return Object.freeze({ artifactId: result.artifactId, attemptId: result.attemptId, correct: result.correct, score: result.score, maxScore: result.maxScore });
  });
  if (new Set(rows.map((item) => item.artifactId)).size !== 3) fail("practice.results", "practice results must cover distinct artifacts", "invalid_practice_completion");
  if (new Set(rows.map((item) => item.attemptId)).size !== 3) fail("practice.results", "practice results must contain distinct attempts", "invalid_practice_completion");
  return Object.freeze({ completed: true, count: 3, correct: rows.filter((item) => item.correct).length, rows });
}

export function normalizeStudyPackAttemptResult(payload, { launch } = {}) {
  exactKeys(payload, [
    "schema_version", "pack_id", "pack_version", "attempt", "result", "answer",
    "explanation", "cited_source_context", "learning_projection_writes", "idempotent_replay", "links",
  ], "attemptResult");
  object(payload.attempt, "attemptResult.attempt");
  rejectEvaluationOrigin(payload.attempt.evidence_origin, "attemptResult.attempt.evidence_origin");
  if (payload.schema_version !== "lumi.study-pack-attempt-result.v1") fail("attemptResult.schema_version", "unsupported schema version");
  const packId = identifier(payload.pack_id, PACK_ID, "attemptResult.pack_id");
  if (!launch || packId !== launch.packId) fail("attemptResult.pack_id", "response does not match the launched pack");
  exactKeys(payload.attempt, [
    "schema_version", "attempt_id", "pack_id", "artifact_id", "artifact_version", "answer_digest",
    "correct", "score", "evidence_origin", "activity_kind", "scorer_id",
  ], "attemptResult.attempt");
  if (payload.attempt.schema_version !== "lumi.study-pack-attempt.v1") fail("attemptResult.attempt.schema_version", "unsupported schema version");
  identifier(payload.attempt.attempt_id, ATTEMPT_ID, "attemptResult.attempt.attempt_id");
  if (payload.attempt.pack_id !== packId) fail("attemptResult.attempt.pack_id", "pack mismatch");
  const artifactId = identifier(payload.attempt.artifact_id, ARTIFACT_ID, "attemptResult.attempt.artifact_id");
  const artifactVersion = integer(payload.attempt.artifact_version, "attemptResult.attempt.artifact_version", { min: 1 });
  if (artifactId !== launch.artifactId || artifactVersion !== launch.artifactVersion) fail("attemptResult.attempt", "response does not match the launched artifact");
  hash(payload.attempt.answer_digest, "attemptResult.attempt.answer_digest");
  if (typeof payload.attempt.correct !== "boolean") fail("attemptResult.attempt.correct", "invalid correctness");
  finite(payload.attempt.score, "attemptResult.attempt.score", { min: 0 });
  if (payload.attempt.activity_kind !== ACTIVITY_KIND) fail("attemptResult.attempt.activity_kind", "unsupported activity kind");
  const scorerId = text(payload.attempt.scorer_id, "attemptResult.attempt.scorer_id", { max: 100 });
  if (scorerId !== `${launch.scorer.kind}@${launch.scorer.version}`) fail("attemptResult.attempt.scorer_id", "response scorer does not match the launch");
  exactKeys(payload.result, ["correct", "score", "max_score"], "attemptResult.result");
  if (typeof payload.result.correct !== "boolean" || payload.result.correct !== payload.attempt.correct) fail("attemptResult.result.correct", "result mismatch");
  const score = finite(payload.result.score, "attemptResult.result.score", { min: 0 });
  const maxScore = finite(payload.result.max_score, "attemptResult.result.max_score", { min: 0.000001 });
  if (score > maxScore || score !== payload.attempt.score) fail("attemptResult.result.score", "score mismatch");
  if (!Array.isArray(payload.cited_source_context) || payload.cited_source_context.length === 0) fail("attemptResult.cited_source_context", "post-attempt citation context is required");
  const citedContext = payload.cited_source_context.map((citation, index) => {
    const path = `attemptResult.cited_source_context[${index}]`;
    exactKeys(citation, ["field_pointer", "span_id", "locator_kind", "locator_index", "start_offset", "end_offset", "excerpt"], path);
    if (!["page", "section"].includes(citation.locator_kind)) fail(`${path}.locator_kind`, "unsupported locator");
    return {
      fieldPointer: text(citation.field_pointer, `${path}.field_pointer`, { max: 300 }),
      spanId: identifier(citation.span_id, SPAN_ID, `${path}.span_id`),
      locatorKind: citation.locator_kind,
      locatorIndex: integer(citation.locator_index, `${path}.locator_index`, { min: 1, max: 120 }),
      startOffset: integer(citation.start_offset, `${path}.start_offset`),
      endOffset: integer(citation.end_offset, `${path}.end_offset`, { min: 1 }),
      excerpt: text(citation.excerpt, `${path}.excerpt`, { max: 2_000 }),
    };
  });
  const contextPointers = citedContext.map((item) => item.fieldPointer);
  if (
    contextPointers.length !== 2
    || new Set(contextPointers).size !== 2
    || !contextPointers.includes("/answer")
    || !contextPointers.includes("/explanation")
  ) fail("attemptResult.cited_source_context", "attempt citations must exactly cover answer and explanation");
  normalizeProjectionWrites(payload.learning_projection_writes, "attemptResult.learning_projection_writes");
  if (typeof payload.idempotent_replay !== "boolean") fail("attemptResult.idempotent_replay", "invalid replay marker");
  exactKeys(payload.links, ["pack", "replay"], "attemptResult.links");
  relativeLink(payload.links.pack, studyPackPath(packId), "attemptResult.links.pack");
  relativeLink(payload.links.replay, `${studyPackPath(packId)}/replay`, "attemptResult.links.replay");
  const packVersion = integer(payload.pack_version, "attemptResult.pack_version", { min: 1 });
  if (packVersion !== launch.packVersion + 1) fail("attemptResult.pack_version", "attempt response version did not advance exactly once");
  return {
    packId,
    packVersion,
    artifactId,
    artifactVersion,
    attemptId: payload.attempt.attempt_id,
    correct: payload.result.correct,
    score,
    maxScore,
    answer: text(payload.answer, "attemptResult.answer", { max: 10_000 }),
    explanation: text(payload.explanation, "attemptResult.explanation", { max: 10_000 }),
    citedContext,
    evidenceOrigin: HUMAN_ORIGIN,
    idempotentReplay: payload.idempotent_replay,
  };
}

export function normalizeStudyPackCitation(payload, { packId, spanId, documentId, sourceVersion, normalizedSha256 } = {}) {
  exactKeys(payload, [
    "schema_version", "verified", "span_id", "document_id", "source_version",
    "normalized_source_sha256", "locator_kind", "locator_index", "start_offset", "end_offset",
    "slice_sha256", "excerpt", "links",
  ], "citation");
  if (payload.schema_version !== "lumi.source-citation.v1" || payload.verified !== true) fail("citation", "citation is not verified");
  identifier(packId, PACK_ID, "citation.pack_id");
  if (payload.span_id !== spanId) fail("citation.span_id", "span mismatch");
  identifier(payload.span_id, SPAN_ID, "citation.span_id");
  identifier(payload.document_id, DOCUMENT_ID, "citation.document_id");
  if (documentId !== undefined && payload.document_id !== documentId) fail("citation.document_id", "citation does not match the requested source document");
  const resolvedSourceVersion = integer(payload.source_version, "citation.source_version", { min: 1 });
  if (sourceVersion !== undefined && resolvedSourceVersion !== sourceVersion) fail("citation.source_version", "citation does not match the requested source version");
  hash(payload.normalized_source_sha256, "citation.normalized_source_sha256");
  if (normalizedSha256 !== undefined && payload.normalized_source_sha256 !== normalizedSha256) fail("citation.normalized_source_sha256", "citation does not match the frozen source");
  if (!["page", "section"].includes(payload.locator_kind)) fail("citation.locator_kind", "unsupported locator");
  const locatorIndex = integer(payload.locator_index, "citation.locator_index", { min: 1, max: 120 });
  const startOffset = integer(payload.start_offset, "citation.start_offset");
  const endOffset = integer(payload.end_offset, "citation.end_offset", { min: 1 });
  if (endOffset <= startOffset) fail("citation.end_offset", "invalid citation range");
  hash(payload.slice_sha256, "citation.slice_sha256");
  exactKeys(payload.links, ["pack"], "citation.links");
  relativeLink(payload.links.pack, studyPackPath(packId), "citation.links.pack");
  return {
    verified: true,
    spanId,
    locatorKind: payload.locator_kind,
    locatorIndex,
    startOffset,
    endOffset,
    excerpt: text(payload.excerpt, "citation.excerpt", { max: 2_000 }),
  };
}

const ERROR_COPY = Object.freeze({
  invalid_source_body: ["资料格式不符合要求", "请粘贴纯文本，或重新选择一个能直接选中文字的 PDF。"],
  source_too_large: ["资料超过本机处理上限", "文本不得超过 512 KB，PDF 不得超过 8 MB。"],
  payload_too_large: ["导入内容过大", "请缩小文件后重新选择。"],
  pdf_parse_failed: ["无法读取这个 PDF", "文件可能损坏或不是有效的 PDF。"],
  pdf_encrypted_unsupported: ["不支持加密 PDF", "请先在本机解除密码保护，再重新选择。"],
  pdf_text_unavailable_ocr_required: ["PDF 没有可读取的文字", "当前版本不能识别扫描图片；请改用能复制文字的 PDF 或粘贴文本。"],
  source_insufficient_for_pack: ["材料不足以形成学习包", "请提供包含多个完整要点的资料。"],
  citation_unresolved: ["来源引用无法核验", "这条内容已停止展示来源，请重新读取学习包。"],
  artifact_unsupported: ["资料包含不受支持的内容", "当前版本无法打开这项学习内容。"],
  artifact_quarantined: ["学习包已隔离", "内容未通过核验，不能发布或练习。"],
  artifact_not_published: ["内容尚未发布", "完成核验并发布后才能开始练习。"],
  stale_version: ["学习包状态已变化", "已保存的版本不是最新版本，请重新读取后再操作。"],
  command_conflict: ["操作编号发生冲突", "本次操作没有继续。重新读取后可以安全重试。"],
  invalid_transition: ["当前状态不能执行此操作", "请重新读取学习包，按当前可用操作继续。"],
  evaluation_fixture_rejected: ["检测到评测数据", "这不是实际学习作答，不能作为生产学习记录。练习已关闭。"],
});

export function studyPackErrorCopy(error) {
  if (error?.kind === "unavailable") return { title: "本机服务未连接", message: "学习资料保留在本机服务中；恢复连接后可重新读取。", state: "offline" };
  const fallback = error?.kind === "contract"
    ? ["学习资料响应异常", "本机返回的数据未通过核验，已停止显示和写入。请重新读取。"]
    : ["操作未完成", "本机服务没有接受这次操作。"];
  const [title, message] = ERROR_COPY[error?.code] || fallback;
  return { title, message, state: error?.code === "stale_version" ? "stale" : "error" };
}

export function studyPackWriteRecovery(error) {
  if (error?.kind === "unavailable" || ["request_timeout", "service_unavailable"].includes(error?.code)) {
    return Object.freeze({ strategy: "retry_same_command", retainCommandId: true, refresh: false, relaunch: false });
  }
  if (error?.code === "stale_version") {
    return Object.freeze({ strategy: "refresh_relaunch", retainCommandId: false, refresh: true, relaunch: true });
  }
  if (error?.code === "command_conflict") {
    return Object.freeze({ strategy: "refresh_new_command", retainCommandId: false, refresh: true, relaunch: false });
  }
  return Object.freeze({ strategy: "show_error", retainCommandId: false, refresh: false, relaunch: false });
}

export function studyPackReceiptRequiresRefresh(value) {
  return value?.idempotentReplay === true;
}

export const STUDY_PACK_LIMITS = Object.freeze({
  pastedTextBytes: 512 * 1024,
  pdfBytes: 8 * 1024 * 1024,
  pdfPages: 120,
  normalizedCodepoints: 250_000,
});

export const STUDY_PACK_LIFECYCLE_COPY = Object.freeze({
  draft: "草稿",
  review: "已核验",
  published: "已发布",
  quarantined: "已隔离",
  stale: "需刷新",
});
