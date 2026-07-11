import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  arrayBufferToBase64,
  buildStudyPackAttempt,
  buildStudyPackCommand,
  buildStudyPackCreate,
  createActivePracticeProjection,
  normalizeStudyPackAttemptResult,
  normalizeStudyPackCitation,
  normalizeStudyPackDetail,
  normalizeStudyPackLaunch,
  normalizeStudyPackList,
  pdfFileToSource,
  studyPackAttemptPath,
  studyPackCitationPath,
  studyPackCommandPath,
  studyPackErrorCopy,
  studyPackLaunchPath,
  studyPackPath,
  studyPackReceiptRequiresRefresh,
  studyPackWriteRecovery,
  summarizePracticeResults,
} from "./studyPackAdapter.js";

const HASH = "a".repeat(64);
const PACK_ID = `p_${"A".repeat(40)}`;
const DOCUMENT_ID = `d_${"B".repeat(40)}`;
const SPAN_ID = `s_${"C".repeat(40)}`;
const COMMAND_ID = `c_${"D".repeat(40)}`;

function artifactId(index) {
  return `a_${String.fromCharCode(65 + index).repeat(40)}`;
}

function metadata() {
  return {
    generator_id: "extractive-local@1",
    mode: "deterministic_extractive",
    model_calls: 0,
    network_calls: 0,
    ocr_calls: 0,
    source_normalized_sha256: HASH,
  };
}

function artifact(index, type, content, lifecycle) {
  const value = {
    artifact_id: artifactId(index),
    pack_id: PACK_ID,
    artifact_version: 1,
    artifact_type: type,
    lifecycle,
    content_digest: HASH,
    generator_id: "extractive-local@1",
    generator_metadata: metadata(),
    content,
  };
  if (type === "study_pack.practice_item") {
    value.links = { launch: `/v1/study-pack-items/${artifactId(index)}/launch` };
  }
  return value;
}

function artifacts(lifecycle = "draft") {
  const citation = [{ field_pointer: "/answer", span_ref: SPAN_ID }];
  return [
    artifact(0, "study_pack.one_page_notes", {
      schema_version: "study_pack.one_page_notes.v1",
      title: "资料要点",
      claims: ["先确认统计口径。"],
      citations: [{ field_pointer: "/claims/0", span_ref: SPAN_ID }],
    }, lifecycle),
    ...[1, 2, 3].map((index) => artifact(index, "study_pack.knowledge_card", {
      schema_version: "study_pack.knowledge_card.v1",
      question: `第 ${index} 条是什么？`,
      answer: "先确认统计口径。",
      citations: citation,
    }, lifecycle)),
    ...[4, 5, 6].map((index) => artifact(index, "study_pack.practice_item", {
      schema_version: "study_pack.practice_item.v1",
      item_kind: "cloze_exact_v1",
      prompt: `第 ${index - 3} 题：先确认____。`,
      scorer: { kind: "cloze_exact_v1", version: "1.0.0" },
    }, lifecycle)),
    artifact(7, "study_pack.review_task", {
      schema_version: "study_pack.review_task.v1",
      instruction: "独立复述资料要点。",
      citations: [{ field_pointer: "/instruction", span_ref: SPAN_ID }],
      scope: "pack_local_only",
      schedule_write_capability: false,
    }, lifecycle),
  ];
}

