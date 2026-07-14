import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  createCommandId,
  createRunId,
  isCommandId,
  isRunId,
} from "./publicLearningId.js";

test("persistent learning ids use the closed 160-bit Web Crypto profiles", () => {
  const runId = createRunId();
  const commandId = createCommandId();
  assert.match(runId, /^r_[A-P]{40}$/);
  assert.match(commandId, /^c_[A-P]{40}$/);
  assert.equal(isRunId(runId), true);
  assert.equal(isCommandId(commandId), true);
  assert.notEqual(runId.slice(2), createRunId().slice(2));
  assert.notEqual(commandId.slice(2), createCommandId().slice(2));
});

test("closed profiles reject UUIDs, semantic ids, wrong prefixes, and common tokens", () => {
  const invalid = [
    "59678fb4-b3ee-4caa-bbb2-2ae95ba15b9c",
    "create-plan-command",
    "assist-next-1",
    "mac-mrgbtft2-bemhcj",
    `sk_live_${"A".repeat(32)}`,
    `ghp_${"A".repeat(32)}`,
    `c_${"A".repeat(39)}`,
    `c_${"A".repeat(41)}`,
    `c_${"Q".repeat(40)}`,
  ];
  for (const value of invalid) {
    assert.equal(isRunId(value), false, value);
    assert.equal(isCommandId(value), false, value);
  }
  assert.equal(isRunId(`c_${"A".repeat(40)}`), false);
  assert.equal(isCommandId(`r_${"A".repeat(40)}`), false);
});

test("persistent id generator contains no timestamp, Math.random, UUID, or fallback path", () => {
  const source = readFileSync(new URL("./publicLearningId.js", import.meta.url), "utf8");
  const assistanceSource = readFileSync(new URL("./learningSupportAdapter.js", import.meta.url), "utf8");
  const planningSource = readFileSync(new URL("./todayPlanAdapter.js", import.meta.url), "utf8");
  const apiSource = readFileSync(new URL("./hermesApi.js", import.meta.url), "utf8");
  assert.match(source, /getRandomValues\(new Uint8Array\(20\)\)/);
  assert.doesNotMatch(source, /Date\.now|Math\.random|randomUUID|fallback/i);
  assert.doesNotMatch(assistanceSource, /Date\.now|Math\.random|randomUUID|assist-/);
  assert.doesNotMatch(planningSource, /Date\.now|Math\.random|randomUUID/);
  assert.doesNotMatch(apiSource, /function createRunId|function createCommandId|run_id:\s*runId\s*\|\|/);
});
