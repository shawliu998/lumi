import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

export const CORE320_SCOPE_COUNTS = Object.freeze({
  "xingce.verbal.core": 80,
  "xingce.judgment.core": 80,
  "xingce.quantitative.core": 80,
  "xingce.data-analysis.core": 80,
  "xingce.mixed.core": 320
});

export async function loadCore320Manifest(desktopRoot) {
  const path = resolve(desktopRoot, "../domains/practice_v3/manifest.json");
  return { path, value: JSON.parse(await readFile(path, "utf8")) };
}

export async function requestCapabilities(port) {
  const response = await fetch(`http://127.0.0.1:${port}/v1/capabilities`, {
    headers: { Host: `127.0.0.1:${port}` },
    signal: AbortSignal.timeout(800)
  });
  return { status: response.status, body: await response.json() };
}

export function assertCore320Capabilities(capabilities, manifest) {
  if (capabilities.status !== 200) {
    throw new Error(`capabilities returned HTTP ${capabilities.status}`);
  }

  const bank = capabilities.body.smart_practice_bank;
  const scopes = Array.isArray(bank?.scopes) ? bank.scopes : [];
  const actualScopeCounts = Object.fromEntries(
    scopes.map((scope) => [scope.scope_id, scope.question_count])
  );
  const expectedScopeEntries = Object.entries(CORE320_SCOPE_COUNTS).sort();
  const actualScopeEntries = Object.entries(actualScopeCounts).sort();
  const expectedModules = Object.entries(manifest.expected_module_counts).sort();
  const actualModules = actualScopeEntries.filter(([scopeId]) => scopeId !== "xingce.mixed.core");

  const failures = [
    [bank?.bank_id === manifest.bank_id, "bank_id"],
    [bank?.version === manifest.version, "bank version"],
    [bank?.generated_sha256 === manifest.generated_sha256, "generated digest"],
    [bank?.target_count === 8, "fixed-eight target"],
    [bank?.counts?.questions === manifest.expected_question_count, "question count"],
    [bank?.counts?.module_scopes === 4, "module scope count"],
    [bank?.counts?.scopes === 5, "total scope count"],
    [bank?.counts?.questions_per_module === 80, "questions per module"],
    [JSON.stringify(actualScopeEntries) === JSON.stringify(expectedScopeEntries), "five scope counts"],
    [JSON.stringify(actualModules) === JSON.stringify(expectedModules), "four module counts"],
    [
      capabilities.body.features?.includes("scope-bound-core-320-practice-v3"),
      "Core-320 capability feature"
    ]
  ].filter(([valid]) => !valid);

  if (failures.length) {
    throw new Error(
      `packaged Core-320 contract mismatch (${failures.map(([, label]) => label).join(", ")}): ` +
        JSON.stringify(capabilities)
    );
  }

  return {
    bank_id: bank.bank_id,
    version: bank.version,
    generated_sha256: bank.generated_sha256,
    question_count: bank.counts.questions,
    scope_counts: actualScopeCounts
  };
}