function detail(lifecycle = "draft", overrides = {}) {
  const content = lifecycle === "quarantined" ? [] : artifacts(lifecycle);
  const reviewed = ["review", "published"].includes(lifecycle);
  const decisions = reviewed ? content.map((item, index) => ({
    decision_id: `v_${String.fromCharCode(65 + index).repeat(40)}`,
    artifact_id: item.artifact_id,
    artifact_version: 1,
    artifact_digest: HASH,
    verifier_id: "study-pack-deterministic-verifier@1",
    accepted: true,
    reason_codes: [],
  })) : [];
  return {
    schema_version: "lumi.study-pack-detail.v1",
    pack_id: PACK_ID,
    title: "资料分析基础",
    lifecycle,
    version: lifecycle === "draft" || lifecycle === "quarantined" ? 1 : lifecycle === "review" ? 2 : 3,
    source: {
      document_id: DOCUMENT_ID,
      source_version: 1,
      input_kind: "pasted_text",
      media_type: "text/plain;charset=utf-8",
      original_sha256: HASH,
      normalized_sha256: HASH,
      byte_count: 120,
      locator_count: 5,
      codepoint_count: 40,
      parser_name: "utf8-text",
      parser_version: "1.0.0",
      normalization_name: "unicode-nfc-canonical-newline",
      normalization_version: "1.0.0",
      extraction_state: "accepted",
      warning_codes: [],
    },
    artifact_set_digest: lifecycle === "quarantined" ? null : HASH,
    artifact_counts: {
      "study_pack.knowledge_card": lifecycle === "quarantined" ? 0 : 3,
      "study_pack.one_page_notes": lifecycle === "quarantined" ? 0 : 1,
      "study_pack.practice_item": lifecycle === "quarantined" ? 0 : 3,
      "study_pack.review_task": lifecycle === "quarantined" ? 0 : 1,
    },
    artifacts: content,
    candidate_skill_links: lifecycle === "quarantined" ? [] : [{
      artifact_id: artifactId(0),
      label: "资料复述",
      skill_id: null,
      status: "unconfirmed_candidate",
      taxonomy_version: null,
      taxonomy_digest: null,
    }],
    review: {
      accepted: reviewed,
      decision_count: decisions.length,
      accepted_count: decisions.length,
      decision_refs: decisions,
      reason_codes: [],
    },
    quarantine_reason: lifecycle === "quarantined" ? "source_insufficient_for_pack" : null,
    generator: { id: "extractive-local@1", model_calls: 0, network_calls: 0, ocr_calls: 0 },
    learning_projection_writes: { kt: false, misconception: false, today_plan: false, review_schedule: false },
    created_at: "2026-07-12T00:00:00+00:00",
    updated_at: "2026-07-12T00:00:00+00:00",
    links: {
      self: `/v1/study-packs/${PACK_ID}`,
      commands: `/v1/study-packs/${PACK_ID}/commands`,
      replay: `/v1/study-packs/${PACK_ID}/replay`,
    },
    ...overrides,
  };
}

function launch(origin = "human_local_interactive", overrides = {}) {
  return {
    schema_version: "lumi.study-pack-launch.v1",
    pack_id: PACK_ID,
    pack_version: 3,
    artifact_id: artifactId(4),
    artifact_version: 1,
    item_kind: "cloze_exact_v1",
    prompt: "先确认____。",
    scorer: { kind: "cloze_exact_v1", version: "1.0.0" },
    activity_kind: "within_pack_practice",
    evidence_origin: origin,
    links: {
      pack: `/v1/study-packs/${PACK_ID}`,
      attempts: `/v1/study-pack-items/${artifactId(4)}/attempts`,
    },
    ...overrides,
  };
}

function launchContext(index = 4, scorer = { kind: "cloze_exact_v1", version: "1.0.0" }) {
  return { packId: PACK_ID, artifactId: artifactId(index), artifactVersion: 1, scorer };
}

function launchFor(index, origin = "human_local_interactive") {
  return launch(origin, {
    artifact_id: artifactId(index),
    links: { pack: `/v1/study-packs/${PACK_ID}`, attempts: `/v1/study-pack-items/${artifactId(index)}/attempts` },
  });
}

