# Lumi product charter

## Positioning

**Lumi — Inspectable Adaptive Learning Agent**

Lumi helps a learner improve by maintaining a structured, evidence-backed view
of what they may understand, what remains uncertain, and what should happen
next. Its central claim is deliberately narrower than “AI teacher”: an agent
should identify competing explanations for an error, choose an action that
reduces uncertainty, and verify the result before it changes learner state.

## Product domain and release order

The application domain is now **all Xingce question types**. Lumi expands
through independently auditable Domain Packs rather than a generic chat layer:
every subtype receives its own scoring semantics, candidate error tree,
discriminating probe, teaching policy, unseen transfer, state receipt and
review schedule.

Conditional logic (sufficient/necessary conditions, direction conversion and
bounded symbolization) remains the reference implementation. As of 2026-07-14,
all 31 canonical subtypes are product-released: each binds a reviewed immutable
pack and deterministic learning mechanism. The owner explicitly waived
type-by-type human-local browser acceptance as a release blocker. Every release
records `owner_acceptance_waiver`, the decision date, and
`human_effect_evidence: unavailable`; release therefore means content and
mechanism availability, not validated usability or learning effect. The
canonical boundary lives in [XINGCE_COVERAGE_V1.md](XINGCE_COVERAGE_V1.md).

Shenlun, Interview, generic K12 tutoring, social or marketplace features,
rankings, payments, and broad AI chat remain out of scope for this delivery.

## Non-negotiable learner loop

```text
observe → diagnose → probe → teach → verify → update → reflect
```

- **Observe** stores answer, elapsed time, confidence, optional learner
  reasoning, and help use as an Evidence Event.
- **Diagnose** ranks multiple error hypotheses; none is presented as confirmed
  merely because one question was wrong.
- **Probe** selects the smallest authored question that can support or refute
  the current hypotheses.
- **Teach** selects an intervention and states why it was preferred over other
  actions.
- **Verify** uses an unseen, unassisted transfer item. Immediate success after
  explanation is not mastery.
- **Update** applies one deterministic learner-state transition with its
  evidence, model version, prior state, and new state—or explicitly withholds
  the update.
- **Reflect** creates an explainable review task; delayed verification remains
  distinct from same-session transfer.

## Product surface

The Learner Workspace is not a chat screen. It centres on:

1. learning map and current state;
2. current diagnostic and its evidence;
3. practice, teaching action, and independent verification;
4. learner-state change and decision explanation;
5. evidence timeline, replay, and review plan.

Conversation may assist input or explanation but cannot authoritatively change
skills, causes, mastery, or scheduling.

## Evidence and safety rules

- Answers, time, confidence, help use, and rationale are evidence, not
  conclusions.
- Candidate misconceptions remain visibly unconfirmed until discriminating
  evidence supports or refutes them.
- Only a deterministic state committer may change KT or schedule a review.
- Evaluation fixtures and synthetic learners use isolated origins/stores and
  never project into a human learner report, cohort claim, or product state.
- Any model-produced teaching or item must pass Domain Pack validation before a
  learner sees it; the first release uses authored items.
- Population, calibration, causality, fairness, and learning-effect claims are
  unavailable without consented, privacy-reviewed data.

## Five-minute demonstration and evidence standard

The owner waiver makes this walkthrough a post-release product-evidence target,
not a content/mechanism release gate. It is still required before Lumi may
claim a subtype has completed human experience validation or improved learning.

1. A learner mistakes an item from a reviewed Xingce subtype with confidence.
2. Lumi displays two or more candidate causes and asks one discriminating
   question.
3. The answer changes the teaching policy and Lumi explains why.
4. The learner attempts a different, unassisted transfer item.
5. Lumi either withholds mastery and schedules a retry, or records a bounded,
   explainable state change and schedules delayed verification.
6. The learner can replay every decision and see known limitations.

This demonstration proves a product mechanism, not population learning
efficacy. Evaluation design and comparison baselines are documented separately.
