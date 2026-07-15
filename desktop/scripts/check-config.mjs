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
const buildSidecarPath = resolve(desktopRoot, "scripts/build-sidecar.sh");
const core320ManifestPath = resolve(desktopRoot, "../domains/practice_v3/manifest.json");
const core320SchemaPath = resolve(desktopRoot, "../domains/practice_v3/practice-bank-manifest.schema.json");
const core320SamplesPath = resolve(desktopRoot, "../domains/practice_v3/samples.safe.json");

const config = JSON.parse(await readFile(configPath, "utf8"));
const capability = JSON.parse(await readFile(capabilityPath, "utf8"));
const [cargo, runtime, bootstrap, launcher, buildSidecar, core320Manifest] = await Promise.all([
  readFile(cargoPath, "utf8"),
  readFile(runtimePath, "utf8"),
  readFile(bootstrapPath, "utf8"),
  readFile(launcherPath, "utf8"),
  readFile(buildSidecarPath, "utf8"),
  readFile(core320ManifestPath, "utf8").then(JSON.parse)
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
  [bootstrap.includes("catalog.LESSON_ROOT"), "frozen sidecar must resolve the packaged lesson data root"],
  [bootstrap.includes("practice_v2.DEFAULT_PRACTICE_ROOT"), "frozen sidecar must resolve the packaged practice-v2 data root"],
  [bootstrap.includes("practice_bank_v3.DEFAULT_PRACTICE_BANK_ROOT"), "frozen sidecar must resolve the packaged core-320 manifest root"],
  [buildSidecar.includes("--collect-submodules hermes_practice"), "sidecar build must explicitly collect the deterministic practice engine"],
  [buildSidecar.includes("--gate core320_bank --no-write"), "sidecar build must fail closed on the Core-320 source/materialization gate before packaging"],
  [buildSidecar.includes("domains/lessons:domains/lessons"), "sidecar build must retain the manifest-backed lesson JSON tree"],
  [buildSidecar.includes("domains/practice_v2:domains/practice_v2"), "sidecar build must package the versioned practice-v2 JSON tree"],
  [buildSidecar.includes("domains/practice_v3:domains/practice_v3"), "sidecar build must package the core-320 version manifest"],
  [core320Manifest.bank_id === "lumi.xingce.core-320.practice-v3", "Core-320 manifest must pin the expected bank"],
  [core320Manifest.expected_question_count === 320, "Core-320 manifest must pin exactly 320 questions"],
  [Object.keys(core320Manifest.expected_module_counts ?? {}).length === 4, "Core-320 manifest must pin four module counts"],
  [Object.values(core320Manifest.expected_module_counts ?? {}).every((count) => count === 80), "each Core-320 module must pin 80 questions"],
  [/^[0-9a-f]{64}$/.test(core320Manifest.generated_sha256 ?? ""), "Core-320 manifest must pin a SHA-256 digest"],
  [launcher.includes("execv(executable, argv)"), "native launcher must exec the tracked sidecar runtime"],
  [JSON.stringify(capability.permissions) === JSON.stringify(["core:default"]), "frontend capability must remain core-only"]
];

for (const [valid, message] of expectations) {
  if (!valid) throw new Error(`Invalid Lumi desktop configuration: ${message}`);
}

await access(distPath);
await access(bootstrapPath);
await access(launcherPath);
await access(core320SchemaPath);
await access(core320SamplesPath);
console.log(
  `Lumi desktop configuration, Core-320 ${core320Manifest.generated_sha256}, packaged-sidecar plan, ` +
    "and client/dist entrypoint are present."
);
