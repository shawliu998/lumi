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
hypotheses, chooses a probe, revises probabilities, teaches, verifies transfer,
updates mastery, schedules review, and then opens the exact trajectory in Agent
Lab. A second demo shows offline degradation and an unresolved item being safely
quarantined.
