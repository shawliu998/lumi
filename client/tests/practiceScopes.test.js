import assert from "node:assert/strict";
import test from "node:test";

import {
  createSmartPracticeStartBody,
  DEFAULT_SMART_PRACTICE_SCOPE_ID,
  getSmartPracticeScope,
  SMART_PRACTICE_BANK_ID,
  SMART_PRACTICE_BANK_SHA256,
  SMART_PRACTICE_BANK_VERSION,
  SMART_PRACTICE_SCOPES,
  SMART_PRACTICE_SCOPE_TARGET,
  validateSmartPracticeCapabilities,
} from "../src/practiceScopes.js";

test("four module scopes each expose an 80-question versioned pool", () => {
  const modules = SMART_PRACTICE_SCOPES.filter((scope) => !scope.mixed);
  assert.deepEqual(modules.map((scope) => scope.label), [
    "言语理解",
    "判断推理",
    "数量关系",
    "资料分析",
  ]);
  assert.equal(new Set(modules.map((scope) => scope.scopeId)).size, 4);
  assert.ok(modules.every((scope) => scope.poolSize === SMART_PRACTICE_SCOPE_TARGET));
});

test("mixed practice reuses the four module pools instead of inventing a fifth pool", () => {
  const mixed = SMART_PRACTICE_SCOPES.find((scope) => scope.mixed);
  assert.equal(mixed.scopeId, "xingce.mixed.core");
  assert.equal(mixed.poolSize, SMART_PRACTICE_SCOPE_TARGET * 4);
});

test("session start sends a stable scope_id and defaults to data analysis", () => {
  assert.deepEqual(createSmartPracticeStartBody(), {
    scope_id: DEFAULT_SMART_PRACTICE_SCOPE_ID,
  });
  assert.deepEqual(createSmartPracticeStartBody("xingce.verbal.core"), {
    scope_id: "xingce.verbal.core",
  });
  assert.equal(getSmartPracticeScope("missing").scopeId, DEFAULT_SMART_PRACTICE_SCOPE_ID);
  assert.throws(() => createSmartPracticeStartBody("missing"), /Unsupported/);
});

function capabilities(overrides = {}) {
  return {
    smart_practice_bank: {
      bank_id: SMART_PRACTICE_BANK_ID,
      version: SMART_PRACTICE_BANK_VERSION,
      generated_sha256: SMART_PRACTICE_BANK_SHA256,
      target_count: 8,
      counts: {
        questions: 320,
        module_scopes: 4,
        scopes: 5,
        questions_per_module: 80,
      },
      scopes: SMART_PRACTICE_SCOPES.map((scope) => ({
        scope_id: scope.scopeId,
        question_count: scope.poolSize,
      })),
      ...overrides,
    },
  };
}

test("capabilities must pin the exact Core-320 bank shape before the client connects", () => {
  assert.equal(validateSmartPracticeCapabilities(capabilities()).bank_id, SMART_PRACTICE_BANK_ID);
  assert.throws(
    () => validateSmartPracticeCapabilities(capabilities({ version: "1.0.0" })),
    /Unsupported Core-320/,
  );
  assert.throws(
    () => validateSmartPracticeCapabilities(capabilities({ generated_sha256: "not-a-digest" })),
    /Unsupported Core-320/,
  );
});
