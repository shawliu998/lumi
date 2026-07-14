import { spawn, execFile as execFileCallback } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { promisify } from "node:util";
import { resolve } from "node:path";
import { createServer } from "node:net";

const execFile = promisify(execFileCallback);
const desktopRoot = resolve(import.meta.dirname, "..");
const workspaceRoot = resolve(desktopRoot, "..");
const appPath = resolve(desktopRoot, "src-tauri/target/debug/bundle/macos/Lumi.app");
const executable = resolve(appPath, "Contents/MacOS/hermes-desktop");
const EXPECTED_SIDECAR_VERSION = "0.3.0";
const EXPECTED_STUDY_PACK_FEATURE = "local-cited-study-pack-v1";
const INTERNAL_ATTEMPT_ORIGIN_ENV = "LUMI_INTERNAL_STUDY_PACK_ATTEMPT_ORIGIN";

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

async function requestJson(port, path, { method = "GET", body } = {}) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, {
    method,
    headers: {
      Host: `127.0.0.1:${port}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(2_000)
  });
  return { status: response.status, body: await response.json() };
}

function assertManaged(condition, code) {
  if (!condition) throw new Error(`managed app check failed: ${code}`);
}

async function verifyManagedProductOrigin(port) {
  const sourceText = await readFile(
    resolve(workspaceRoot, "evals/fixtures/study_pack/pasted_text.txt"),
    "utf8"
  );
  const created = await requestJson(port, "/v1/study-packs", {
    method: "POST",
    body: {
      title: "Lumi managed product-origin contract",
      command_id: `c_${"A".repeat(40)}`,
      source: { kind: "pasted_text", text: sourceText },
    },
  });
  assertManaged(created.status === 201, "product_origin_create_failed");
  const reviewed = await requestJson(port, `/v1/study-packs/${created.body.pack_id}/commands`, {
    method: "POST",
    body: {
      action: "request_review",
      expected_version: created.body.version,
      command_id: `c_${"B".repeat(40)}`,
    },
  });
  assertManaged(reviewed.status === 200, "product_origin_review_failed");
  const published = await requestJson(port, `/v1/study-packs/${created.body.pack_id}/commands`, {
    method: "POST",
    body: {
      action: "publish",
      expected_version: reviewed.body.version,
      command_id: `c_${"C".repeat(40)}`,
    },
  });
  assertManaged(published.status === 200, "product_origin_publish_failed");
  const practice = published.body.artifacts?.find(
    (artifact) => artifact.artifact_type === "study_pack.practice_item"
  );
  assertManaged(practice?.links?.launch, "product_origin_practice_missing");
  const launch = await requestJson(port, practice.links.launch);
  assertManaged(launch.status === 200, "product_origin_launch_failed");
  assertManaged(
    launch.body.evidence_origin === "human_local_interactive",
    "managed_product_origin_not_human_default"
  );
}

async function waitFor(predicate, description, timeoutMs = 16_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const value = await predicate();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  }
  throw new Error(`${description}: ${lastError?.message ?? "timed out"}`);
}

function waitForExit(child, description, timeoutMs = 16_000) {
  return new Promise((resolveExit, reject) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolveExit(child.exitCode);
    const timer = setTimeout(() => reject(new Error(`${description}: timed out`)), timeoutMs);
    child.once("exit", (code) => {
      clearTimeout(timer);
      resolveExit(code);
    });
  });
}

function spawnManagedApp(port, database, { exitAfterHealth = false, testMode } = {}) {
  // Keep lifecycle verification deterministic and isolate every debug run from
  // the learner's normal app database and saved-window state.
  const productionEnvironment = { ...process.env };
  delete productionEnvironment[INTERNAL_ATTEMPT_ORIGIN_ENV];
  return spawn(executable, ["-ApplePersistenceIgnoreState", "YES"], {
    stdio: "ignore",
    env: {
      ...productionEnvironment,
      HERMES_SIDECAR_PORT: String(port),
      HERMES_SIDECAR_DATABASE: database,
      ...(exitAfterHealth ? { HERMES_EXIT_AFTER_SIDECAR_HEALTH: "1" } : {}),
      ...(testMode ? { HERMES_SIDECAR_TEST_MODE: testMode } : {})
    }
  });
}

async function bundledSidecarPids() {
  const { stdout } = await execFile("ps", ["-axo", "pid=,command="]);
  return stdout
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.includes(`${appPath}/Contents/`) && line.includes("hermes-sidecar"))
    .map((line) => Number(line.split(/\s+/, 1)[0]))
    .filter(Number.isInteger);
}

async function waitForNoBundledSidecars(description) {
  await waitFor(
    async () => (await bundledSidecarPids()).length === 0,
    description,
    4_000
  );
}

async function removeBundledSidecars() {
  for (const pid of await bundledSidecarPids()) {
    try { process.kill(pid, "SIGTERM"); } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  for (const pid of await bundledSidecarPids()) {
    try { process.kill(pid, "SIGKILL"); } catch (error) {
      if (error.code !== "ESRCH") throw error;
    }
  }
  await waitForNoBundledSidecars("cleanup could not reap a bundled sidecar or worker");
}

const stateDirectory = await mkdtemp(resolve(tmpdir(), "lumi-managed-app-check-"));
let app;
let killedApp;
let failedApp;
let timeoutApp;
let blocker;
try {
  const port = await reserveLoopbackPort();
  app = spawnManagedApp(port, resolve(stateDirectory, "healthy.sqlite3"), {
    exitAfterHealth: true,
  });
  const health = await waitFor(async () => {
    const result = await requestJson(port, "/v1/health");
    return result.status === 200 &&
      result.body.local_only === true &&
      result.body.version === EXPECTED_SIDECAR_VERSION
      ? result.body
      : undefined;
  }, "managed app did not complete the sidecar health handshake");
  const capabilities = await requestJson(port, "/v1/capabilities");
  if (
    capabilities.status !== 200 ||
    capabilities.body.service_version !== EXPECTED_SIDECAR_VERSION ||
    !capabilities.body.features?.includes(EXPECTED_STUDY_PACK_FEATURE)
  ) {
    throw new Error("managed app sidecar did not advertise the frozen P0.3 capability");
  }
  await verifyManagedProductOrigin(port);

  await waitFor(async () => {
    try {
      await requestJson(port, "/v1/health");
      return false;
    } catch {
      return true;
    }
  }, "sidecar remained reachable after Lumi exited");
  const healthyExit = await waitForExit(app, "Lumi did not exit after its managed sidecar shut down");
  if (healthyExit !== 0) throw new Error(`healthy managed app exited with code ${healthyExit}`);
  await waitForNoBundledSidecars("healthy app exit left a bundled sidecar or worker");

  const abruptPort = await reserveLoopbackPort();
  killedApp = spawnManagedApp(
    abruptPort,
    resolve(stateDirectory, "abrupt.sqlite3")
  );
  await waitFor(async () => {
    const result = await requestJson(abruptPort, "/v1/health");
    return result.status === 200 && result.body.version === EXPECTED_SIDECAR_VERSION;
  }, "abrupt-exit app did not start its managed sidecar");
  killedApp.kill("SIGKILL");
  await waitForExit(killedApp, "abrupt-exit Lumi process did not terminate");
  await waitFor(async () => {
    try {
      await requestJson(abruptPort, "/v1/health");
      return false;
    } catch {
      return true;
    }
  }, "sidecar remained reachable after abrupt Lumi termination");
  await waitForNoBundledSidecars("abrupt app exit left a bundled sidecar or worker");

  const occupiedPort = await reserveLoopbackPort();
  blocker = createServer();
  await new Promise((resolveListen, reject) => {
    blocker.once("error", reject);
    blocker.listen({ host: "127.0.0.1", port: occupiedPort }, resolveListen);
  });
  failedApp = spawnManagedApp(
    occupiedPort,
    resolve(stateDirectory, "occupied.sqlite3")
  );
  const occupiedExit = await waitForExit(
    failedApp,
    "Lumi did not fail closed when its sidecar port was occupied"
  );
  if (occupiedExit === 0) throw new Error("occupied-port startup failure exited successfully");
  await waitForNoBundledSidecars("occupied-port failure left a bundled sidecar or worker");

  const timeoutPort = await reserveLoopbackPort();
  const timeoutStartedAt = Date.now();
  timeoutApp = spawnManagedApp(
    timeoutPort,
    resolve(stateDirectory, "timeout.sqlite3"),
    { testMode: "pdf-worker-health-timeout" }
  );
  const timeoutExit = await waitForExit(
    timeoutApp,
    "Lumi did not reap the frozen PDF worker after the health timeout",
    20_000
  );
  if (timeoutExit === 0) throw new Error("frozen PDF worker health timeout exited successfully");
  const timeoutElapsedMs = Date.now() - timeoutStartedAt;
  if (timeoutElapsedMs < 7_000 || timeoutElapsedMs > 20_000) {
    throw new Error(`frozen PDF worker health timeout duration was out of bounds: ${timeoutElapsedMs}ms`);
  }
  await waitForNoBundledSidecars("health timeout left a bundled sidecar or PDF worker");

  console.log(
    `Managed app health, P0.3 capability/default-human launch, graceful/abrupt exit, occupied-port, and frozen-worker timeout checks passed (sidecar ${health.version}; timeout ${timeoutElapsedMs}ms; no orphan processes).`
  );
} finally {
  if (app?.exitCode === null && app?.signalCode === null) app.kill("SIGKILL");
  if (killedApp?.exitCode === null && killedApp?.signalCode === null) killedApp.kill("SIGKILL");
  if (failedApp?.exitCode === null && failedApp?.signalCode === null) failedApp.kill("SIGKILL");
  if (timeoutApp?.exitCode === null && timeoutApp?.signalCode === null) timeoutApp.kill("SIGKILL");
  if (blocker?.listening) {
    await new Promise((resolveClose, reject) => blocker.close((error) => (error ? reject(error) : resolveClose())));
  }
  await removeBundledSidecars();
  await rm(stateDirectory, { recursive: true, force: true });
}
