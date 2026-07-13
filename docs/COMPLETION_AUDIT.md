# Lumi completion audit

This is the live requirement-to-evidence audit for the local Lumi objective.
`complete` means the stated scope has direct reproducible evidence; it does not
mean population learning efficacy or production distribution has been proved.

> **Scope correction — 2026-07-12.** The application target is now the
> judgement-reasoning-first [Inspectable Adaptive Learning Agent
> charter](PRODUCT_CHARTER.md), with its active acceptance scope in
> [ADAPTIVE_DEMO_SCOPE.md](ADAPTIVE_DEMO_SCOPE.md). The P0.1–P0.3.1 material
> below is retained as a **historical infrastructure audit**: it documents
> reusable local event, verification, replay, and scheduling mechanisms, not
> the current product release. In particular, a data-analysis run, a Study
> Pack, synthetic fixture coverage, or the old 42-path matrix cannot satisfy
> the new judgement-reasoning learner-workspace acceptance.

> **Current release status:** not ready. The new scope needs (1) a
> human-reviewed, rights-cleared in-repository judgement-reasoning pack, (2)
> a human-local cross-run learner-state/decision projection, (3) a connected
> workspace for observe → diagnose → probe → teach → verify → update →
> reflect, (4) deterministic replay/evaluation evidence, and (5) one voluntary
> human walkthrough. No automated answer may be used to fill item (5), and no
> learning-effect claim is permitted from the resulting demo.

## Current judgment-reasoning implementation slice

This table supersedes any implication that the historical 42-fixture or
data-analysis gates are a release signal for the active application.

| Active requirement | Current evidence | Remaining release condition |
| --- | --- | --- |
| Rights-clear conditional-reasoning content | 12 original CC BY 4.0 source records remain checksum-bound and `draft_unreviewed` in `domains/content/judgment/lumi-conditional-reasoning-v0`. The owner-authorized release wrapper `domains/released/judgment/lumi-conditional-reasoning-v0-0.1.0-reviewed-local-20260713` binds the third-review workbook digest, two distinct anonymous reviewer IDs, their date-only precision, the source hashes, and the transformed local release hashes. P02 now makes the necessary→sufficient error explicit before mapping it to M-ROLE support, and T02 removes a time-sequence analogy. | A current sidecar and voluntary human-local browser walkthrough are still required. This is a local controlled release record, not a claim of broad content coverage, population learning effect, or public production distribution. |
| Reachable observe → diagnose → probe → teach → verify loop | `JudgmentSessionService`, closed local HTTP routes, and Workspace expose both D01 condition-direction and D02 inference-validity entry paths; candidates remain unconfirmed and only authored probes/teaching/transfer roles can follow. QA-only browser evidence in `client/design-qa.md` drives D01 → P01 → T01 → V01 through the real temporary sidecar. | One reviewed content pack must complete this exact path in the human-local sidecar; automated paths remain `evaluation_fixture`. |
| Durable learner evidence and update gate | `LearnerStateStore` records origin-isolated facts, hypotheses, decisions, verification receipts, and append-only snapshots. Only an unhinted, unseen transfer may produce its bounded deterministic update; failed or assisted outcomes are withheld. A durable transfer-observation event resumes the same command after interruption. Earlier probe observations are now replayed only for the same learner/origin/pack and can break a tie **only after** the current probe supports multiple authored routes. QA-only browser interaction confirms the same scope after reload, never as a confirmation or write trigger by itself. | The policy has deterministic and QA-only coverage; reviewed content and a voluntary human walkthrough are still required. |
| Reflect and replay | First-answer commands are idempotent; a completed transfer persists a replayable `schedule_review` policy decision. Workspace reload derives local review tasks from that decision ledger; replay displays the learner's submitted answers and state receipt without answer-key/proof leakage. QA-only browser replay observed the four expected events after a committed transfer. | Review-task completion and delayed-item delivery still need their dedicated current-domain flow and human walkthrough. |
| Four-policy mechanics evaluation | `evals/judgment_experiment` has isolated `synthetic:` databases, frozen manifests, redacted traces, paired per-seed outputs, and independent-transfer commit tests for the four protocol policies. | This proves only deterministic simulation mechanics. It cannot approve content, enter a human namespace, or support learning-effect, calibration, cohort, causal, or fairness claims. |

