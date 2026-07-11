# Lumi release evidence harness

This directory is the executable source of truth for Lumi v0 release evidence.
It deliberately distinguishes three outcomes:

- `pass`: the gate inspected authoritative evidence and its assertions succeeded;
- `fail`: evidence exists but is invalid, contradictory, or a command failed;
- `pending`: required product evidence or an integration surface does not exist yet.

`pending` is release-blocking by default. The runner never converts a missing
runtime, domain module, fixture, trace, or teaching policy into a synthetic pass.

## Run

```bash
python3 evals/run_all.py
```

Reports are written to `evals/reports/latest.json` and
`evals/reports/latest.md`. A timestamped JSON report and any computed golden
trajectory are retained beside them. Exit codes are:

- `0`: every required gate passed;
- `1`: at least one gate failed;
- `2`: no gate failed, but at least one required gate is pending.

For local harness development only, `--allow-pending` changes exit code `2` to
`0`; the report and overall status remain `pending`.

Useful options:

```bash
python3 evals/run_all.py --list
python3 evals/run_all.py --gate diagnosis --gate kt
python3 evals/run_all.py --no-write
python3 -m unittest discover -s evals/tests -v
```

## Gate inventory

| Gate | Evidence |
| --- | --- |
| `contracts` | JSON schema syntax and canonical contract examples |
| `fixtures` | 42 independently resolved domain/path/mode fixtures |
| `engine_tests` | deterministic engine test suite |
| `attempt_api` | black-box POST `/v1/attempts`, trace, and replay safety contract |
| `cohort_prior_guardrail` | minimum/privacy policy plus no-data engineering fallback |
| `attempt_continuation` | versioned probe/verification states and fail-closed writes |
| `trace` | replayable observation → decision → state delta → evaluation record |
| `diagnosis` | ranked hypotheses, normalized uncertainty, cohort provenance |
| `kt` | bounded mastery, evidence link, versioned state transition |
| `teaching_transfer` | real success/ambiguous/offline domain→engine→runtime closures |
| `privacy` | redaction contract, local-default/source scan, cloud-bound disclosure |
| `readonly_boundary` | no code dependency or symlink into the production Shenlun repo |

The integration probe writes full replay evidence for all three modes to
`evals/reports/integration-*-trajectory-latest.json`. The compact release report
records their SHA-256 hashes and asserted outcomes.

The attempt API probe starts the real loopback sidecar on an ephemeral port. It
persists only hashed request descriptors and redacted responses in
`evals/reports/attempt-api-evidence-latest.json`; deliberate PII test strings
must never appear in that artifact. Stepwise continuation remains a separate
gate so an initial accepted POST cannot be mistaken for completed teaching.

The schemas are intentionally dependency-free at runtime: `run_all.py` includes
a small validator for the subset used here. Installing `jsonschema` is optional.
