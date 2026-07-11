# Lumi claim-to-evidence index

Status: **P0.1 verified and Git-published evidence index; the authoritative cut
is `evals/reports/latest.json` run `run-20260711T095034Z`, published at
implementation commit `c62c66a`; population claims remain prohibited**

No portfolio claim is ready until it has an artifact, scope, reproducible command,
and limitation. Prefer machine-readable release reports and trace IDs over screenshots.

| ID | Proposed claim | Scope | Required proof | Current artifact | Status/limitation |
| --- | --- | --- | --- | --- | --- |
| C01 | Diagnosis preserves competing causes and uncertainty | one frozen Xingce fixture | contract-valid engine result with normalized probabilities and sample-zero engineering-prior provenance | `evals/reports/latest.json` → `diagnosis` | baseline fixture only; not accuracy/calibration or cohort evidence |
| C02 | Every demonstrated mastery update is evidence-linked and versioned | frozen engine trajectory | before/after, attempt ID, formula version | `evals/reports/golden-trajectory-latest.json` | one deterministic trajectory |
| C03 | Assisted work cannot prove independent transfer | engine verification mechanics | hinted and independent deterministic tests | `evals/reports/latest.json` → `engine_tests`; `engine/tests/test_mastery.py` | deterministic invariant, not learner outcome |
| C04 | Lumi closes a real tutor loop | one representative Xingce path in three modes | persisted observe→diagnose→probe→teach→verify→update→reflect and verified replay | `evals/reports/integration-*-trajectory-latest.json`; `latest.json` → `teaching_transfer` | real package integration; synthetic content and learner |
| C05 | Representative domain/path/mode contract coverage is complete | 14 paths × success/ambiguous/offline | 42 uniquely addressed resolved fixtures, contract tests, hashes | `evals/reports/latest.json` → `fixtures` | contract/scoring coverage; not 42 runtime E2E learner trials |
| C06 | Learner data stays local by default | Mac/runtime | loopback bind, origin/host checks, cloud disclosure trace, redaction test | `service/tests/test_sidecar.py`; `evals/reports/latest.json` → `privacy`; `desktop/src-tauri/tauri.conf.json` | local deterministic runtime; optional future cloud providers require a new gate |
| C07 | Production Shenlun remains isolated | repository boundary | no symlink/code dependency plus operational policy | `evals/reports/latest.json` → `readonly_boundary` | static boundary gate; process controls still apply |
| C08 | Strong/economical model routing saves cost without quality loss | routing benchmark | stratified quality/cost/latency and verifier rejection | `<MISSING>` | no benchmark yet |
| C09 | Lumi improves learner outcomes | population | preregistered controlled pilot and delayed retention | `<MISSING>` | must not claim from fixtures |
| C10 | The Mac client matches the selected visual truth without AI-slop patterns | current P0.1 overview/report/core-flow states | side-by-side visual QA, real interactions, production build, true PNGs | the explicit authentic allow-list and hashes in `client/design-qa.md`; `scripts/check_client_artifacts.py` | one desktop visual baseline; older non-allow-listed PNGs are not current evidence; no broad usability study |
| C11 | The Mac app owns its packaged local sidecar lifecycle | ARM64 debug app | strict/deep signature verification, staged and bundle-resident identifier/version checks, health handshake, fail-closed occupied port, normal exit, startup-failure cleanup, zero residual process | `desktop/scripts/sign-debug-app.mjs`; `desktop/scripts/check-sidecar.mjs`; `desktop/scripts/check-managed-app.mjs`; `desktop/README.md`; `Lumi.app` | verified ad-hoc debug build, not Developer ID signed, notarized, or universal |
| C12 | Real attempts preserve correct/no-cause and wrong/unconfirmed-cause semantics | loopback `POST /v1/attempts` | accepted responses plus hash-verified trace/replay | `evals/reports/attempt-api-evidence-latest.json`; `latest.json` → `attempt_api` | valid only when the gate is pass |
| C13 | No-data diagnosis does not masquerade as cohort intelligence | real wrong-attempt trace + deterministic guardrail suite | sample size 0, synthetic source, engineering-prior evidence, small/unreviewed fallback tests | `latest.json` → `cohort_prior_guardrail` | no population/common-error conclusion |
| C14 | Learner can continue probe and independent verification safely | one local versioned HTTP session | ordered states, stale/out-of-order rejection, redacted replay, KT only after independent verification | `evals/reports/attempt-api-evidence-latest.json`; `latest.json` → `attempt_continuation` | deterministic local v1; no cross-device claim |
| C15 | The visible Mac flow uses the real versioned sidecar contract | one local browser session | connected/empty/offline/invalid-contract/processing states, real first answer→probe→teaching→verification, 409 recovery, no pre-verification KT, report refresh after completion | `client/design-qa.md`; authentic P0.1 PNGs; Sol task `019f4fdb-9368-7b41-81f4-53538957ce7b` | one supported Xingce UI fixture; other tools are explicitly disabled |
| C16 | Progressive help cannot masquerade as independent evidence | six authored levels on a real probe prompt | ordered server levels, uncalibrated weights, assistance exhaustion, no verification help, withheld KT when independence is absent | `latest.json` → `progressive_assistance`; `engine/tests/test_assistance.py`; `service/tests/test_sidecar.py` | engineering policy only; no population learning-effect claim |
| C17 | Probe evidence changes cause-specific teaching without confirming a cause | 42 resolved representative fixtures | support/refute/ambiguous probe samples, per-cause teaching variants, refuted cause excluded from instructional focus | domain/integration tests; `latest.json` → `misconception_dossier` and `teaching_transfer` | deterministic authored semantics; real paraphrase/ASR coverage remains limited |

## Evidence record template

Copy this block for each new result:

```yaml
claim_id: CXX
claim: ""
scope: ""
run_id: ""
artifact_path: ""
artifact_sha256: ""
command: ""
fixture_or_dataset_version: ""
model_policy_versions: []
sample_size: null
confidence_interval: null
reviewer: ""
known_limitations: []
```
