# Lumi P1 Runtime audit and implementation contract

Status: **audit/specification only; blocked on the P0 release gate**
Audit date: 2026-07-11
Audited scope: `AGENTS.md`, `docs/P0_P1_P2_EXECUTION.md`, `runtime/`,
`service/`, `integration/`, and `engine/`.

This document is a read-only P1 planning artifact. It does not authorize changes
to runtime, service, integration, engine, or client production code. No P1
production implementation, schema migration, or client flow may start until the
root supervisor records that P0 passed and explicitly releases P1.

## 1. Executive decision

The repository has a useful P1 seed, but not a durable bounded-agent platform.
The following foundations can be retained:

- phase-boundary `interrupt`/`resume` and snapshot reconstruction;
- a local SQLite, append-only, redacted, per-run hash-chained trace;
- typed JSON tool boundaries with phase restrictions and versioned manifests;
- deterministic model routing metadata and recorded model-call metadata;
- stale/out-of-order attempt continuation checks;
- an independent-transfer gate before a staged real attempt reaches the current
  `update` phase;
- deterministic KT functions that accept structured attempt evidence;
- an atomic SQLite trace-version compare-and-append that rejects two same-version
  writes even across separate local connections, with a process-local lock kept
  only as a UX optimization.

The following P1 capabilities do **not** exist yet and must not be inferred from
the above:

- no `DurableJob` aggregate, checkpoint record, lease/fencing protocol, retry
  policy, cancellation state machine, delivery idempotency ledger, or dead-letter
  disposition;
- no cross-process or crash-safe continuation claim;
- no Tool/Skill/Artifact/Policy registry separation;
- no durable artifact lifecycle owned independently from run snapshots;
- no confirmed long-term preference-memory store or consent lifecycle;
- no authoritative longitudinal KT store;
- no independent `ReviewSchedule` store or scheduling interface;
- no bounded worker proposal/verifier/committer protocol;
- no deterministic single-writer enforcement for mastery, misconception state,
  and review schedules.

P1 should extend the current event-sourced vocabulary, but should not turn
`AgentState`, free-form artifacts, or conversation memory into authoritative
learning state.

## 2. Current-state audit

### 2.1 Reusable runtime behavior

| Existing behavior | Evidence in the current tree | P1 reuse decision | Limit that must remain explicit |
| --- | --- | --- | --- |
| Bounded phase machine | `runtime/hermes_runtime/machine.py` executes `observe → diagnose → probe → teach → verify → update → reflect`; `max_steps` and `max_cycles` bound execution | Reuse the phase runner as one job handler or workflow definition | A loop run is not a durable job and its phase output is not automatically an authorized state write |
| Phase-boundary interrupt | `AgentRuntime.run(..., interrupt_after=...)` appends `run_interrupted` before the next phase | Reuse as a cooperative safe point | It cannot interrupt a tool already executing and has no durable cancel intent |
| Resume from stored snapshot | `EventStore.load_state()` finds the latest `state_after`; `AgentRuntime.resume()` appends `run_resumed` | Reuse snapshot format through an explicit versioned checkpoint adapter | It resumes any interrupted/paused run without lease ownership, registry compatibility resolution, or checkpoint CAS |
| Append-only trace | `runtime/hermes_runtime/store.py` uses SQLite WAL, `BEGIN IMMEDIATE`, append-only triggers, sequence numbers, redaction, and a SHA-256 chain | Reuse canonical JSON, redaction, hash-chain verification, and local SQLite operational assumptions | The sequence lookup and append protect one event append, not an entire read/execute/checkpoint transaction |
| Offline replay | `EventStore.replay()` verifies the chain and yields recorded snapshots without invoking tools/models | Retain for audit and build a version-aware job replay projection around it | Replay currently trusts stored `state_after`; it does not re-run reducers or validate registry availability |
| Tool boundary | `ToolSpec` has name, version, schemas, phases, handler; `ToolRegistry.invoke()` checks a small schema subset | Use as the compatibility adapter for the first Tool Registry migration | The registry is in-memory, rejects any duplicate name regardless of version, and has no capabilities, digest, lifecycle, or compatibility declarations |
| Guardrails | protected-path/network checks and phase allow-lists | Retain as defense in depth and move effective authorization into versioned Policy entries | `repr(payload)` substring checks are not a complete capability sandbox |
| Model trace | tier, model, settings, usage, latency, cost, and route reason are recorded when available | Retain fields in proposal and job-attempt traces | Current deterministic integration path makes no model calls; absence of calls must remain explicit |

### 2.2 Reusable service and integration behavior

| Existing behavior | Reuse | Required correction before a P1 claim |
| --- | --- | --- |
| `expected_version` plus `expected_state` rejects stale and out-of-order attempt responses; `EventStore.append_if_version()` performs the trace compare-and-append under `BEGIN IMMEDIATE` | Reuse the fail-closed SQLite CAS semantics for job commands and committer writes | The CAS protects one trace append, not an atomic durable-job checkpoint/result/outbox transaction |
| `SidecarApplication._continuation_lock` avoids redundant concurrent local work while SQLite CAS accepts exactly one same-version write across connections | Keep the lock as a local UX optimization and SQLite CAS as a storage primitive | A restarted caller still lacks a stored command result; P1 also needs job row versions, leases/fencing, and command-result replay |
| `learner_response_recorded` stores redacted text, digest, timing, confidence, phase, and prior version | Reuse the evidence projection and redaction policy version | A digest is not an idempotency key; duplicate delivery needs a caller-scoped command key and stored result |
| staged attempt stops before teaching and before verification, then resumes one authorized segment | Reuse waiting states and explicit learner-response commands | Waiting-for-user and worker retry/cancel states must be different durable job states |
| real attempt does not expose a mastery update before verification | Preserve as a P1 invariant | Current integration computes an initial KT update inside `_verify`; P1 must make the committer the only authority and must reject unverified or assisted evidence according to the learning policy |
| tool and policy versions are copied into trace outputs | Reuse provenance fields | Jobs must pin resolved registry entry IDs/digests, not look up “latest” on resume |

