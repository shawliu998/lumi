# Lumi v0 evaluation plan

## Evaluation philosophy

Lumi is evaluated as a learning system and as an agent. A fluent explanation is
not enough. Claims must be supported by frozen fixtures, deterministic invariants,
calibration measures, end-to-end trajectories, and learning outcomes.

## Evaluation layers

### 1. Content and data quality

- Schema, checksum, asset, answer, skill-link, and provenance validation.
- Duplicate identity separated from paper occurrence.
- Item quarantine for conflicting answers or insufficient scoring evidence.
- Cohort priors include sample size, interval, version, and fallback level.

### 2. Deterministic software correctness

- Event append and projection rebuild produce the same learner state.
- Duplicate/retried tool calls are idempotent.
- Mastery remains within valid ranges; uncertainty does not disappear without
  evidence; assisted attempts receive the configured evidence discount.
- Dry-run replay cannot mutate learner data.
- Offline mode supports scoring/import/history/baseline KT/scheduling.
- Repository-boundary checks prevent production Shenlun paths from becoming
  writable dependencies.

### 2.1 Real-attempt API safety

`POST /v1/attempts` is evaluated through a real ephemeral loopback sidecar, not
an in-process substitute. A release run must prove:

- a correct answer produces no error-cause hypotheses;
- an incorrect answer preserves multiple ranked candidates as
  `unconfirmed_hypothesis`, never ground truth;
- the initial response cannot claim effective teaching before an independent
  verification response;
- raw email, phone, and national-ID test values are absent from the response,
  trace, replay, and saved evaluation artifact;
- unknown request fields fail closed before creating a run;
- trace and replay hashes verify for every accepted request.

Stepwise probe and verification continuation is a distinct release gate. It can
pass only when the versioned HTTP contract proves legal state order,
optimistic-concurrency rejection, redacted response persistence, and independent
verification. The initial-attempt gate alone is not evidence that this
multi-step contract works.

### 2.2 Explainable TodayPlan and independent ReviewSchedule

`today_plan_schedule` is a separate machine-executable release gate. It uses the
real loopback HTTP router and a temporary local database; an injected local-date
provider advances deterministic test days without changing production policy.
The gate must prove all of the following:

- no learner evidence yields an honest empty plan and empty review schedule;
- completed `human_local_interactive` attempt traces produce the three authored
  branches: +1 unconfirmed cause probe, +3 delayed-retention review after
  successful independent verification, and +1 generic retry after a correct
  first answer but failed verification;
- batch/demo/synthetic-origin runs cannot seed a learner plan;
- every task contains an executable immutable activity reference and structured
  evidence references that resolve to the cited trace event, hash, and JSON
  pointer. The current activity is explicitly
  `same_fixture_retest_not_novel_item`; its success criterion says it is a
  same-fixture independent retest and not transfer to an unseen parallel item;
- candidate causes remain explicitly unconfirmed, while durations and +1/+3
  windows remain labeled as fixed, unvalidated engineering policy;
- overdue evidence is not discarded after 14 days. `base_due_on`,
  `initial_due_on`, `policy_offset_days`, and `scheduling_adjustment` must make an
  `overdue_catch_up` distinguishable from delivery on the original window;
- the daily budget and recovery-load presentation limit never delete review
  tasks: three recent failed attempts remain three ReviewSchedule records while
  `max_non_accepted_tasks` limits only the non-accepted Today selection. Every
  due accepted commitment is shown first and does not consume that cap. A budget
  below the total accepted duration returns the closed 409 error
  `budget_below_accepted_commitment`, creates no plan or task mutation, and may
  be retried with the same command ID and a sufficient budget. Its response is
  the closed `error.{code,message,request_id}` envelope, not a partial TodayPlan.
  Repeated skips rotate fairly, accepted work carries into the next day ahead of
  competing work, and the oldest skipped task returns within the bounded
  eight-day dynamic-arrival probe even when a new failed run arrives every day;
- strict request fields, sensitive-ID rejection, persisted command receipt
  replay, command conflict, task-version checks, and cross-instance CAS fail
  closed without partial writes;
- skip and postpone keep work eligible in ReviewSchedule without promising it
  will be displayed the next day; `postpone_until` is the earliest due/queue
  date. Historical plans remain read-only even when two live Sidecars disagree
  about the local date, and event replay verifies both the hash chain and current
  projection;
