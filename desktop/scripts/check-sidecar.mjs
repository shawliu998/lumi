import { spawn, execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdir, mkdtemp, readFile, readdir, readlink, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);
const desktopRoot = resolve(import.meta.dirname, "..");
const workspaceRoot = resolve(desktopRoot, "..");
const checkBundledSidecar = process.argv.includes("--bundle");
const appPath = resolve(desktopRoot, "src-tauri/target/debug/bundle/macos/Lumi.app");
const launcher = checkBundledSidecar
  ? resolve(appPath, "Contents/MacOS/hermes-sidecar")
  : resolve(desktopRoot, "src-tauri/binaries/hermes-sidecar-aarch64-apple-darwin");
const runtimeDirectory = checkBundledSidecar
  ? resolve(appPath, "Contents/Resources/sidecar-runtime")
  : resolve(desktopRoot, "src-tauri/resources/sidecar-runtime");
const EXPECTED_SIDECAR_VERSION = "0.3.0";
const EXPECTED_STUDY_PACK_FEATURE = "local-cited-study-pack-v1";
const EXPECTED_PRODUCT_ACTIVITY_COUNT = 2;
const TEST_INPUT = "LUMI_DESKTOP_TEST_INPUT_NON_LEARNER";
const TEST_EVIDENCE = Object.freeze({
  test_input_non_learner: true,
  learner_projection_eligible: false,
});
const EVALUATION_ATTEMPT_ORIGIN = "evaluation_fixture";
const LEARNING_TABLES = Object.freeze([
  "content_snapshots",
  "review_schedule_tasks",
  "schedule_command_results",
  "schedule_events",
  "schedule_migrations",
  "today_plan_tasks",
  "today_plans",
  "trace_events",
]);

function assertCheck(condition, code) {
  if (!condition) throw new Error(`Lumi sidecar check failed: ${code}`);
}

function opaquePublicId(prefix, label) {
  const alphabet = "ABCDEFGHIJKLMNOP";
  const digest = createHash("sha256").update(label).digest().subarray(0, 20);
  return `${prefix}_${[...digest]
    .map((byte) => `${alphabet[byte >> 4]}${alphabet[byte & 15]}`)
    .join("")}`;
}

function opaqueCommand(label) {
  return opaquePublicId("c", label);
}

async function bundleTreeDigest(root) {
  const digest = createHash("sha256");
  let fileCount = 0;

  async function visit(path, relativePath) {
    const metadata = await lstat(path);
    digest.update(`${relativePath}\0${metadata.mode}\0`);
    if (metadata.isDirectory()) {
      digest.update("directory\0");
      const entries = await readdir(path);
      for (const entry of entries.sort()) {
        await visit(resolve(path, entry), `${relativePath}/${entry}`);
      }
      return;
    }
    fileCount += 1;
    if (metadata.isSymbolicLink()) {
      digest.update(`symlink\0${await readlink(path)}\0`);
      return;
    }
    if (metadata.isFile()) {
      digest.update("file\0");
      digest.update(await readFile(path));
      return;
    }
    digest.update("other\0");
  }

  await visit(root, ".");
  return { sha256: digest.digest("hex"), file_count: fileCount };
}

function reserveLoopbackPort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen({ host: "127.0.0.1", port: 0 }, () => {
      const address = server.address();
      server.close((error) => (error ? reject(error) : resolvePort(address.port)));
    });
  });
}

