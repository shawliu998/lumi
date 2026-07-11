# Lumi completion audit

This is the live requirement-to-evidence audit for the local Lumi objective.
`complete` means the stated scope has direct reproducible evidence; it does not
mean population learning efficacy or production distribution has been proved.

| Requirement | Status | Authoritative evidence | Remaining limitation |
| --- | --- | --- | --- |
| `peikao` is the Lumi main repository | complete | root `README.md`, `AGENTS.md`, module layout; `origin=https://github.com/shawliu998/zhishixingqiu.git` | P0.1 milestone branch still requires final verified push |
| Production Shenlun repository remains read-only | complete | `scripts/check_boundaries.py`; release `readonly_boundary` gate | must remain an operational invariant on every future run |
| Editable Xingce data factory | complete for bounded factory | `$HOME/Documents/xingcetiku/hermes`; 100-item overlay build/validation; `ENRICHMENT_AUDIT_V1.md` | 97/100 have candidate skill/misconception mappings; 3 remain explicitly blocked by missing key content |
| Explainable KT and cause diagnosis | complete for deterministic v0 | `engine/` tests; release `diagnosis` and `kt` gates | no population calibration or delayed-retention evidence yet |
| Bounded Agent learning loop | complete | `runtime/`, `integration/`, append-only trace/replay tests | model-assisted production providers remain optional and gated |
| Xingce, Shenlun, Interview representative coverage | complete | 14 paths × success/ambiguous/offline = 42 fixtures; `domains/` and release gates | representative synthetic fixtures are not the full item bank |
| Loopback-only local service | complete | `service/` tests; health/capabilities/run/trace/replay/skill-report endpoints | browser client wiring is tracked below |
| Real-attempt safety projection | complete | release `attempt_api` and `cohort_prior_guardrail` gates; redacted API evidence artifact | synthetic engineering priors are not real cohort evidence |
| Stepwise learner continuation | complete for local v1 | release `attempt_continuation` gate; versioned probe/verification HTTP trace and replay | single local learner/session; no cross-device concurrency claim |
| Progressive assistance and misconception dossier | complete for P0.1 | six authored levels; `progressive_assistance` and `misconception_dossier` gates; 42 resolved probe/teaching contracts | engineering policy is uncalibrated; synonym/ASR coverage is conservative |
| Khanmigo-grounded, non-AI-slop client | complete | `client/design-qa.md`; 11 authenticated artifacts (six 1280×720 states and five 1800×526 comparisons) with enforced dimensions and hashes; `scripts/check_client_artifacts.py` | visual result is a v0 shell, not a public design system |
| UI uses real sidecar and labels fallback honestly | complete for P0.1 | `client/design-qa.md`; authentic current PNGs; final Sol task `019f4fdb-9368-7b41-81f4-53538957ce7b` | one visible Xingce fixture; Today schedule, Shenlun, Interview and 11 other tools are explicitly unavailable |
| macOS Tauri app manages packaged sidecar | complete for local debug app | `desktop/`; `npm run check:signature`; `npm run check:bundled-sidecar`; `npm run check:managed-app`; `cargo check --locked`; zero-residual process check | strict/deep verified ad-hoc ARM64 debug build, not Developer ID signed, notarized, or universal |
| Automated release evidence | complete for current P0.1 source | `scripts/verify_core.py`; `evals/run_all.py`; fresh 15/15 release run `run-20260711T095034Z` | local deterministic/loopback evidence only; no population efficacy claim |
| Portfolio evidence | complete for v0 mechanics | `portfolio/`, release reports, `client/design-qa.md`, Mac artifact | learner interviews, calibrated population results, and notarized distribution remain future evidence |

## Current release blockers

P0.1 has passed the adversarial re-audit, fresh 15/15 release gates, final full
verifier, strict/deep signed `Lumi.app` checks, bundle-resident sidecar checks,
and frozen Shenlun boundary. The only remaining release action is the intentional
Git commit and push of this exact source cut. P0.2 implementation remains blocked
until that publication completes.

Notarization, population calibration, delayed-retention evidence, full item
coverage, crash recovery, continuation command-result idempotency, and
authoritative longitudinal KT remain future milestones rather than P0.1 claims.

## Claims that remain prohibited

- population learning improvement;
- calibrated cohort-level causal diagnosis;
- delayed-retention lift;
- notarized or production-distributed macOS readiness;
- full Xingce content coverage.
