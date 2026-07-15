# Lumi local sidecar

A dependency-free Python HTTP sidecar for the macOS client. The default learner
path is the answer-only, fixed-eight core-320 practice flow exposed at
`/v1/practice-sessions`; its public response schema remains
`lumi.practice-session.v2` for client compatibility. The original growth-rate
slice, lesson, fixture, and stepwise-attempt routes remain available for
regression; they are not the default learner journey. The sidecar connects the
existing domain, policy, KT, Agent runtime, and integration packages rather than
reimplementing their decisions.

Security properties:

- the server rejects every bind address except `127.0.0.1`;
- browser origins are restricted to the local Tauri/webview allowlist;
- requests and structured errors carry `X-Request-ID`;
- JSON request bodies are type checked and capped at 64 KiB;
- Host headers are limited to loopback names;
- responses use no-store, nosniff, and restrictive CSP headers;
- pre-answer public projections never expose filesystem paths, the production
  Shenlun repository, the bulk question-bank directory, answer keys, scoring,
  error-option mappings, evidence/material families, validation roles, or
  private authoring metadata.

## Run

```bash
cd $HOME/Documents/zhishixingqiu/service
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
| GET | `/v1/capabilities` | API/features, content version, and capability summary |
| POST | `/v1/practice-sessions` | Start or resume the local fixed-eight smart-practice session |
| GET | `/v1/practice-sessions/{id}` | Resume one persisted practice session |
| POST | `/v1/practice-sessions/{id}/answers` | Submit the currently presented answer |
| POST | `/v1/practice-sessions/{id}/probes` | Answer or skip a pending optional structured probe |
| POST | `/v1/practice-sessions/{id}/end` | End the active session early without fabricating completion |
| GET | `/v1/practice-sessions/{id}/report` | Rebuild one auditable session report from its verified trace |
| GET | `/v1/practice/overview` | One-call profile, recent sessions, wrong-question preview, and next-scope decision |
| GET | `/v1/practice/history` | Paginated fixed-eight practice history |
| GET | `/v1/practice/wrong-questions` | Paginated version-aware wrong-question book |
| GET | `/v1/practice/profile` | Four-module evidence profile without fabricated mastery |
| GET | `/v1/scenarios` | Safe 42-scenario regression catalog; filters: `domain`, `mode` |
| GET | `/v1/lessons` | Manifest-verified historical lesson summaries |
| GET | `/v1/lessons/{lesson_id}` | Auditable historical lesson detail |
| POST | `/v1/attempts` | Start historical stepwise attempt (`hermes.attempt-session.v1`) |
| POST | `/v1/attempts/{id}/responses` | Continue historical probe or verification |
| POST | `/v1/runs` | Run a `success`, `ambiguous`, or `offline` regression loop |
| GET | `/v1/runs/{id}/trace` | Append-only events and state/tool artifacts |
| GET | `/v1/runs/{id}/replay` | Hash-verified replay frames |
| GET | `/v1/skills/report` | Evidence-backed per-skill trace summary |

## Core-320 use (v3 content, compatible v2 response schema)

Start a version-pinned core-320 session by selecting one public scope. The four
module scopes each contain 80 QuestionVersions; the mixed scope reuses the same
320 questions. Scope is fixed in the session trace while learner evidence and
exposure history remain shared across v3 sessions.

```bash
curl -sS http://127.0.0.1:8765/v1/practice-sessions \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: practice-start-1' \
  -d '{"scope_id":"xingce.data-analysis.core"}'
```

Supported v3 scopes are `xingce.verbal.core`, `xingce.judgment.core`,
`xingce.quantitative.core`, `xingce.data-analysis.core`, and
`xingce.mixed.core`. The historical empty body and explicit
`unit_id: xingce.data-analysis.direct-growth-rate` remain available only as the
v2 growth-rate regression path; `scope_id` and `unit_id` cannot be combined.

Copy `session.session_id`, `question.question_id`, and
`question.question_version_id` from that response. The identifiers are
server-issued content/concurrency guards; `answer` is the only required new
learner input. `response_time_seconds` is optional instrumentation.

```bash
curl -sS http://127.0.0.1:8765/v1/practice-sessions/SESSION_ID/answers \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: practice-answer-1' \
  -d '{"question_id":"QUESTION_ID","question_version_id":"1.0.1","answer":"B","response_time_seconds":18}'
```

The response contains the scored result, the minimum feedback selected by
policy, the next safe question when one is due, and links for resuming, ending,
or inspecting the hash-verified trace. If `result.feedback.probe` appears, the
probe is optional and uses one of the same eight slots. Submit one of its option
IDs, or send `__skip__`:

```bash
curl -sS http://127.0.0.1:8765/v1/practice-sessions/SESSION_ID/probes \
  -H 'Content-Type: application/json' \
  -d '{"hypothesis_id":"HYPOTHESIS_ID","answer":"B"}'

curl -sS http://127.0.0.1:8765/v1/practice-sessions/SESSION_ID/probes \
  -H 'Content-Type: application/json' \
  -d '{"hypothesis_id":"HYPOTHESIS_ID","answer":"__skip__"}'
```

Resume an existing session or stop early:

```bash
curl -sS http://127.0.0.1:8765/v1/practice-sessions/SESSION_ID

