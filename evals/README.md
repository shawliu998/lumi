# Lumi release evidence harness

This directory is the executable source of truth for the deterministic Lumi
gate set. The runner includes four explicit Core-320 gates and the focused
continuous-practice v1 gate in addition to the historical 13-gate regression
set. The tracked `latest.json` remains the
dated 2026-07-14 legacy 13/13 result until a new run is deliberately written;
do not read that old artifact as evidence for the four-module bank. The harness
deliberately distinguishes three outcomes:

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
python3 evals/run_all.py --gate core320_bank --gate core320_scopes --no-write
python3 evals/run_all.py --gate continuous_practice_v1 --no-write
python3 evals/run_all.py --no-write
python3 -m unittest discover -s evals/tests -v
```

## Gate inventory

| Gate | Evidence |
| --- | --- |
| `contracts` | JSON schema syntax and canonical contract examples |
| `fixtures` | 42 independently resolved domain/path/mode fixtures |
| `engine_tests` | deterministic engine test suite |
| `integration_surfaces` | runtime/domain/integration suites plus real demo, replay, and three-mode learning-loop probes |
| `attempt_api` | black-box POST `/v1/attempts`, trace, and replay safety contract |
| `cohort_prior_guardrail` | minimum/privacy policy plus no-data engineering fallback |
| `attempt_continuation` | versioned probe/verification states and fail-closed writes |
| `trace` | replayable observation → decision → state delta → evaluation record |
| `diagnosis` | ranked hypotheses, normalized uncertainty, cohort provenance |
| `kt` | bounded mastery, evidence link, versioned state transition |
| `teaching_transfer` | real success/ambiguous/offline domain→engine→runtime closures |
| `privacy` | redaction contract, local-default/source scan, cloud-bound disclosure |
| `readonly_boundary` | no code dependency or symlink into the production Shenlun repo |
| `core320_bank` | manifest/schema/digest, 320 unique versions, 80×4, five-scope catalog, complete outside-Git materialization, and inside-Git refusal |
| `core320_scopes` | focused real loopback service suite for all four module scopes plus mixed, fixed-eight behavior, safe projection, persistence, and fail-closed inputs |
| `continuous_practice_v1` | frozen product contract plus focused next-scope policy, five read-model, client contract, and fixed-eight continuation tests; no production build |
| `core320_client` | source-manifest identity, exact client scope catalog, client tests, and production build |
| `core320_packaging` | desktop configuration, packed sidecar digest/five-scope capability, bundled content equality, and managed debug-app lifecycle |

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

## Core-320 behavior

`core320_bank` materializes all four 80-question module files under an ephemeral
directory outside the repository, audits their IDs/counts/digest, then proves
the same command refuses an output path inside the Git workspace. It retains
only hashes and counts as evidence, not a bulk question dump.

`core320_packaging` returns `PENDING`, rather than silently passing, when the
ARM64 sidecar or debug `.app` has not been built. A pass means the built
sidecar reported the source manifest's exact bank ID, version, digest and five
scope counts, and the debug app contained byte-identical versioned manifest,
schema, and safe-sample files while passing lifecycle checks. It is not signing,
notarization, content review, or learner-outcome evidence.

## Continuous-practice v1 behavior

`continuous_practice_v1` requires the frozen contract and four focused test
files to exist. It records each file's SHA-256, the exact command and working
directory for each test surface, command/input/output hashes, exit status, and
captured output. A missing contract, test file, or Node.js runtime is `PENDING`;
a present surface whose focused command fails is `FAIL`.

The gate runs only:

- the deterministic next-scope policy tests;
- the loopback service learning-record/read-model tests;
- the client read-model contract and fixed-eight state tests.

It deliberately does not run `npm run build`; `core320_client` remains the one
gate responsible for client production-build evidence. A pass is evidence for
the documented mechanics and local contracts, not learner usability, transfer,
retention, or exam-score improvement.

`scripts/verify_core.py` invokes the consolidated runner with `--no-write`, so
routine verification cannot overwrite tracked evidence. Run `evals/run_all.py`
without that flag only when a new dated report is intentionally being recorded.
