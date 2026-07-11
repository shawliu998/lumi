# Lumi P0.1 completion audit

Status: **verified and Git-published P0.1 milestone**
Evidence cut: `run-20260711T095034Z`, generated
`2026-07-11T09:50:34.167001+00:00`
Release report: `evals/reports/latest.json` and `evals/reports/latest.md`

This audit covers only P0.1: progressive probe assistance, the misconception
dossier, and the real first-answer-to-independent-verification path. It does not
declare the broader P0, P1, or P2 roadmap complete.

Status meanings:

- **PASS**: current deterministic or real-loopback evidence directly supports
  the bounded claim.
- **PASS — bounded**: the mechanism is evidenced, but only for the stated
  fixture, client surface, or synthetic contract scope.
- **PENDING**: required before the P0.1 Git milestone can be released.
- **DEFERRED**: explicitly outside P0.1 and must not be presented as current
  capability.

## Release summary

The current evaluation cut passes **15/15 gates, with 0 failed and 0 pending**.
It supports the P0.1 learning-loop mechanics, local service boundary, privacy
fallback, replay, and read-only repository boundary. The current client also has
real sidecar evidence for its single enabled Xingce fixture.

All bounded P0.1 engineering gates are closed for this source cut. The packaged
`Lumi.app` was rebuilt from the same backend and client, explicitly ad-hoc signed,
strict/deep verified, exercised through its staged and bundle-resident sidecars,
and checked for normal-exit and startup-failure cleanup. Implementation commit
`c62c66a` is published on `origin/codex/lumi-p0-p1-p2` for review.

## Requirement-to-evidence audit