The historical `evals/reports/latest.*` release count therefore remains
compatibility evidence only. It must not be cited as active
judgment-reasoning product acceptance.

## Historical P0.1–P0.3.1 correction status

- P0.1 assistance/diagnosis and P0.2 scheduling remain bounded, verified
  foundations.
- P0.3 Study Pack is implemented for pasted text and text-bearing PDF; real
  learner QA exposed and corrected answer-feedback focus, score-only completion,
  and refresh-history loss at commit `3b237a1`.
- These slices do **not** yet form the required five-minute product loop. The
  active P0.3.1 gate must connect one real Xingce item through subtype-specific
  diagnosis, probe, targeted teaching, unseen parallel transfer, independent KT
  commit, and explainable review scheduling.
- P0.3.1 now has one rights-gated local real-item activity: a signed first item
  and different signed transfer item, an authored probe/teaching overlay, safe
  activity API, and real-material client. A real learner completed all seven
  phases in run `r_NNPBCBAOLCDCFLFJJALKBJCMMFHKKIIHEGLFGEFN`; that run exposed
  two release blockers: a failed transfer incorrectly reduced mastery, and no
  review task was persisted. Policy v2 now withholds KT on failed, assisted, or
  inconclusive verification, and the same immutable trace idempotently created
  a +1-day independent-retry task. A fresh real learner completion on the v2
  build is still required, so the milestone remains open.
- P0.4 Shenlun, user-facing Interview, P1 durable agent infrastructure, and P2
  data/evaluation infrastructure remain unimplemented production work.
- The current 42 representative synthetic contracts are backend coverage, not
  three completed domain products or real learner trials.

Until P0.3.1 passes, `complete` rows below describe their bounded mechanism only
and must not be combined into a claim that the end-to-end P0 product is complete.

