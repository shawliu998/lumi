import { access, readFile } from "node:fs/promises";
import { resolve } from "node:path";

const desktopRoot = resolve(import.meta.dirname, "..");
const configPath = resolve(desktopRoot, "src-tauri/tauri.conf.json");
const distPath = resolve(desktopRoot, "../client/dist/index.html");
const capabilityPath = resolve(desktopRoot, "src-tauri/capabilities/default.json");
const cargoPath = resolve(desktopRoot, "src-tauri/Cargo.toml");
const runtimePath = resolve(desktopRoot, "src-tauri/src/main.rs");
const bootstrapPath = resolve(desktopRoot, "sidecars/hermes_sidecar_bootstrap.py");
const launcherPath = resolve(desktopRoot, "sidecars/hermes_sidecar_launcher.c");

const config = JSON.parse(await readFile(configPath, "utf8"));
const capability = JSON.parse(await readFile(capabilityPath, "utf8"));
const [cargo, runtime, bootstrap, launcher] = await Promise.all([
  readFile(cargoPath, "utf8"),
  readFile(runtimePath, "utf8"),
  readFile(bootstrapPath, "utf8"),
  readFile(launcherPath, "utf8")
]);

const expectations = [
  [config.productName === "Lumi", "productName must be Lumi"],
  [config.identifier === "com.lumi.learning", "bundle identifier must be com.lumi.learning"],
  [config.build?.frontendDist === "../../client/dist", "frontendDist must point at client/dist"],
  [config.build?.devUrl === "http://127.0.0.1:1420", "devUrl must be loopback-only"],
  [config.app?.security?.csp?.includes("default-src 'self'"), "CSP must default to self"],
  [config.app?.security?.csp?.includes("connect-src 'self' http://127.0.0.1:8765"), "CSP must allow only the exact loopback sidecar origin"],
  [!config.app?.security?.csp?.includes("127.0.0.1:1420"), "CSP must not grant the development port network access"],
  [JSON.stringify(config.bundle?.externalBin) === JSON.stringify(["binaries/hermes-sidecar"]), "bundle must package only the Lumi sidecar"],
  [JSON.stringify(config.bundle?.resources) === JSON.stringify({ "resources/sidecar-runtime": "sidecar-runtime" }), "bundle must include the sidecar runtime tree"],
  [cargo.includes('tauri-plugin-shell = "2.3.5"'), "Rust runtime must use the pinned Tauri shell plugin"],
  [runtime.includes('.sidecar(SIDECAR_NAME)?'), "runtime must launch the named packaged sidecar"],
  [runtime.includes('.env("HERMES_SIDECAR_RUNTIME_DIR", runtime_directory)'), "launcher must receive only the packaged runtime directory"],
  [runtime.includes("const SIDECAR_PORT: u16 = 8765"), "release runtime must default to port 8765"],
  [runtime.includes("#[cfg(debug_assertions)]"), "port override must be limited to debug builds"],
  [runtime.includes("HERMES_EXIT_AFTER_SIDECAR_HEALTH"), "managed lifecycle test hook must be debug-only"],
  [runtime.includes("wait_for_sidecar_health"), "runtime must perform a health handshake"],
  [runtime.includes("RunEvent::Exit"), "runtime must stop the sidecar on application exit"],
  [runtime.includes("child.kill()"), "runtime must terminate the sidecar process"],
  [runtime.includes("impl Drop for RunningSidecar"), "runtime must retain an RAII sidecar cleanup guard"],
  [runtime.includes("terminate_and_wait"), "runtime must reap the sidecar after termination"],
  [bootstrap.includes("_parent_death_watchdog"), "sidecar bootstrap must stop when its parent disappears"],
  [launcher.includes("execv(executable, argv)"), "native launcher must exec the tracked sidecar runtime"],
  [JSON.stringify(capability.permissions) === JSON.stringify(["core:default"]), "frontend capability must remain core-only"]
];

for (const [valid, message] of expectations) {
  if (!valid) throw new Error(`Invalid Lumi desktop configuration: ${message}`);
}

await access(distPath);
await access(bootstrapPath);
await access(launcherPath);
console.log("Lumi desktop configuration, packaged-sidecar plan, and client/dist entrypoint are present.");
