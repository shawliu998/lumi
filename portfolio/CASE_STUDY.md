# Lumi: an auditable local learning agent for civil-service exam preparation

Status: **evidence-backed v0 case study; learner-outcome sections remain templates**

Current evidence boundary: 42/42 representative domain contract cases and real
success/ambiguous/offline domain→engine→runtime traces are reproducible through
`evals/run_all.py`. The ARM64 debug Mac shell, packaged sidecar lifecycle, and
28 dimension/hash-gated client artifacts are also reproducible. The P0.2 release
cut adds 23 real HTTP/storage scheduling cases. This still does not prove
population learning gains, delayed-retention lift, notarized distribution
readiness, or full content coverage.

The real-attempt endpoint has a separate black-box safety gate for zero-cause
correct answers, unconfirmed hypotheses, PII redaction, fail-closed fields, and
engineering-prior fallback. The separate continuation gate proves one local
versioned probe→verification session; the visible Mac flow now follows that
same state machine and only shows mastery after independent verification. The
initial POST alone still must not be described as a completed tutoring session.

Owner: `<NAME>`
Version/date: `<VERSION>`
Reproducible release report: current `run_id` in `evals/reports/latest.json`

## One-sentence thesis

Lumi turns a learner-entered answer into an evidence-linked cycle of uncertain
diagnosis, targeted probing, cause-specific teaching, independent verification,
and a per-run KT update, then projects trace-cited work into an independent
TodayPlan/ReviewSchedule that cannot write mastery.

## Problem and user

Describe the learner, exam context, and existing failure mode. Distinguish:

- scoring an answer;
- inferring a plausible cause;
- proving the cause through a probe;
- improving independent transfer;
- retaining the skill later.

Evidence: `<INTERVIEWS_DATA_OR_CITATIONS>`

## Why this is an agent system

Document the closed loop using exact runtime artifacts:

| Capability | Product behavior | Authoritative artifact |
| --- | --- | --- |
| Observe | captures answer/process/confidence/assistance | `<ATTEMPT_EVENT>` |
| Diagnose | ranks causes with uncertainty | `<DIAGNOSIS_RESULT>` |
| Plan | selects probe/intervention from state | `<POLICY_DECISION>` |
| Act | invokes domain/tool/model capability | `<TOOL_CALL>` |
| Verify | checks correctness through an independent verification response | `<VERIFIER_RESULT>` |
| Learn | applies an evidence-linked per-run KT update after independent verification | `<STATE_DIFF>` |
| Reflect | evaluates trajectory and policy result | `<EVAL_RESULT>` |

State explicitly what remains deterministic, model-assisted, expert-authored,
or learned from cohort data.

## System architecture and boundaries

Include one diagram covering:

- macOS client and local store;
- orchestrator, domain tools, KT, diagnosis, tutor policy, verifier;
- model router (strong vs economical tiers) and guardrails;
- versioned Xingce data-package input;
- optional cloud boundary with consent/redaction;
- trace/evaluation store.

Boundary statement:

> `$HOME/Desktop/shenlun-agent-platform` is independent, shared production
> work and is never modified or used as a writable/runtime dependency by Lumi.

Evidence: `<ARCHITECTURE_COMMIT_OR_ARTIFACT>`

## Technical contribution 1 — cause-specific diagnosis

Explain the hierarchical posterior in plain language and math. Report:

- engineering-prior source, or for future eligible cohort input the consent,
  privacy-review, cohort definition, sample size, interval/version;
- personal-history contribution;
- answer/process likelihood features;
- ranked alternatives and abstention rule;
- discriminating-probe information gain;
- calibration metrics by domain/path/evidence availability.

Do not label posterior ranking as causal certainty.

Evidence and result table: `<DIAGNOSIS_EVAL_REPORT>`

## Technical contribution 2 — hybrid knowledge tracing

Describe BKT/PFA/IRT or graph/sequence extensions, ensemble calibration,
forgetting, uncertainty, assisted-evidence discount, temporal split, and leakage
controls. Compare against simpler baselines.

| Model | n learners/items/events | AUC | Log loss | Brier | ECE | Delayed retention |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BKT | `<N>` | `<VALUE>` | `<VALUE>` | `<VALUE>` | `<VALUE>` | `<VALUE>` |
| Hybrid | `<N>` | `<VALUE>` | `<VALUE>` | `<VALUE>` | `<VALUE>` | `<VALUE>` |

For expert fixtures, replace predictive claims with invariant/test results.

Forgetting models and delayed-retention calibration remain future evaluation
work; the P0.2 scheduler uses no forgetting probability or fatigue score.

Evidence: `<KT_REPORT_AND_SPLIT_MANIFEST>`

## Technical contribution 3 — bounded scheduling independent from KT

P0.2 scheduling is deliberately independent from KT. Only completed
`human_local_interactive` traces can seed tasks. Candidate causes remain
unconfirmed; +1/+3 windows and durations are fixed unvalidated policy; the
current activity is a same-fixture independent retest rather than unseen-item
transfer. Accept, complete, postpone, and skip are replayable schedule actions,
while resurfacing is internal fair rotation. User-marked completion does not
update KT or establish a learning effect. Cohort, peer, calibration, and
population-effect evidence remain unavailable.

Evidence: `evals/reports/latest.json` → `today_plan_schedule` and
`evals/reports/today-plan-evidence-latest.json`.

## Technical contribution 4 — model routing under quality constraints

Explain why ambiguity, free text, multimodality, and high-impact decisions route
to a strong tier, while simple structured work can use an economical tier only
with deterministic checks or strong-model review. Report quality, latency, cost,
escalation, and verifier-rejection rates by tier.

Evidence: `<ROUTER_EVAL>`

## Evaluation design

Cover the representative matrix and four baselines:

1. no tutor / ordinary explanation;
2. generic tutor without history;
3. history-aware tutor without cause-specific probe;
4. full Lumi policy.

Separate deterministic correctness, diagnosis calibration, KT prediction, tutor
quality, transfer, delayed retention, observability, privacy, and recovery. State
the preregistration and stopping criteria before population claims.

Evidence: `<RELEASE_REPORT_AND_STUDY_PROTOCOL>`

## Results

Use three sections so fixture replay cannot be mistaken for a user outcome:

### Proven by deterministic evidence

- `<CLAIM>` — `<ARTIFACT>`

### Supported by offline/expert evaluation

- `<CLAIM WITH SAMPLE SIZE/INTERVAL>` — `<ARTIFACT>`

### Requires a learner pilot

- population learning gain;
- delayed retention lift;
- policy superiority across cohorts;
- long-term engagement/agency effects.

## Failure analysis

Show at least one wrong diagnosis, one inconclusive intervention, one model-router
error, and one degraded/offline case. For each, include the trace, detection,
safe behavior, fix, and regression gate.

Evidence: `<FAILURE_TRACE_INDEX>`

## Product judgment and trade-offs

Discuss local-first latency/privacy vs cloud capability, interpretable baselines
vs sequence models, breadth vs fixture depth, cohort cold-start vs bias, and model
cost vs verification burden. Tie every decision to evidence or an explicit risk.

## What I would do next

Prioritize by which unproven claim matters most. Include instrumentation, pilot
design, success/guardrail metrics, rollback criteria, and data-governance review.

## Reproduction

```bash
python3 evals/run_all.py
```

- environment manifest: `<PATH>`
- report: `<PATH>`
- golden trace: `<PATH>`
- fixture checksums: `<PATH_OR_REPORT_FIELD>`
- known pending gates: `<LIST>`
