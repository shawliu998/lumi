import { spawn, execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import { resolve } from "node:path";
import { createServer } from "node:net";

const execFile = promisify(execFileCallback);
const desktopRoot = resolve(import.meta.dirname, "..");
const appPath = resolve(desktopRoot, "src-tauri/target/debug/bundle/macos/Lumi.app");
const executable = resolve(appPath, "Contents/MacOS/hermes-desktop");
const bundleSidecarPattern = `${appPath}/Contents/.+hermes-sidecar`;

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
    if (child.exitCode !== null) return resolveExit(child.exitCode);
    const timer = setTimeout(() => reject(new Error(`${description}: timed out`)), timeoutMs);
    child.once("exit", (code) => {
      clearTimeout(timer);
      resolveExit(code);
    });
  });
}

function spawnManagedApp(port, exitAfterHealth = false) {
  // AppKit can show a modal crash-restoration prompt after a previous test was
  // force-terminated. Keep lifecycle verification deterministic and isolated
  // from the user's normal saved-window state.
  return spawn(executable, ["-ApplePersistenceIgnoreState", "YES"], {
    stdio: "ignore",
    env: {
      ...process.env,
      HERMES_SIDECAR_PORT: String(port),
      ...(exitAfterHealth ? { HERMES_EXIT_AFTER_SIDECAR_HEALTH: "1" } : {})
    }
  });
}

async function bundledSidecarPids() {
  try {
    const { stdout } = await execFile("pgrep", ["-f", bundleSidecarPattern]);
    return stdout.trim().split("\n").filter(Boolean).map(Number);
  } catch (error) {
    if (error.code === 1) return [];
    throw error;
  }
}

async function removeBundledSidecars() {
  for (const pid of await bundledSidecarPids()) {
    process.kill(pid, "SIGTERM");
  }
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  for (const pid of await bundledSidecarPids()) {
    process.kill(pid, "SIGKILL");
  }
  const remaining = await bundledSidecarPids();
  if (remaining.length) throw new Error(`bundled sidecar process leak: ${remaining.join(", ")}`);
}

let app;
let failedApp;
let blocker;
try {
  const port = await reserveLoopbackPort();
  app = spawnManagedApp(port, true);
  const health = await waitFor(async () => {
    const result = await requestHealth(port);
    return result.status === 200 && result.body.local_only === true ? result.body : undefined;
  }, "managed app did not complete the sidecar health handshake");

  await waitFor(async () => {
    try {
      await requestHealth(port);
      return false;
    } catch {
      return true;
    }
  }, "sidecar remained reachable after Lumi exited");
  await waitForExit(app, "Lumi did not exit after its managed sidecar shut down");

  const occupiedPort = await reserveLoopbackPort();
  blocker = createServer();
  await new Promise((resolveListen, reject) => {
    blocker.once("error", reject);
    blocker.listen({ host: "127.0.0.1", port: occupiedPort }, resolveListen);
  });
  failedApp = spawnManagedApp(occupiedPort);
  await waitForExit(failedApp, "Lumi did not fail closed when its sidecar port was occupied");

  console.log(`Managed app lifecycle and startup-failure checks passed (sidecar ${health.version}).`);
} finally {
  if (app?.exitCode === null) app.kill("SIGKILL");
  if (failedApp?.exitCode === null) failedApp.kill("SIGKILL");
  if (blocker?.listening) {
    await new Promise((resolveClose, reject) => blocker.close((error) => (error ? reject(error) : resolveClose())));
  }
  await removeBundledSidecars();
}
