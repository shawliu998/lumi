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
| POST | `/v1/runs` | Run `success`, `ambiguous`, or `offline` learning loop |
| GET | `/v1/runs/{id}/trace` | Append-only events and state/tool artifacts |
| GET | `/v1/runs/{id}/replay` | Hash-verified replay frames |
| GET | `/v1/skills/report` | Evidence-backed per-skill trace summary |

Example:

```bash
curl -sS http://127.0.0.1:8765/v1/attempts \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: real-attempt-1' \
  -d '{"fixture_id":"xingce.data-analysis.growth-rate.synthetic-01","response":"A","confidence":0.8,"response_time_seconds":31}'

# Use run_id, state_version and state from the previous response.
curl -sS http://127.0.0.1:8765/v1/attempts/ATTEMPT_ID/responses \
  -H 'Content-Type: application/json' \
  -d '{"phase":"probe","expected_version":5,"expected_state":"awaiting_probe","response":"增长率分母是基期量","confidence":0.8,"response_time_seconds":20}'

# Use the new version returned by the probe continuation.
curl -sS http://127.0.0.1:8765/v1/attempts/ATTEMPT_ID/responses \
  -H 'Content-Type: application/json' \
  -d '{"phase":"verification","expected_version":9,"expected_state":"awaiting_verification","response":"C","confidence":0.9,"response_time_seconds":18}'

curl -sS http://127.0.0.1:8765/v1/runs \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: mac-client-1' \
  -d '{"mode":"offline","run_id":"offline-demo"}'
```

The attempt contract accepts only `fixture_id`, `response`, `confidence`,
`response_time_seconds`, and optional `run_id`. Unknown fields are rejected, so
clients cannot inject a misconception label, mastery value, score, or model
output. The raw response is scored in memory and persisted only as redacted text,
a one-way digest, length, and redaction metadata.

The session is a strict optimistic-concurrency state machine:

1. The first attempt runs `observe → diagnose → probe`, issues the probe prompt,
   then interrupts in `awaiting_probe`. Teaching and KT update do not exist yet.
2. A real `probe` response appends `learner_response_recorded`, resumes only the
   teaching phase, returns teaching plus the independent verification prompt,
   then interrupts in `awaiting_verification`.
3. A real `verification` response resumes `verify → update → reflect`. Only this
   step can produce intervention effectiveness and the final KT update.

Every continuation must send the exact `expected_version` and `expected_state`
returned by the previous response. Duplicate, stale, and out-of-order writes are
rejected with `409`; the compare-and-append operation is serialized inside the
sidecar. Continuation bodies use a strict field whitelist and inherit the same
PII redaction and size limits as the first answer.

The skill endpoint deliberately reports the latest per-run mastery and aggregate
delta; it does not fabricate a longitudinal merge across isolated demo runs.