### 2.3 Reusable engine behavior

`engine/hermes_kt` already provides deterministic, JSON-friendly diagnosis,
mastery, and independent-transfer functions. In particular:

- `AttemptEvidence` is structured and carries attempt/item identity, correctness,
  response time, confidence, hint count, independence, feature evidence, and
  observation time;
- `update_skill_state()` records component values, ensemble weights, formula
  version, and attempt provenance;
- `evaluate_intervention()` distinguishes independently verified, effective,
  ineffective, and inconclusive outcomes;
- routing decisions explicitly set `may_directly_update_mastery=False`;
- generated diagnosis validation requires normalized hypotheses and evidence IDs.

These functions should remain behind a replaceable deterministic KT interface.
They do not currently provide a persistent, longitudinal, concurrency-controlled
`KTState`. `integration/hermes_integration/loop.py::_initial_state()` resets each
run to a fixed value, and `service.skill_report()` explicitly reports a trace
summary rather than a longitudinal merge. P1 must not rebrand either behavior as
the learner's authoritative mastery history.

The current engine function also does not itself reject hinted or
non-independent evidence: `update_skill_state()` updates whatever valid
`AttemptEvidence` it receives, while `evaluate_intervention()` marks assisted
verification inconclusive only after producing a post-state. Therefore P1 must
enforce evidence eligibility/discount in the pinned learning policy and
deterministic committer. Callers must not treat the engine's JSON-friendly API as
write authorization.

### 2.4 What the current event store proves—and does not prove

It proves:

1. events within a run receive a monotonic sequence;
2. stored payloads are passed through the current redactor;
3. update/delete of trace rows is blocked by triggers;
4. the per-run hash chain can be verified;
5. a process can reopen a database and resume from the last stored snapshot at a
   phase boundary.

It does not prove:

1. that a tool side effect and its event/checkpoint are atomic;
2. that two processes cannot run the same checkpoint concurrently;
3. that an expired worker cannot commit after a new worker takes ownership;
4. that duplicate commands return the same result without repeating effects;
5. that cancellation reaches or safely fences an executing tool;
6. that a retry resolves the same Tool/Skill/Artifact/Policy versions;
7. that a stored snapshot is readable after schema/registry upgrades;
8. that redaction catches arbitrary personal or sensitive learning content.

## 3. DurableJob contract to add after P0 release

### 3.1 Aggregate and state machine

The minimum durable aggregate is `DurableJob`. A job is orchestration state, not
learner state.

```text
queued → leased → running → {waiting_user, retry_wait, compatibility_blocked,
                             succeeded, failed}
                    │
                    ├→ cancel_requested → cancelled
                    └─(checkpoint event)→ queued/leased

retry_wait → queued
waiting_user → queued (only through a valid, idempotent continuation command)
compatibility_blocked → queued (only when the exact pinned dependency is usable)
failed → new queued successor job (only through an explicit retry command)
```

Terminal states are `succeeded`, `failed`, and `cancelled`. `cancel_requested`
and `compatibility_blocked` are non-terminal. A checkpoint is an event/safe
boundary, not a status. `dead_lettered` may be represented as `failed` plus a
terminal failure disposition in v1; it does not need a separate public state.

Minimum `durable_jobs` fields:

| Field | Rule |
| --- | --- |
| `job_id` | Stable opaque ID; primary key |
| `job_type` | Namespaced workflow type, for example `artifact.generate` |
| `job_schema_version` | Integer envelope version |
| `status` | Closed enum above |
| `subject_ref` | Typed local subject, not arbitrary free text |
| `input_json` / `input_digest` | Validated redacted input plus canonical digest |
| `priority` | Bounded integer; must not bypass policy |
| `attempt_count` / `max_attempts` | Retry accounting; attempt increments only on a newly acquired execution attempt |
| `next_attempt_at` | UTC time for deterministic backoff scheduling |
| `idempotency_scope` / `idempotency_key` | Caller-defined command identity; unique together |
| `registry_lock_json` | Exact resolved registry entry IDs, versions, schema versions, and digests |
| `policy_snapshot_digest` | Exact effective policy set used for authorization |
| `created_at`, `updated_at` | UTC audit timestamps |
| `cancel_requested_at`, `terminal_at` | Nullable lifecycle timestamps |
| `row_version` | Monotonic CAS counter independent of trace sequence |

Required uniqueness: `(idempotency_scope, idempotency_key)`. Re-submission with
the same key and same canonical input digest returns the original `job_id` and
stored outcome. The same key with a different digest fails closed as
`idempotency_conflict`.

### 3.2 Checkpoint

A checkpoint is a validated reducer state at a declared safe boundary. It is not
an arbitrary pickle and must not contain a live handler, model client, file
descriptor, secret, or unredacted conversation.

Minimum `job_checkpoints` fields:

- `job_id`, `checkpoint_seq` as the composite primary key;
- `checkpoint_schema_version` and `workflow_version`;
- `step_name`, `step_attempt`, and `safe_point_kind`;
- canonical `state_json`, `state_digest`, and `previous_checkpoint_digest`;
- exact `registry_lock_json` and `policy_snapshot_digest`;
- `lease_fencing_token` that authorized the append;
- `created_at` and the causing `job_event_seq`;
- optional `waiting_command_schema` for a user continuation.

One transaction must verify the active lease and fencing token, append the job
event, insert the checkpoint, update `durable_jobs.row_version/status`, and write
any deterministic outbox record. A crash before commit leaves no new checkpoint;
a crash after commit resumes from that checkpoint without repeating committed
effects.

