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

### 2.2 Micro-lesson product contract

A micro-lesson is releaseable only when deterministic checks prove all of the
following before human QA:

- its manifest allowlists the exact lesson file and verifies its SHA-256;
- the lesson is 5–8 minutes and targets exactly one knowledge component;
- source use is concept-structure-only, learner-facing questions/examples are
  original, and source text is not included;
- reading or revealing a worked example cannot create mastery evidence;
- completion requires at least three scored questions and two consecutive,
  unassisted transfer successes; a failed transfer resets the streak;
- safe lesson APIs omit answer keys, scoring rules, pass conditions, diagnosis
  internals, private authorship, and protected local paths;
- the learner UI does not expose cause probabilities or KT deltas as the main
  learning flow, and it preserves retry/conflict safety.

Automated fixtures may prove these mechanics, but they may not be presented as
a voluntarily completed learner journey. Fresh connected/offline/error,
narrow-width, focus, scroll, and recovery evidence remains a separate product
gate.

### 2.3 Smart-practice v2 product contract

The growth-rate vertical slice is releaseable only when one deterministic HTTP
journey and its persisted replay prove all of the following:

- the server fixes the session target at eight, accepts an early stop, and never
  appends a ninth slot for a probe or validation;
- answer is the only learner-entered field required to submit a scored item;
- the first occurrence of an error signature produces level-B feedback without
  asserting a psychological cause;
- level-C/D intervention requires the same observable signature in two
  independent evidence and material families;
- any probe is structured, skippable, and consumes a normal session slot;
- near transfer is inserted after two to four other scored items, is unseen,
  unhinted, and from an independent family;
- delayed validation is not eligible before 24 hours and is cross-family;
- reading feedback, viewing a tutorial, answering a probe, or using a hint never
  creates positive diagnostic-unit evidence;
- every recommendation and transition carries content/policy versions, reason
  codes, evidence links, and a hash-verified local trace;
- public question projections never expose an answer key, error-option mapping,
  validation role, or protected local path before submission.

Client QA must additionally show the direct eight-question entry, answer-only
submission, folded explanation, repeated-error intervention, natural next-item
flow, early exit, completed summary, and offline/error recovery at normal and
narrow widths. See `SMART_PRACTICE_V2.md` for the approved product semantics.

### 2.4 Core-320 v3 content and scope contract

The four-module bank is eligible for internal MVP use only when deterministic
checks prove all of the following:

- the manifest resolves exactly 320 QuestionVersions: 80 verbal, 80 judgment,
  80 quantitative, and 80 data-analysis questions;
- every module has eight diagnostic units, with 64 ordinary/near-transfer
  versions and 16 delayed-only versions;
- the complete generated bank matches SHA-256
  `854ba5e483454718408cfbf8b428881333130d2224cfd4b5db3499cd54baf117`;
- deterministic semantic, structural, or numeric oracles verify every answer,
  option mapping, explanation invariant, and module-specific constraint;
- answer keys are balanced 20/20/20/20 across A/B/C/D within each module and
  cannot be inferred from the question's local index;
- definition stems do not repeat the complete correct option verbatim, every
  question owns a distinct material group, and ordinary/delayed evidence-family
  sets are disjoint;
- a module's first eight candidates pair four diagnostic units across
  independent evidence and material families, while mixed practice rotates
  verbal, judgment, quantitative, and data analysis twice;
- delayed-only items cannot enter ordinary sessions, and safe pre-answer
  projections omit keys, distractor signatures, validation roles, and protected
  paths;
- all five scopes share one learner trace and policy state so switching between
  module and mixed practice does not erase exposure, hypotheses, interventions,
  or pending delayed validations;
- an active session resumes only for the same scope; a different scope fails
  explicitly, accepted answers and their immediate intervention commands persist
  atomically, and semantic replay recomputes pinned scoring/commands/state rather
  than checking hashes alone;
- the repository stores generators, schemas, checksums, and safe samples rather
  than a committed bulk dump, and materialization refuses an output path inside
  the repository;
- the desktop sidecar packages and verifies the frozen v3 manifest and exposes
  the exact bank digest, module counts, and supported scopes through local
  capabilities.

Passing this contract establishes reproducibility and software correctness, not
human content quality, visual usability, transfer efficacy, retention lift, or
external publication rights. Those claims require their own evidence.

### 2.5 Continuous-practice v1 record and recommendation contract

The cross-session direct-practice loop is mechanically complete only when a
real ephemeral loopback sidecar proves the frozen contract in
`CONTINUOUS_PRACTICE_V1.md`:

- the schema-pinned session report, overview, profile, history, and wrong-
  question `GET` APIs are discoverable, read-only, and explicit for empty state;
- all five views reconcile to the same accepted attempts, content versions, and
  session counters, with normal questions, scored probes, and skipped probes
  accounted separately;
- every projection is rebuilt from a hash-verified, semantically replayed local
  trace, survives restart unchanged, and creates no shadow learner-record table;
- invalid filters, pagination, session references, schemas, and recommendation
  evidence fail closed;
- module evidence labels and next-scope redirects use independent attempts only;
  a redirect requires two failures across two sessions and two evidence
  families, while recovery requires two later successes that themselves span
  two sessions and two evidence families;
- cause confidence remains ordinal and reversible, and every recommendation
  carries its policy/version, reason codes, and evidence refs;
- insufficient evidence preserves the current valid scope or falls back to
  mixed practice, and the client keeps learner scope choice available;
- all of the above operates locally without a cloud account or hidden cloud-
  bound operation.

Passing these gates does not establish mastery, usability, teaching efficacy,
transfer lift, retention lift, or exam-score improvement. Those claims require
separately consented human evidence and an appropriate evaluation design.

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
