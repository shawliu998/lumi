# Lumi completion audit

This is the live requirement-to-evidence audit for the local Lumi objective.
`complete` means the stated scope has direct reproducible evidence; it does not
mean population learning efficacy or production distribution has been proved.

| Requirement | Status | Authoritative evidence | Remaining limitation |
| --- | --- | --- | --- |
| `peikao` is the Lumi main repository | complete | root `README.md`, `AGENTS.md`, module layout, root verification | remote repository is intentionally not bound until the user creates it |
| Production Shenlun repository remains read-only | complete | `scripts/check_boundaries.py`; release `readonly_boundary` gate | must remain an operational invariant on every future run |
| Editable Xingce data factory | complete for bounded factory | `$HOME/Documents/xingcetiku/hermes`; 100-item overlay build/validation; `ENRICHMENT_AUDIT_V1.md` | 97/100 have candidate skill/misconception mappings; 3 remain explicitly blocked by missing key content |
| Explainable KT and cause diagnosis | complete for deterministic v0 | `engine/` tests; release `diagnosis` and `kt` gates | no population calibration or delayed-retention evidence yet |
| Bounded Agent learning loop | complete | `runtime/`, `integration/`, append-only trace/replay tests | model-assisted production providers remain optional and gated |
| Xingce, Shenlun, Interview representative coverage | complete | 14 paths × success/ambiguous/offline = 42 fixtures; `domains/` and release gates | representative synthetic fixtures are not the full item bank |
| Loopback-only local service | complete | `service/` tests; health/capabilities/run/trace/replay/skill-report endpoints | browser client wiring is tracked below |
| Real-attempt safety projection | complete | release `attempt_api` and `cohort_prior_guardrail` gates; redacted API evidence artifact | synthetic engineering priors are not real cohort evidence |
| Stepwise learner continuation | complete for local v1 | release `attempt_continuation` gate; versioned probe/verification HTTP trace and replay | single local learner/session; no cross-device concurrency claim |
| Khanmigo-grounded, non-AI-slop client | complete | `client/design-qa.md`; three 1440×1024 final PNGs; `scripts/check_client_artifacts.py` | visual result is a v0 shell, not a public design system |
| UI uses real sidecar and labels fallback honestly | complete for local v1 | `client/design-qa.md`; Sol thread `019f4f2c-22d6-7973-9c03-d6079ffbe9bd` | one local learner/session; completed-panel capture was excluded because of the documented in-app compositor failure, so DOM/API/layout/console evidence is recorded instead |
| macOS Tauri app manages packaged sidecar | complete for local debug app | `desktop/`; `npm run check:managed-app`; `cargo check --locked`; zero-residual process check | ad-hoc signed ARM64 debug build, not notarized or universal |
| Automated release evidence | complete | `scripts/verify_core.py`; `evals/run_all.py`; run `run-20260711T051110Z` with 13/13 gates | rerun after future runtime, UI, packaging, or data-contract changes |
| Portfolio evidence | complete for v0 mechanics | `portfolio/`, release reports, `client/design-qa.md`, Mac artifact | learner interviews, calibrated population results, and notarized distribution remain future evidence |

## Current release blockers

No blocker remains for the bounded local v0 mechanics demo. Binding the new
remote is intentionally deferred until the user creates and authorizes it.
Notarization, population calibration, delayed-retention evidence, and full item
coverage are future milestones rather than claims of this v0.

## Claims that remain prohibited

- population learning improvement;
- calibrated cohort-level causal diagnosis;
- delayed-retention lift;
- notarized or production-distributed macOS readiness;
- full Xingce content coverage.
