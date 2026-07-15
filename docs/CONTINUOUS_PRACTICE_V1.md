# Lumi continuous-practice v1 contract

Status: frozen internal-MVP product contract, 2026-07-15.

This document freezes the learner loop that follows Core-320. It complements
`SMART_PRACTICE_V2.md`, which still owns item-level feedback, intervention, and
transfer timing. This contract owns the cross-session experience: group report,
wrong-question view, history, local profile, and conservative selection of the
next practice scope.

Passing this contract establishes software behavior and auditable evidence
handling. It does not establish learning gains, exam-score improvement,
psychological-cause accuracy, usability, or delayed-retention effectiveness.

## Frozen learner loop

The default experience is intentionally short:

```text
choose verbal / judgment / quantitative / data analysis / mixed
→ answer up to eight normal practice slots
→ receive deterministic scoring and minimum useful feedback after each answer
→ see one factual group report
→ continue with the conservatively recommended scope or choose another scope
```

The system updates the local history, wrong-question view, evidence profile, and
next-scope recommendation from the same accepted answer trace. These are not
extra assignments. The learner is never required to open them before starting
the next group.

The following product invariants are frozen:

- A normal session targets exactly eight slots and may end early.
- Answer is the only required learner-entered field for a scored question.
- Explanation remains available after scoring; it is not a prerequisite for the
  next question.
- A structured probe is optional, skippable, and consumes an ordinary session
  slot. It never creates a ninth slot.
- The end-of-group report separates observed facts from possible error causes.
- The primary continuation action starts another fixed-eight direct-practice
  group. It does not create a Feynman-restatement, confidence-reporting,
  self-diagnosis, lesson-completion, or other mandatory training task.
- The recommendation chooses a `scope_id`. Concrete question selection remains
  an internal serving concern and is not exposed as a learner commitment.
- Learner choice remains authoritative: a recommendation can be ignored by
  selecting any available Core-320 scope.

## Evidence semantics

Structured attempt state is authoritative. Conversation text, explanation
views, or client-local summaries cannot replace the accepted attempt and trace
records.

An observed fact may include question and content versions, selected option,
deterministic correctness, diagnostic unit, evidence family, material group,
response time when recorded, assistance/exposure state, and session identity.
Accuracy and elapsed time are descriptive facts, not mastery estimates.

Only attempts marked `independent_evidence` may drive module evidence status or
a weak-skill redirect. Probe answers, skipped probes, hinted attempts, repeated
exposures, and other policy-ineligible attempts remain visible for accounting
but do not become positive mastery evidence or independent weakness support.

The profile read model uses categorical evidence labels, not latent mastery:

- `no_evidence`: no independent attempts;
- `insufficient`: fewer than three independent attempts;
- `needs_attention`: at least three independent attempts with observed accuracy
  below `0.6`;
- `consistent`: at least five independent attempts with observed accuracy at or
  above `0.8`;
- `developing`: the remaining mixed or limited-evidence cases.

These thresholds summarize recorded evidence only. They do not predict an exam
score or assert that a skill has been learned.

Error causes are ranked, reversible hypotheses. Public confidence labels and
scores are ordinal policy outputs with basis/reason codes; they are not
probabilities and are not calibrated psychological claims. Every hypothesis
must retain its supporting independent attempt references.

## One source of truth and read-model rules

The append-only local practice trace remains the source of truth. Each of the
five APIs below rebuilds its response from the verified trace and pinned content
metadata. The derived views must not create separate wrong-book, profile,
history, or recommendation tables that could drift from accepted attempts.

Before returning a view, the service verifies the relevant trace hash and runs
semantic replay through the practice policy. A response carries an `audit`
object that identifies the verified traces and whether the view is rebuildable.
Reading a view must not append an attempt, change evidence status, resolve a
hypothesis, or create a learning-state transition.

Empty local state is valid and explicit: counts are zero, collections are empty,
accuracy is `null`, all four module summaries remain present where applicable,
and the next-scope policy falls back conservatively.

## Five read-only API contracts

All five routes are loopback-local, JSON, `GET`-only contracts. Unknown query
parameters fail with `400 invalid_query`. Schema versions are exact and must be
changed if a breaking response change is introduced.

### 1. Session report

`GET /v1/practice-sessions/{session_id}/report`

Schema: `lumi.practice-session-report.v1`

The report contains:

- the versioned session identity, scope, status, timestamps, and fixed target;
- factual metrics, including authoritative session `scored_count`,
  `question_attempt_count`, `probe_or_skip_count`, and `probe_scored_count`;
- correct/incorrect counts, nullable accuracy, and response-time coverage;
- a module breakdown for modules actually represented in the group;
- evidence-linked, reversible error hypotheses;
- a deterministic continuation summary with reason codes and evidence refs;
- trace and semantic-replay audit metadata.

`scored_count` is the authoritative session counter and may include a scored
probe. `question_attempt_count` counts normal question attempts. Probe counts
must not be silently merged into accuracy or module question totals.

The route accepts no query parameters. An unknown safe session identifier
returns `404 practice_session_not_found`.

### 2. Practice overview

`GET /v1/practice/overview`

Schema: `lumi.practice-overview.v1`

The overview is the compact continuation payload. It embeds the current profile,
the five most recent sessions, up to five `needs_review` wrong-question records,
the versioned next-scope recommendation, and audit metadata. The client consumes
`recommendation.decision.recommended_scope_id`; it must validate that value
against the five known Core-320 scopes before offering the continuation action.

The route accepts no query parameters. Overview recommendation evidence is
descriptive and conservative; it does not override a learner-selected scope.

### 3. Practice profile

`GET /v1/practice/profile`

Schema: `lumi.practice-profile.v1`

The profile contains:

- overall session, scored-question, correctness, independent-evidence, and
  recorded-time facts;
- one entry for each of the four modules, even when it has no evidence;
- all-attempt facts separated from independent-evidence facts;
- ignored non-independent counts, evidence-family coverage, and verified
  transfer counts;
- categorical evidence status with reason codes;
- evidence-linked reversible error hypotheses and an explicit
  `mastery_claimed: false` policy marker;
- audit metadata.

The route accepts no query parameters. The profile is not a KT score, ability
estimate, ranking, or exam forecast.

### 4. Practice history

`GET /v1/practice/history`

Schema: `lumi.practice-history.v1`

Supported query parameters are:

- `limit`: decimal integer in `[1, 100]`, default `50`;
- `offset`: decimal integer in `[0, 1000000]`, default `0`;
- `scope_id`: one of the four module scopes or `xingce.mixed.core`;
- `status`: `active`, `completed`, or `ended_early`.

The response returns `total`, page `count`, pagination values, reverse-
chronological session summaries, links to session detail/report, and audit
metadata. Session summaries keep normal-question and probe accounting distinct.

### 5. Wrong-question book

`GET /v1/practice/wrong-questions`

Schema: `lumi.wrong-question-book.v1`

Supported query parameters are:

- `limit` and `offset` with the same bounds and defaults as history;
- `state`: `needs_review`, `resolved`, or `all`, default `needs_review`;
- `module_id`: one of the four module IDs; mixed is not a module filter.

Records are grouped by the pair `(question_id, question_version_id)`, not by
mutable prompt text. A record is `needs_review` when its latest attempt is wrong
and `resolved` when its latest attempt is correct. It includes the attempted
question projection, post-answer review, attempt counts/timestamps, and any
evidence-linked reversible diagnosis hypotheses.

The wrong-question book is a derived view, not a mandatory review queue. A
correct latest attempt changes the view state; it does not by itself prove
durable retention or erase the historical error evidence.

## Next-scope recommendation policy

Policy ID: `lumi.practice.next-scope`

Policy version: `1.0.0`

Schema: `lumi.next-scope-recommendation.v1`

The policy accepts JSON-first attempt evidence plus the versioned scope catalog.
Its result records policy/version, decision time, recommended/current scope,
reason codes, evidence refs, module summaries, skill summaries, cause
hypotheses, evidence accounting, and internal serving hints.

### Redirect threshold

A diagnostic unit can redirect the next group only when it has all of:

- at least two incorrect attempts eligible as independent evidence;
- failures from at least two distinct sessions;
- failures from at least two distinct evidence families.

Question repetition, help exposure, one session with several errors, or several
attempts from one evidence family cannot satisfy this threshold.

A historically supported weakness is treated as recovered for recommendation
only after the latest failure is followed by at least two independent correct
attempts from at least two sessions and at least two evidence families. Recovery
changes the recommendation status; it does not delete history or establish
long-term retention.

### Module ranking and fallback

Eligible modules are ranked deterministically by:

1. supported weak-skill count, descending;
2. supporting independent failure count, descending;
3. latest supported failure time, descending;
4. the current scope on an exact tie;
5. stable `scope_id` order if a tie remains.

If no weakness meets the redirect threshold, the policy keeps the current valid
scope. If there is no current scope, it returns `xingce.mixed.core`. This is an
explicit insufficient-evidence fallback, not a random recommendation.

### Cause-hypothesis confidence

Cause candidates use fixed ordinal confidence scores:

- `75`, moderate: the same unambiguous candidate appears across at least two
  sessions and two evidence families;
- `60`, moderate: the candidate repeats across those boundaries but at least one
  supporting candidate set remains ambiguous;
- `45`, low: the candidate repeats without both cross-session and cross-family
  support;
- `25`, low: the candidate is observed once.

Every score carries the reason code
`confidence_score_is_ordinal_not_probability`. No score is a calibrated
probability or a finding about the learner's internal mental state.

### Recent-question serving hint

The policy may return the most recent sixteen distinct question IDs as a
`service_internal` soft-avoid list. This delays immediate repetition when the
eligible pool has alternatives. It is not exposed as the learner-facing
recommendation and may be relaxed when the content pool would otherwise be
exhausted. This hint alone is not a spaced-repetition or retention scheduler.

## Explicit non-goals

Continuous-practice v1 does not include or claim:

- mandatory Feynman restatement, written reasoning, confidence input,
  self-diagnosis, or a separate generated training task;
- a mandatory lesson, probe, wrong-book, or review workflow between groups;
- psychological-cause truth, guessing detection, calibrated mastery, ability
  ranking, or exam-score prediction;
- causal teaching effectiveness, transfer lift, delayed-retention lift, or
  population learning improvement;
- a guaranteed question-level schedule, full spaced repetition, or online-RL
  policy optimization;
- common/political-knowledge coverage beyond the current four-module Core-320;
- cloud sync, multi-user accounts, public cohort analytics, or collaboration;
- external content clearance, signed/notarized distribution, or production
  release readiness.

## Local privacy boundary

Core practice, scoring, traces, reports, history, profile, wrong-question views,
and recommendations operate on one Mac through a loopback-only sidecar. The
five read contracts do not require an account or cloud call.

Accepted practice events and version metadata remain in the local SQLite trace.
Derived views are rebuilt rather than copied into new learner-profile tables.
Protected local paths and pre-answer scoring keys remain outside public question
projections. The wrong-question endpoint may reveal the answer only as a
post-answer review of a version the local learner has attempted.

Any future external provider boundary must be separately visible, opt-in,
scoped, redactable, and audited. This contract neither authorizes cloud transfer
nor proves that future export/delete, telemetry-consent, or external privacy
controls are complete.

## Completion gates

This loop may be called mechanically complete only when frozen deterministic
evaluation proves all of the following without manual database repair:

- all five routes are capability-discoverable, schema-pinned, read-only, and
  explicit on an empty database;
- one accepted fixed-eight session reconciles session report, overview, profile,
  history, and wrong-question facts from the same attempts;
- normal-question, scored-probe, skipped-probe, accuracy, and response-time
  accounting cannot be conflated;
- repeated reads and a local restart return the same projections, while no
  shadow learning-record tables are created;
- trace hashes and semantic replay verify before a response is returned;
- invalid filters, unknown fields, unknown sessions, malformed pagination, and
  conflicting evidence fail closed;
- non-independent attempts and probes cannot improve evidence status or satisfy
  the next-scope redirect threshold;
- recommendation branches cover insufficient evidence, cross-session and
  cross-family support, recovery, deterministic ties, duplicate evidence,
  input-order independence, and policy-unavailable fallback;
- the client rejects malformed schemas or unknown recommended scopes and still
  allows the learner to select another valid scope;
- the local build performs the loop without a cloud account or hidden
  cloud-bound operation.

These gates are also recorded in `EVALUATION.md`. Automated completion of them
is engineering evidence only. Real learning, usability, transfer, and retention
claims require separately consented human evidence and an appropriate study.

## Change control

A breaking route, field, status, threshold, confidence meaning, or evidence-
eligibility change requires a new schema or policy version plus replay and
client-contract migration. Copy changes may remain within v1 only when they do
not alter the structured meaning. Recommendation behavior must never be changed
only inside a prompt.