curl -sS http://127.0.0.1:8765/v1/practice-sessions/SESSION_ID/end \
  -H 'Content-Type: application/json' \
  -d '{"reason":"learner_ended_early"}'
```

## Local learning records

The learning-record endpoints are read-only projections over the same
append-only practice commands and canonical policy state. They do not create a
second learner table. Each request verifies the hash chain and performs the
existing semantic replay before it derives a response; the resulting views are
therefore recoverable after a sidecar restart and retain their pinned content
and policy evidence.

```bash
curl -sS http://127.0.0.1:8765/v1/practice/overview
curl -sS http://127.0.0.1:8765/v1/practice/profile
curl -sS 'http://127.0.0.1:8765/v1/practice/history?limit=20&offset=0'
curl -sS 'http://127.0.0.1:8765/v1/practice/wrong-questions?state=needs_review&limit=20'
curl -sS http://127.0.0.1:8765/v1/practice-sessions/SESSION_ID/report
```

History accepts `limit` (1–100), `offset`, `scope_id`, and `status`. The
wrong-question book accepts the same pagination plus
`state=needs_review|resolved|all` and one of the four module IDs. Empty
collections return HTTP 200 with `total: 0`, `count: 0`, and `items: []`; only
an unknown session report returns `practice_session_not_found`.

Question correctness and response time are observable facts. Error causes are
ranked, reversible hypotheses with ordinal confidence labels and explicit
supporting attempt references. Module `evidence_status` uses independent
question attempts only. Optional probes, skipped probes, repeated exposure,
and other non-independent attempts remain visible in accounting but cannot
create a mastery claim. `overview.recommendation` is the replaceable,
deterministic next-scope policy output; its authoritative scope is
`recommendation.decision.recommended_scope_id`.

The v2 policy has these enforced semantics:

1. A session has exactly eight slots and may end early. The service never adds
   a ninth item to finish a diagnosis, probe, or validation.
2. A correct response continues with folded explanation. The first occurrence
   of an observed error signature receives one light correction without a
   psychological-cause claim.
3. The same signature must recur in independent evidence and material families
   before a controlled microtutorial is shown. If more than one actionable
   cause remains plausible, the service offers the structured, skippable probe
   instead.
4. After an intervention, an unseen and unhinted near-transfer item is eligible
   after two to four other scored questions. If the fixed session has no room,
   the event defers to a later session.
5. A delayed validation is not eligible until at least 24 hours after a
   successful near transfer and must again be independent. Feedback, tutorial
   views, probes, repeated questions, and assisted answers cannot create
   positive diagnostic-unit evidence.

Every accepted mutation records the policy/content versions, reason codes, and
resulting state in the append-only local trace. Immediate answer/intervention
commands are persisted atomically, and replay recomputes pinned score, command,
and canonical state snapshots rather than verifying event hashes alone.
Question/version mismatches, duplicate probe submissions, answers after closure,
unknown fields, and out-of-order requests fail closed. Starting while one local
session is active resumes it only when the requested scope matches; a different
scope returns an explicit conflict instead of silently changing the learner's
selection.

The bundled Core-320 and growth-rate assets are authorized only for the internal
MVP. Human content/correctness and copyright/rights reviews remain required
before external release; deterministic tests are not those reviews.

## Historical v1 regression APIs

The following exercises the older mandatory
`answer → probe → teaching → verification` attempt state machine. It remains
useful regression evidence but is not the smart-practice v2 product path.

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
  -H 'X-Request-ID: offline-regression-1' \
  -d '{"mode":"offline","run_id":"offline-demo"}'
```

The historical attempt contract accepts only `fixture_id`, `response`,
`confidence`, `response_time_seconds`, and optional `run_id`. Unknown fields are
rejected, so clients cannot inject a misconception label, mastery value, score,
or model output. Raw responses are scored in memory and persisted only as
redacted text, a one-way digest, length, and redaction metadata.

That attempt session remains a strict optimistic-concurrency state machine:

1. The first attempt runs `observe → diagnose → probe` and interrupts in
   `awaiting_probe`.
2. A real probe response records the learner response, runs the teaching phase,
   and interrupts in `awaiting_verification`.
3. A verification response resumes `verify → update → reflect`; only this step
   may produce the historical intervention-effectiveness and KT update.

Every continuation sends the exact `expected_version` and `expected_state`
returned previously. Duplicate, stale, and out-of-order writes are rejected
with `409`; continuation bodies inherit the initial request's PII redaction and
size limits.

Historical lesson routes are read-only and accept no query parameters. Their
loader verifies the allowlisted manifest, hashes, `hermes.lesson.v1` contract,
and embedded fixtures before building a separate safe projection. Lesson detail
excludes worked answers, scoring keys, diagnosis internals, verification pass
conditions, source page locators, and private authorship data. A lesson fixture
may still run through `/v1/attempts`, but that route must not replace v2
usability, transfer, or delayed-validation acceptance evidence.

`/v1/scenarios` remains the fixed 42-fixture representative regression catalog.
The skill endpoint reports the latest per-run mastery and aggregate delta; it
does not fabricate a longitudinal merge across isolated demo runs.
