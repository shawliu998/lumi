import test from "node:test";
import assert from "node:assert/strict";
import { reportGroupsFromSidecar } from "./reportEvidenceAdapter.js";

function traceItem(overrides = {}) {
  return {
    skill_id: "xingce.data.growth.identify-base-current",
    run_count: 1,
    verified_transfers: 1,
    failed_or_inconclusive: 0,
    latest_mastery: 0.1,
    latest_uncertainty: 0.9,
    average_mastery_delta: 0.01,
    latest_at: "2026-07-11T08:39:51.568961+00:00",
    ...overrides,
  };
}

function report(items) {
  return { policy: "trace-summary-v1", items };
}

test("trace summary labels only explicit verification and run counts", () => {
  const [group] = reportGroupsFromSidecar(report([traceItem()]));
  const [skill] = group.skills;
  assert.equal(skill.evidenceKind, "verified");
  assert.equal(skill.evidenceTitle, "有独立验证通过记录");
  assert.equal(skill.completedRuns, 1);
  assert.equal(skill.verifiedTransfers, 1);
  assert.equal(skill.failedOrInconclusive, 0);
});

test("latest_mastery thresholds never create longitudinal mastery labels", () => {
  for (const latestMastery of [0.1, 0.45, 0.68, 0.99]) {
    const [group] = reportGroupsFromSidecar(report([traceItem({ latest_mastery: latestMastery })]));
    const [skill] = group.skills;
    assert.equal(skill.evidenceKind, "verified");
    assert.equal(skill.evidenceTitle, "有独立验证通过记录");
    assert.equal(skill.latestTraceValue, latestMastery);
    assert.doesNotMatch(skill.evidenceTitle, /学习中|基本稳定|掌握|近期/);
  }
});

test("failed or missing verification stays explicit and evidence-limited", () => {
  const groups = reportGroupsFromSidecar(report([
    traceItem({ skill_id: "xingce.data.growth.compute-rate", verified_transfers: 0, failed_or_inconclusive: 2 }),
    traceItem({ skill_id: "xingce.verbal.main-idea.integrate", verified_transfers: 0, failed_or_inconclusive: 0 }),
  ]));
  const dataSkill = groups.find((group) => group.id === "data").skills[0];
  assert.equal(dataSkill.evidenceKind, "not_verified");
  assert.equal(dataSkill.evidenceTitle, "仅有未通过或不确定记录");
  const verbal = reportGroupsFromSidecar(report([
    traceItem({ skill_id: "xingce.verbal.main-idea.integrate", verified_transfers: 0, failed_or_inconclusive: 0 }),
  ]))[0].skills[0];
  assert.equal(verbal.evidenceKind, "insufficient");
  assert.equal(verbal.evidenceTitle, "证据不足");
});

test("missing trace fields never become fabricated zero values", () => {
  for (const missing of [null, undefined, ""]) {
    const [group] = reportGroupsFromSidecar(report([traceItem({
      latest_mastery: missing,
      latest_uncertainty: missing,
      average_mastery_delta: missing,
    })]));
    const [skill] = group.skills;
    assert.equal(skill.latestTraceValue, null);
    assert.equal(skill.latestTraceUncertainty, null);
    assert.equal(skill.averageTraceDelta, null);
  }
  assert.deepEqual(reportGroupsFromSidecar(report([traceItem({ run_count: null })])), []);
  assert.deepEqual(reportGroupsFromSidecar(report([traceItem({ verified_transfers: "" })])), []);
});