| Requirement | Status | Authoritative evidence | What is proved, and no more |
| --- | --- | --- | --- |
| Real first answer is the learner's submitted answer | **PASS** | `attempt_api`; `attempt_continuation`; `evals/reports/attempt-api-evidence-latest.json`; `service/hermes_service/application.py`; `integration/hermes_integration/loop.py` | `POST /v1/attempts` scores the submitted response, records a redacted evidence projection and current UTC observation time, then stops at `awaiting_probe`. It does not fabricate a later probe or verification answer. Correct first answers create no invented error cause. |
| Real probe response changes evidence | **PASS** | `attempt_continuation`; `misconception_dossier`; domain and integration tests | A continuation accepts the learner's actual probe response under the returned state, version, and prompt instance. Authored assessment can support, refute, or leave a candidate ambiguous. Stale and out-of-order writes fail closed. |
| Probe evidence selects cause-specific teaching | **PASS — bounded** | `teaching_transfer`; `misconception_dossier`; `domains/fixtures/*`; `integration/tests/test_learning_loop.py` | Every resolved representative fixture has authored probe assessment and teaching variants. Supported evidence can change the instructional focus, while a refuted candidate cannot remain the teaching focus. This is authored deterministic coverage, not proof of broad natural-language, synonym, or ASR understanding. |
| Independent verification precedes KT | **PASS** | `attempt_continuation`; `teaching_transfer`; `engine/tests/test_mastery.py`; `service/tests/test_sidecar.py` | Teaching and the probe do not create a final mastery mutation. Only a separately submitted independent verification can reach `verify → update → reflect`. Assisted or non-independent verification withholds KT and requires a fresh independent prompt. |
| Six-level progressive assistance | **PASS** | `progressive_assistance`; `engine/hermes_kt/assistance.py`; `engine/tests/test_assistance.py`; service tests | The server orders `retry → locate_evidence → rule_hint → analogous_example → worked_step → full_explanation`. Each delivery is persisted and versioned; the client cannot choose its level, evidence weight, or independence status. Exhaustion fails closed. The configured weights are explicitly `engineering_policy_unvalidated`, not measured learning-effect weights. |
| Persistent misconception dossier | **PASS** | `misconception_dossier`; `service/hermes_service/dossier.py`; `evals/contracts/misconception-dossier.schema.json` | The dossier is rebuilt from the append-only trace and separates observations, ranked hypotheses, supporting evidence, refuting evidence, learning status, next action, and event references. It is not a second mutable source of truth. |
| Candidate causes never become causal confirmation | **PASS** | domain contracts; dossier contract; client API/adapter tests; `client/design-qa.md` | Allowed claim states are `unconfirmed_hypothesis`, `supported_hypothesis`, and `refuted_hypothesis`. Support and refutation change evidence status and teaching selection, but the UI continues to label each candidate as unconfirmed. `confirmed` and unknown statuses fail closed. |
| No-data cohort fallback is honest | **PASS** | `cohort_prior_guardrail`; `evals/fixtures/xingce_data_analysis_ambiguous.json`; `engine/hermes_kt/cohort.py`; `service/README.md` | Current diagnosis provenance uses `sample_size: 0`, `engineering_prior`, and a synthetic engineering source. The dossier returns cohort evidence as unavailable and emits no peer error rate, popularity ranking, or common-error claim. |
| Representative domain contracts | **PASS — bounded** | `fixtures`; `teaching_transfer`; `evals/reports/latest.json` | **42/42** fixtures resolve: 14 representative domain paths × success, ambiguous, and offline modes. This is contract/scoring/teaching coverage over owned synthetic fixtures, not 42 learner trials, full question-bank coverage, or three completed user-facing products. |
| SQLite CAS, immutable snapshots, and replay | **PASS** | `runtime/hermes_runtime/store.py`; runtime/integration/service tests; `trace`; `attempt_continuation` | Trace events are appended in SQLite with database-level version compare-and-append. Attempt content is stored in immutable hash-addressed snapshots, preventing later fixture drift from changing an existing run. Hash verification and replay are executable. This is not a durable background-job or crash-checkpoint system. |
| Loopback-only local service | **PASS** | service tests; `privacy`; `service/README.md`; `desktop/src-tauri/tauri.conf.json` | The sidecar binds only to `127.0.0.1`, checks Host and allowed browser origins, applies bounded typed request contracts, and exposes no remote connection permission in the current desktop configuration. P0.1 records zero cloud operations. |
| Real client connected and empty states | **PASS — bounded** | `client/design-qa.md`; `client/qa/p01-authentic-overview-empty-real-1280x720.png`; `client/qa/p01-authentic-overview-connected-real-1280x720.png`; `client/qa/p01-authentic-report-connected-real-1280x720.png` | A fresh real sidecar produces a connected empty state with no generated tasks. After one completed real run, the client shows exactly the service-backed run, skill, and independent-verification counts. It does not derive longitudinal mastery labels from the per-run trace summary. |
| Real client learning continuation | **PASS — bounded** | `client/design-qa.md`; the three authentic `p01-authentic-*` core-flow captures; client tests | The visible path submits a real first answer, receives a real probe, records progressive help, shows the event-sourced dossier, renders probe-driven teaching, removes help from independent verification, completes the real verification write, and refreshes the report. Only `xingce.data-analysis.growth-rate.synthetic-01` is currently enabled. |
| Client offline, invalid/error, conflict, and processing behavior | **PASS — bounded** | `client/design-qa.md`; client API/adapter tests | Offline uses a stopped real sidecar and exposes no fallback write. Invalid-contract/error behavior is exercised with a strict health-contract harness. A real stale-version conflict requires restart. Processing states are strict DOM/contract-harness evidence: they remove the consumed prompt and inputs and offer only a fresh-attempt restart; they are not evidence of crash recovery. |
| Packaged Mac app uses the current source | **PASS — bounded** | `desktop/src-tauri/target/debug/bundle/macos/Lumi.app`; `npm run check:sidecar`; `npm run check:bundled-sidecar`; `npm run check:signature`; `npm run check:managed-app`; `cargo check --locked`; app-tree SHA-256 `f25c4b9efbb9f6ba8fe85b26a2b46a4d9fb69a441b21b219a08a0dbab0a8276a` | The ARM64 debug app embeds `index-xjOwtbZH.js`, returns sidecar `0.2.0` with 42 scenarios, rejects PII/secret-like run and command IDs, passes strict/deep ad-hoc signature verification, and leaves zero residual managed process after normal exit and occupied-port failure. It is not Developer ID signed, notarized, universal, or production-distributed. |
| Production Shenlun repository remains read-only | **PASS** | `readonly_boundary`; `scripts/check_boundaries.py`; root `AGENTS.md` | The final full verifier repeated the frozen boundary after packaging: head `b5a6a4065cf401d54b2809ce7639217c95db3f5d`, clean worktree, no dependency or symlink into the production repository. This remains an operational invariant. |
| Portfolio evidence is claim-scoped | **PASS — bounded** | `portfolio/EVIDENCE_INDEX.md`; `portfolio/DEMO_SCRIPT.md`; `portfolio/CASE_STUDY.md`; `client/qa/README.md`; final report and Mac artifact above | Current portfolio evidence may demonstrate local, auditable mechanics on synthetic fixtures and one real browser/sidecar path. Only the `p01-authentic-*` allow-list is current visual evidence. The review branch is published; population/product claims remain prohibited. |

## Current P0.1 gate decision

| Gate item | Decision |
| --- | --- |
| `run-20260711T095034Z`: 15 pass / 0 fail / 0 pending | **PASS** |
| Real answer → probe → cause-specific teaching → independent verification → KT | **PASS — bounded** |
| Progressive assistance and dossier truthfulness | **PASS** |
| `sample_size=0` engineering-prior fallback | **PASS** |
| Authentic connected/empty/core-flow client evidence | **PASS — one fixture** |
| Offline/error/conflict/processing fail-closed behavior | **PASS — evidence types disclosed above** |
| Final `Lumi.app` rebuild and strict/deep ad-hoc signature verification | **PASS** |
| Final bundle-resident identifier guards, managed lifecycle, and zero-residual-process exercise | **PASS** |
| Final full verifier and frozen-boundary recheck after packaging | **PASS** |
| P0.1 Git commit/push | **PASS — `c62c66a` on `origin/codex/lumi-p0-p1-p2`** |

