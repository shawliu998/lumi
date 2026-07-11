import { lstat, mkdir, mkdtemp, readFile, readdir, readlink, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";

const desktopRoot = resolve(import.meta.dirname, "..");
const checkBundledSidecar = process.argv.includes("--bundle");
const appPath = resolve(desktopRoot, "src-tauri/target/debug/bundle/macos/Lumi.app");
const launcher = checkBundledSidecar
  ? resolve(appPath, "Contents/MacOS/hermes-sidecar")
  : resolve(desktopRoot, "src-tauri/binaries/hermes-sidecar-aarch64-apple-darwin");
const runtimeDirectory = checkBundledSidecar
  ? resolve(appPath, "Contents/Resources/sidecar-runtime")
  : resolve(desktopRoot, "src-tauri/resources/sidecar-runtime");
const EXPECTED_SIDECAR_VERSION = "0.2.0";

function opaquePublicId(prefix, label) {
  const alphabet = "ABCDEFGHIJKLMNOP";
  const digest = createHash("sha256").update(label).digest().subarray(0, 20);
  return `${prefix}_${[...digest]
    .map((byte) => `${alphabet[byte >> 4]}${alphabet[byte & 15]}`)
    .join("")}`;
}

async function bundleTreeDigest(root) {
  const digest = createHash("sha256");

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
  return digest.digest("hex");
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

function requestHealth(port) {
  return requestJson(port, "/v1/health");
}

async function waitForHealth(port, timeoutMs = 16_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
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
      lastError = new Error(`unexpected health payload: ${JSON.stringify(health)}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  }
  throw new Error(`sidecar health handshake timed out: ${lastError?.message ?? "unknown error"}`);
}

function waitForExit(child, timeoutMs = 4_000) {
  return new Promise((resolveExit, reject) => {
    const timer = setTimeout(() => reject(new Error("sidecar did not exit after SIGTERM")), timeoutMs);
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolveExit({ code, signal });
    });
  });
}

const port = await reserveLoopbackPort();
const stateDirectory = await mkdtemp(resolve(tmpdir(), "hermes-sidecar-check-"));
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
const bundleTreeBefore = checkBundledSidecar ? await bundleTreeDigest(appPath) : undefined;
const bundleMtimeBefore = checkBundledSidecar ? (await lstat(appPath)).mtimeMs : undefined;
const child = spawn(launcher, ["--db", resolve(stateDirectory, "sidecar.sqlite3"), "serve", "--port", String(port)], {
  stdio: ["ignore", "pipe", "pipe"],
  env: {
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
  }
});
let stderr = "";
child.stderr.setEncoding("utf8");
child.stderr.on("data", (chunk) => {
  stderr += chunk;
});

try {
  const health = await waitForHealth(port);
  const capabilities = await requestJson(port, "/v1/capabilities");
  if (
    capabilities.status !== 200 ||
    capabilities.body.service_version !== EXPECTED_SIDECAR_VERSION ||
    capabilities.body.api_version !== "v1" ||
    capabilities.body.local_only !== true ||
    capabilities.body.scenario_count !== 42
  ) {
    throw new Error(`unexpected capabilities payload: ${JSON.stringify(capabilities)}`);
  }
  const advertisedEndpoints = capabilities.body.endpoints ?? {};
  if (
    Object.hasOwn(advertisedEndpoints, "run") ||
    Object.keys(advertisedEndpoints).some((name) => name.includes("offline")) ||
    JSON.stringify(capabilities.body).toLowerCase().includes("offline")
  ) {
    throw new Error(`capabilities advertised a removed run/offline product path: ${JSON.stringify(capabilities)}`);
  }
  const disabledRuns = await requestJson(port, "/v1/runs", {
    method: "POST",
    body: { mode: "offline", run_id: opaquePublicId("r", "disabled-public-runs") },
  });
  if (disabledRuns.status !== 404) {
    throw new Error(`public POST /v1/runs was not disabled: ${JSON.stringify(disabledRuns)}`);
  }
  const rejectedRunIds = [
    "legacy-safe-run",
    "0123456789abcdef0123456789abcdef",
    "550e8400-e29b-41d4-a716-446655440000",
    "run-013800138000",
    "sk_live_" + "A".repeat(32),
    "ghp_" + "A".repeat(36),
    "github_pat_" + "A".repeat(82),
    "AIzaSy" + "A".repeat(33),
    "npm_" + "A".repeat(36),
    "xoxb-" + "A".repeat(24) + "-" + "B".repeat(24),
  ];
  const attemptBody = {
    fixture_id: "xingce.data-analysis.growth-rate.synthetic-01",
    response: "A",
    confidence: 0.5,
    response_time_seconds: 20,
  };
  for (const runId of rejectedRunIds) {
    const rejected = await requestJson(port, "/v1/attempts", {
      method: "POST",
      body: { ...attemptBody, run_id: runId },
    });
    if (rejected.status !== 400 || rejected.body?.error?.code !== "invalid_run_id") {
      throw new Error(`unsafe run identifier was not rejected: ${JSON.stringify(rejected)}`);
    }
  }
  const afterRejectedRuns = await requestHealth(port);
  if (afterRejectedRuns.body.run_count !== health.run_count) {
    throw new Error("rejected run identifiers changed learner-visible run_count");
  }
  const accepted = await requestJson(port, "/v1/attempts", {
    method: "POST",
    body: { ...attemptBody, run_id: opaquePublicId("r", "desktop-identifier-guard") },
  });
  if (accepted.status !== 201) {
    throw new Error(`identifier guard setup attempt failed: ${JSON.stringify(accepted)}`);
  }
  const traceBeforeRejectedCommands = await requestJson(port, accepted.body.links.trace);
  const rejectedCommandIds = [
    "legacy-command",
    "0123456789abcdef0123456789abcdef",
    "550e8400-e29b-41d4-a716-446655440000",
    "cmd-013800138000",
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
    if (rejected.status !== 400 || rejected.body?.error?.code !== "invalid_command_id") {
      throw new Error(`unsafe command identifier was not rejected: ${JSON.stringify(rejected)}`);
    }
  }
  const traceAfterRejectedCommands = await requestJson(port, accepted.body.links.trace);
  if (JSON.stringify(traceAfterRejectedCommands.body) !== JSON.stringify(traceBeforeRejectedCommands.body)) {
    throw new Error("rejected command identifiers changed the learning trace");
  }
  const exit = waitForExit(child);
  child.kill("SIGTERM");
  await exit;

  await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
  try {
    await requestHealth(port);
    throw new Error("sidecar still answered health checks after termination");
  } catch (error) {
    if (error.message === "sidecar still answered health checks after termination") throw error;
  }
  const source = checkBundledSidecar ? "bundled" : "staged";
  const integrity = checkBundledSidecar
    ? ` Bundle tree SHA-256 ${bundleTreeBefore} was unchanged.`
    : "";
  console.log(`Sidecar ${source} health, 42-scenario capabilities, identifier guards, and termination checks passed (version ${health.version}).${integrity}`);
} finally {
  if (!child.killed) child.kill("SIGKILL");
  await rm(stateDirectory, { recursive: true, force: true });
  if (checkBundledSidecar) {
    const bundleTreeAfter = await bundleTreeDigest(appPath);
    const bundleMtimeAfter = (await lstat(appPath)).mtimeMs;
    if (bundleTreeAfter !== bundleTreeBefore || bundleMtimeAfter !== bundleMtimeBefore) {
      throw new Error(
        `bundled sidecar check mutated Lumi.app (tree ${bundleTreeBefore} -> ${bundleTreeAfter}; mtime ${bundleMtimeBefore} -> ${bundleMtimeAfter})`
      );
    }
  }
}