### 3.3 Lease and fencing

Minimum `job_leases` fields:

- `job_id` primary key;
- opaque `owner_id` identifying process/worker instance;
- strictly increasing `fencing_token` per acquisition;
- `acquired_at`, `heartbeat_at`, and `expires_at` using persisted UTC times;
- `lease_version` for CAS.

Acquisition is one SQLite transaction that succeeds only when no unexpired lease
exists or the caller is renewing its own lease. Taking over an expired lease
increments `fencing_token`. Every checkpoint, proposal acceptance, committer
write, and terminal transition must compare the current token. A stale owner may
finish computation but cannot append or commit. Wall-clock expiry alone is never
sufficient authorization.

Initial constraints:

- one job has at most one active lease;
- lease duration and heartbeat cadence are Policy Registry values;
- long non-checkpointable tool calls must declare a timeout shorter than the
  lease or run through an adapter with explicit external-effect reconciliation;
- background execution remains local and bounded; no cloud queue is introduced.

### 3.4 Idempotency at three layers

1. **Command idempotency:** job creation and continuation commands use a unique
   `(scope, key)` and cache the canonical result/error.
2. **Step idempotency:** each logical step uses
   `(job_id, checkpoint_seq, step_name, step_generation)`; a retry may recompute
   but can publish at most one accepted proposal/result for that identity.
3. **Commit idempotency:** every authoritative mutation uses a unique
   `commit_key`. KT should normally use the evidence event ID; schedule mutations
   use the scheduling command ID; artifact publication uses artifact version plus
   transition command ID.

“Exactly once” must be claimed only for a SQLite transaction guarded by a unique
constraint. External tool execution is at-least-once unless that tool advertises
an idempotent operation and reconciliation contract.

### 3.5 Cancellation

- `request_cancel(job_id, command_key, expected_row_version)` durably appends the
  intent and changes non-terminal work to `cancel_requested`.
- Workers check cancellation before tool invocation, after invocation, and at
  each checkpoint boundary.
- A cooperative handler may return a final safe checkpoint and then transition
  to `cancelled`.
- A force-stop may terminate a worker process, but the lease/fencing token—not
  process termination—prevents late commits.
- Cancellation never rolls back an already committed learner-state event. It may
  cancel uncommitted proposals or leave a draft artifact quarantined.
- Repeated cancel commands with the same key return the same result. Cancelling a
  terminal job is a no-op response, not a new transition.

### 3.6 Retry

Retry classification must be deterministic and policy-versioned:

- retryable: process crash, lease expiry, temporary local resource exhaustion,
  explicitly retryable provider error, or verifier infrastructure failure;
- non-retryable: schema invalidity, compatibility failure, policy denial,
  idempotency conflict, unsupported external-effect reconciliation, or exhausted
  attempts;
- user correction required: invalid/missing learner response; move to
  `waiting_user`, not `retry_wait`;
- cancellation is never retried automatically.

Backoff is computed from attempt number and the pinned Retry Policy. Tests use an
injected clock; no test sleeps. Automatic retries create a new attempt under the
same non-terminal job and exact registry lock. Retrying a terminal `failed` job
creates a successor job with `retry_of_job_id`, a new command idempotency key,
and the same registry lock. Changing that lock requires a separate explicit,
audited rebase job.

### 3.7 Event-store evolution

Keep `trace_events` readable and hash-verifiable. Do not rewrite its history.
Add a migration ledger and job-specific tables/events rather than overloading
`run_id` semantics silently. Minimum additions:

- `schema_migrations(version, name, checksum, applied_at)`;
- `job_events(job_id, seq, kind, payload_json, previous_hash, event_hash, ...)`;
- the job, checkpoint, lease, idempotency-result, proposal, verification, commit,
  registry, KT, review-schedule, memory, and artifact tables described here;
- a transaction API that performs expected-version/fencing checks and all
  related inserts/updates atomically.

Every new event envelope carries `event_schema_version`, `producer`,
`correlation_id`, `causation_id`, effective registry locks, policy digest, and a
redaction-policy version. Unknown event kinds or unsupported major versions fail
closed in state reconstruction while raw audit export remains possible.

## 4. Four separate registries

### 4.1 Common registry envelope

All four registries use immutable version rows. “Registry” means a durable local
catalog with deterministic resolution, not four dictionaries sharing mutable
objects.

```json
{
  "registry_kind": "tool | skill | artifact | policy",
  "entry_id": "stable namespaced identity",
  "version": "SemVer",
  "schema_version": 1,
  "status": "draft | active | deprecated | revoked",
  "definition": {},
  "definition_digest": "sha256 of canonical definition",
  "compatibility": {
    "runtime_api": ">=1.0.0 <2.0.0",
    "reads": ["declared schema ranges"],
    "writes": ["exact declared schema versions"],
    "requires": ["exact/ranged registry dependencies"]
  },
  "created_at": "UTC timestamp",
  "supersedes": "optional exact entry version",
  "provenance": {}
}
```

The durable identity is `(registry_kind, entry_id, version)`. A digest mismatch
for that identity is corruption and fails closed. Existing rows are immutable;
deprecation/revocation is a new signed/audited status event, not an in-place
definition rewrite. Jobs pin exact resolved identities and digests at creation.

### 4.2 Tool Registry minimum definition

```json
{
  "name": "learning.verify",
  "description": "human-readable purpose",
  "handler_ref": "package.module:callable or adapter ID",
  "input_schema": {},
  "output_schema": {},
  "allowed_phases": ["verify"],
  "capabilities": ["read:attempt_evidence", "propose:learning_evidence"],
  "side_effect_class": "pure | local_idempotent | external_reconcilable | forbidden",
  "timeout_ms": 30000,
  "idempotency_contract": "none | key | reconcile",
  "offline_behavior": "available | degraded | unavailable"
}
```

