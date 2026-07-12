import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("a successful judgment workspace read clears a stale shell offline indicator", () => {
  const workspace = readFileSync(new URL("./JudgmentWorkspace.jsx", import.meta.url), "utf8");
  const app = readFileSync(new URL("./App.jsx", import.meta.url), "utf8");

  assert.match(workspace, /export function JudgmentWorkspace\(\{ onServiceReachable = undefined \}\)/);
  assert.match(workspace, /const result = await fetchJudgmentWorkspace\(\);\s*reportServiceReachable\(\);/);
  assert.match(workspace, /void onServiceReachable\?\.\(\);/);
  assert.match(workspace, /elapsed_seconds: "作答用时"/);
  assert.match(workspace, /hint_count: "帮助次数"/);
  assert.match(app, /<JudgmentWorkspace onServiceReachable=\{refreshSidecar\} \/>/);
});