function attemptResult(origin = "human_local_interactive", overrides = {}) {
  return {
    schema_version: "lumi.study-pack-attempt-result.v1",
    pack_id: PACK_ID,
    pack_version: 4,
    attempt: {
      schema_version: "lumi.study-pack-attempt.v1",
      attempt_id: `t_${"E".repeat(40)}`,
      pack_id: PACK_ID,
      artifact_id: artifactId(4),
      artifact_version: 1,
      answer_digest: HASH,
      correct: true,
      score: 1,
      evidence_origin: origin,
      activity_kind: "within_pack_practice",
      scorer_id: "cloze_exact_v1@1.0.0",
    },
    result: { correct: true, score: 1, max_score: 1 },
    answer: "统计口径",
    explanation: "先确认统计口径。",
    cited_source_context: [
      {
        field_pointer: "/answer",
        span_id: SPAN_ID,
        locator_kind: "section",
        locator_index: 1,
        start_offset: 3,
        end_offset: 7,
        excerpt: "统计口径",
      },
      {
        field_pointer: "/explanation",
        span_id: SPAN_ID,
        locator_kind: "section",
        locator_index: 1,
        start_offset: 0,
        end_offset: 9,
        excerpt: "先确认统计口径。",
      },
    ],
    learning_projection_writes: { kt: false, misconception: false, today_plan: false, review_schedule: false },
    idempotent_replay: false,
    links: { pack: `/v1/study-packs/${PACK_ID}`, replay: `/v1/study-packs/${PACK_ID}/replay` },
    ...overrides,
  };
}

test("Study Pack route helpers close every public path", () => {
  assert.equal(studyPackPath(PACK_ID), `/v1/study-packs/${PACK_ID}`);
  assert.equal(studyPackCommandPath(PACK_ID), `/v1/study-packs/${PACK_ID}/commands`);
  assert.equal(studyPackCitationPath(PACK_ID, SPAN_ID), `/v1/study-packs/${PACK_ID}/citations/${SPAN_ID}`);
  assert.equal(studyPackLaunchPath(artifactId(4)), `/v1/study-pack-items/${artifactId(4)}/launch`);
  assert.equal(studyPackAttemptPath(artifactId(4)), `/v1/study-pack-items/${artifactId(4)}/attempts`);
  assert.throws(() => studyPackPath("/Users/me/private.pdf"), /identifier/i);
});

test("create, review, and publish use closed bodies and authoritative lifecycle projections", () => {
  assert.deepEqual(buildStudyPackCreate({
    title: "  资料分析基础  ",
    source: { kind: "pasted_text", text: "第一条。\n\n第二条。" },
    commandId: COMMAND_ID,
  }), {
    title: "资料分析基础",
    source: { kind: "pasted_text", text: "第一条。\n\n第二条。" },
    command_id: COMMAND_ID,
  });
  const draft = normalizeStudyPackDetail(detail("draft"), { packId: PACK_ID });
  assert.deepEqual(buildStudyPackCommand({ pack: draft, action: "request_review", commandId: COMMAND_ID }), {
    action: "request_review", expected_version: 1, command_id: COMMAND_ID,
  });
  const review = normalizeStudyPackDetail(detail("review"), { packId: PACK_ID });
  assert.equal(review.lifecycle, "review");
  assert.equal(review.review.accepted, true);
  assert.deepEqual(buildStudyPackCommand({ pack: review, action: "publish", commandId: COMMAND_ID }), {
    action: "publish", expected_version: 2, command_id: COMMAND_ID,
  });
  assert.equal(normalizeStudyPackDetail(detail("published"), { packId: PACK_ID }).lifecycle, "published");
  assert.throws(() => normalizeStudyPackDetail(detail("published", { invented_mastery: 0.9 }), { packId: PACK_ID }), /unknown/i);
});

test("detail and command responses are bound to the exact request and version transition", () => {
  const otherPackId = `p_${"P".repeat(40)}`;
  assert.throws(() => normalizeStudyPackDetail(detail("draft"), { packId: otherPackId }), /requested pack/i);
  assert.throws(() => normalizeStudyPackDetail(detail("draft")), /request context/i);
  assert.equal(normalizeStudyPackDetail(detail("draft"), {
    creation: true,
    title: "资料分析基础",
    sourceKind: "pasted_text",
  }).version, 1);
  const reviewed = normalizeStudyPackDetail(detail("review"), {
    packId: PACK_ID,
    action: "request_review",
    expectedVersion: 1,
    previousLifecycle: "draft",
  });
  assert.equal(reviewed.version, 2);
  assert.throws(() => normalizeStudyPackDetail(detail("review", { version: 3 }), {
    packId: PACK_ID,
    action: "request_review",
    expectedVersion: 1,
    previousLifecycle: "draft",
  }), /advance exactly once/i);
  assert.throws(() => normalizeStudyPackDetail(detail("published"), {
    packId: PACK_ID,
    action: "publish",
    expectedVersion: 2,
    previousLifecycle: "draft",
  }), /original lifecycle/i);
});

