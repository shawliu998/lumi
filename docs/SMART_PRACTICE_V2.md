# Lumi smart-practice v2 contract

Status: frozen v2 policy reference, approved for the internal growth-rate slice
on 2026-07-14. The policy remains active; the current four-module content scope
is defined in `CONTENT_BANK_V3.md`.

This contract supersedes the earlier mandatory
`first answer -> probe -> lesson -> verification` product path. The older v1
runtime remains available for regression evidence, but it is not the default
learner flow.

## Learner contract

- A session contains exactly eight slots. The learner may end it early; the
  system never adds a ninth item to finish a diagnosis or validation.
- The learner supplies only an answer. Confidence, reasoning, self-diagnosis,
  and Feynman restatement are optional and are never submission gates.
- A stable correct answer advances immediately. Explanation stays folded.
- The first error with a given observable signature shows one key correction;
  the full explanation is available on demand.
- The same signature must be observed in two independent evidence families
  before Lumi may select a reviewed microtutorial. This supports an error-pattern
  hypothesis, not a claim about the learner's true psychological cause.
- When more than one cause remains plausible, Lumi may offer one short,
  structured probe. A probe uses a normal session slot and is skippable.
- A near-transfer item appears after two to four other scored items, uses a
  different evidence family, and receives no reminder that it is a validation.
- A delayed validation becomes eligible no earlier than 24 hours after a
  successful near transfer and must again use a different evidence family.
- Review and validation items are mixed into later practice; there is no
  mandatory separate review task.

## Evidence contract

The system records observations separately from interpretations.

Observations include the selected option, deterministic score, question and
content versions, evidence and material families, response time when available,
hint/tutorial exposure, and recommendation decision. Error causes are ranked,
withdrawable hypotheses backed by those observations.

Positive learning evidence requires an unseen, unhinted, independently authored
item. Reading an explanation, viewing a tutorial, answering a probe, or solving
an exposed/assisted item cannot improve the diagnostic-unit state.

The production state labels are categorical and inspectable. The earlier
BKT/IRT path is experimental evidence only and must not silently determine v2
feedback or recommendations.

## Decision ownership

Structured content owns answers, scoring, diagnostic units, error-option
mappings, evidence families, and reviewed teaching assets. Deterministic policy
code owns intervention level, validation timing, and next-item ranking. A
language model may rewrite an approved explanation within fixed facts, but it
may not score an answer or create a learning-state transition.

Every accepted command records its input, policy/content version, reason codes,
resulting state, and tamper-evident event hash in the local SQLite trace.

## Frozen reference vertical slice

The original v2 target was growth-rate calculation in data analysis. It must
include independently authored questions across multiple evidence/material
families, explicit denominator, ratio-versus-growth, and negative-sign error
signatures, reviewed microtutorial assets, near-transfer eligibility, delayed
validation eligibility, deterministic tests, and one complete eight-slot HTTP
and client journey.

This retained slice is regression and focused-practice evidence. Core-320 v3
generalizes the same policy to verbal, judgment, quantitative, data analysis,
and mixed practice. Neither scope establishes
population learning gains, psychological cause identification, guessing
detection, speed proficiency, long-term retention lift, or full Xingce coverage.