| Requirement | Status | Authoritative evidence | Remaining limitation |
| --- | --- | --- | --- |
| `peikao` is the Lumi main repository | complete | root `README.md`, `AGENTS.md`, module layout; `origin=https://github.com/shawliu998/lumi.git`; P0.1 commit `c62c66a`; P0.2 implementation commit `5e8709d0a1e35bfa85d5a91db2bb42dba9e10af0` | review/merge remains pending; implementation continues on the milestone branch |
| Production Shenlun repository remains read-only | complete | `scripts/check_boundaries.py`; release `readonly_boundary` gate | must remain an operational invariant on every future run |
| Editable Xingce data factory | complete for bounded factory | `$HOME/Documents/xingcetiku/hermes`; 100-item overlay build/validation; `ENRICHMENT_AUDIT_V1.md` | 97/100 have candidate skill/misconception mappings; 3 remain explicitly blocked by missing key content |
| Explainable KT and cause diagnosis | complete for deterministic v0 | `engine/` tests; release `diagnosis` and `kt` gates | no population calibration or delayed-retention evidence yet |
| Bounded Agent learning loop | complete | `runtime/`, `integration/`, append-only trace/replay tests | model-assisted production providers remain optional and gated |
| Xingce, Shenlun, Interview representative coverage | complete | 14 paths × success/ambiguous/offline = 42 fixtures; `domains/` and release gates | representative synthetic fixtures are not the full item bank |
| Loopback-only local service | complete | `service/` tests; health/capabilities/real-attempt/trace/replay/skill-report endpoints | public batch/demo run creation is disabled; internal evaluation traces remain separately auditable |
| Real-attempt safety projection | complete | release `attempt_api` and `cohort_prior_guardrail` gates; redacted API evidence artifact | synthetic engineering priors are not real cohort evidence |
| Stepwise learner continuation | complete for local v1 | release `attempt_continuation` gate; versioned probe/verification HTTP trace and replay | single local learner/session; no cross-device concurrency claim |
| P0.3.1 real Xingce product activity | in progress | `domains/content/xingce/p031-data-analysis-v1`; ProductActivity/HTTP/client tests; `client/design-qa.md`; immutable real run `r_NNPBCBAOLCDCFLFJJALKBJCMMFHKKIIHEGLFGEFN`; release verifier 18/18; local debug `Lumi.app` tree `4752ff221c1c72a3a528e945688b3608b2cbf7580200eb0cf7fb232fe0d2d4fb` | v1 real completion exposed and drove KT/review fixes; v2 requires a fresh real full-path acceptance run before release |
| Progressive assistance and misconception dossier | complete for P0.1 | six authored levels; `progressive_assistance` and `misconception_dossier` gates; 42 resolved probe/teaching contracts | engineering policy is uncalibrated; synonym/ASR coverage is conservative |
| Explainable TodayPlan and independent ReviewSchedule | complete for bounded P0.2 | `evals/reports/latest.json` → `today_plan_schedule`; closed schemas; schedule/API tests; `client/design-qa.md` | only completed human-local attempts seed tasks; one owned launchable fixture; +1/+3 and durations are uncalibrated; activity is a same-fixture retest; completion cannot write KT; no population-effect claim |
| Khanmigo-grounded, non-AI-slop client | complete for P0.2 | `client/design-qa.md`; 28 dimension/hash-gated artifacts: 17 current P0.2 states/comparisons plus 11 retained P0.1 artifacts; `scripts/check_client_artifacts.py` | one launchable Xingce fixture; no broad usability or public design-system claim |
| UI uses real sidecar and labels fallback honestly | complete for bounded P0.2 | real first-answer continuation plus TodayPlan/ReviewSchedule browser QA; connected/offline/error/conflict/budget-retry states; Sol task `019f50e4-5a05-7a33-97f3-d47ef1330322` | Shenlun and Interview remain unavailable in the client; no synthetic learner answer or cached/demo plan is substituted |
| macOS Tauri app manages packaged P0.2 sidecar | complete for local ARM64 debug app | `Lumi.app` app-tree SHA-256 `2a2a4002fba273c60eb49352cf3a69978e4722538abe94c46f5ebc3dd93a877d`; strict/deep signature; read-only bundle tree gate; managed lifecycle and zero-residual process checks | ad-hoc signed only; not Developer ID signed, notarized, universal, or production-distributed |
| Automated release evidence | complete for final P0.2 source | `scripts/verify_core.py`: 17/17 checks; `evals/run_all.py`: 16/16 final release cut `run-20260711T132028Z`; `today_plan_schedule`: 23 cases / 2675 assertions | local deterministic/loopback evidence only; no population efficacy claim |
| Portfolio evidence | complete for v0 mechanics | `portfolio/`, release reports, `client/design-qa.md`, Mac artifact | learner interviews, calibrated population results, and notarized distribution remain future evidence |

## Current release state

P0.2 at implementation commit
`5e8709d0a1e35bfa85d5a91db2bb42dba9e10af0` has passed adversarial security and evidence re-audit, the final 16/16
release cut, the 17/17 full verifier, strict/deep signed `Lumi.app` checks,
bundle-tree non-mutation, managed sidecar lifecycle, and the frozen Shenlun
boundary. This proves bounded local scheduling mechanics, not delayed retention
or learning effectiveness.

New public run/command writes use closed opaque IDs. Learner-facing health,
skill, misconception, TodayPlan, and ReviewSchedule projections include only
real `human_local_interactive` attempts. Evaluation-only synthetic traces remain
isolated engineering evidence. Notarization, population calibration,
delayed-retention evidence, full item coverage, crash recovery, continuation
command-result idempotency, and authoritative longitudinal KT remain future
milestones.

## Claims that remain prohibited

- population learning improvement;
- calibrated cohort-level causal diagnosis;
- delayed-retention lift;
- unseen-item transfer from the current same-fixture retest;
- calibrated forgetting, fatigue, duration, or +1/+3 timing;
- user-marked completion as learning evidence;
- cohort/common-error rates without eligible consented data;
- notarized or production-distributed macOS readiness;
- full Xingce content coverage.