test("duplicate artifacts, decisions, unsafe candidate links, and lifecycle mismatches fail closed", () => {
  const duplicateArtifact = structuredClone(detail("draft"));
  duplicateArtifact.artifacts[1].artifact_id = duplicateArtifact.artifacts[0].artifact_id;
  assert.throws(() => normalizeStudyPackDetail(duplicateArtifact, { packId: PACK_ID }), /duplicate artifact/i);

  const duplicateDecision = structuredClone(detail("review"));
  duplicateDecision.review.decision_refs[1].decision_id = duplicateDecision.review.decision_refs[0].decision_id;
  assert.throws(() => normalizeStudyPackDetail(duplicateDecision, { packId: PACK_ID }), /duplicate verifier decision/i);

  const duplicateBinding = structuredClone(detail("review"));
  duplicateBinding.review.decision_refs[1].artifact_id = duplicateBinding.review.decision_refs[0].artifact_id;
  duplicateBinding.review.decision_refs[1].artifact_digest = duplicateBinding.review.decision_refs[0].artifact_digest;
  assert.throws(() => normalizeStudyPackDetail(duplicateBinding, { packId: PACK_ID }), /duplicate verifier decision artifact|exactly bind/i);

  const wrongDigest = structuredClone(detail("review"));
  wrongDigest.review.decision_refs[0].artifact_digest = "b".repeat(64);
  assert.throws(() => normalizeStudyPackDetail(wrongDigest, { packId: PACK_ID }), /exactly bind/i);

  const wrongAcceptedCount = structuredClone(detail("review"));
  wrongAcceptedCount.review.accepted_count -= 1;
  assert.throws(() => normalizeStudyPackDetail(wrongAcceptedCount, { packId: PACK_ID }), /accepted count mismatch/i);

  const lifecycleMismatch = structuredClone(detail("published"));
  lifecycleMismatch.artifacts[0].lifecycle = "review";
  assert.throws(() => normalizeStudyPackDetail(lifecycleMismatch, { packId: PACK_ID }), /lifecycle does not match/i);

  const duplicateCandidate = structuredClone(detail("draft"));
  duplicateCandidate.candidate_skill_links.push(structuredClone(duplicateCandidate.candidate_skill_links[0]));
  assert.throws(() => normalizeStudyPackDetail(duplicateCandidate, { packId: PACK_ID }), /duplicate candidate/i);
});

test("note, card, and review citations require exact unique field coverage", () => {
  const missingNote = structuredClone(detail("draft"));
  missingNote.artifacts[0].content.citations = [];
  assert.throws(() => normalizeStudyPackDetail(missingNote, { packId: PACK_ID }), /citations|citation field/i);

  const duplicateNote = structuredClone(detail("draft"));
  duplicateNote.artifacts[0].content.citations.push(structuredClone(duplicateNote.artifacts[0].content.citations[0]));
  assert.throws(() => normalizeStudyPackDetail(duplicateNote, { packId: PACK_ID }), /duplicate citation/i);

  const wrongCardPointer = structuredClone(detail("draft"));
  wrongCardPointer.artifacts[1].content.citations[0].field_pointer = "/question";
  assert.throws(() => normalizeStudyPackDetail(wrongCardPointer, { packId: PACK_ID }), /exactly cover/i);

  const duplicateReviewPointer = structuredClone(detail("draft"));
  duplicateReviewPointer.artifacts[7].content.citations.push(structuredClone(duplicateReviewPointer.artifacts[7].content.citations[0]));
  assert.throws(() => normalizeStudyPackDetail(duplicateReviewPointer, { packId: PACK_ID }), /duplicate citation/i);
});