Therefore, the P0.1 implementation is an evidence-backed, fully verified and
Git-published milestone. Review/merge remains a repository workflow decision;
P0.2 may now begin on top of this published source cut.

## Explicit P1 deferrals

These are known boundaries, not P0.1 defects hidden by a green evaluation run:

- **Processing recovery is restart-only.** `processing_probe` and
  `processing_verification` fail closed and require a new first answer. There is
  no durable checkpoint that resumes the consumed continuation after a crash.
- **Probe/verification continuation has no command-result idempotency ledger.**
  SQLite CAS rejects duplicate or stale versions, but a continuation request has
  no stable `command_id` whose completed result can be replayed after an unknown
  client outcome. Progressive-assistance commands do have their own bounded
  `command_id` replay behavior; that does not generalize to continuation.
- **KT is per-run, not longitudinal.** Each current attempt starts from the
  engineering seed state with mastery `0.30`. `/v1/skills/report` summarizes
  completed run evidence; it is not an authoritative learner-skill history and
  must not be presented as “recently stable”, “mastered”, or a durable trajectory
  across sessions.
- Durable jobs, leases/fencing, retry/cancel checkpoints, a command ledger,
  policy registry, confirmed preference memory, and a single authoritative
  committer across background workers remain P1 work.

## Explicit product and UI deferrals

- The client enables exactly one real fixture:
  `xingce.data-analysis.growth-rate.synthetic-01`.
- Dynamic question/content mapping is not implemented in the client. Disabled
  tool cards must remain disabled and must not silently open the growth fixture.
- The explainable Today plan, persistent review schedule, accept/postpone/skip/
  resurface transitions, and due-review projections are P0.2 work.
- Study Pack creation and source-citation verification are P0.3 work.
- The user-facing Shenlun process coach is P0.4 work.
- Agent Lab, dynamic trajectory exploration, and cross-domain Xingce/Shenlun/
  Interview client workflows are not implemented.
- The 42 synthetic fixtures validate shared contracts and backend mechanics; they
  do not make the disabled cross-domain UI available.

## Explicit P2 and research deferrals

- Assistance weights, diagnosis priors, probe rubrics, teaching variants, and KT
  parameters are engineering rules. They are not calibrated on a consented
  learner population.
- There is no evidence for population learning effectiveness, causal tutoring
  effect, error-cause accuracy across learners, subgroup fairness, equalized
  performance, delayed-retention lift, examination-score lift, or long-term
  engagement benefit.
- A supported hypothesis is not a confirmed personal cause. A completed
  independent verification is one bounded observation, not proof that the
  teaching intervention caused the result.
- With no consented, privacy-reviewed dataset meeting the approved sample and
  cell thresholds, cohort, calibration, causal, and fairness outputs must remain
  unavailable. Synthetic fixtures cannot fill those sample counts.
- Future synthetic learner simulation is permitted only as an isolated
  engineering/evaluation asset. It must be explicitly marked `synthetic`, use a
  separate manifest/namespace, remain excluded from consented cohort builders,
  calibration datasets, product reports, and population metrics, and never be
  described as real learner or peer evidence.

## Portfolio-safe wording

Allowed for this verified, Git-published P0.1 milestone:

> On 42 owned synthetic representative fixtures and one real loopback browser
> path, Lumi enforces a versioned answer → probe → cause-specific teaching →
> independent verification flow, preserves candidate causes as hypotheses, and
> writes replayable per-run KT evidence only after independent verification.

Not allowed:

- “Lumi has confirmed why this learner made the mistake.”
- “This is a common error among other learners” or any peer error rate.
- “The learner has mastered this skill” or “recent performance is stable.”
- “Lumi improves learning, retention, fairness, or exam results.”
- “All three domains are available in the Mac client.”
- “P0.1 includes durable crash recovery, longitudinal KT, scheduling, or Agent
  Lab.”

## Final release checklist

- [x] Fresh P0.1 evaluation report is `run-20260711T095034Z` with 15/15 gates.
- [x] Sample-zero engineering-prior and unavailable-cohort semantics are present.
- [x] Authentic client artifacts are allow-listed and synthetic visual history is
  excluded from current evidence.
- [x] Rebuild `Lumi.app` from the exact current backend and client source.
- [x] Run staged and bundle-resident sidecar identifier/version checks,
  strict/deep signature verification, normal-exit, occupied-port/startup-failure,
  termination, and zero-residual-process checks.
- [x] Run the final full verifier and repeat the frozen Shenlun boundary check.
- [x] Confirm the final report, Mac artifact, and portfolio index refer to the
  same source cut.
- [x] Create and push the P0.1 Git milestone (`c62c66a`,
  `origin/codex/lumi-p0-p1-p2`).
