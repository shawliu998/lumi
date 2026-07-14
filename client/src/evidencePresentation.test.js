import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { evidenceDisplayLabel } from "./evidencePresentation.js";

test("planning evidence semantics map to strict restrained Chinese labels", () => {
  assert.equal(evidenceDisplayLabel({ kind: "trace_skill_evidence", semantic: "verification_effective" }), "独立验证结果");
  assert.equal(evidenceDisplayLabel({ kind: "trace_observation", semantic: "initial_answer_passed" }), "首答评分");
  assert.equal(evidenceDisplayLabel({ kind: "trace_terminal", semantic: "terminal_completed" }), "本轮完成记录");
  assert.equal(evidenceDisplayLabel({ kind: "candidate_cause", semantic: "candidate_claim_status" }), "候选错因证据");
  assert.equal(evidenceDisplayLabel({ kind: "candidate_cause", semantic: "candidate_hypothesis" }), "候选错因证据");
});

test("unknown evidence never invents meaning", () => {
  assert.equal(evidenceDisplayLabel({ kind: "trace_observation", semantic: "future_unknown_enum" }), "记录证据");
  assert.equal(evidenceDisplayLabel({ kind: "unknown", semantic: "verification_effective" }), "记录证据");
  assert.equal(evidenceDisplayLabel(null), "记录证据");
});

test("raw evidence diagnostics are behind a collapsed disclosure", () => {
  const source = readFileSync(new URL("./TodayPlanViews.jsx", import.meta.url), "utf8");
  assert.match(source, /<details className="evidence-details">/);
  assert.match(source, /<summary>查看证据详情<\/summary>/);
  assert.doesNotMatch(source, /<details[^>]*\sopen/);
  assert.match(source, /证据哈希/);
  assert.match(source, /JSON 指针/);
});

test("P0.2 planning and ReviewSchedule copy uses readable body sizes", () => {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  assert.match(css, /\.report-note\s*{[^}]*font-size:\s*10px/s);
  assert.match(css, /\.planning-notice p\s*{[^}]*font-size:\s*9px/s);
  assert.match(css, /\.task-definition-grid > div\s*{[^}]*font-size:\s*9px/s);
  assert.match(css, /\.task-evidence-list > div\s*{[^}]*font-size:\s*9px/s);
  assert.match(css, /\.review-report-row\s*{[^}]*font-size:\s*9\.5px/s);
  assert.match(css, /\.review-report-row\.head\s*{[^}]*font-size:\s*9px/s);
});
