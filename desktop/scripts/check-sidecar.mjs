import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn } from "node:child_process";

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
const child = spawn(launcher, ["--db", resolve(stateDirectory, "sidecar.sqlite3"), "serve", "--port", String(port)], {
  stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env, HERMES_SIDECAR_RUNTIME_DIR: runtimeDirectory }
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
  const tokenTail = "abcdefghijklmnopqrstuvwxyz" + "123456";
  const rejectedRunIds = [
    "run-013800138000",
    "run-" + "sk-" + tokenTail,
    "run-" + "ghp_" + tokenTail,
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
  const accepted = await requestJson(port, "/v1/attempts", {
    method: "POST",
    body: { ...attemptBody, run_id: "desktop-identifier-guard" },
  });
  if (accepted.status !== 201) {
    throw new Error(`identifier guard setup attempt failed: ${JSON.stringify(accepted)}`);
  }
  const rejectedCommandIds = [
    "cmd-013800138000",
    "cmd-" + "sk-" + tokenTail,
    "cmd-" + "ghp_" + tokenTail,
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
  console.log(`Sidecar ${source} health, 42-scenario capabilities, identifier guards, and termination checks passed (version ${health.version}).`);
} finally {
  if (!child.killed) child.kill("SIGKILL");
  await rm(stateDirectory, { recursive: true, force: true });
}
