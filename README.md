# Lumi

Lumi is a local-first, inspectable learning agent for Chinese civil-service
exam preparation. The current learner-facing Xingce loop is deliberately short:

```text
choose a scope -> answer up to 8 questions -> factual group report
-> conservatively recommended or learner-selected next group
```

Diagnosis, optional probes, minimum interventions, transfer checks, and state
updates remain evidence-backed internal policy actions; they are not mandatory
steps the learner must complete after every question.

The repository is intentionally separate from the shared production Shenlun
website. That repository is a read-only reference and is never a dependency or
write target.

The public product name is **Lumi**. Existing lowercase `hermes_*` package,
schema, trace, and sidecar identifiers remain as versioned internal contracts
so the rename does not invalidate stored evidence or API compatibility.

## Current executable foundation

- `engine/`: explainable diagnosis and hybrid BKT/PFA/IRT baseline.
- `runtime/`: bounded local agent loop, traces, persistence, and replay.
- `integration/`: real domain → engine → runtime teaching trajectories.
- `service/`: loopback-only local HTTP sidecar for the desktop client.
- `domains/`: Core-320 Xingce generators plus owned cross-domain regression cases.
- `client/`: Khanmigo-grounded React desktop interface, visually owned by Sol.
- `desktop/`: Tauri 2 macOS wrapper and sidecar launch boundary.
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

The current internal Xingce MVP is Core-320: 80 versioned questions each for
verbal, judgment, quantitative, and data analysis, plus a mixed scope that
reuses the same bank. It is reproduced from deterministic module generators and
the checksum-pinned `domains/practice_v3/manifest.json`; no 320-item dump is
committed. The continuous-practice layer adds a factual eight-question report,
rebuildable history and wrong-question views, a four-module evidence profile,
and a conservative next-scope recommendation without creating a second learner
state store. See `docs/CONTENT_BANK_V3.md` and
`docs/CONTINUOUS_PRACTICE_V1.md`.

External bulk question-bank data remains in `$HOME/Documents/xingcetiku`. Lumi
consumes only bounded, versioned exports with provenance and checksums and never
depends on mutable factory files.

## Safety boundary

`$HOME/Desktop/shenlun-agent-platform` must remain clean and unchanged.
`scripts/check_boundaries.py` verifies the agreed baseline without writing to it.
