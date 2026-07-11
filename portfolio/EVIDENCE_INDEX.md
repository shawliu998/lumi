# Lumi claim-to-evidence index

Status: **live evidence index; release run `run-20260711T051110Z` passes 13/13 gates; population claims remain prohibited**

No portfolio claim is ready until it has an artifact, scope, reproducible command,
and limitation. Prefer machine-readable release reports and trace IDs over screenshots.

| ID | Proposed claim | Scope | Required proof | Current artifact | Status/limitation |
| --- | --- | --- | --- | --- | --- |
| C01 | Diagnosis preserves competing causes and uncertainty | one frozen Xingce fixture | contract-valid engine result with normalized probabilities and cohort provenance | `evals/reports/latest.json` → `diagnosis` | baseline fixture only; not accuracy/calibration |
| C02 | Every demonstrated mastery update is evidence-linked and versioned | frozen engine trajectory | before/after, attempt ID, formula version | `evals/reports/golden-trajectory-latest.json` | one deterministic trajectory |
| C03 | Assisted work cannot prove independent transfer | engine verification mechanics | hinted and independent deterministic tests | `evals/reports/latest.json` → `engine_tests`; `engine/tests/test_mastery.py` | deterministic invariant, not learner outcome |
| C04 | Lumi closes a real tutor loop | one representative Xingce path in three modes | persisted observe→diagnose→probe→teach→verify→update→reflect and verified replay | `evals/reports/integration-*-trajectory-latest.json`; `latest.json` → `teaching_transfer` | real package integration; synthetic content and learner |
| C05 | Representative domain/path/mode contract coverage is complete | 14 paths × success/ambiguous/offline | 42 uniquely addressed resolved fixtures, contract tests, hashes | `evals/reports/latest.json` → `fixtures` | contract/scoring coverage; not 42 runtime E2E learner trials |
| C06 | Learner data stays local by default | Mac/runtime | loopback bind, origin/host checks, cloud disclosure trace, redaction test | `service/tests/test_sidecar.py`; `evals/reports/latest.json` → `privacy`; `desktop/src-tauri/tauri.conf.json` | local deterministic runtime; optional future cloud providers require a new gate |
| C07 | Production Shenlun remains isolated | repository boundary | no symlink/code dependency plus operational policy | `evals/reports/latest.json` → `readonly_boundary` | static boundary gate; process controls still apply |
| C08 | Strong/economical model routing saves cost without quality loss | routing benchmark | stratified quality/cost/latency and verifier rejection | `<MISSING>` | no benchmark yet |
| C09 | Lumi improves learner outcomes | population | preregistered controlled pilot and delayed retention | `<MISSING>` | must not claim from fixtures |
| C10 | The three-screen Mac client matches the selected visual truth without AI-slop patterns | overview/tools/reports at 1440×1024 | side-by-side visual QA, real interactions, production build, true PNGs | `client/design-qa.md`; `client/qa/*.png`; `scripts/check_client_artifacts.py` | one desktop visual baseline; no broad usability study |
| C11 | The Mac app owns its packaged local sidecar lifecycle | ARM64 debug app | health handshake, fail-closed occupied port, normal exit, startup-failure cleanup, zero residual process | `desktop/scripts/check-managed-app.mjs`; `desktop/README.md`; `Lumi.app` | ad-hoc debug build, not notarized/universal |
| C12 | Real attempts preserve correct/no-cause and wrong/unconfirmed-cause semantics | loopback `POST /v1/attempts` | accepted responses plus hash-verified trace/replay | `evals/reports/attempt-api-evidence-latest.json`; `latest.json` → `attempt_api` | valid only when the gate is pass |
| C13 | No-data diagnosis does not masquerade as cohort intelligence | real wrong-attempt trace + deterministic guardrail suite | sample size 0, synthetic source, engineering-prior evidence, small/unreviewed fallback tests | `latest.json` → `cohort_prior_guardrail` | no population/common-error conclusion |
| C14 | Learner can continue probe and independent verification safely | one local versioned HTTP session | ordered states, stale/out-of-order rejection, redacted replay, KT only after independent verification | `evals/reports/attempt-api-evidence-latest.json`; `latest.json` → `attempt_continuation` | deterministic local v1; no cross-device claim |
| C15 | The visible Mac flow uses the real versioned sidecar contract | one local browser session | connected/offline/invalid-contract states, v5→v9→v14 continuation, 409 recovery, no pre-verification mastery, report refresh after completion | `client/design-qa.md` → `Local sidecar and continuation evidence`; Sol thread `019f4f2c-22d6-7973-9c03-d6079ffbe9bd` | DOM/API/layout/console evidence; completed-panel screenshot excluded because of documented in-app compositor failure |

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
