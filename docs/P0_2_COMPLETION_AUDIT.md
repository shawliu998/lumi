# Lumi P0.2 completion audit

Status: **verified and Git-published P0.2 milestone**

- Release run: `run-20260711T132028Z`
- Implementation commit: `5e8709d0a1e35bfa85d5a91db2bb42dba9e10af0`
- Published branch: `origin/codex/lumi-p0-p1-p2`
- Release report: `evals/reports/latest.json` and `evals/reports/latest.md`
- Release gates: **16/16 pass, 0 fail, 0 pending**
- Full verifier: **17/17 checks pass**
- Scheduling evidence: **23 real HTTP/storage cases, 2675 assertions**
- Mac artifact: `desktop/src-tauri/target/debug/bundle/macos/Lumi.app`
- App-tree SHA-256: `2a2a4002fba273c60eb49352cf3a69978e4722538abe94c46f5ebc3dd93a877d`

This audit covers only P0.2: the independent ReviewSchedule projection,
explainable TodayPlan, its real client flow, identifier and provenance
boundaries, and the rebuilt local Mac app. It does not declare P0.3/P0.4, P1,
P2, population efficacy, or production distribution complete.

## Requirement-to-evidence audit

| Requirement | Decision | Authoritative evidence | Bounded conclusion |
| --- | --- | --- | --- |
| Only real completed learner attempts seed scheduling | **PASS** | `today_plan_schedule`; service/runtime schedule tests | Eligible evidence must be a completed `human_local_interactive` attempt with a verified terminal/update/assessment chain. Evaluation and synthetic origins are excluded. |
| ReviewSchedule is independent from KT/mastery | **PASS** | `runtime/hermes_runtime/schedule.py`; schedule replay tests | The schedule has its own projection, events, versions, receipts, and replay. It cannot commit mastery. |
| TodayPlan recommendations cite resolvable evidence | **PASS** | closed plan/schedule schemas; 23-case release evidence | Each task cross-binds run, event sequence/hash/kind, pointer, semantic, phase, fixture hash, domain, and skill. Candidate causes remain unconfirmed. |
| Scheduling time claims are honest | **PASS — bounded** | `overdue_plus_3_catch_up`; `overdue_plus_1_old_evidence`; client copy QA | +1/+3 windows, durations, and workload limits are fixed, unvalidated engineering policy. Catch-up exposes both the missed base window and actual re-entry date. |
| Current activity truthfully describes transfer limits | **PASS — bounded** | activity-ref contract; client adapter/QA | The only launchable activity is a same-fixture independent retest, not an unseen parallel-item transfer test. |
| Public task actions are replayable and fail closed | **PASS** | runtime/API CAS, receipt, and replay tests | Public actions are `accept`, `complete`, `postpone`, and `skip`. Resurfacing is internal due-date/fair-rotation behavior, not a public command. |
| Accepted commitments cannot be hidden by budget | **PASS** | `accepted_budget_retry`; browser 409→retry QA | A budget below accepted minutes returns `budget_below_accepted_commitment` with zero plan write; the same form can retry with a larger budget. Accepted commitments are shown before the non-accepted cap. |
| Fair rotation does not starve older tasks | **PASS** | skip rotation, dynamic-arrival, recovery-load tests | Due date, presentation count, last presentation, and accepted priority produce deterministic fair rotation. Skip/postpone copy makes no next-day-display promise. |
| Migration, concurrency, and clock skew are auditable | **PASS** | partial/legacy migration, two-Sidecar CAS, stale-clock cases | Nullable/novelty/workload migrations append audit evidence; healthy reopen is nonwriting; exact receipts replay; stale clocks cannot create or mutate historical plans. |
| User-marked completion is not learning evidence | **PASS** | `user_marked_completion`; trace/skill hashes before and after | Completion changes scheduling state only, leaves the learning trace and skill report unchanged, and cannot update KT. |
| Synthetic/demo runs cannot masquerade as learners | **PASS** | `synthetic_origin_excluded`; service black-box tests | Public `POST /v1/runs` is absent. Health, skills, misconception list/single dossier, TodayPlan, and ReviewSchedule project only real human-local attempts. Internal evaluation traces remain explicitly auditable through trace/replay. |
| New public persistent IDs cannot store PII/secrets | **PASS** | runtime/service/client identifier tests; desktop sidecar gate | New run IDs are `r_` plus 40 `A–P` characters; new command IDs are `c_` plus 40 `A–P` characters, generated from 20 random bytes. Legacy safe/32-hex run IDs are read-compatible only. Phone, ID, UUID, semantic, `sk`, GitHub, Google, npm, and Slack-token shapes fail before writes. |
| Client is real, legible, and non-AI-slop | **PASS — bounded** | `client/design-qa.md`; 28 dimension/hash-gated PNGs; 39/39 client tests | Overview, Practice, and Report use real sidecar planning data. Evidence enums are localized; technical hashes/pointers are collapsed by default. Connected, offline, 500, conflict, budget retry, and 640px states were exercised. |
| Packaged Mac app owns the current sidecar | **PASS — bounded** | desktop gates; app hash above | The ARM64 debug app embeds final UI assets and P0.2 sidecar, passes strict/deep ad-hoc signing, a read-only bundle check, normal exit, occupied-port fail-closed, and zero-residual-process checks. It is not notarized or distribution-signed. |
| Production Shenlun repository remains untouched | **PASS** | `readonly_boundary`; final full verifier | Frozen HEAD is `b5a6a4065cf401d54b2809ce7639217c95db3f5d`; worktree is clean and no writable/runtime dependency exists. |

