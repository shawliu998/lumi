# Lumi

Lumi is an **Inspectable Adaptive Learning Agent**: a local-first system that
uses learning evidence to maintain an explicit learner state, select the next
diagnostic or teaching action, and verify whether learning actually transfers.
It is not a question-bank wrapper or a chat-first AI tutor.

```text
observe -> diagnose -> probe -> teach -> verify -> update -> reflect
```

The active application domain is **all Xingce question types**. Conditional
logic is the first released, human-reviewed component; the remaining 30 rows
of the versioned 31-subtype coverage matrix are still planned, not implied by
the historical fixture catalogue. See
[the coverage contract](docs/XINGCE_COVERAGE_V1.md). Shenlun, Interview,
communities, and generic tutoring are future Domain Packs, not current product
claims.

The repository is intentionally separate from the shared production Shenlun
website. That repository is a read-only reference and is never a dependency or
write target.

The public product name is **Lumi**. Existing lowercase `hermes_*` package,
schema, trace, and sidecar identifiers remain as versioned internal contracts
so the rename does not invalidate stored evidence or API compatibility.

## Current executable foundation

- `engine/`: explainable diagnosis and hybrid BKT/PFA/IRT baseline.
- `runtime/`: bounded local agent loop, traces, replay, and persistent independent
  ReviewSchedule/TodayPlan projections.
- `integration/`: real domain → engine → runtime teaching trajectories.
- `service/`: loopback-only local HTTP sidecar for real attempt continuation and
  scheduling; public batch/demo run creation is disabled.
- `domains/`: versioned Domain Packs, including the current judgement-reasoning
  draft pack and bounded historical representative fixtures. The draft pack is
  deliberately not launchable until logic and editorial/rights review bind the
  exact content hashes.
- `client/`: Khanmigo-grounded React desktop interface for real connected
  learning and planning states, visually owned by Sol.
- `desktop/`: Tauri 2 macOS wrapper, managed sidecar boundary, and strict/deep
  verified local ARM64 debug app path.
- `evals/`: deterministic release gates and evidence reports.
- `docs/`: product, architecture, learning-loop, evaluation, and roadmap specs.
- `portfolio/`: reviewer-facing case study and demonstration material.

Run the local deterministic checks from the repository root:

```bash
python3 scripts/verify_core.py
```

The application verifier runs against in-repository Lumi Domain Packs and the
protected `$HOME/Desktop/shenlun-agent-platform` boundary. Legacy question-bank
validation is opt-in for data-factory work, not a requirement to build or
demonstrate Lumi. The frozen Shenlun revision can be overridden explicitly with
`LUMI_SHENLUN_EXPECTED_HEAD`; it remains read-only.

The application demo must run with a compact, rights-clear item bank committed
with the repository. Bulk question-bank data remains an optional, bounded
reference input; the product must not require it for reviewer reproducibility.

Current evidence proves bounded assistance/diagnosis, scheduling, Study Pack,
and local agent-loop mechanics. The active product programme is one such
five-minute path for each coverage-matrix subtype: real learner evidence →
competing diagnosis hypotheses → discriminating probe → targeted teaching action
→ unseen transfer → explicit state update or withholding → delayed review. Until
all 31 rows meet that bar, Lumi does not claim complete Xingce coverage,
delayed-retention efficacy, calibrated population effects, or production macOS
distribution. See [the product charter](docs/PRODUCT_CHARTER.md).

## Safety boundary

`$HOME/Desktop/shenlun-agent-platform` must remain clean and unchanged.
`scripts/check_boundaries.py` verifies the agreed baseline without writing to it.