async function requestJson(port, path, { method = "GET", body, timeoutMs = 4_000 } = {}) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, {
    method,
    headers: {
      Host: `127.0.0.1:${port}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs)
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("Lumi sidecar check failed: non_json_response");
  }
  return { status: response.status, body: payload };
}

function requestHealth(port) {
  return requestJson(port, "/v1/health");
}

async function waitForHealth(port, sidecar, timeoutMs = 16_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (sidecar.child.exitCode !== null || sidecar.child.signalCode !== null) {
      throw new Error("Lumi sidecar check failed: sidecar_exited_before_health");
    }
    try {
      const health = await requestHealth(port);
      if (
        health.status === 200 &&
        health.body.status === "ok" &&
        health.body.service === "hermes-local-sidecar" &&
        health.body.version === EXPECTED_SIDECAR_VERSION &&
        health.body.local_only === true
      ) {
        return health.body;
      }
    } catch {
      // The frozen runtime has a short cold start; retry without logging paths.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  }
  throw new Error("Lumi sidecar check failed: health_timeout");
}

function waitForExit(child, timeoutMs = 5_000) {
  return new Promise((resolveExit, reject) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      return resolveExit({ code: child.exitCode, signal: child.signalCode });
    }
    const timer = setTimeout(
      () => reject(new Error("Lumi sidecar check failed: process_exit_timeout")),
      timeoutMs
    );
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolveExit({ code, signal });
    });
  });
}

async function processGroupPids(groupId) {
  const { stdout } = await execFile("ps", ["-axo", "pid=,pgid="]);
  return stdout
    .split("\n")
    .map((line) => line.trim().split(/\s+/).map(Number))
    .filter(([pid, pgid]) => Number.isInteger(pid) && pgid === groupId)
    .map(([pid]) => pid);
}

async function waitForEmptyProcessGroup(groupId, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await processGroupPids(groupId)).length === 0) return;
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  }
  throw new Error("Lumi sidecar check failed: orphan_sidecar_or_pdf_worker");
}

function spawnSidecar(port, database, environment) {
  const child = spawn(launcher, ["--db", database, "serve", "--port", String(port)], {
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
    env: environment,
  });
  // Consume both pipes so a bounded diagnostic cannot deadlock the child. The
  // contents are deliberately not included in release evidence.
  child.stdout.resume();
  child.stderr.resume();
  return { child, processGroup: child.pid };
}

async function stopSidecar(sidecar, port) {
  const exit = waitForExit(sidecar.child);
  sidecar.child.kill("SIGTERM");
  await exit;
  await waitForEmptyProcessGroup(sidecar.processGroup);
  try {
    await requestHealth(port);
    throw new Error("Lumi sidecar check failed: health_after_termination");
  } catch (error) {
    if (error.message === "Lumi sidecar check failed: health_after_termination") throw error;
  }
}

async function initializeLearningProjections(port) {
  for (const path of ["/v1/review-schedule", "/v1/misconceptions", "/v1/skills/report"]) {
    const response = await requestJson(port, path);
    assertCheck(response.status === 200, "learning_projection_unavailable");
  }
}

async function verifyReviewedXingceCatalog(port) {
  const catalog = await requestJson(port, "/v1/xingce/coverage");
  assertCheck(catalog.status === 200, "xingce_catalog_unavailable");
  const { summary, items } = catalog.body;
  assertCheck(summary?.total_subtypes === 31, "xingce_catalog_total_mismatch");
  assertCheck(summary?.released_subtypes === 31, "xingce_catalog_released_count_mismatch");
  assertCheck(summary?.reviewed_release_ready_subtypes === 0, "xingce_catalog_reviewed_count_mismatch");
  assertCheck(summary?.available_subtypes === 31, "xingce_catalog_available_count_mismatch");
  assertCheck(summary?.is_complete === true, "xingce_catalog_release_incomplete");
  assertCheck(items?.length === 31 && items.every((item) => item.availability === "available"), "xingce_catalog_unavailable_pack");
  const tableMaterial = items.find((item) => item.subtype_id === "xingce.data.table_material");
  assertCheck(tableMaterial?.launch === "/v1/xingce/adaptive/xingce.data.table_material/workspace", "xingce_table_material_launch_missing");
  const workspace = await requestJson(port, tableMaterial.launch);
  assertCheck(workspace.status === 200 && workspace.body?.available === true, "xingce_table_material_workspace_unavailable");
  assertCheck(workspace.body?.entry_items?.length > 0, "xingce_table_material_entry_missing");
  assertCheck(!JSON.stringify(workspace.body).includes("correct_option"), "xingce_workspace_answer_leaked");
  return {
    total_subtypes: summary.total_subtypes,
    released_subtypes: summary.released_subtypes,
    reviewed_release_ready_subtypes: summary.reviewed_release_ready_subtypes,
    available_subtypes: summary.available_subtypes,
    table_material_workspace_verified: true,
  };
}

async function runPackagedIdentifierGuards(port, initialHealth) {
  const rejectedRunIds = [
    "legacy-safe-run",
    "0123456789abcdef0123456789abcdef",
    "550e8400-e29b-41d4-a716-446655440000",
    "run-013800138000",
    "run-11010519491231002X",
    "sk_live_" + "A".repeat(32),
    "ghp_" + "A".repeat(36),
    "github_pat_" + "A".repeat(82),
    "AIzaSy" + "A".repeat(33),
    "npm_" + "A".repeat(36),
    "xoxb-" + "A".repeat(24) + "-" + "B".repeat(24),
  ];
  const setupAttempt = {
    fixture_id: "xingce.data-analysis.growth-rate.synthetic-01",
    response: TEST_INPUT,
    confidence: 0.5,
    response_time_seconds: 20,
  };
  for (const runId of rejectedRunIds) {
    const rejected = await requestJson(port, "/v1/attempts", {
      method: "POST",
      body: { ...setupAttempt, run_id: runId },
    });
    assertError(rejected, 400, "invalid_run_id");
  }
  const afterRejectedRuns = await requestHealth(port);
  assertCheck(
    afterRejectedRuns.body.run_count === initialHealth.run_count,
    "rejected_run_identifier_changed_run_count"
  );

  const accepted = await requestJson(port, "/v1/attempts", {
    method: "POST",
    body: {
      ...setupAttempt,
      run_id: opaquePublicId("r", "desktop-identifier-guard"),
    },
  });
  assertCheck(accepted.status === 201, "identifier_guard_setup_failed");
  assertCheck(accepted.body?.links?.trace && accepted.body?.links?.assist, "identifier_guard_links_missing");
  const traceBeforeRejectedCommands = await requestJson(port, accepted.body.links.trace);
  assertCheck(traceBeforeRejectedCommands.status === 200, "identifier_guard_trace_unavailable");

  const rejectedCommandIds = [
    "legacy-command",
    "0123456789abcdef0123456789abcdef",
    "550e8400-e29b-41d4-a716-446655440000",
    "cmd-013800138000",
    "cmd-11010519491231002X",
    "sk_live_" + "A".repeat(32),
    "ghp_" + "A".repeat(36),
    "github_pat_" + "A".repeat(82),
    "AIzaSy" + "A".repeat(33),
    "npm_" + "A".repeat(36),
    "xoxb-" + "A".repeat(24) + "-" + "B".repeat(24),
  ];
  for (const commandId of rejectedCommandIds) {
    const rejected = await requestJson(port, accepted.body.links.assist, {
      method: "POST",
      body: {
        phase: "probe",
        expected_version: accepted.body.state_version,
        expected_state: "awaiting_probe",
        prompt_instance_id: accepted.body.probe.prompt_instance_id,
        action: "next",
        elapsed_time_seconds: 1,
        command_id: commandId,
      },
    });
    assertError(rejected, 400, "invalid_command_id");
  }
  const traceAfterRejectedCommands = await requestJson(port, accepted.body.links.trace);
  assertCheck(traceAfterRejectedCommands.status === 200, "identifier_guard_trace_recheck_failed");
  assertCheck(
    JSON.stringify(traceAfterRejectedCommands.body) ===
      JSON.stringify(traceBeforeRejectedCommands.body),
    "rejected_command_identifier_changed_trace"
  );
  return {
    rejected_run_id_count: rejectedRunIds.length,
    rejected_command_id_count: rejectedCommandIds.length,
    rejected_command_trace_unchanged: true,
    accepted_setup_ephemeral_test_input: true,
  };
}

async function learningStateDigest(database) {
  const digest = createHash("sha256");
  for (const table of LEARNING_TABLES) {
    const schema = await execFile("sqlite3", [
      "-json",
      database,
      `PRAGMA table_info(\"${table}\");`,
    ]);
    const rows = await execFile(
      "sqlite3",
      ["-json", database, `SELECT * FROM \"${table}\" ORDER BY rowid;`],
      { maxBuffer: 16 * 1024 * 1024 }
    );
    digest.update(`${table}\0${schema.stdout}\0${rows.stdout}\0`);
  }
  return digest.digest("hex");
}