The current `ToolSpec` maps to name, description, schemas, phases, version, and a
handler adapter. The P1 registry adds capabilities, effect class, timeout,
offline behavior, digest, lifecycle, and compatibility. A Tool never receives a
raw database handle or a capability to write mastery, misconception state,
review schedules, or confirmed memory.

### 4.3 Skill Registry minimum definition

This registry describes learning taxonomy and scoring/KT bindings; it is not a
prompt-skill/plugin catalog.

```json
{
  "skill_id": "xingce.data-analysis.growth.base-period",
  "display_name": "Base-period growth calculation",
  "domain": "xingce",
  "taxonomy_version": "1.0.0",
  "parent_ids": [],
  "prerequisite_ids": [],
  "evidence_contract": "attempt-evidence.v1",
  "scorer_ref": {"tool": "domain.xingce.score", "version": "1.0.0"},
  "kt_model_ref": {"model": "bkt-pfa-rasch-ensemble", "version": "1.0.0"},
  "parameter_set_ref": "growth-defaults@1.0.0",
  "review_policy_ref": "review.default@1.0.0"
}
```

Skill aliases and splits/merges require an explicit migration map with weights
and provenance. A renamed ID is not silently treated as the same skill. A skill
definition may declare which evidence it accepts; natural-language memory is
never an accepted evidence contract.

### 4.4 Artifact Registry minimum definition

This registry defines artifact **types and contracts**. Artifact instances live
in a separate durable artifact store.

```json
{
  "artifact_type": "study_pack.knowledge_cards",
  "instance_schema": {},
  "lifecycle": ["draft", "review", "published", "quarantined", "retired"],
  "allowed_transitions": {},
  "source_requirements": ["source_version", "source_hash", "source_spans"],
  "verifier_refs": [],
  "publisher_policy_ref": "artifact.publish.study-pack@1.0.0",
  "retention_class": "local-user-content",
  "renderer_contract": "optional exact version"
}
```

An artifact instance minimally has `artifact_id`, `artifact_type` and registry
version, `artifact_version`, lifecycle state, content blob/reference plus digest,
source/citation lineage, creator job/proposal, verifier result, timestamps, and
transition event sequence. Background workers may create drafts/proposals only.
Only the deterministic committer may accept a verified lifecycle transition;
artifact publication never implies a KT or schedule update.

### 4.5 Policy Registry minimum definition

```json
{
  "policy_id": "worker.background-artifact",
  "scope": "job | tool | worker | memory | kt | schedule | artifact",
  "priority": 100,
  "rules_schema": {},
  "rules": {},
  "effective_from": "UTC timestamp",
  "effective_until": null,
  "rollback_of": null,
  "decision_contract_version": 1
}
```

Policy resolution is deterministic by explicit scope, priority, exact version,
and effective time supplied by an injected clock. Conflicting same-priority
rules fail closed. Every decision records candidate policy IDs, selected exact
versions/digests, input digest, decision, and reason codes.

### 4.6 Version and compatibility rules

1. Registry `version` uses SemVer; stored/event/schema envelope versions remain
   integers. These are different dimensions.
2. Patch: semantics-preserving correction with identical accepted input/output
   schemas. Minor: backward-compatible additive fields or capability. Major:
   removed/renamed fields, changed meaning, lifecycle, scoring, authorization,
   or side effects.
3. Writers emit one exact schema version. Readers declare a bounded range and
   must reject unknown required fields/semantics where safety depends on them.
4. A job resolves version ranges once and stores exact versions plus digests.
   Resume/retry uses that lock; it never floats to latest.
5. If a pinned entry is unavailable, incompatible, or revoked, the job pauses as
   `compatibility_blocked`. It may not fall back silently. Revocation may block
   new execution while preserving audit replay.
6. Upcasters are pure, deterministic, version-to-version functions. Each hop has
   golden tests; destructive downcasts are forbidden.
7. Policy rollback activates a previously known immutable version through a new
   registry event. In-flight jobs retain their pinned policy unless the rollback
   marks the old version unsafe; then they pause for explicit rebase/cancel.
8. Registry dependency graphs must be acyclic and resolvable offline before a
   job is admitted.

## 5. Confirmed long-term memory boundary

### 5.1 Memory classes

P1 long-term memory is limited to typed user preferences and stable user-declared
constraints that improve product behavior, for example preferred explanation
language, session length, notification window, or accessibility preference.

The following are **not** preference memory:

- mastery, ability, correctness, attempts, response timing, hint usage;
- misconception observations or hypotheses;
- review due dates, task completion, fatigue signals, or exam coverage;
- generated summaries, hidden chain of thought, or an agent's interpretation of
  a conversation;
- credentials, secrets, raw documents, or unnecessary sensitive attributes.

Those belong, if allowed at all, in their own structured, versioned evidence or
domain stores.

### 5.2 Candidate-to-confirmed lifecycle

```text
conversation/setting action
  → memory_candidate (typed proposal, no behavioral authority)
  → user confirms or edits an explicit value and scope
  → confirmed preference
  → active until expiry, edit, or delete
```

Minimum candidate/record fields:

- `memory_id`, `learner_id`, `preference_key`, typed `value_json`, and value
  schema version;
- `scope`, `purpose`, `source_event_refs`, redacted display evidence, and
  proposing tool/model/policy versions;
- `status`: `candidate`, `confirmed`, `rejected`, `expired`, or `deleted`;
- `confidence` only for candidate ranking; it never replaces confirmation;
- `proposed_at`, `confirmed_at`, `expires_at`, `updated_at`, `deleted_at`;
- `confirmation_event_id`, `confirmation_ui_version`, and immutable edit/delete
  lineage;
- local retention and export/delete lineage.

