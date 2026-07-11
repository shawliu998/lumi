import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { spawn } from "node:child_process";

const desktopRoot = resolve(import.meta.dirname, "..");
const launcher = resolve(desktopRoot, "src-tauri/binaries/hermes-sidecar-aarch64-apple-darwin");
const runtimeDirectory = resolve(desktopRoot, "src-tauri/resources/sidecar-runtime");

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

async function requestHealth(port) {
  const response = await fetch(`http://127.0.0.1:${port}/v1/health`, {
    headers: { Host: `127.0.0.1:${port}` },
    signal: AbortSignal.timeout(400)
  });
  return { status: response.status, body: await response.json() };
}

async function waitForHealth(port, timeoutMs = 8_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await requestHealth(port);
      if (
        health.status === 200 &&
        health.body.status === "ok" &&
        health.body.service === "hermes-local-sidecar" &&
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
  console.log(`Sidecar health and termination checks passed (version ${health.version}).`);
} finally {
  if (!child.killed) child.kill("SIGKILL");
  await rm(stateDirectory, { recursive: true, force: true });
}
