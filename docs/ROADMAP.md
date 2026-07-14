# Lumi v0 roadmap

Implementation status is tracked in `COMPLETION_AUDIT.md`; this document keeps
the dependency order and future exit criteria.

The roadmap validates risk in dependency order. Breadth means every exam domain
crosses the same audited contract; it does not mean importing every item first.

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

## Phase 2 — Xingce complete coverage

Deliver:

- a reviewed immutable content package for every subtype in the canonical
  [Xingce coverage matrix](XINGCE_COVERAGE_V1.md), beginning with the released
  conditional-logic reference pack;
- subtype-specific misconception trees and distractor mappings;
- answer/process/confidence capture and deterministic scoring;
- micro-lessons, probes, transfer items, and spaced review;
- first item/distractor/cohort analytics in DuckDB.

Start with text-choice types, then add material and visual asset contracts,
then time-sensitive common/political knowledge. The previous representative
fixture matrix remains mechanism coverage only; it does not make a subtype
available to learners.

Exit: all 31 coverage-matrix rows have a type-specific release pack, isolated
evaluation, human-local browser acceptance and Mac delivery evidence.

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
