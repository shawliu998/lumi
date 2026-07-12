const SCHEMA_VERSION = "lumi.product-activity.v1";
const RESPONSE_MODE = "single_choice";
const ROLES = new Set(["first_answer", "independent_transfer"]);
const FORBIDDEN_KEYS = new Set([
  "answer",
  "answer_labels",
  "correct_answer",
  "correct_option",
  "explanation",
  "explanation_text",
  "is_correct",
  "candidate_skills",
  "candidate_causes",
  "private",
  "scoring",
]);

function invariant(condition, message) {
  if (!condition) throw new TypeError(message);
}

function requiredText(value, field) {
  invariant(typeof value === "string" && value.trim(), `${field} must be non-empty text`);
  return value.trim();
}

function assertNoPrivateFields(value, path = "activity") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoPrivateFields(item, `${path}[${index}]`));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    invariant(!FORBIDDEN_KEYS.has(key.toLowerCase()), `${path}.${key} is private`);
    assertNoPrivateFields(child, `${path}.${key}`);
  }
}

function normalizeSource(source) {
  invariant(source && typeof source === "object" && !Array.isArray(source), "source must be an object");
  const year = Number(source.year);
  const questionNo = Number(source.question_no);
  invariant(Number.isInteger(year) && year >= 1900 && year <= 2100, "source.year is invalid");
  invariant(Number.isInteger(questionNo) && questionNo > 0, "source.question_no is invalid");
  return Object.freeze({
    paperTitle: requiredText(source.paper_title, "source.paper_title"),
    year,
    questionNo,
    sourceSite: requiredText(source.source_site, "source.source_site"),
    sourceUrl: typeof source.source_url === "string" ? source.source_url : "",
  });
}

export function normalizeProductActivity(payload, { expectedRole, expectedReleaseId } = {}) {
  assertNoPrivateFields(payload);
  invariant(payload && typeof payload === "object" && !Array.isArray(payload), "activity must be an object");
  invariant(payload.schema_version === SCHEMA_VERSION, "unsupported activity schema");
  invariant(payload.domain === "xingce" && payload.module === "资料分析", "unsupported activity domain");
  invariant(payload.response_mode === RESPONSE_MODE, "unsupported response mode");
  invariant(ROLES.has(payload.diagnostic_role), "unsupported diagnostic role");
  if (expectedRole) invariant(payload.diagnostic_role === expectedRole, "diagnostic role mismatch");
  if (expectedReleaseId) invariant(payload.release_id === expectedReleaseId, "release id mismatch");

  invariant(Array.isArray(payload.options) && payload.options.length === 4, "activity must contain four options");
  const options = payload.options.map((option, index) => {
    invariant(option && typeof option === "object" && !Array.isArray(option), "option must be an object");
    const label = requiredText(option.label, `options[${index}].label`).toUpperCase();
    invariant(label === String.fromCharCode(65 + index), "options must be ordered A-D");
    return Object.freeze({ label, text: requiredText(option.text, `options[${index}].text`) });
  });

  const activityId = requiredText(payload.activity_id, "activity_id");
  const releaseId = requiredText(payload.release_id, "release_id");
  const contentSignature = requiredText(payload.content_signature, "content_signature");
  invariant(/^[a-f0-9]{64}$/i.test(contentSignature), "content_signature is invalid");
  const selfLink = payload.links?.self;
  invariant(selfLink === `/v1/product-activities/${encodeURIComponent(activityId)}`, "activity self link mismatch");
  invariant(payload.links?.attempts === "/v1/attempts", "activity attempt link mismatch");
  return Object.freeze({
    activityId,
    releaseId,
    contentSignature: contentSignature.toLowerCase(),
    diagnosticRole: payload.diagnostic_role,
    materialText: requiredText(payload.material_text, "material_text"),
    stemText: requiredText(payload.stem_text, "stem_text"),
    options: Object.freeze(options),
    source: normalizeSource(payload.source),
  });
}

export function assertIndependentTransferBinding(continuation, transferActivity) {
  const binding = continuation?.teaching?.independent_verification_item;
  invariant(binding && typeof binding === "object" && !Array.isArray(binding), "independent transfer binding is missing");
  invariant(binding.item_id === transferActivity?.activityId, "independent transfer item id mismatch");
  invariant(
    typeof binding.content_signature === "string"
      && binding.content_signature.toLowerCase() === transferActivity?.contentSignature,
    "independent transfer content signature mismatch",
  );
  return transferActivity;
}

export function normalizeProductActivityList(payload, expected = {}) {
  invariant(payload && typeof payload === "object" && !Array.isArray(payload), "activity list must be an object");
  invariant(Number.isInteger(payload.count) && payload.count >= 0, "activity count is invalid");
  invariant(Array.isArray(payload.items) && payload.items.length === payload.count, "activity count mismatch");
  return Object.freeze(payload.items.map((item) => normalizeProductActivity(item, expected)));
}

export function normalizeProductActivityBundle(firstPayload, transferPayload, { releaseId } = {}) {
  const firstItems = normalizeProductActivityList(firstPayload, {
    expectedRole: "first_answer",
    expectedReleaseId: releaseId,
  });
  const transferItems = normalizeProductActivityList(transferPayload, {
    expectedRole: "independent_transfer",
    expectedReleaseId: releaseId,
  });
  invariant(firstItems.length === 1, "release must contain exactly one first-answer activity");
  invariant(transferItems.length === 1, "release must contain exactly one transfer activity");
  invariant(firstItems[0].activityId !== transferItems[0].activityId, "transfer activity must use a different item id");
  invariant(firstItems[0].releaseId === transferItems[0].releaseId, "activity release mismatch");
  return Object.freeze({
    releaseId: firstItems[0].releaseId,
    firstAnswer: firstItems[0],
    independentTransfer: transferItems[0],
  });
}

export function productActivityListPath({ releaseId, diagnosticRole }) {
  invariant(typeof releaseId === "string" && releaseId.trim(), "releaseId is required");
  invariant(ROLES.has(diagnosticRole), "diagnosticRole is invalid");
  const query = new URLSearchParams({ release_id: releaseId, diagnostic_role: diagnosticRole });
  return `/v1/product-activities?${query.toString()}`;
}
