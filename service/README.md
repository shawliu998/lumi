# Lumi local sidecar

A dependency-free Python HTTP sidecar for the macOS client. It connects the
existing domain, KT engine, Agent runtime, and integration packages; it does not
copy their scoring, diagnosis, mastery, orchestration, or trace implementations.

Security properties:

- the server rejects every bind address except `127.0.0.1`;
- browser origins are restricted to the local Tauri/webview allowlist;
- requests and structured errors carry `X-Request-ID`;
- JSON request bodies are type checked and capped at 64 KiB;
- Host headers are limited to loopback names;
- responses use no-store, nosniff, and restrictive CSP headers;
- public projections never expose filesystem paths, the production Shenlun
  repository, or the bulk question-bank directory.

## Run

```bash
cd $HOME/Documents/peikao/service
python3 -m unittest discover -s tests -v
python3 -m hermes_service --db /tmp/hermes-sidecar.sqlite3 capabilities
python3 -m hermes_service --db /tmp/hermes-sidecar.sqlite3 serve --port 8765
```

The server always listens at `http://127.0.0.1:PORT`; there is intentionally no
CLI option to widen the bind address.

## API

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/v1/health` | Liveness and local storage status |
| GET | `/v1/capabilities` | API/features and 42-scenario capability summary |
| GET | `/v1/scenarios` | Safe 42-scenario catalog; filters: `domain`, `mode` |
| POST | `/v1/attempts` | Start real attempt session (`hermes.attempt-session.v1`) |
| POST | `/v1/attempts/{id}/responses` | Continue probe or independent verification |
| POST | `/v1/attempts/{id}/assistance` | Deliver the next authored probe-help level |
| GET | `/v1/misconceptions` | Rebuildable misconception-dossier summaries |
| GET | `/v1/misconceptions/{id}` | Event-sourced evidence dossier for one attempt |
| POST | `/v1/today-plans` | Create the local-date evidence-backed plan |
| GET | `/v1/today-plans/{id}` | Read a TodayPlan projection |
| GET | `/v1/review-schedule` | Read the independent-review schedule |
| GET | `/v1/runs/{id}/trace` | Append-only events and state/tool artifacts |
| GET | `/v1/runs/{id}/replay` | Hash-verified replay frames |
| GET | `/v1/skills/report` | Evidence-backed per-skill trace summary |

Example:

```bash
curl -sS http://127.0.0.1:8765/v1/attempts \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: real-attempt-1' \
  -d '{"fixture_id":"xingce.data-analysis.growth-rate.synthetic-01","response":"A","confidence":0.8,"response_time_seconds":31}'

# Use run_id, state_version, state and prompt_instance_id from the response.
curl -sS http://127.0.0.1:8765/v1/attempts/ATTEMPT_ID/assistance \
  -H 'Content-Type: application/json' \
  -d '{"phase":"probe","expected_version":5,"expected_state":"awaiting_probe","prompt_instance_id":"ATTEMPT_ID:probe:1","action":"next","elapsed_time_seconds":8,"command_id":"c_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}'

curl -sS http://127.0.0.1:8765/v1/attempts/ATTEMPT_ID/responses \
  -H 'Content-Type: application/json' \
  -d '{"phase":"probe","expected_version":6,"expected_state":"awaiting_probe","prompt_instance_id":"ATTEMPT_ID:probe:1","response":"增长率分母是基期量","confidence":0.8,"response_time_seconds":20}'

# Use the new version returned by the probe continuation.
curl -sS http://127.0.0.1:8765/v1/attempts/ATTEMPT_ID/responses \
  -H 'Content-Type: application/json' \
  -d '{"phase":"verification","expected_version":11,"expected_state":"awaiting_verification","prompt_instance_id":"ATTEMPT_ID:verification:1","response":"C","confidence":0.9,"response_time_seconds":18}'

```

The attempt contract accepts only `fixture_id`, `response`, `confidence`,
`response_time_seconds`, and optional `run_id`. Unknown fields are rejected, so
clients cannot inject a misconception label, mastery value, score, or model
output. The raw response is scored in memory and persisted only as redacted text,
a one-way digest, length, and redaction metadata. The redactor covers email,
mainland mobile/identity numbers, bearer credentials, common API-token forms,
and private-key blocks. Every new public run identifier is an opaque
`r_` plus exactly 40 `A`–`P` characters; every idempotency command identifier
uses the corresponding `c_` profile. The sidecar generates run identifiers when
one is omitted. Existing safe legacy and 32-hex run keys remain readable, but
are never accepted at a new public write boundary. This prevents arbitrary PII
or credentials from becoming durable SQLite keys. Real response evidence uses
current UTC timestamps.

The session is a strict optimistic-concurrency state machine:

1. The first attempt runs `observe → diagnose → probe`, issues the probe prompt,
   then interrupts in `awaiting_probe`. Teaching and KT update do not exist yet.
2. A real `probe` response appends `learner_response_recorded`, resumes only the
   authored `probe_assessed` evidence and teaching phase, returns teaching plus
   the independent verification prompt, then interrupts in
   `awaiting_verification`.
3. A real `verification` response resumes `verify → update → reflect`. Only this
   step can produce intervention effectiveness and the final KT update.

Every continuation must send the exact `expected_version`, `expected_state`, and
`prompt_instance_id` returned by the previous response. Duplicate, stale, and
out-of-order writes are rejected with `409`; the compare-and-append is an atomic
SQLite trace-version CAS as well as a sidecar-local critical section.

The fixture used by an attempt is stored once as an immutable, hash-addressed
content snapshot. Continuation and dossier projection read that snapshot, so a
later catalog edit cannot silently change the meaning of an existing trace.

Probe assistance is server-ordered and fixture-authored: `retry`, locate
evidence, rule hint, analogous example, one worked step, then full explanation.
Each delivery advances the trace version, is idempotent by `command_id`, and
records an explicitly uncalibrated engineering evidence weight. The client
cannot submit a level or evidence weight. Independent verification refuses help;
the verification engine also fails safe if an assisted verification event is
present, withholding mastery and requiring a fresh independent prompt.

The misconception dossier is a rebuildable projection of the append-only trace,
not a second mutable source of truth. It separates observed answer patterns,
ranked hypotheses, authored probe support/refutation, and learning resolution.
Probe evidence also selects the matching authored teaching variant; a refuted
candidate cannot remain the teaching focus. Support never becomes causal ground
truth. A correct initial answer followed by failed independent verification is
reported as a targeted-retry need rather than “no misconception observed”. With
no consented cohort data the dossier returns
`cohort_evidence.status=unavailable` and never emits peer error rates.

Health counts and learner-facing skill, misconception, TodayPlan, and review
projections include only `scenario=attempt` records whose evidence origin is
`human_local_interactive`. Internal evaluation fixtures remain available to the
test harness and explicit trace/replay audit routes, but cannot appear as
learner progress and cannot be created through a public `/v1/runs` route.

The skill endpoint deliberately ignores withheld assisted-verification updates.
It reports the latest committed per-run mastery and aggregate delta; it does not
fabricate a longitudinal merge across isolated demo runs.

P0 does not claim crash recovery, a stored idempotency result for probe or
verification continuation, or longitudinal KT. Processing states fail closed
and require a fresh attempt; durable checkpoints, command ledgers, and an
authoritative learner-skill store are P1 work.