- restart repairs a deliberately partial five-field schedule migration, upgrades
  the pre-novelty activity/success/skip contract with an auditable migration
  record, rebuilds historical task snapshots, and then proves a healthy second
  reopen performs zero data changes. Legacy create/transition receipts remain
  immutable but retry as `command_conflict` so stale task copy is never replayed;
- `user_marked_not_learning_evidence` completion changes only scheduling state.
  The originating learning trace and skill/KT projection remain byte-for-byte
  unchanged. The next day reports `no_pending_review_tasks`, and a completed
  overdue task is excluded from the pending catch-up count.

The contracts in `evals/contracts/today-plan.schema.json` and
`evals/contracts/review-schedule.schema.json` are closed objects. Neither
contract permits peer/cohort rates, forgetting probability, fatigue score, or a
mastery-gain claim. Population evidence is `unavailable` and schedule commands
have no mastery-write capability.

### 3. Diagnosis quality

Use expert-authored cases with cause labels, plausible alternatives, evidence,
and discriminating probes. Measure top-1/top-k accuracy, Brier score/log loss,
expected calibration error, abstention quality, and information gain from probes.
Track performance by domain, subtype, ability band, and evidence availability.

When no privacy-reviewed real cohort aggregate exists, every API trace must show
`sample_size: 0`, a synthetic engineering source version, and
`engineering_prior` evidence. It must not label the same evidence
`cohort_prior` or support a population/common-error claim. Small or unreviewed
aggregates must fail closed to this fallback.

### 4. KT quality

Compare BKT/PFA, IRT-aware, graph-aware, and later sequence candidates using
temporal splits by learner. Measure next-response AUC/log loss/Brier score,
calibration, delayed-retention prediction, cold-start behavior, and stability
under sparse evidence. Prevent learner and item leakage across splits.

### 5. Tutor and policy quality

- Correctness and citation to source material/rubric.
- Hint leakage and answer-giving rate.
- Alignment between selected intervention and diagnosed cause.
- Independent next-item transfer, delayed retention, and assistance dependence.
- Learner agency: overrides honored, uncertainty disclosed, stop requests obeyed.
- Cost, latency, tool count, timeout, and recovery behavior.
- Model-router correctness: high-risk cases reach the strong tier, routine cases
  avoid needless escalation, and every light-model output that can affect learning
  has a recorded deterministic check or strong-model review.

### 6. Agent observability

For every golden trajectory, a reviewer must locate the triggering observation,
policy decision, tool/model version, verifier result, learner-state before/after,
and evaluation result. Missing provenance is a release-blocking error.

## Representative end-to-end matrix

Every listed path needs at least one success case, one ambiguous-diagnosis case,
and one degraded/offline case.

| Domain | Representative paths | Required closure evidence |
| --- | --- | --- |
| Xingce | verbal, judgment, quantitative, data analysis, common/political knowledge | scored attempt, option/process evidence, subtype cause, probe, independent item, KT delta |
| Shenlun | summary, comprehensive analysis, recommendation, official writing, essay | rubric/material evidence, dimension causes, targeted revision, independently rescored response, skill deltas |
| Interview | comprehensive analysis, organization, interpersonal, emergency | transcript/audio evidence, content/delivery rubric, coaching turn, second response, dimension deltas |

## Baselines

Compare against:

1. no tutor / ordinary answer explanation;
2. generic tutor without learner history;
3. tutor with learner history but no cause-specific probe;
4. full Lumi policy with cohort prior, diagnosis, probe, and KT.

For a single-user portfolio v0, use expert fixtures and counterfactual replay to
validate mechanics. Do not claim population learning gains until a preregistered
pilot or equivalent controlled data exists.

## Release gates

A v0 milestone is complete only when:

- all representative paths run from import to persisted verification without
  manual database repair;
- all deterministic invariants pass;
- 100% of mastery changes have an evidence link and model/policy version;
- 100% of cloud-bound operations surface provider/data-boundary state;
- no unresolved content-quality case changes mastery;
- golden trajectories are replayable and compare state diffs;
- diagnosis and tutoring metrics are reported with sample sizes and confidence,
  even when results are below target;
- a fresh Mac setup can launch the documented offline demo.

## Portfolio demonstration

The demo should show one deliberately ambiguous error. Lumi displays competing
hypotheses, chooses a probe, revises probabilities, teaches, records an
independent verification response, updates per-run mastery, and schedules
review. The exact trace and replay evidence are then inspected through the
current evidence surfaces; Agent Lab remains a future product surface. A second
demo shows offline degradation and an unresolved item being safely quarantined.