Only an explicit user action may create `confirmed`. Silence, continued use,
model confidence, repeated mention, or an existing mastery signal do not count.
The confirmation surface must show the exact normalized value, its behavioral
scope, expiry, and edit/delete controls. Rejected candidates are not repeatedly
re-proposed without new source evidence.

### 5.3 Hard write firewall

Natural-language memory must never be passed as `AttemptEvidence`, an answer
score, a KT observation, a skill weight, or a mastery delta. Enforce this at
schema and capability layers:

- KT committer accepts only a `VerifiedLearningEvidence` envelope whose source
  type is allow-listed (`scored_attempt`, `independent_probe`, or a future
  explicitly versioned evidence type);
- the envelope references immutable scorer/verifier results and a Skill Registry
  version;
- memory IDs and conversation text are forbidden fields in the KT evidence
  schema except optional non-semantic audit correlation outside the hashed
  evidence payload;
- Policy Registry denies `memory:* → commit:kt`, and deterministic tests assert
  the denial;
- confirmed preferences may affect presentation/scheduling constraints only when
  a declared policy reads them. They still cannot alter mastery.

Example: “I am bad at growth-rate questions” may create a candidate coaching
preference only if a supported typed key exists; it cannot decrement mastery or
create a confirmed misconception. Mastery changes only after structured scored
evidence passes the learning verifier and deterministic committer.

## 6. KT and ReviewSchedule separation

### 6.1 Ownership

- `KTState` answers: what does structured evidence imply about learner × skill
  state under a specific KT model/version?
- `ReviewSchedule` answers: when and why should a learner next see an activity
  under a specific scheduling policy/version?

They have separate tables, row versions, event streams, APIs, model/policy
versions, and idempotency keys. A schedule row may reference a KT snapshot but
is not part of it. Being due, skipped, postponed, or completed is not evidence of
mastery. A KT update may cause a scheduling command, but cannot directly mutate
schedule fields inside a KT model function.

### 6.2 KT interface

```text
get_kt_state(learner_id, skill_id, at_event_seq?)
  -> KTStateSnapshot

preview_kt_transition(previous_snapshot, verified_learning_evidence,
                      skill_registry_lock, kt_model_lock)
  -> KTTransitionProposal

commit_kt_transition(proposal_id, expected_kt_version, commit_key,
                     committer_fencing_token)
  -> KTStateSnapshot
```

Minimum `KTStateSnapshot`: learner ID, skill ID/version, numeric component state,
mastery and uncertainty, evidence count, last evidence event ID, model and
parameter versions, row version, created/updated timestamps, and provenance
digest. The committer recomputes or verifies the deterministic transition; it
does not accept a worker-supplied mastery number as authority.

### 6.3 ReviewSchedule interface

```text
get_review_schedule(learner_id, filters, as_of)
  -> ReviewTask[]

propose_review_change(trigger_event_id, kt_snapshot_ref?, misconception_refs,
                      goal_constraints, confirmed_preferences,
                      review_policy_lock, as_of)
  -> ReviewScheduleProposal

commit_review_change(proposal_id, expected_schedule_version, commit_key,
                     committer_fencing_token)
  -> ReviewTask

transition_review_task(task_id, action, expected_version, command_key, as_of)
  -> ReviewTask
```

Minimum `ReviewTask`: task ID, learner ID, target skill/activity reference,
status (`scheduled`, `accepted`, `completed`, `postponed`, `skipped`, `cancelled`),
due window, expected duration, reason codes plus immutable evidence references,
success criterion, skip consequence, schedule policy/version, source KT snapshot
reference if any, transition lineage, and row version.

The scheduler may consume a KT snapshot, confirmed scheduling preferences,
misconception hypotheses, exam date, coverage, and fatigue guardrails. It emits
a proposal with reason codes. It cannot write KT, confirm a misconception, or
turn task completion into correctness. A completed review produces learning
evidence only if a separate scored attempt exists.

### 6.4 Consistency model

The committed learning-evidence event is the source trigger. The committer first
idempotently commits KT, then emits a schedule-proposal command referencing the
new KT version. If the process crashes between them, replay of the deterministic
outbox completes scheduling without reapplying KT. This gives independent state
and interfaces without losing causal linkage.

## 7. Bounded worker protocol

### 7.1 Flow

```text
orchestrator admits bounded job
  → leased worker executes only declared capabilities
  → immutable Proposal
  → verifier(s)
  → VerificationDecision
  → deterministic committer
  → authoritative event/state transition
```

The worker is never an authority. It may propose:

- an artifact draft or lifecycle transition;
- structured learning evidence derived from an allowed scorer;
- ranked misconception hypotheses plus a next probe;
- a candidate preference-memory record;
- a review-schedule change.

It may not propose an opaque “set mastery to X” command, confirm memory, publish
an unverified artifact, or directly access authoritative state tables.

### 7.2 Proposal envelope

Minimum fields:

- `proposal_id`, `proposal_kind`, `proposal_schema_version`;
- `job_id`, `job_attempt`, `checkpoint_seq`, worker ID, and lease fencing token;
- immutable input/evidence references and canonical input digest;
- proposed payload plus payload digest;
- exact Tool/Skill/Artifact/Policy locks;
- model/provider/settings/usage/latency/cost when available, or explicit
  `model_calls=[]` for deterministic/offline work;
- capability grant, created time, expiry, and sensitivity/redaction labels;
- unique logical step identity.

Proposal insert is idempotent. Two different payload digests for the same logical
step identity are a nondeterminism conflict and require quarantine, not
last-write-wins.

### 7.3 Verifier

Verification is layered and recorded:

1. envelope/schema and registry compatibility;
2. capability, policy, local-first/network-opt-in, and protected-boundary checks;
3. evidence/source/citation integrity and redaction checks;
4. domain semantic checks (scoring, answerability, leakage, hypothesis evidence,
   independent-transfer rules);
5. deterministic recomputation where available;
6. expected state/version and active fencing token.