async function studyPackAttemptOriginCounts(database) {
  const { stdout } = await execFile("sqlite3", [
    "-json",
    database,
    "SELECT evidence_origin, COUNT(*) AS count FROM study_pack_attempts GROUP BY evidence_origin ORDER BY evidence_origin;",
  ]);
  const rows = JSON.parse(stdout || "[]");
  return Object.fromEntries(rows.map((row) => [row.evidence_origin, Number(row.count)]));
}

function assertLearningWritesDisabled(payload) {
  const writes = payload?.learning_projection_writes;
  assertCheck(writes && typeof writes === "object", "learning_write_contract_missing");
  assertCheck(
    ["kt", "misconception", "today_plan", "review_schedule"].every(
      (key) => writes[key] === false
    ),
    "study_pack_learning_write_enabled"
  );
}

function assertLaunchRedacted(launch) {
  const forbidden = new Set([
    "answer",
    "answer_key",
    "explanation",
    "citation",
    "citations",
    "cited_source_context",
    "span_ref",
  ]);
  const visit = (value) => {
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (!value || typeof value !== "object") return;
    for (const [key, nested] of Object.entries(value)) {
      assertCheck(!forbidden.has(key.toLowerCase()), "pre_answer_material_exposed");
      visit(nested);
    }
  };
  visit(launch);
}

