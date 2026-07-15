# Lumi claim-to-evidence index

Status: **Core-320 gates are executable; the tracked `latest.json` is still the
dated legacy 13/13 regression run, not a Core-320 or population-learning verdict**

No portfolio claim is ready until it has an artifact, scope, reproducible command,
and limitation. Prefer machine-readable release reports and trace IDs over screenshots.

| ID | Proposed claim | Scope | Required proof | Current artifact | Status/limitation |
| --- | --- | --- | --- | --- | --- |
| C01 | Diagnosis preserves competing causes and uncertainty | one frozen Xingce fixture | contract-valid engine result with normalized probabilities and cohort provenance | `evals/reports/latest.json` → `diagnosis` | baseline fixture only; not accuracy/calibration |
| C02 | Every demonstrated mastery update is evidence-linked and versioned | frozen engine trajectory | before/after, attempt ID, formula version | `evals/reports/golden-trajectory-latest.json` | one deterministic trajectory |
| C03 | Assisted work cannot prove independent transfer | engine verification mechanics | hinted and independent deterministic tests | `evals/reports/latest.json` → `engine_tests`; `engine/tests/test_mastery.py` | deterministic invariant, not learner outcome |
| C04 | Lumi closes the historical deterministic tutor-loop contract | one representative Xingce path in three modes | persisted observe→diagnose→probe→teach→verify→update→reflect and verified replay | `evals/reports/integration-*-trajectory-latest.json`; `latest.json` → `teaching_transfer` | legacy regression with synthetic content and learner; not the default Core-320 flow |
| C05 | Representative domain/path/mode contract coverage is complete | 14 paths × success/ambiguous/offline | 42 uniquely addressed resolved fixtures, contract tests, hashes | `evals/reports/latest.json` → `fixtures` | contract/scoring coverage; not 42 runtime E2E learner trials |
| C06 | Learner data stays local by default | Mac/runtime | loopback bind, origin/host checks, cloud disclosure trace, redaction test | `service/tests/test_sidecar.py`; `evals/reports/latest.json` → `privacy`; `desktop/src-tauri/tauri.conf.json` | local deterministic runtime; optional future cloud providers require a new gate |
| C07 | Production Shenlun remains isolated | repository boundary | no symlink/code dependency plus operational policy | `evals/reports/latest.json` → `readonly_boundary` | static boundary gate; process controls still apply |
| C08 | Strong/economical model routing saves cost without quality loss | routing benchmark | stratified quality/cost/latency and verifier rejection | `<MISSING>` | no benchmark yet |
| C09 | Lumi improves learner outcomes | population | preregistered controlled pilot and delayed retention | `<MISSING>` | must not claim from fixtures |
| C10 | The three-screen Mac client matches the selected visual truth without AI-slop patterns | overview/tools/reports at 1440×1024 | side-by-side visual QA, real interactions, production build, true PNGs | `client/design-qa.md`; `client/qa/*.png`; `scripts/check_client_artifacts.py` | one desktop visual baseline; no broad usability study |
| C11 | The Mac app owns its packaged local sidecar lifecycle | ARM64 debug app | health handshake, fail-closed occupied port, normal exit, startup-failure cleanup, zero residual process | `desktop/scripts/check-managed-app.mjs`; `desktop/README.md`; `Lumi.app` | ad-hoc debug build, not notarized/universal |
| C12 | Real attempts preserve correct/no-cause and wrong/unconfirmed-cause semantics | loopback `POST /v1/attempts` | accepted responses plus hash-verified trace/replay | `evals/reports/attempt-api-evidence-latest.json`; `latest.json` → `attempt_api` | valid only when the gate is pass |
| C13 | No-data diagnosis does not masquerade as cohort intelligence | real wrong-attempt trace + deterministic guardrail suite | sample size 0, synthetic source, engineering-prior evidence, small/unreviewed fallback tests | `latest.json` → `cohort_prior_guardrail` | no population/common-error conclusion |
| C14 | A local test client can continue the historical probe and independent-verification flow safely | one local versioned HTTP session | ordered states, stale/out-of-order rejection, redacted replay, KT only after independent verification | `evals/reports/attempt-api-evidence-latest.json`; `latest.json` → `attempt_continuation` | deterministic local v1 regression; not the default Core-320 flow |
| C15 | The dated v1 Mac test flow used the real versioned sidecar contract | one historical local browser session | connected/offline/invalid-contract states, v5→v9→v14 continuation, 409 recovery, no pre-verification mastery, report refresh after completion | `client/design-qa.md` → `Local sidecar and continuation evidence` | historical DOM/API/layout evidence; not current Core-320 visual QA |
| C16 | Lumi retains a manifest-verified growth-rate micro-lesson technical MVP | one internal original lesson, two practice fixtures | checksum/provenance validation, one-KC/8-minute policy, four scored questions, two consecutive verified transfers, safe lesson API, trace/replay, client policy tests | `domains/lessons/`; `domains/tests/test_lessons.py`; `service/tests/test_sidecar.py`; `client/tests/lessonProgress.test.js`; legacy run `run-20260714T120838Z` | historical deterministic evidence only; not the current default learner path |
| C17 | Lumi exposes a checksum-pinned four-module Core-320 bank through five practice scopes | v1.0.1, 320 internal QuestionVersions, four module scopes plus mixed | manifest digest/counts, generator oracles, safe pre-answer projection, scope isolation, mixed rotation, shared learner trace, client selection, packaged sidecar | `evals/run_all.py` → `core320_bank`, `core320_scopes`, `core320_client`, `core320_packaging`; digest `854ba5e483454718408cfbf8b428881333130d2224cfd4b5db3499cd54baf117`; 76 domain + 41 engine + 43 service + 22 client tests | deterministic internal mechanics; human content/rights review, current visual QA, real transfer and retention remain unproved |
| C18 | Lumi rebuilds a factual practice report, wrong-question view, evidence profile and conservative next-group decision from local accepted attempts | continuous-practice v1 on Core-320 | no shadow learner tables, verified semantic replay, explicit empty state, cross-session/cross-family redirect threshold, evidence refs, strict client contract and fixed-eight continuation | `evals/run_all.py` → `continuous_practice_v1`; `docs/CONTINUOUS_PRACTICE_V1.md`; `service/tests/test_learning_records.py`; `engine/tests/test_next_scope_policy.py`; `client/tests/practiceInsights.test.js` | deterministic software behavior only; no usability, recommendation-benefit, transfer, retention or score-lift claim |

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