Each verifier emits `accept`, `reject`, or `quarantine` with stable reason codes,
verifier version, input/proposal digests, and evidence. A model may assist a
semantic review only where policy allows, but it cannot replace deterministic
schema, policy, citation, scoring, independence, or concurrency checks.

### 7.4 Deterministic committer

The committer is a narrow local service with the only database capabilities for
mastery, misconception-state transitions, review schedules, confirmed memory
transitions, and artifact publication. It:

1. loads the proposal and accepted verifier decisions;
2. re-checks policy, expected aggregate version, registry digests, lease fencing,
   and unique `commit_key`;
3. recomputes deterministic domain/KT/scheduling transitions rather than trusting
   proposed deltas;
4. writes the authoritative event, new state, outbox, and commit receipt in one
   SQLite transaction;
5. returns the existing receipt for duplicate `commit_key` delivery;
6. records a state diff and causal links in the audit trace.

Background artifact jobs receive only `propose:artifact` and cannot obtain any
learning-state write capability. Even a verified/published artifact does not
change mastery. Learner performance on a separately scored artifact-derived
attempt may later create verified learning evidence.

### 7.5 Resource bounds

Every worker grant declares maximum wall time, tool calls, model calls/tokens,
artifact bytes, checkpoints, retry attempts, and allowed registry entries. It
also declares network mode (`offline`, `local_only`, or explicit opt-in scope),
filesystem roots, and sensitivity class. Exceeding a bound yields a recorded,
non-authoritative failure proposal or job failure; it never widens permissions.

## 8. Executable P1 test plan

Tests below are implementation requirements after P0 release. They use temporary
SQLite databases, injected clocks/IDs, deterministic fake tools, and process
boundaries where stated. No test relies on sleep or an LLM evaluation for a
state-transition assertion.

Proposed deterministic test placement and direct commands:

| Slice | Proposed files | Command |
| --- | --- | --- |
| Durable job, checkpoint, lease, cancellation, retry | `runtime/tests/test_durable_jobs.py`, `runtime/tests/test_job_concurrency.py` | `cd runtime && python3 -m unittest tests.test_durable_jobs tests.test_job_concurrency -v` |
| Four registries and compatibility/upcasters | `runtime/tests/test_registries.py` | `cd runtime && python3 -m unittest tests.test_registries -v` |
| Memory confirmation API and KT firewall | `service/tests/test_memory_api.py`, `integration/tests/test_memory_boundary.py` | Run each package with `python3 -m unittest <module> -v` |
| KT persistence and schedule separation | `engine/tests/test_kt_transitions.py`, `service/tests/test_review_schedule.py`, `integration/tests/test_kt_schedule_flow.py` | Run each package with `python3 -m unittest <module> -v` |
| Worker proposal/verifier/committer | `runtime/tests/test_bounded_workers.py`, `integration/tests/test_proposal_commit_flow.py` | Run each package with `python3 -m unittest <module> -v` |
| Full regression | existing package tests plus `scripts/verify_core.py` | `python3 scripts/verify_core.py` |

The exact filenames may be adjusted when root assigns implementation ownership,
but every checklist case below must map one-to-one to a named deterministic test
before the P1 gate is evaluated.

### 8.1 DurableJob and recovery

- [ ] **Crash before checkpoint commit:** kill a worker after computation but
  before the transaction; assert no checkpoint/effect exists, lease eventually
  transfers, and one accepted result is committed.
- [ ] **Crash after checkpoint commit:** kill immediately after transaction
  commit; assert resume starts at the next safe step and committed effect count
  stays one.
- [ ] **Checkpoint chain:** corrupt state/digest/previous digest in a copied test
  DB; reconstruction fails closed with `checkpoint_integrity_failed`.
- [ ] **Unsupported checkpoint version:** resume with no registered upcaster;
  job becomes `compatibility_blocked` and no handler runs.
- [ ] **Bounded execution:** exceed step, time, tool-call, artifact-size, and retry
  limits independently; assert a stable reason code and no authoritative write.
- [ ] **Waiting user vs retry:** missing learner input enters `waiting_user` and
  does not consume retry attempts or schedule automatic execution.

### 8.2 Lease, fencing, and concurrency

- [ ] **Two-process acquisition:** launch two worker processes against the same
  DB; exactly one acquires the lease and starts the step.
- [ ] **Expired-owner fencing:** worker A lease expires, worker B acquires a
  higher token, A tries to checkpoint/commit; A is rejected and B can finish.
- [ ] **Heartbeat renewal:** only the matching owner/token renews; renewal after
  takeover fails.
- [ ] **Concurrent continuation without process lock:** bypass/remove the
  application mutex in the test harness; two same-version commands yield one
  accepted receipt and one deterministic stale/idempotent result through DB CAS.
- [ ] **Stale committer:** a verified proposal created under an old aggregate
  version cannot overwrite newer KT, schedule, memory, or artifact state.

### 8.3 Idempotency and retry

- [ ] **Duplicate create delivery:** same scope/key and same digest returns the
  same job/result; event and job counts do not increase.
- [ ] **Conflicting duplicate:** same scope/key with changed input fails
  `idempotency_conflict` before a job or event is created.
- [ ] **Duplicate step/result:** repeat delivery around a simulated lost response;
  only one accepted proposal and commit receipt exists.
- [ ] **Duplicate KT evidence:** applying the same evidence event twice leaves KT
  version and numeric state unchanged on the second call.
- [ ] **Deterministic backoff:** injected clock proves exact next-attempt times,
  max-attempt behavior, and no retry after cancellation/non-retryable errors.
- [ ] **External non-idempotent tool:** registry admission rejects background use
  when no idempotency/reconciliation contract exists.

### 8.4 Cancellation

- [ ] cancel while queued transitions directly to `cancelled` and handler is not
  invoked;
