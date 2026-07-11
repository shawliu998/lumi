# Lumi P0 → P1 → P2 execution contract

Status: active. P0.1 is verified and published on
`origin/codex/lumi-p0-p1-p2` at implementation commit `c62c66a`. P0.2 is
verified by final release cut `run-20260711T132028Z` and published at
implementation commit `5e8709d0a1e35bfa85d5a91db2bb42dba9e10af0`; P0.3
is the next production slice. Later phases may prepare read-only audits and isolated evaluation
scaffolding, but production implementation cannot be merged before the
preceding phase passes.

## Non-negotiable boundaries

- `$HOME/Desktop/shenlun-agent-platform` remains read-only and at the frozen
  baseline unless the owner explicitly updates that baseline.
- One deterministic committer owns mastery, misconception state, and review
  schedules. Generators, domain workers, and model calls may only propose
  evidence or artifacts.
- Candidate causes remain hypotheses until a targeted probe supports or rejects
  them. A correct answer never receives an invented error cause.
- Preference memory requires user confirmation. Natural-language memory cannot
  directly change mastery.
- No population, cohort, calibration, or learning-gain claim may be produced
  without consented data and the declared minimum sample/review policy.
- The public product name is Lumi. Existing lowercase `hermes_*` identifiers are
  retained as versioned internal contracts until a deliberate migration exists.

## Ownership and model routing

| Lane | Owner | Model policy | Write scope |
| --- | --- | --- | --- |
| Root supervisor | current task | quality-first | contracts, integration, merge, gates, Git |
| P0 product | Sol window | `gpt-5.6-sol`, xhigh | client plus P0 API/product slices assigned by root |
| P1 runtime | Sol window | `gpt-5.6-sol`, xhigh | initial audit/spec only until P0 gate passes |
| P2 data/eval | Terra window | `gpt-5.6-terra`, high | initial audit/spec and non-production eval scaffolding only |

Low-risk mechanical checks may use Terra. Visual judgment and high-impact
learning-policy decisions require Sol or deterministic verification.

## P0 — user-visible deliberate-practice path

### P0.1 Progressive assistance and misconception dossier

Deliver:

- versioned assistance ladder: retry, locate evidence, rule hint, analogous
  example, one worked step, full explanation;
- assistance events with level, policy version, elapsed time, and evidence
  discount;
- persistent misconception dossier separating observations, ranked hypotheses,
  supporting/refuting evidence, status, and next probe;
- real UI flow over the current versioned attempt continuation API.

Gate:

- assisted work cannot count as independent transfer;
- mastery is absent before independent verification;
- every cause is subtype-specific and visibly unconfirmed where appropriate;
- stale/out-of-order writes fail closed and replay remains hash-valid.

### P0.2 Explainable Today plan and review schedule

Deliver:

- persistent ReviewSchedule projection independent from mastery and KT;
- task reason, expected duration, success criterion, skip consequence,
  immutable activity reference, and trace-resolvable evidence references;
- public accept, complete, postpone, and skip transitions; resurfacing/re-entry
  is an internal due-date and fair-rotation behavior, not a public command;
- deterministic scheduling from completed `human_local_interactive` traces,
  unconfirmed causes, independent-verification evidence, due/overdue windows,
  exam date, accepted commitments, daily budget, and a fixed workload policy.
  It does not consume peer/cohort rates, forgetting probability, fatigue score,
  or predicted learning gain.

Gate:

- every recommendation cites recorded evidence;
- no fabricated precision or peer comparison;
- completion/skip/postpone are replayable and idempotent;
- new public run and command writes use opaque identifiers; batch/demo/
  synthetic-origin runs cannot be created through a public run endpoint or seed
  learner-facing projections;
- +1/+3 windows and task durations are fixed, unvalidated engineering policy;
- the current launchable activity is a same-fixture independent retest, not
  transfer to an unseen parallel item;
- user-marked completion changes scheduling state only and cannot update KT or
  prove learning effectiveness.

### P0.3 Minimal Study Pack

Initial input scope: pasted text and text-bearing PDF. OCR, web crawling, audio,
and bulk ingestion are explicitly deferred.

Deliver:

- durable StudyPack, SourceDocument, SourceSpan, and Artifact records;
- source version/hash and page/section citations;
- one-page notes, 3–5 knowledge cards, three scored practice items, candidate
  skill links, and a review task;
- draft/review/published/quarantined lifecycle;
- generation never publishes an answer key or citation without verification.

Gate:

- citation spans resolve to the frozen source version;
- unsupported or contradictory generation is quarantined;
- generated questions must be answerable from cited evidence and pass schema,
  scoring, leakage, and replay checks.

### P0.4 Shenlun process coach

Deliver one owned representative path:

`material evidence → point extraction → grouping → outline → answer → local
revision → independent rewrite → re-score`.

Gate:

- no production Shenlun repository dependency or mutation;
- evidence coverage, structure, and expression remain separate dimensions;
- model output cannot silently replace learner text;
- independent rewrite is required before learning-state update.

### P0 release gate

- Sol browser QA covers connected, unavailable, invalid-contract, empty,
  loading, error, resume, and completed states at the approved desktop geometry;
- no P0/P1/P2 visual findings and no AI-slop patterns;
- full `scripts/verify_core.py`, release evals, packaged `Lumi.app` lifecycle,
  privacy, and read-only-boundary checks pass.

## P1 — durable bounded-agent platform

Deliver after P0 passes:

- durable jobs with checkpoint, resume, cancel, retry, lease, and idempotency;
- separate Tool, Skill, Artifact, and Policy registries with versions and
  compatibility declarations;
- background artifact generation that cannot commit learning state;
- candidate preference memory with confirm/edit/expire/delete UX;
- KT state plus an independent review-scheduling interface;
- bounded workers/subagents whose proposals require verifier and committer.

P1 gate: crash recovery, duplicate delivery, concurrent continuation, policy
rollback, memory consent, and offline degradation are all executable tests.

## P2 — privacy-safe data flywheel and evaluation

Engineering scope:

- consented learner-event schema and deletion/export lineage;
- semantic metric definitions for independent accuracy, hint reliance,
  misconception resolution, delayed retention, and abstention;
- leakage-safe temporal splits and delayed-retention evaluation harness;
- counterfactual/off-policy replay that is explicitly observational;
- coach view for evidence and review queues;
- cohort-prior pipeline with privacy review and minimum-sample gate.

P2 gate: isolated synthetic learner simulation may validate schemas, lineage,
replay, deletion, and policy invariants, but it cannot enter product
projections, consented cohort denominators, calibration, causal, fairness, or
learning-effect outputs. Without privacy-reviewed consented population data,
those population outputs remain `unavailable`. Engineering readiness can pass
while population efficacy remains unproven.

## Automation and evidence

- Heartbeat automation: `lumi-p0-p2`, every 30 minutes on the supervisor task.
- Canonical evidence remains in `evals/reports/`, `client/design-qa.md`, and
  `docs/COMPLETION_AUDIT.md`.
- Each phase ends with an explicit requirement-to-evidence audit before the next
  phase receives production write authorization.
