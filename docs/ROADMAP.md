# Lumi v0 roadmap

Implementation status is tracked in `COMPLETION_AUDIT.md`; this document keeps
the dependency order and future exit criteria.

## Current execution order

The numbered phases below describe the architecture roadmap; they are **not** a
claim that every earlier product phase is externally released. The active
checkpoint is **P0.4 — continuous-practice v1**. Core-320 breadth and the local
cross-session continuation layer are implemented: verbal, judgment,
quantitative, and data-analysis each contain 80 versioned questions and share
the same direct-practice policy:

```text
learner sees: direct eight-question practice → answer
→ minimum feedback → natural next item → factual group summary
→ one-click recommended or learner-selected next group

system records: versioned item → deterministic score → uncertain cause hypotheses
→ minimum intervention policy → unseen transfer → delayed validation eligibility
→ rebuildable history/wrong-question/profile views → audited next-scope decision
```

Every automated record binds the visible activity to its content artifact,
launch request, learner attempt, trace/replay, policy decision, and state delta.
The owner has explicitly removed a voluntary usability session as a prerequisite
for internal breadth. Automation may prove mechanics but may not impersonate a
learner or be cited as real usability, transfer, or retention evidence.

The approved 2026-07-14 correction remains specified in
`SMART_PRACTICE_V2.md`. Growth-rate is the retained deep reference slice; v3
generalizes its checksum-verified content, fixed-eight policy, direct-practice
client, append-only decisions, near transfer, and delayed-validation contracts
to four modules. The earlier micro-lesson, mandatory continuation runtime, and
v2 content package remain regression or focused-practice fixtures rather than
the default product path.

The roadmap validates risk in dependency order. Breadth means every exam domain
crosses the same audited contract; it does not mean importing every item first.

### Next execution slice — P0.4.1 internal trial and learner calibration

Do not add another large question batch or mandatory teaching stage yet.
Content review is deferred from this internal execution slice by owner decision;
it remains an external-release requirement. Prioritize:

1. restore a supported screenshot/browser channel and capture the current
   module selection, normal answer, incorrect feedback, optional intervention,
   final summary, offline/error, and narrow-width states;
2. collect consented local attempt telemetry for item difficulty, option
   selection, completion, response time, intervention exposure, near transfer,
   and delayed return—without treating it as psychological ground truth;
3. observe whether the factual report and one-click next group improve session
   continuation without adding learner work; keep recommendation evidence and
   learner overrides separately measurable;
4. add an explicit version-preservation or migration path before a future bank
   version replaces v1.0.1, so old accepted attempts remain replayable;
5. replace the text/Unicode-only judgment-figure subset with versioned visual
   assets and deterministic geometry metadata;
6. use those data to calibrate scheduling before
   deciding whether common-knowledge breadth or additional volume is valuable.

This slice is the recommended next work order, not a condition for continuing
to use the current internal Core-320 build.

## Phase 0 — repository and executable skeleton

Deliver:

- repository conventions, architecture decision records, and local setup;
- Tauri/React macOS shell with the approved Khanmigo-grounded navigation and learning views;
- Python sidecar handshake and health status;
- SQLite migrations, append-only event contract, trace IDs, and fixture importer;
- offline/cloud capability indicator and provider interface.

Exit: a fresh local launch records and replays a synthetic trajectory without a
model call, and no dependency writes to the Shenlun production repository.

## Phase 1 — shared learning kernel

Deliver:

- versioned skill graph and content-skill Q-matrix;
- attempt/event, hypothesis, intervention, verification, mastery-history, and
  review-schedule entities;
- interpretable BKT/PFA baseline with uncertainty, forgetting, and rebuild;
- cohort-prior hierarchy with synthetic/curated provenance labels;
- bounded orchestrator state machine and typed learning tools;
- trace timeline and state-diff views.

Exit: frozen synthetic cases execute observe → diagnose → probe → teach → verify
→ update with deterministic replay and evidence-complete state changes.

## Phase 2 — Xingce breadth slice

Deliver:

- a small validated content package for one subtype in each major module;
- subtype-specific misconception trees and distractor mappings;
- answer/process/confidence capture and deterministic scoring;
- micro-lessons, probes, transfer items, and spaced review;
- first item/distractor/cohort analytics in DuckDB.

2026-07-15 checkpoint: the contract is implemented for verbal, judgment,
quantitative, and data analysis as Core-320. Common/political knowledge remains
deferred; adding it is not required for the current four-module internal MVP.

Exit: all Xingce rows in the representative matrix pass release gates.

## Phase 3 — independent Shenlun module

Deliver:

- owned fixtures and rubrics for five representative task types;
- material-point, dimension, evidence-span, and revision events;
- verifier-supported structured scoring with explicit unresolved states;
- targeted revision and independent re-evaluation loops.

Constraint: use the production Shenlun repository only as read-only conceptual
reference. Do not modify, branch, commit, or depend on its mutable source tree.

Exit: all Shenlun matrix rows pass without production-repository mutation.

## Phase 4 — Interview module

Deliver:

- local recording/import, configurable retention, transcription adapter;
- four representative rubrics with content and delivery evidence separated;
- second-answer comparison, coaching, and skill updates;
- transcript-first offline/degraded workflow.

Exit: all Interview rows pass, including audio-disabled transcript fixtures.

## Phase 5 — hybrid intelligence and policy research

Deliver:

- BKT/PFA/IRT/graph-aware comparison and calibrated ensemble interface;
- model disagreement and abstention surfaced in Agent Lab;
- expected-information-gain probe selection;
- offline contextual-bandit dataset and counterfactual policy evaluator;
- frozen regression suite for prompt/tool/policy candidates.

Sequence KT models are experimental until trajectory volume and leakage-safe
evaluation justify them.

Exit: a versioned model card compares candidates and the production default wins
or is retained on declared criteria.

## Phase 6 — portfolio hardening

Deliver:

- reproducible signed/notarization-ready macOS build path;
- demo learner and resettable local dataset;
- privacy/export/delete controls and cloud-boundary walkthrough;
- architecture, research, limitations, and evaluation narrative;
- two scripted demonstrations from `EVALUATION.md`.

Exit: a new Mac can run the offline demo, a reviewer can audit every state change,
and limitations distinguish measured results from future hypotheses.

## Workstream ownership and integration order

Workstreams may proceed in parallel only after shared contracts are versioned:

1. Client/runtime consumes the event and trace contracts.
2. Learning kernel owns state transitions and model interfaces.
3. Domain modules own evidence extraction and scoring payloads.
4. Content/data factory publishes immutable packages.
5. Evaluation owns frozen fixtures and release-gate reports.

Integrate vertical slices early. A thin complete loop in each domain has priority
over polishing isolated subsystems.

## Explicitly deferred

- multi-user server and real-time collaboration;
- automatic production deployment or shared-repository integration;
- full 78k-question import before package QA and skill coverage are stable;
- online RL, unreviewed self-modifying prompts, or autonomous policy release;
- cross-device sync and public cohort analytics before privacy governance.
