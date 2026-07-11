# Lumi learning-loop integration

This package is glue only. It imports and exercises the existing implementations:

- `hermes_domains.score_attempt` loads and scores a real synthetic domain fixture.
- `HermesKTTool` ranks error-cause hypotheses, updates mastery, and verifies an
  intervention using an independent attempt.
- `AgentRuntime` sequences the seven phases and persists every artifact, state
  diff, and provenance record in its append-only `EventStore`.

No scoring, KT, or tracing algorithm is copied here. The integration tools pass
JSON-compatible payloads across package boundaries. All current operations are
deterministic and local, so the trace correctly records zero model calls rather
than inventing model activity.

`run_attempt(...)` is the real learner-input boundary. It accepts an already
resolved catalog fixture plus response, confidence, and elapsed time. The raw
response is used for deterministic domain scoring in memory; only a PII-redacted
projection and SHA-256 evidence digest enter the runtime trace. It executes only
`observe → diagnose → probe` and interrupts before teaching. `continue_attempt`
accepts an exact trace version/state: a real probe response resumes one teaching
step and interrupts before verification; a real independent verification answer
then resumes `verify → update → reflect`. Each learner response is a distinct
append-only event. No later answer, intervention effect, or mastery update is
invented.

## Run

```bash
cd $HOME/Documents/peikao/integration
python3 -m unittest discover -s tests -v

python3 -m hermes_integration --db /tmp/hermes-integration.sqlite3 run success --run-id success-1
python3 -m hermes_integration --db /tmp/hermes-integration.sqlite3 replay success-1
python3 -m hermes_integration --db /tmp/hermes-ambiguous.sqlite3 run ambiguous
python3 -m hermes_integration --db /tmp/hermes-offline.sqlite3 run offline
```

The `success` scenario confirms independent transfer, `ambiguous` triggers a
disambiguating probe and records failed transfer, and `offline` proves the full
loop and replay need no network or model call. Every mastery delta includes its
attempt evidence, engine provenance, mastery/verification model versions, and
learning-policy version.