- [ ] cancel while running records `cancel_requested`, worker observes it at the
  next safe point, and no later proposal/commit is accepted;
- [ ] kill an uncooperative worker, transfer lease, and reject its late commit;
- [ ] duplicate cancel returns the same receipt;
- [ ] cancel after success is a no-op and does not rewrite history;
- [ ] already committed KT/schedule state is preserved while uncommitted draft
  artifacts/proposals are quarantined or abandoned.

### 8.5 Registry compatibility and rollback

- [ ] register two versions of the same Tool/Skill/Artifact/Policy ID and resolve
  a declared compatible range deterministically;
- [ ] reject duplicate identity with a different definition digest;
- [ ] pin exact locks at job creation, change active registry versions, resume,
  and assert the job still uses pinned versions;
- [ ] remove/unavailable pinned handler and assert `compatibility_blocked`, not
  silent latest-version fallback;
- [ ] run golden upcast fixtures for every supported schema hop and reject a
  missing/ambiguous hop;
- [ ] activate policy v2, create a job, roll back to v1, and prove old and new
  jobs use their recorded snapshots according to the unsafe-version rule;
- [ ] reject cyclic registry dependencies and conflicting policy priority.

### 8.6 Memory consent and deletion

- [ ] inferred preference remains `candidate` and has no behavioral authority;
- [ ] only an explicit confirm command with exact candidate/value/version creates
  `confirmed`;
- [ ] confirmation after candidate edit/staleness fails expected-version CAS;
- [ ] edit creates lineage and changes only the declared typed value/scope;
- [ ] expiry removes the preference from policy resolution without deleting audit
  lineage;
- [ ] delete removes active/read projections, export reports deletion lineage,
  and replay does not resurrect the preference;
- [ ] rejection prevents automatic re-proposal without new source evidence;
- [ ] raw sensitive text is redacted/omitted according to policy;
- [ ] a confirmed or candidate memory ID/text submitted to KT is rejected, and
  mastery bytes/state/version remain identical.

### 8.7 KT and ReviewSchedule separation

- [ ] scored verified evidence deterministically changes KT and records model,
  skill, evidence, and prior-state versions;
- [ ] hinted/non-independent work follows the pinned learning policy and never
  masquerades as independent transfer;
- [ ] schedule due/postpone/skip/complete transitions do not change KT;
- [ ] KT changes do not mutate a review task except through a separate scheduling
  proposal and commit event;
- [ ] crash after KT commit but before schedule processing is recovered by the
  outbox; KT remains single-applied and one schedule change appears;
- [ ] duplicate schedule trigger yields one review transition;
- [ ] review reasons cite existing evidence/KT snapshot IDs and never fabricated
  precision;
- [ ] a completed task without a scored attempt creates no learning evidence;
- [ ] current engine formula fixtures remain deterministic across migration.

### 8.8 Proposal/verifier/committer

- [ ] worker database credentials/capabilities cannot insert or update KT,
  misconception, schedule, confirmed-memory, or published-artifact tables;
- [ ] an artifact worker can create a draft proposal but cannot publish or commit
  learning state;
- [ ] malformed, unsupported, contradictory, leakage-bearing, or uncited artifact
  proposals are rejected/quarantined with stable reason codes;
- [ ] worker-supplied mastery deltas are ignored/rejected; committer recomputes
  from verified evidence;
- [ ] two verifier decisions with conflicting required outcomes quarantine the
  proposal;
- [ ] duplicate accepted proposal delivery produces one commit receipt;
- [ ] stale lease token, stale aggregate version, revoked unsafe policy, or digest
  mismatch blocks the committer transaction entirely;
- [ ] offline mode records zero cloud calls and a network-requiring job degrades
  visibly to unavailable/waiting rather than fabricating output.

### 8.9 Existing regression gates

- [ ] current runtime interrupt/resume/replay/hash/redaction tests still pass;
- [ ] current integration staged probe→teach→independent verify→update ordering
  still passes through the compatibility adapter;
- [ ] current service stale/out-of-order/concurrent continuation and local-only
  HTTP security tests still pass;
- [ ] current deterministic engine diagnosis/mastery/verification tests still
  pass;
- [ ] `scripts/verify_core.py` and the applicable P0 release evidence remain green
  before and after every migration slice.

## 9. Migration order after explicit P1 release

Each step has its own reversible migration, deterministic tests, and requirement-
to-evidence entry. Do not combine the early schema/authority changes into one
large cutover.

1. **Freeze and evidence the P0 baseline.** Record P0 gate approval, current DB
   schema/checksums, golden trace fixtures, version matrix, and current tests.
   Until this record exists, stop here.
2. **Introduce migration infrastructure.** Add `schema_migrations`, transactional
   migration checksums, backup/restore test, and read-only verification of legacy
   `trace_events`. No behavior change.
3. **Add common event envelopes and transactional store primitives.** Implement
   compare-version/fencing-capable append APIs and reducer/upcaster tests while
   retaining the current runtime adapter.
4. **Create the four immutable registries.** Seed exact entries representing the
   current tools, skill taxonomy, artifact types needed by approved P0, and
   policies. Resolve and record locks without changing execution behavior.
5. **Add DurableJob tables and a deterministic fake workflow.** Prove lifecycle,
   checkpoint, command idempotency, cancellation, retry, lease takeover, and
   fencing entirely outside the learning path.
6. **Move background artifact generation first.** It has the safest authority
   boundary: draft proposal → verifier → artifact committer. It receives no
   learning-state capability. Pass crash/duplicate/offline/quarantine tests.
7. **Introduce proposal/verifier/committer infrastructure.** Add narrow commit
   receipts, capability grants, expected-version checks, and transactional
   outbox. Run adversarial late/stale/duplicate worker tests.