## Final artifact evidence

The final local app was built at `2026-07-11T21:17:10+0800`.

| Artifact | SHA-256 |
| --- | --- |
| App content-tree aggregate | `2a2a4002fba273c60eb49352cf3a69978e4722538abe94c46f5ebc3dd93a877d` |
| Bundled runtime-tree aggregate | `2a6c6ee23cd0d66afe881788565455c7d645d5078e85dc5f6151d8f9c30c0c98` |
| Main `hermes-desktop` executable | `ea7dafbb2d10e82a3faf50784fe841e4a8643283e6688755e51177bd33332aff` |
| Bundle launcher | `70c6d67010fbe73ae1d292aa8359117543cd6039c823d7188249fcae2064fba0` |
| Bundle sidecar runtime | `be91471eede2faeb26908dd2ec7bf2b9fa2283c6c9a0976a8901bb0050b6a6a9` |
| Client CSS `index-DBVsnI8n.css` | `7e3845b39d70bf8c5c60e60eaa9c2c09181cdd30dcd533ea6f7d02e6507251b3` |
| Client JS `index-ReWI9cxo.js` | `186cfe145a20ad2e37fe4f87346400a00db1ea392ca4e74aa5f337e29fef1d0f` |

Codesign reports `Identifier=com.lumi.learning`, `Signature=adhoc`, no team
identifier, and sealed resources version 2 with 100 files. Strict/deep
verification reports `valid on disk` and `satisfies its Designated Requirement`.
The bundle-resident sidecar check isolates HOME/cache/temp/pycache and asserts
the app tree is unchanged before final signing.

## Explicit limitations

- One Xingce growth-rate fixture is launchable from TodayPlan. Shenlun,
  Interview, and other tools remain disabled in the current client.
- A same-fixture retest is not evidence of unseen-item transfer.
- +1/+3 windows, duration, workload, and exam-date rules are uncalibrated.
- There is no forgetting probability, fatigue score, predicted gain, peer rate,
  eligible cohort prior, or population learning-effect result.
- A supported cause remains a supported hypothesis, not a confirmed personal
  cause.
- A completed real verification is one bounded observation; it does not prove
  the teaching intervention caused the result or that retention improved.
- The debug app is ARM64 and ad-hoc signed, not Developer ID signed, notarized,
  universal, or production-distributed.

## P2 synthetic-data boundary

P2 may use simulated learners only in an isolated database/namespace with
`synthetic=true`, generator version, seed, and lineage. That data may test
schemas, deletion/export lineage, replay, and policy invariants. It may never
enter product projections, consented cohort denominators, calibration, causal,
fairness, peer/common-error, or learning-effect outputs.

## Gate decision

All bounded P0.2 engineering, client, desktop, privacy, and read-only gates are
closed for release run `run-20260711T132028Z`. The implementation is recorded at
`5e8709d0a1e35bfa85d5a91db2bb42dba9e10af0` on
`origin/codex/lumi-p0-p1-p2`. P0.3 Study Pack is the next production slice; the
wider P0/P1/P2 objective remains active.