function assertError(response, status, code) {
  assertCheck(response.status === status, `unexpected_error_status_${code}`);
  assertCheck(response.body?.error?.code === code, `unexpected_error_code_${code}`);
}

function assertPackProjection(pack, inputKind) {
  assertCheck(pack.schema_version === "lumi.study-pack-detail.v1", "pack_schema_mismatch");
  assertCheck(pack.source?.input_kind === inputKind, "source_kind_mismatch");
  assertCheck(/^[a-f0-9]{64}$/.test(pack.source?.original_sha256 ?? ""), "source_hash_missing");
  assertCheck(/^[a-f0-9]{64}$/.test(pack.source?.normalized_sha256 ?? ""), "normalized_hash_missing");
  assertCheck(pack.artifact_counts?.["study_pack.practice_item"] === 3, "practice_count_mismatch");
  assertCheck(
    pack.candidate_skill_links?.every((link) => link.status === "unconfirmed_candidate"),
    "candidate_skill_not_unconfirmed"
  );
  assertLearningWritesDisabled(pack);
}

async function runStudyPackFlow(port, database, fixture) {
  const create = await requestJson(port, "/v1/study-packs", {
    method: "POST",
    body: {
      title: fixture.title,
      source: fixture.source,
      command_id: opaqueCommand(`${fixture.label}-create`),
    },
    timeoutMs: 15_000,
  });
  assertCheck(create.status === 201, `${fixture.label}_create_failed`);
  assertPackProjection(create.body, fixture.inputKind);
  assertCheck(create.body.lifecycle === "draft" && create.body.version === 1, "draft_state_mismatch");
  if (fixture.inputKind === "text_pdf") {
    assertCheck(create.body.source.parser_name === "pypdf", "packaged_pdf_parser_mismatch");
    assertCheck(create.body.source.parser_version === "6.10.0", "packaged_pypdf_pin_mismatch");
  }

  const practice = create.body.artifacts?.find(
    (artifact) => artifact.artifact_type === "study_pack.practice_item"
  );
  assertCheck(practice?.artifact_id, "practice_item_missing");
  const draftLaunch = await requestJson(port, `/v1/study-pack-items/${practice.artifact_id}/launch`);
  assertError(draftLaunch, 409, "artifact_not_published");

  const review = await requestJson(port, `/v1/study-packs/${create.body.pack_id}/commands`, {
    method: "POST",
    body: {
      action: "request_review",
      expected_version: create.body.version,
      command_id: opaqueCommand(`${fixture.label}-review`),
    },
    timeoutMs: 15_000,
  });
  assertCheck(review.status === 200, `${fixture.label}_review_failed`);
  assertPackProjection(review.body, fixture.inputKind);
  assertCheck(review.body.lifecycle === "review" && review.body.review?.accepted === true, "review_state_mismatch");

  const publish = await requestJson(port, `/v1/study-packs/${review.body.pack_id}/commands`, {
    method: "POST",
    body: {
      action: "publish",
      expected_version: review.body.version,
      command_id: opaqueCommand(`${fixture.label}-publish`),
    },
  });
  assertCheck(publish.status === 200, `${fixture.label}_publish_failed`);
  assertPackProjection(publish.body, fixture.inputKind);
  assertCheck(publish.body.lifecycle === "published", "publish_state_mismatch");

  const note = publish.body.artifacts?.find(
    (artifact) => artifact.artifact_type === "study_pack.one_page_notes"
  );
  const spanId = note?.content?.citations?.[0]?.span_ref;
  assertCheck(spanId, "published_citation_missing");
  const citation = await requestJson(
    port,
    `/v1/study-packs/${publish.body.pack_id}/citations/${spanId}`
  );
  assertCheck(citation.status === 200 && citation.body.verified === true, "citation_resolution_failed");
  assertCheck(/^[a-f0-9]{64}$/.test(citation.body.slice_sha256 ?? ""), "citation_hash_missing");
  assertCheck(citation.body.locator_kind === fixture.locatorKind, "citation_locator_mismatch");

  const currentPractice = publish.body.artifacts.find(
    (artifact) => artifact.artifact_id === practice.artifact_id
  );
  assertCheck(currentPractice?.links?.launch, "published_practice_link_missing");
  const launch = await requestJson(port, currentPractice.links.launch);
  assertCheck(launch.status === 200, "published_launch_failed");
  assertLaunchRedacted(launch.body);
  assertCheck(launch.body.scorer?.kind === launch.body.item_kind, "scorer_kind_mismatch");
  assertCheck(launch.body.scorer?.version === "1.0.0", "scorer_version_mismatch");
  assertCheck(launch.body.evidence_origin === EVALUATION_ATTEMPT_ORIGIN, "launch_attempt_origin_mismatch");
  assertCheck(launch.body.activity_kind === "within_pack_practice", "activity_kind_mismatch");

  assertCheck(TEST_EVIDENCE.test_input_non_learner === true, "test_input_evidence_missing");
  assertCheck(TEST_EVIDENCE.learner_projection_eligible === false, "test_input_projection_guard_missing");
  const attemptBody = {
    learner_answer: TEST_INPUT,
    expected_pack_version: launch.body.pack_version,
    expected_artifact_version: launch.body.artifact_version,
    command_id: opaqueCommand(`${fixture.label}-attempt`),
  };
  const attempt = await requestJson(port, launch.body.links.attempts, {
    method: "POST",
    body: attemptBody,
  });
  assertCheck(attempt.status === 201, `${fixture.label}_test_attempt_failed`);
  assertCheck(attempt.body.schema_version === "lumi.study-pack-attempt-result.v1", "attempt_schema_mismatch");
  assertCheck(/^t_[A-P]{40}$/.test(attempt.body.attempt?.attempt_id ?? ""), "attempt_id_mismatch");
  assertCheck(
    attempt.body.attempt?.evidence_origin === EVALUATION_ATTEMPT_ORIGIN,
    "saved_attempt_origin_mismatch"
  );
  assertCheck(typeof attempt.body.answer === "string" && attempt.body.answer.length > 0, "post_answer_reveal_missing");
  assertCheck(typeof attempt.body.explanation === "string" && attempt.body.explanation.length > 0, "post_answer_explanation_missing");
  assertCheck(Array.isArray(attempt.body.cited_source_context) && attempt.body.cited_source_context.length > 0, "post_answer_citation_missing");
  assertLearningWritesDisabled(attempt.body);

  const receiptReplay = await requestJson(port, launch.body.links.attempts, {
    method: "POST",
    body: attemptBody,
  });
  assertCheck(receiptReplay.status === 201, "attempt_receipt_replay_failed");
  assertCheck(receiptReplay.body.idempotent_replay === true, "attempt_receipt_not_idempotent");
  assertCheck(
    receiptReplay.body.attempt?.attempt_id === attempt.body.attempt?.attempt_id,
    "attempt_receipt_identity_changed"
  );

  const replay = await requestJson(port, `/v1/study-packs/${publish.body.pack_id}/replay`);
  assertCheck(replay.status === 200, "study_pack_replay_failed");
  assertCheck(replay.body.trace_verified === true && replay.body.projection_verified === true, "replay_verification_failed");
  assertCheck(!JSON.stringify(replay.body).includes(TEST_INPUT), "test_input_leaked_to_replay");

  const learningDigest = await learningStateDigest(database);
  return {
    packId: publish.body.pack_id,
    spanId,
    artifactId: practice.artifact_id,
    attemptId: attempt.body.attempt?.attempt_id,
    attemptPath: launch.body.links.attempts,
    attemptBody,
    learningDigest,
  };
}

