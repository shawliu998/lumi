import { readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

test("generic Xingce workspace keeps adaptive evidence and answer modes visible without confirming candidates", () => {
  const source = readFileSync(new URL("./XingceAdaptiveWorkspace.jsx", import.meta.url), "utf8");
  assert.match(source, /fetchXingceAdaptiveWorkspace/);
  assert.match(source, /answerXingceAdaptiveProbe/);
  assert.match(source, /answerXingceAdaptiveTransfer/);
  assert.match(source, /候选错因只用于决定下一步，始终保持“未确认”/);
  assert.match(source, /record\.response_mode === "numeric"/);
  assert.match(source, /function SourceMaterial/);
  assert.match(source, /<caption>\{material\.scope_note\}<\/caption>/);
  assert.match(source, /aria-label=\{material\.alt_text\}/);
  assert.match(source, /adaptive-diagram-panels/);
  assert.match(source, /只有独立作答才有资格进入状态收据/);
  assert.match(source, /displayTitle = undefined/);
  assert.match(source, /title=\{displayTitle\}/);
  assert.doesNotMatch(source, /correct_option|answer_spec|candidate_misconception_ids/);
});