test("launch and attempt contracts disclose answers only after a human submission", () => {
  const normalizedLaunch = normalizeStudyPackLaunch(launch(), launchContext());
  assert.equal(normalizedLaunch.prompt, "先确认____。");
  assert.equal("answer" in normalizedLaunch, false);
  assert.deepEqual(buildStudyPackAttempt({ launch: normalizedLaunch, learnerAnswer: " 统计口径 ", commandId: COMMAND_ID }), {
    learner_answer: "统计口径", expected_pack_version: 3, expected_artifact_version: 1, command_id: COMMAND_ID,
  });
  const result = normalizeStudyPackAttemptResult(attemptResult(), { launch: normalizedLaunch });
  assert.equal(result.answer, "统计口径");
  assert.equal(result.explanation, "先确认统计口径。");
  assert.equal(result.citedContext[0].excerpt, "统计口径");
});

test("launch and attempt reject wrong artifact, pack, version, and published scorer context", () => {
  assert.throws(() => normalizeStudyPackLaunch(launch(), launchContext(5)), /requested artifact/i);
  assert.throws(() => normalizeStudyPackLaunch(launch(), launchContext(4, { kind: "normalized_exact_v1", version: "1.0.0" })), /scorer/i);
  const normalizedLaunch = normalizeStudyPackLaunch(launch(), launchContext());

  const wrongArtifact = attemptResult("human_local_interactive", {
    attempt: { ...attemptResult().attempt, artifact_id: artifactId(5) },
  });
  assert.throws(() => normalizeStudyPackAttemptResult(wrongArtifact, { launch: normalizedLaunch }), /launched artifact/i);

  const wrongVersion = attemptResult("human_local_interactive", { pack_version: 5 });
  assert.throws(() => normalizeStudyPackAttemptResult(wrongVersion, { launch: normalizedLaunch }), /advance exactly once/i);

  const wrongScorer = attemptResult("human_local_interactive", {
    attempt: { ...attemptResult().attempt, scorer_id: "normalized_exact_v1@1.0.0" },
  });
  assert.throws(() => normalizeStudyPackAttemptResult(wrongScorer, { launch: normalizedLaunch }), /scorer/i);

  const otherPack = attemptResult("human_local_interactive", { pack_id: `p_${"P".repeat(40)}` });
  assert.throws(() => normalizeStudyPackAttemptResult(otherPack, { launch: normalizedLaunch }), /launched pack/i);
});

test("PDF bytes are encoded in the browser and paths never enter the source union", async () => {
  const bytes = Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37]);
  assert.equal(arrayBufferToBase64(bytes.buffer), "JVBERi0xLjc=");
  const source = await pdfFileToSource({
    name: "notes.pdf",
    type: "application/pdf",
    size: bytes.length,
    async arrayBuffer() { return bytes.buffer; },
  });
  assert.deepEqual(source, { kind: "text_pdf", pdf_base64: "JVBERi0xLjc=" });
  assert.equal("path" in source, false);
  assert.throws(() => buildStudyPackCreate({ title: "路径", source: { kind: "text_pdf", pdf_base64: source.pdf_base64, path: "/tmp/a.pdf" }, commandId: COMMAND_ID }), /unknown/i);
});

