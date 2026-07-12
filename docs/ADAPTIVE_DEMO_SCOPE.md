# Judgment-reasoning adaptive-demo scope

This is the active implementation scope for the Lumi application version. It
replaces the earlier multi-domain/data-analysis product scope; historical
mechanisms and traces remain immutable compatibility evidence.

## One demonstrable claim

Lumi can distinguish several plausible causes of a conditional-logic error,
select a small authored probe, choose a fitting teaching action, and use an
unseen no-help item to decide whether to make or withhold a bounded learner
state update.

It does **not** claim that a single transfer item proves durable learning or
that the policy outperforms a tutor without a registered comparison study.

## v0.1 skill graph

```text
xingce.judgment.conditional
├── language_direction
│   ├── only_a_then_b      (B → A)
│   └── if_a_then_b        (A → B)
├── necessary_vs_sufficient_role
└── inference_validity
    ├── direct_inference
    ├── contrapositive
    ├── converse_fallacy
    └── affirming_consequent
```

No “unless”, compound antecedents, truth-tellers, sets, analogy, figure
reasoning, or external-exam content is included in v0.1.

## Candidate causes

| ID | Candidate interpretation | Probe needed to distinguish it |
| --- | --- | --- |
| `M-DIR` | reverses `只有 A，才 B` | choose an arrow for a new sentence |
| `M-ROLE` | treats a necessary condition as sufficient | test whether prerequisite without outcome is compatible |
| `M-INF` | parses a rule but applies an invalid converse/affirming-consequent inference | solve a symbol-only inference item |
| `M-READ` | possible reading or attention slip | neutral reread/restate; no long lesson or mastery claim |

Every row is a hypothesis. A distractor, confidence, time, or one probe may
support or refute it; none can turn it into a causal fact by itself.

## Required item roles and separation

| Role | Purpose | Independence rule |
| --- | --- | --- |
| entry diagnostic | creates competing hypotheses | not reused as transfer or teaching example |
| probe | maximally separates current candidates | one per decision, authored rationale recorded |
| teaching asset | short explanation, contrast, or counterexample | never scored as independent evidence |
| transfer | no-help verification | distinct `independence_group`, surface vocabulary, and option order |
| delayed review | retention evidence | distinct item and later scheduled session |

### Cross-session evidence rule

Earlier probe observations may be replayed only for the same local learner,
namespace, origin, and exact Domain Pack version. They remain counts of `supported`,
`refuted`, or `insufficient` observations—not probabilities, diagnoses, or
mastery. A later session must still run its current authored probe. Only if the
current probe supports more than one authored teaching route may earlier
observations break that current tie; history alone cannot select teaching,
confirm a cause, create a state update, or schedule a review.

## Content and release policy

The initial pack is **Lumi Original Conditional Reasoning Pack** under CC BY
4.0. Every item stores source origin, licence, formalization, answer proof,
answer key, distractor mapping, skill links, misconception links, item role,
independence group, semantic version, and content hash.

All new items start `draft_unreviewed`. They cannot be returned by the product
catalogue until two human reviewers record, against the exact content hash:

1. logic review: formalization, unique answer, distractor interpretation, and
   transfer independence;
2. editorial/rights review: original wording, clarity, accessibility, and
   licence confirmation.

No generated or imported draft can claim `release_ready`; the current product
will fail closed rather than silently falling back to historical data-analysis
content.

## Five-minute acceptance

1. Learner answers a conditional-logic item with confidence and optional
   rationale.
2. Workspace separates observations from at least two candidate causes.
3. Planner displays its chosen probe and why that probe distinguishes the
   candidates better than the available alternatives.
4. Teaching policy displays its chosen intervention, target candidate, and why
   it did not choose generic explanation or another action.
5. Learner attempts an unseen no-help transfer.
6. Workspace shows a state-change receipt or an explicit withheld receipt,
   followed by a review task and replayable evidence timeline.