async function verifyAfterRestart(port, database, record, baselineDigest) {
  await initializeLearningProjections(port);
  const current = await requestJson(port, `/v1/study-packs/${record.packId}`);
  assertCheck(current.status === 200 && current.body.lifecycle === "published", "restart_pack_projection_failed");
  assertPackProjection(current.body, current.body.source.input_kind);
  const citation = await requestJson(
    port,
    `/v1/study-packs/${record.packId}/citations/${record.spanId}`
  );
  assertCheck(citation.status === 200 && citation.body.verified === true, "restart_citation_failed");
  const replay = await requestJson(port, `/v1/study-packs/${record.packId}/replay`);
  assertCheck(replay.status === 200, "restart_replay_failed");
  assertCheck(replay.body.trace_verified === true && replay.body.projection_verified === true, "restart_replay_unverified");
  assertCheck(!JSON.stringify(replay.body).includes(TEST_INPUT), "restart_replay_test_input_leak");
  const durableReceipt = await requestJson(port, record.attemptPath, {
    method: "POST",
    body: record.attemptBody,
  });
  assertCheck(durableReceipt.status === 201, "restart_attempt_receipt_failed");
  assertCheck(durableReceipt.body.idempotent_replay === true, "restart_attempt_receipt_not_idempotent");
  assertCheck(durableReceipt.body.attempt?.attempt_id === record.attemptId, "restart_attempt_identity_changed");
  assertCheck(await learningStateDigest(database) === baselineDigest, "restart_learning_digest_changed");
}

