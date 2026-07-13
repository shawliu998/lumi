import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  createRunId,
  isValidMisconceptionDossierContract,
  isValidXingceCoverageContract,
  submitAttempt,
} from "./hermesApi.js";

function xingceCoverageContract() {
  const modules = {
    verbal: { label: "言语理解与表达", total: 6, released: 0, reviewed_release_ready: 6, available: 6 },
    quantitative: { label: "数量关系", total: 2, released: 0, reviewed_release_ready: 2, available: 2 },
    judgment: { label: "判断推理", total: 7, released: 1, reviewed_release_ready: 6, available: 7 },
    data_analysis: { label: "资料分析", total: 4, released: 0, reviewed_release_ready: 4, available: 4 },
    common_knowledge: { label: "常识判断", total: 6, released: 0, reviewed_release_ready: 6, available: 6 },
    political_theory: { label: "政治理论", total: 6, released: 0, reviewed_release_ready: 6, available: 6 },
  };
  const reviewed = Object.entries(modules).flatMap(([moduleId, module]) => Array.from({ length: module.reviewed_release_ready }, (_, index) => ({
    subtype_id: `xingce.${moduleId}.planned_${index}`,
    module_id: moduleId,
    module_label: module.label,
    label: `待审核子型 ${index + 1}`,
    form: "text_mcq",
    content_status: "reviewed_release_ready",
    availability: "available",
    launch: `/v1/xingce/adaptive/xingce.${moduleId}.planned_${index}/workspace`,
    unavailable_reason: null,
    pack: { pack_id: `lumi-${moduleId}-${index}`, pack_version: "0.1.0-reviewed-local-20260713" },
  })));
  return {
    schema_version: "lumi.xingce-coverage-catalog.v1",
    local_only: true,
    summary: {
      schema_version: "lumi.xingce-coverage-summary.v1",
      taxonomy_version: "lumi.xingce-taxonomy.v1",
      total_subtypes: 31,
      released_subtypes: 1,
      reviewed_release_ready_subtypes: 30,
      planned_subtypes: 0,
      content_release_ready: true,
      available_subtypes: 31,
      is_complete: false,
      modules,
    },
    items: [
      {
        subtype_id: "xingce.judgment.conditional_logic",
        module_id: "judgment",
        module_label: "判断推理",
        label: "逻辑判断·条件关系",
        form: "text_mcq",
        content_status: "released",
        availability: "available",
        launch: "/v1/judgment/workspace",
        unavailable_reason: null,
        pack: { pack_id: "lumi-conditional-reasoning-v0", pack_version: "0.1.0-reviewed-local-20260713" },
      },
      ...reviewed,
    ],
  };
}

test("Xingce coverage distinguishes reviewed local availability from full runtime release", () => {
  assert.equal(isValidXingceCoverageContract(xingceCoverageContract()), true);
  const leaked = xingceCoverageContract();
  leaked.items[0].options = [{ label: "A", text: "leak" }];
  assert.equal(isValidXingceCoverageContract(leaked), false);
  const overclaimed = xingceCoverageContract();
  overclaimed.summary.is_complete = true;
  assert.equal(isValidXingceCoverageContract(overclaimed), false);
});

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

test("attempt run ids use the closed Web Crypto profile", () => {
  assert.match(createRunId(), /^r_[A-P]{40}$/);
});

test("attempt submission rejects caller-supplied run ids outside the closed profile", async () => {
  await assert.rejects(
    () => submitAttempt({
      fixtureId: "xingce.data-analysis.growth-rate.synthetic-01",
      response: "A",
      confidence: 0.5,
      runId: "59678fb4-b3ee-4caa-bbb2-2ae95ba15b9c",
    }),
    (error) => error?.code === "invalid_run_id" && error?.kind === "client",
  );
  const source = readFileSync(new URL("./hermesApi.js", import.meta.url), "utf8");
  assert.match(source, /attempt\?\.run_id !== resolvedRunId/);
  assert.match(source, /!isRunId\(attempt\?\.run_id\)/);
});

test("verification client requires closed KT and review commit receipts", () => {
  const source = readFileSync(new URL("./hermesApi.js", import.meta.url), "utf8");
  assert.match(source, /masteryCommitSummary\(continuation\.mastery_commit\)/);
  assert.match(source, /reviewCommitSummary\(continuation\.review_schedule_commit\)/);
  assert.match(source, /invalid_learning_commit_receipt/);
  assert.doesNotMatch(source, /if \(!continuation\?\.mastery_update \|\| !continuation\?\.reflection\)/);
});
