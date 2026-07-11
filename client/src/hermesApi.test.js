import test from "node:test";
import assert from "node:assert/strict";
import { isValidMisconceptionDossierContract } from "./hermesApi.js";

function dossierContract(claimStatus) {
  return {
    schema_version: "hermes.misconception-dossier.v1",
    run_id: "run-contract",
    observations: { items: [] },
    hypotheses: [{
      claim_status: claimStatus,
      supporting_evidence: [],
      refuting_evidence: [],
      ranking_factors: ["engineering_prior"],
      prior: {
        kind: "engineering_prior",
        source_version: "synthetic-engineering-prior-v1",
        sample_size: 0,
        population_calibrated: false,
      },
    }],
    learning_status: "awaiting_probe",
    state: "awaiting_probe",
    next_action: { action: "answer_targeted_probe", prompt_instance_id: "run-contract:probe:1" },
    hypothesis_semantics: "ranked_candidates_never_causal_ground_truth",
    cohort_evidence: { status: "unavailable", sample_size: 0 },
    provenance: { trace_verified: true },
  };
}

test("dossier API accepts only the three hypothesis claim statuses", () => {
  for (const claimStatus of [
    "unconfirmed_hypothesis",
    "supported_hypothesis",
    "refuted_hypothesis",
  ]) {
    assert.equal(
      isValidMisconceptionDossierContract(dossierContract(claimStatus), "run-contract"),
      true,
    );
  }
});

test("dossier API rejects malicious confirmed and unknown claim statuses", () => {
  for (const claimStatus of ["confirmed", "unknown_status", "", null]) {
    assert.equal(
      isValidMisconceptionDossierContract(dossierContract(claimStatus), "run-contract"),
      false,
    );
  }
});

test("dossier API rejects unknown and mismatched continuation actions", () => {
  const unknownState = dossierContract("unconfirmed_hypothesis");
  unknownState.state = "unknown_state";
  assert.equal(isValidMisconceptionDossierContract(unknownState, "run-contract"), false);

  const processingWithOldPrompt = dossierContract("unconfirmed_hypothesis");
  processingWithOldPrompt.state = "processing_probe";
  processingWithOldPrompt.learning_status = "processing_probe_response";
  processingWithOldPrompt.next_action = {
    action: "answer_targeted_probe",
    prompt_instance_id: "run-contract:probe:1",
  };
  assert.equal(isValidMisconceptionDossierContract(processingWithOldPrompt, "run-contract"), false);
});

test("dossier API rejects fabricated cohort evidence", () => {
  const cohortPrior = dossierContract("unconfirmed_hypothesis");
  cohortPrior.hypotheses[0].prior = {
    kind: "cohort_prior",
    source_version: "invented-population",
    sample_size: 120,
    population_calibrated: true,
  };
  assert.equal(isValidMisconceptionDossierContract(cohortPrior, "run-contract"), false);

  const cohortFactor = dossierContract("unconfirmed_hypothesis");
  cohortFactor.hypotheses[0].ranking_factors = ["cohort_prior"];
  assert.equal(isValidMisconceptionDossierContract(cohortFactor, "run-contract"), false);

  for (const disguisedZero of [null, "0", false]) {
    const disguisedCohortSample = dossierContract("unconfirmed_hypothesis");
    disguisedCohortSample.cohort_evidence.sample_size = disguisedZero;
    assert.equal(isValidMisconceptionDossierContract(disguisedCohortSample, "run-contract"), false);

    const disguisedPriorSample = dossierContract("unconfirmed_hypothesis");
    disguisedPriorSample.hypotheses[0].prior.sample_size = disguisedZero;
    assert.equal(isValidMisconceptionDossierContract(disguisedPriorSample, "run-contract"), false);
  }
});