8. **Create authoritative longitudinal KT storage.** Wrap current deterministic
   engine functions; migrate only evidence-backed current state. Do not infer a
   historical longitudinal state from `skill_report` averages or free-form run
   artifacts. Preserve legacy trace linkage.
9. **Create independent ReviewSchedule storage/API.** Consume committed KT and
   other structured triggers through the outbox. Migrate approved P0 review tasks
   by explicit versioned mapping; never fold schedule status into KT.
10. **Add candidate preference memory and confirmation UX/API.** Ship
    candidate/confirm/edit/expire/delete/export behavior plus the KT firewall
    before any policy may read confirmed preferences.
11. **Migrate staged learning continuation onto DurableJob.** Preserve the P0 API
    through an adapter, pin registries/policies, and prove multi-process CAS,
    crash recovery, cancellation, and duplicate delivery.
12. **Run the P1 gate and cut over deliberately.** Crash recovery, duplicate
    delivery, concurrent continuation, policy rollback, memory consent, offline
    degradation, regression suites, privacy checks, and representative end-to-
    end evaluations must all have stored evidence. Remove compatibility paths
    only in a later, separately approved migration.

Rollback for each step means disabling new admission and returning to the prior
reader/writer while retaining append-only audit rows. Never down-migrate by
deleting events or rewriting hashes.

## 10. Risks and mitigations

| Risk | Why it is material | Required mitigation |
| --- | --- | --- |
| Mistaking a trace snapshot for a durable checkpoint | Repeating a tool can duplicate effects | Atomic checkpoint/event/outbox transaction plus declared side-effect/idempotency contract |
| Process-local lock presented as concurrency safety | A second sidecar or restart bypasses it | SQLite CAS/unique constraints and lease fencing; process lock is optional only |
| Stale worker commits after lease takeover | Corrupts authoritative learner state | Monotonic fencing token checked inside every committer transaction |
| Floating registry/policy versions on resume | Makes replay and decisions non-reproducible | Exact version/digest lock per job/checkpoint |
| Registry sprawl or conflation | Tool execution, learning taxonomy, artifacts, and policy have different authorities | Four separate tables/APIs and typed cross-registry dependency refs |
| Worker/model output directly changes mastery | Violates deterministic single-writer boundary | Worker proposes evidence; verifier validates; committer recomputes KT |
| Natural-language memory leaks into mastery | Converts self-description or model inference into false ability evidence | Typed memory store, explicit confirmation, schema/capability firewall, negative tests |
| KT and schedule coupled in one aggregate | Due/skip behavior can contaminate mastery and migrations | Separate versions, events, tables, APIs, idempotency keys, and causal outbox |
| Cancellation assumed to undo committed learning state | Rewriting audit history breaks replay | Cooperative cancel only for future work; committed events remain immutable |
| Overclaiming exactly-once | External effects cannot be covered by a local DB transaction | Say at-least-once execution; claim single commit only under constraints |
| Redaction treated as comprehensive privacy | Current key/regex redaction is intentionally narrow | Data minimization, typed schemas, sensitivity labels, policy-versioned redaction, deletion/export tests |
| In-place event/schema migration breaks hash replay | Existing chain includes canonical payload bytes | Add readers/upcasters and new tables/events; never rewrite legacy payloads |
| Wall-clock and flaky crash tests | Lease/retry behavior becomes nondeterministic | Injected clock, process barriers/fault hooks, no sleeps |
| P1 implementation starts before P0 stabilizes | Creates moving contracts and violates the phase gate | Root-recorded P0 pass plus explicit P1 write release is migration step zero |

## 11. Explicitly out of scope / do not do

- Do not modify P1 production code before P0 passes and root releases it.
- Do not edit, branch, stage, commit, or push in
  `$HOME/Desktop/shenlun-agent-platform`.
- Do not make Lumi depend directly on mutable `$HOME/Documents/xingcetiku`
  working files.
- Do not introduce a cloud queue, mandatory account, remote control plane, or
  hidden network call. Core jobs, KT, memory, scheduling, and audit remain local.
- Do not allow background workers, tools, skills, artifacts, policies, prompts,
  or models to write mastery, misconception state, or schedules directly.
- Do not store chain of thought or promote free-form conversation summaries to
  authoritative state.
- Do not write natural-language memory into mastery—directly, through a feature,
  as a pseudo-attempt, or as a prior.
- Do not infer user confirmation from silence, engagement, repetition, model
  confidence, or an existing learner-state value.
- Do not treat a correct answer as evidence of an invented error cause; causes
  remain ranked hypotheses until targeted evidence changes their status.
- Do not merge `KTState` and `ReviewSchedule`, and do not count schedule actions
  as learning evidence.
- Do not let artifact generation publish unverified citations/answer keys or
  update learning state.
- Do not claim exactly-once external execution, distributed durability,
  population efficacy, calibration, cohort effects, or causal learning gain from
  the P1 local platform.
- Do not migrate longitudinal mastery from current per-run `skill_report`
  summaries; there is no authoritative longitudinal source to migrate yet.
- Do not rewrite legacy trace events, hashes, or timestamps during migration.
- Do not remove lowercase `hermes_*` internal identifiers without a separately
  versioned migration; the public product name remains Lumi.

## 12. P1 release checklist for root

P1 production work may begin only after all are true:

- [ ] P0 release gate has a root-owned, evidence-linked pass record.
- [ ] Root explicitly grants the P1 Runtime/Sol window production write scope.
- [ ] The migration owner, database backup/rollback procedure, and file scope are
  assigned.
- [ ] DurableJob, registry, memory, KT, schedule, proposal, verifier, and committer
  contracts have stable version identifiers.
- [ ] The deterministic test matrix above has named target test files and owners.
- [ ] No concurrent task owns overlapping production files without coordination.

Until then, this audit is the handoff artifact and the P1 Runtime/Sol window must
wait for root release.
