# Lumi

Lumi is a local-first, inspectable learning agent for Chinese civil-service
exam preparation. It unifies Xingce, Shenlun, and Interview practice around one
evidence-backed loop:

```text
observe -> diagnose -> probe -> teach -> verify -> update -> reflect
```

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
- `domains/`: owned synthetic representative cases for all three domains.
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

The verifier defaults to `$HOME/Documents/xingcetiku` and
`$HOME/Desktop/shenlun-agent-platform`. Override those locations with
`LUMI_XINGCE_ROOT` and `LUMI_SHENLUN_REPO`; the frozen Shenlun revision can be
overridden explicitly with `LUMI_SHENLUN_EXPECTED_HEAD`.

Bulk question-bank data remains in `$HOME/Documents/xingcetiku`. Lumi
consumes only bounded, versioned exports with provenance and checksums.

Current evidence proves bounded P0.1 assistance/diagnosis, P0.2 scheduling, and
P0.3 cited Study Pack mechanics. The active milestone is P0.3.1: join those
mechanisms into one five-minute real Xingce path with a subtype-specific probe,
targeted teaching, a genuinely unseen parallel transfer item, independent KT
commit, and review scheduling. Until that passes, the repository does not claim
a complete P0 product, three user-facing domains, unseen-item transfer, delayed
retention, calibrated population effects, or production macOS distribution.

## Safety boundary

`$HOME/Desktop/shenlun-agent-platform` must remain clean and unchanged.
`scripts/check_boundaries.py` verifies the agreed baseline without writing to it.
