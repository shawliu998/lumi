import test from "node:test";
import assert from "node:assert/strict";
import {
  appendAssistance,
  assertSupportedDossierContinuation,
  assertSupportedDossierClaimStatuses,
  buildAssistanceCommand,
  createAssistanceState,
  normalizeMisconceptionDossier,
} from "./learningSupportAdapter.js";

function dossierPayload(overrides = {}) {
  return {
    run_id: "run-contract",
    observations: {
      score: { score: 0, max_score: 1, passed: false },
      items: [],
      event: { seq: 3 },
    },
    hypotheses: [{
      cause_id: "ratio-growth-confusion",
      claim_status: "unconfirmed_hypothesis",
      supporting_evidence: [],
      refuting_evidence: [],
    }],
    learning_status: "awaiting_probe",
    state: "awaiting_probe",
    next_action: { action: "answer_targeted_probe", prompt_instance_id: "run-contract:probe:1" },
    cohort_evidence: { status: "unavailable", sample_size: 0 },
    ...overrides,
  };
}

test("assistance command matches the strict writable contract", () => {
  const body = buildAssistanceCommand({
    session: {
      state_version: 5,
      probe: { prompt_instance_id: "prompt-1" },
    },
    elapsedTimeSeconds: 12.5,
    commandId: "command-1",
  });
  assert.deepEqual(Object.keys(body), [
    "phase",
    "expected_version",
    "expected_state",
    "prompt_instance_id",
    "action",
    "elapsed_time_seconds",
    "command_id",
  ]);
  assert.equal(body.phase, "probe");
  assert.equal(body.action, "next");
  assert.equal("level" in body, false);
  assert.equal("diagnostic_evidence_weight" in body, false);
  assert.equal("independent" in body, false);
});

test("assistance state is unavailable until a real prompt instance exists", () => {
  assert.equal(createAssistanceState().status, "unavailable");
  assert.equal(createAssistanceState({ available: true }).status, "ready");
});

test("server assistance advances UI without inventing level or weight", () => {
  const state = createAssistanceState({ available: true });
  const next = appendAssistance(state, {
    assistance: {
      ordinal: 1,
      action: "retry",
      title: "再试一次",
      content: "重新标出两个量。",
      policy_version: "assistance-policy-v1",
      diagnostic_evidence_weight: 0.8,
      calibration_status: "engineering_policy_unvalidated",
    },
  });
  assert.equal(next.status, "ready");
  assert.equal(next.items[0].ordinal, 1);
  assert.equal(next.items[0].calibration_status, "engineering_policy_unvalidated");
});

test("event-sourced dossier keeps unconfirmed claim explicit", () => {
  const dossier = normalizeMisconceptionDossier(dossierPayload({
    run_id: "run-2",
    hypotheses: [{
      cause_id: "ratio-growth-confusion",
      claim_status: "unconfirmed_hypothesis",
      supporting_evidence: [{ kind: "initial_response_pattern", event: { seq: 3 } }],
      refuting_evidence: [],
    }],
  }));
  assert.equal(dossier.persistence, "event_sourced");
  assert.equal(dossier.statusCopy, "尚未确认");
  assert.equal(dossier.rankedHypotheses[0].claimStatus, "unconfirmed_hypothesis");
});

test("malicious dossier contract rejects confirmed and unknown claim statuses", () => {
  for (const claimStatus of ["confirmed", "unknown_status", "", null]) {
    const payload = dossierPayload({
      hypotheses: [{
        cause_id: "ratio-growth-confusion",
        claim_status: claimStatus,
        supporting_evidence: [],
        refuting_evidence: [],
      }],
    });
    assert.throws(
      () => assertSupportedDossierClaimStatuses(payload),
      /unsupported claim_status/,
    );
    assert.throws(
      () => normalizeMisconceptionDossier(payload),
      /unsupported claim_status/,
    );
  }
});

test("processing dossier requires a restart action and never keeps the prompt writable", () => {
  const processing = dossierPayload({
    state: "processing_probe",
    learning_status: "processing_probe_response",
    next_action: {
      action: "restart_attempt_after_processing_failure",
      target: "/v1/attempts",
      reason: "The prior probe response was consumed but processing did not finish.",
    },
    probe: { prompt: "This consumed prompt must not survive normalization." },
  });
  const dossier = normalizeMisconceptionDossier(processing);
  assert.equal(dossier.requiresRestart, true);
  assert.equal(dossier.serviceState, "processing_probe");
  assert.equal(dossier.nextAction.action, "restart_attempt_after_processing_failure");
  assert.equal(dossier.nextProbe, null);
});

test("unknown dossier state and next action fail closed", () => {
  for (const payload of [
    dossierPayload({ state: "unknown_state" }),
    dossierPayload({ next_action: { action: "continue_old_prompt", prompt_instance_id: "prompt-1" } }),
    dossierPayload({
      state: "processing_verification",
      learning_status: "processing_verification_response",
      next_action: { action: "answer_independent_verification", prompt_instance_id: "prompt-2" },
    }),
  ]) {
    assert.throws(() => assertSupportedDossierContinuation(payload), /unsupported state or next_action/);
    assert.throws(() => normalizeMisconceptionDossier(payload), /unsupported state or next_action/);
  }
});

test("supported and refuted dossier candidates remain hypotheses", () => {
  const dossier = normalizeMisconceptionDossier({
    run_id: "run-120-div-100",
    module: "资料分析/增长率",
    observations: {
      score: { score: 0, max_score: 1, passed: false },
      items: [],
      event: { seq: 3 },
    },
    hypotheses: [
      {
        rank: 1,
        cause_id: "denominator-current-base-confusion",
        claim_status: "refuted_hypothesis",
        ranking_probability: 0.62,
        supporting_evidence: [],
        refuting_evidence: [{ kind: "targeted_probe_assessment", assessment_event: { seq: 9 } }],
      },
      {
        rank: 2,
        cause_id: "ratio-growth-confusion",
        claim_status: "supported_hypothesis",
        ranking_probability: 0.24,
        supporting_evidence: [{ kind: "targeted_probe_assessment", assessment_event: { seq: 9 } }],
        refuting_evidence: [],
      },
    ],
    learning_status: "awaiting_independent_verification",
    state: "awaiting_verification",
    next_action: { action: "answer_independent_verification", prompt_instance_id: "run-120-div-100:verification:1" },
    cohort_evidence: { status: "unavailable", sample_size: 0 },
  });
  assert.deepEqual(
    dossier.rankedHypotheses.map((item) => item.claimStatus),
    ["refuted_hypothesis", "supported_hypothesis"],
  );
  assert.equal(dossier.statusCopy, "尚未确认");
  assert.match(dossier.rankedHypotheses[0].refutingEvidence[0], /事件 9/);
  assert.match(dossier.rankedHypotheses[1].supportingEvidence[0], /事件 9/);
});