test("resolved citations bind the requested span and frozen source exactly", () => {
  const payload = {
    schema_version: "lumi.source-citation.v1",
    verified: true,
    span_id: SPAN_ID,
    document_id: DOCUMENT_ID,
    source_version: 1,
    normalized_source_sha256: HASH,
    locator_kind: "section",
    locator_index: 1,
    start_offset: 0,
    end_offset: 9,
    slice_sha256: HASH,
    excerpt: "先确认统计口径。",
    links: { pack: `/v1/study-packs/${PACK_ID}` },
  };
  const expected = { packId: PACK_ID, spanId: SPAN_ID, documentId: DOCUMENT_ID, sourceVersion: 1, normalizedSha256: HASH };
  assert.equal(normalizeStudyPackCitation(payload, expected).verified, true);
  assert.throws(() => normalizeStudyPackCitation({ ...payload, document_id: `d_${"P".repeat(40)}` }, expected), /source document/i);
  assert.throws(() => normalizeStudyPackCitation({ ...payload, source_version: 2 }, expected), /source version/i);
  assert.throws(() => normalizeStudyPackCitation({ ...payload, normalized_source_sha256: "b".repeat(64) }, expected), /frozen source/i);
});

test("evaluation_fixture launch and persisted attempt data fail closed", () => {
  assert.throws(() => normalizeStudyPackLaunch(launch("evaluation_fixture"), launchContext()), (error) => error?.code === "evaluation_fixture_rejected");
  const humanLaunch = normalizeStudyPackLaunch(launch(), launchContext());
  assert.throws(() => normalizeStudyPackAttemptResult(attemptResult("evaluation_fixture"), { launch: humanLaunch }), (error) => error?.code === "evaluation_fixture_rejected");
});

test("active-practice projection contains no notes, cards, answers, citations, or explanation", () => {
  const projection = createActivePracticeProjection(normalizeStudyPackLaunch(launch(), launchContext()));
  const serialized = JSON.stringify(projection);
  for (const forbidden of ["answer", "explanation", "citation", "claims", "cards", "excerpt"]) assert.doesNotMatch(serialized, new RegExp(forbidden, "i"));
  assert.deepEqual(Object.keys(projection), ["packId", "artifactId", "prompt", "itemKind", "evidenceOrigin"]);
});

test("stable service errors map to plain retry and conflict copy", () => {
  assert.deepEqual(studyPackErrorCopy({ kind: "unavailable" }).state, "offline");
  assert.equal(studyPackErrorCopy({ code: "stale_version" }).state, "stale");
  assert.match(studyPackErrorCopy({ code: "pdf_text_unavailable_ocr_required" }).message, /扫描图片/);
  assert.match(studyPackErrorCopy({ code: "command_conflict" }).message, /重新读取/);
});

test("write recovery retains only ambiguous commands and receipts require fresh projections", () => {
  assert.deepEqual(studyPackWriteRecovery({ kind: "unavailable", code: "request_timeout" }), {
    strategy: "retry_same_command", retainCommandId: true, refresh: false, relaunch: false,
  });
  assert.deepEqual(studyPackWriteRecovery({ code: "stale_version" }), {
    strategy: "refresh_relaunch", retainCommandId: false, refresh: true, relaunch: true,
  });
  assert.deepEqual(studyPackWriteRecovery({ code: "command_conflict" }), {
    strategy: "refresh_new_command", retainCommandId: false, refresh: true, relaunch: false,
  });
  assert.equal(studyPackReceiptRequiresRefresh({ idempotentReplay: true }), true);
  assert.equal(studyPackReceiptRequiresRefresh({ idempotentReplay: false }), false);
});

