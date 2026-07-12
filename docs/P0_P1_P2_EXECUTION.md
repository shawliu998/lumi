# Lumi P0 → P1 → P2 execution contract

Status: active. P0.1 and P0.2 are verified and published on
`origin/codex/lumi-p0-p1-p2`. The bounded P0.3 Study Pack implementation is at
`0749092`; the real-learner feedback/history correction is at `3b237a1`.
P0.3.1 product-loop correction is now the only production slice. P0.4, P1, and
P2 may retain read-only audits, but their production work cannot begin until the
five-minute vertical loop below passes a real learner browser review.

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

### P0.3.1 Five-minute product-loop correction

The P0.1, P0.2, and P0.3 mechanisms currently exist as bounded slices. This
correction joins them into one learner-visible vertical path before any new
platform phase is allowed:

`real Xingce item/material → first answer → ranked subtype-specific cause
hypotheses → minimal probe → targeted micro-lesson/progressive help → unseen
parallel transfer item → independent verification → explainable KT commit →
review task`.

Deliver:

- a small immutable Xingce data-analysis export with manifest, source version,
  checksums, complete stems/materials/options/keys, and no direct dependency on
  mutable question-bank working files;
- a first-answer screen that visibly presents material, question, choices or
  process input and records answer, confidence, elapsed time, and bounded
  reasoning evidence;
- a versioned data-analysis cause tree covering at least definition/scope,
  base/current period, growth amount/rate, denominator, unit, time range,
  requested quantity, extraction, and calculation errors;
- a probe selected to distinguish the leading hypotheses, followed by teaching
  that targets the supported/refuted evidence rather than the wrong answer in
  general;
- a genuinely unseen parallel item that changes the diagnostic variable while
  preserving the skill target; assisted work cannot count as independent;
- one deterministic committer that alone may update KT and schedule review
  after independent verification;
- an explicit evidence-proposal bridge from Study Pack/domain activity into the
  diagnostic loop; Study Pack itself still cannot write KT, misconception,
  TodayPlan, or ReviewSchedule.

Five-minute acceptance script:

1. A learner opens one real, readable data-analysis item without inspecting
   developer artifacts or knowing fixture IDs.
2. The learner submits an answer and confidence; the interface keeps the
   question and response visible and explains the next diagnostic step.
3. Lumi shows observed facts separately from two or more visibly unconfirmed
   cause hypotheses.
4. One probe changes the evidence for at least one hypothesis; the UI shows
   what was supported or refuted without claiming causality.
5. The learner receives the smallest relevant teaching action and can request
   progressively stronger help.
6. A different parallel item is answered without help. Only this independent
   verification may produce a KT delta.
7. The result explains the state change and the resulting review task, including
   reason, expected duration, success criterion, and skip consequence.

Gate:

- a real learner completes the script in the browser at desktop and narrow
  geometry; question, feedback, and next action are visible in the current
  viewport or reached by an obvious bounded scroll;
- component interaction tests exercise typing, submission, feedback, explicit
  next-step clicks, recovery, and completion; source-text regex checks are only
  supplemental;
- the transfer item is not the first item or the same-fixture retest;
- no synthetic/evaluation answer enters learner projections or visual evidence;
- the final trace replays, every state delta cites evidence, the protected
  Shenlun repository remains untouched, and the Mac app is rebuilt only for the
  completed release candidate.

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

- Heartbeat automation: `lumi-p0-p2` / “Lumi 产品主线持续打磨”, every two hours
  on the supervisor task while waiting for human-only evidence.
- Canonical evidence remains in `evals/reports/`, `client/design-qa.md`, and
  `docs/COMPLETION_AUDIT.md`.
- Each phase ends with an explicit requirement-to-evidence audit before the next
  phase receives production write authorization.