const port = await reserveLoopbackPort();
const stateDirectory = await mkdtemp(resolve(tmpdir(), "lumi-sidecar-check-"));
const database = resolve(stateDirectory, "sidecar.sqlite3");
const isolatedHome = resolve(stateDirectory, "home");
const isolatedCache = resolve(stateDirectory, "cache");
const isolatedConfig = resolve(stateDirectory, "config");
const isolatedData = resolve(stateDirectory, "data");
const isolatedPycache = resolve(stateDirectory, "pycache");
await Promise.all([
  mkdir(isolatedHome),
  mkdir(isolatedCache),
  mkdir(isolatedConfig),
  mkdir(isolatedData),
  mkdir(isolatedPycache),
]);
const environment = {
  ...process.env,
  HERMES_SIDECAR_RUNTIME_DIR: runtimeDirectory,
  HOME: isolatedHome,
  TMPDIR: stateDirectory,
  XDG_CACHE_HOME: isolatedCache,
  XDG_CONFIG_HOME: isolatedConfig,
  XDG_DATA_HOME: isolatedData,
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHONPYCACHEPREFIX: isolatedPycache,
  PYTHONNOUSERSITE: "1",
  LUMI_INTERNAL_STUDY_PACK_ATTEMPT_ORIGIN: EVALUATION_ATTEMPT_ORIGIN,
  LUMI_INTERNAL_LEARNING_ATTEMPT_ORIGIN: EVALUATION_ATTEMPT_ORIGIN,
  LUMI_INTERNAL_EVALUATION_PROJECTION: "1",
};
const bundleTreeBefore = checkBundledSidecar ? await bundleTreeDigest(appPath) : undefined;
const bundleMtimeBefore = checkBundledSidecar ? (await lstat(appPath)).mtimeMs : undefined;
let sidecar = spawnSidecar(port, database, environment);