test("empty, quarantine, and completed states remain explicit and isolated", () => {
  assert.deepEqual(normalizeStudyPackList({ schema_version: "lumi.study-pack-list.v1", count: 0, items: [] }), []);
  const quarantine = normalizeStudyPackDetail(detail("quarantined"), { packId: PACK_ID });
  assert.equal(quarantine.lifecycle, "quarantined");
  assert.equal(quarantine.artifactCounts.total, 0);
  assert.equal(quarantine.quarantineReason, "source_insufficient_for_pack");

  const expectedIds = [4, 5, 6].map(artifactId);
  const results = [4, 5, 6].map((artifactIndex, index) => {
    const normalizedLaunch = normalizeStudyPackLaunch(launchFor(artifactIndex), launchContext(artifactIndex));
    return {
      ...normalizeStudyPackAttemptResult(attemptResult("human_local_interactive", {
        attempt: {
          ...attemptResult().attempt,
          attempt_id: `t_${String.fromCharCode(69 + index).repeat(40)}`,
          artifact_id: artifactId(artifactIndex),
        },
      }), { launch: normalizedLaunch }),
      correct: index !== 2,
    };
  });
  const summary = summarizePracticeResults(results, expectedIds);
  assert.deepEqual({ completed: summary.completed, count: summary.count, correct: summary.correct }, { completed: true, count: 3, correct: 2 });
  assert.throws(() => summarizePracticeResults(results.slice(0, 2), expectedIds), /exactly three/i);
  assert.throws(() => summarizePracticeResults([results[0], results[0], results[2]], expectedIds), /expected practice order|distinct/i);
  assert.throws(() => summarizePracticeResults(results, [expectedIds[0], expectedIds[0], expectedIds[2]]), /distinct/i);
  assert.throws(() => summarizePracticeResults([results[1], results[0], results[2]], expectedIds), /expected practice order/i);

  const viewSource = readFileSync(new URL("./StudyPackViews.jsx", import.meta.url), "utf8");
  assert.match(viewSource, /data-state="empty"/);
  assert.match(viewSource, /data-state="quarantined"/);
  assert.match(viewSource, /data-state="completed"/);
  assert.match(viewSource, /evaluation-fixture/);
});

test("Study Pack view source keeps writes guarded, partial reads isolated, and citations fail closed", () => {
  const viewSource = readFileSync(new URL("./StudyPackViews.jsx", import.meta.url), "utf8");
  const apiSource = readFileSync(new URL("./hermesApi.js", import.meta.url), "utf8");
  assert.match(viewSource, /inFlightRef\.current/);
  assert.match(viewSource, /operationRef\.current/);
  assert.match(viewSource, /Promise\.allSettled/);
  assert.match(viewSource, /studyPackWriteRecovery/);
  assert.match(viewSource, /phase: "recovering"/);
  assert.doesNotMatch(viewSource, /\|\|\s*content\.citations\[0\]/);
  assert.doesNotMatch(viewSource, /<main\b/);
  assert.doesNotMatch(viewSource, /role="row"/);
  assert.match(apiSource, /item\?\.content\?\.scorer \|\| item\?\.scorer/);
  assert.match(apiSource, /studyPackReceiptRequiresRefresh/);
});

test("StrictMode lifecycle replay re-arms every async write guard and clears in-flight state", () => {
  const source = readFileSync(new URL("./StudyPackViews.jsx", import.meta.url), "utf8");
  const componentSource = (name, nextMarker) => {
    const start = source.indexOf(`function ${name}`);
    const end = source.indexOf(nextMarker, start + 1);
    assert.notEqual(start, -1, name);
    assert.notEqual(end, -1, `${name} end marker`);
    return source.slice(start, end);
  };
  const guarded = [
    componentSource("StudyPackImport", "function CitationButton"),
    componentSource("StudyPackDetail", "function PracticeError"),
    componentSource("StudyPackPractice", "export function StudyPackMaterials"),
  ];
  for (const section of guarded) {
    const cleanup = section.indexOf("return () =>");
    assert.ok(cleanup > 0, "guard requires an effect cleanup");
    assert.ok(section.indexOf("aliveRef.current = true;") > 0, "effect setup must re-arm aliveRef");
    assert.ok(section.indexOf("aliveRef.current = true;") < cleanup, "aliveRef must re-arm before cleanup is declared");
    assert.ok(section.indexOf("inFlightRef.current = false;") < cleanup, "effect setup must clear stale in-flight state");
    assert.ok(section.indexOf("aliveRef.current = false;", cleanup) > cleanup, "cleanup must reject genuine late responses");
    assert.ok(section.indexOf("inFlightRef.current = false;", cleanup) > cleanup, "cleanup must not leave in-flight stuck");
    assert.ok(section.indexOf("operationRef.current += 1;", cleanup) > cleanup, "cleanup must invalidate the prior operation");
  }
});