try {
  const health = await waitForHealth(port, sidecar);
  const capabilities = await requestJson(port, "/v1/capabilities");
  assertCheck(capabilities.status === 200, "capabilities_unavailable");
  assertCheck(capabilities.body.service_version === EXPECTED_SIDECAR_VERSION, "capability_version_mismatch");
  assertCheck(capabilities.body.api_version === "v1", "api_version_mismatch");
  assertCheck(capabilities.body.local_only === true, "non_local_capability");
  assertCheck(capabilities.body.scenario_count === 42, "scenario_count_mismatch");
  assertCheck(
    capabilities.body.product_activity_count === EXPECTED_PRODUCT_ACTIVITY_COUNT,
    "product_activity_count_mismatch",
  );
  assertCheck(capabilities.body.features?.includes(EXPECTED_STUDY_PACK_FEATURE), "study_pack_capability_missing");
  assertCheck(
    capabilities.body.features?.includes("local-product-activity-catalog-v1"),
    "product_activity_capability_missing",
  );
  const advertisedEndpoints = capabilities.body.endpoints ?? {};
  assertCheck(advertisedEndpoints.study_pack_create === "POST /v1/study-packs", "study_pack_create_route_missing");
  assertCheck(advertisedEndpoints.study_pack_item_attempt === "POST /v1/study-pack-items/{artifact_id}/attempts", "study_pack_attempt_route_missing");
  assertCheck(!Object.hasOwn(advertisedEndpoints, "run"), "removed_run_route_advertised");
  assertCheck(!JSON.stringify(capabilities.body).toLowerCase().includes("offline"), "offline_product_path_advertised");

  const xingceCatalogEvidence = await verifyReviewedXingceCatalog(port);

  const disabledRuns = await requestJson(port, "/v1/runs", {
    method: "POST",
    body: { mode: "offline", run_id: opaquePublicId("r", "disabled-public-runs") },
  });
  assertCheck(disabledRuns.status === 404, "public_batch_run_enabled");

  const identifierEvidence = await runPackagedIdentifierGuards(port, health);

  await initializeLearningProjections(port);
  const baselineDigest = await learningStateDigest(database);
  const pastedText = await readFile(
    resolve(workspaceRoot, "evals/fixtures/study_pack/pasted_text.txt"),
    "utf8"
  );
  const pdfBytes = await readFile(
    resolve(workspaceRoot, "evals/fixtures/study_pack/text_bearing_chinese.pdf")
  );
  const fixtures = [
    {
      label: "pasted",
      title: "Lumi P0.3 pasted-text fixture",
      inputKind: "pasted_text",
      locatorKind: "section",
      source: { kind: "pasted_text", text: pastedText },
    },
    {
      label: "pdf",
      title: "Lumi P0.3 text-PDF fixture",
      inputKind: "text_pdf",
      locatorKind: "page",
      source: { kind: "text_pdf", pdf_base64: pdfBytes.toString("base64") },
    },
  ];

  const records = [];
  for (const fixture of fixtures) {
    const record = await runStudyPackFlow(port, database, fixture);
    assertCheck(record.learningDigest === baselineDigest, `${fixture.label}_learning_digest_changed`);
    records.push(record);

    await stopSidecar(sidecar, port);
    sidecar = spawnSidecar(port, database, environment);
    await waitForHealth(port, sidecar);
    await verifyAfterRestart(port, database, record, baselineDigest);
  }

  const attemptOriginCounts = await studyPackAttemptOriginCounts(database);
  assertCheck(attemptOriginCounts.human_local_interactive === undefined, "human_study_pack_test_attempt_persisted");
  assertCheck(attemptOriginCounts[EVALUATION_ATTEMPT_ORIGIN] === fixtures.length, "evaluation_attempt_count_mismatch");
  assertCheck(Object.keys(attemptOriginCounts).length === 1, "unexpected_study_pack_attempt_origin");

  await stopSidecar(sidecar, port);
  sidecar = undefined;

  const source = checkBundledSidecar ? "bundled" : "staged";
  const evidence = {
    service_version: health.version,
    capability: EXPECTED_STUDY_PACK_FEATURE,
    source_kinds: fixtures.map((fixture) => fixture.inputKind),
    pack_count: records.length,
    restart_count: records.length,
    durable_receipt_replay_count: records.length,
    citation_verified_count: records.length,
    study_pack_attempt_origins: {
      evaluation_fixture: attemptOriginCounts[EVALUATION_ATTEMPT_ORIGIN],
      human_local_interactive: 0,
    },
    ...identifierEvidence,
    learning_state_sha256: baselineDigest,
    xingce_catalog: xingceCatalogEvidence,
    ...TEST_EVIDENCE,
    raw_source_saved_to_report: false,
    raw_answer_saved_to_report: false,
  };
  if (checkBundledSidecar) {
    evidence.app_tree_sha256 = bundleTreeBefore.sha256;
    evidence.app_tree_file_count = bundleTreeBefore.file_count;
    evidence.app_root_mtime_ms = bundleMtimeBefore;
    evidence.app_root_mtime_iso = new Date(bundleMtimeBefore).toISOString();
  }
  console.log(`Lumi ${source} sidecar P0.3 lifecycle check passed ${JSON.stringify(evidence)}`);
} finally {
  if (sidecar?.child.exitCode === null && sidecar?.child.signalCode === null) {
    try { process.kill(-sidecar.processGroup, "SIGKILL"); } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
    await waitForEmptyProcessGroup(sidecar.processGroup);
  }
  await rm(stateDirectory, { recursive: true, force: true });
  if (checkBundledSidecar) {
    const bundleTreeAfter = await bundleTreeDigest(appPath);
    const bundleMtimeAfter = (await lstat(appPath)).mtimeMs;
    if (
      bundleTreeAfter.sha256 !== bundleTreeBefore.sha256 ||
      bundleTreeAfter.file_count !== bundleTreeBefore.file_count ||
      bundleMtimeAfter !== bundleMtimeBefore
    ) {
      throw new Error("Lumi sidecar check failed: bundled_app_mutated");
    }
  }
}
