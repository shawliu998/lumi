# Judgment-reasoning experiment protocol

**Status:** application/portfolio evaluation protocol. This is a proposed,
replayable experiment specification for the first `xingce.judgment` Domain
Pack. It does not add a product feature, an evaluation runner, a clinical
study, or a claim that Lumi improves learning.

## 1. Decision this protocol can support

The protocol is intended to answer a narrow engineering question:

> Given the same authored conditional-reasoning pack, response budget, and
> seeded simulated learner, does a policy select a traceable diagnostic,
> teaching, verification, and review sequence without leaking answers or
> crossing learner-data boundaries?

It may compare mechanics among policies and expose failure modes. It cannot
establish teaching efficacy, causal learning gain, calibrated mastery, or
population error rates. In particular, a simulated learner's hidden label is a
test oracle, not a claim about a real learner's psychology.

The application story remains:

```text
observe -> diagnose -> probe -> teach -> verify -> update -> reflect
```

The experiment evaluates whether every transition in that story is reproducible
and evidence-bounded. The active product scope and item roles are defined in
[ADAPTIVE_DEMO_SCOPE.md](ADAPTIVE_DEMO_SCOPE.md); the proposed persistent-state
contracts are defined in
[JUDGMENT_REASONING_LEARNER_STATE_CONTRACT_PROPOSAL.md](JUDGMENT_REASONING_LEARNER_STATE_CONTRACT_PROPOSAL.md).

## 2. Scope, data boundary, and non-claims

- **Domain.** Only the small, versioned conditional-logic pack: direction of
  language, necessary versus sufficient roles, and valid/invalid inference.
  Do not silently substitute mutable question-bank files or external exam
  content.
- **Content.** Every evaluated item and teaching asset is pinned by
  `pack_id`, semantic version, content hash, role, and `independence_group`.
  Only reviewed, rights-cleared content may be used in an application-facing
  experiment. Draft items can be used only in an explicitly labelled local
  content-validation run and never as product evidence.
- **Synthetic data.** A simulation run has its own database/namespace and
  uses `evidence_origin: synthetic_isolated`, `synthetic: true`,
  `generator_version`, `seed`, and lineage metadata. It MUST NOT read or write
  a human learner namespace.
- **Human data.** A future small human study may assess usability of the
  workspace (for example: whether participants can find a chosen probe and
  explain a state-change receipt). It is not a learning-effect study. It must
  use explicit consent and a separate protocol before data collection; it must
  not be pooled with simulated trajectories.
- **No aggregation claims.** Synthetic results and small usability observations
  MUST NOT feed human state, cohort/peer displays, common-error estimates,
  calibration, causal inference, fairness analysis, or effect-size claims.
  Those fields remain unavailable in the product.

## 3. Four policies under comparison

The runner evaluates the same episode under exactly one policy, then repeats
that episode for every policy. Policies are versioned, deterministic when given
the same manifest and seed, and have no access to a persona's hidden cause
label or future responses.

| Policy ID | Strategy | Allowed state and actions | What it isolates |
| --- | --- | --- | --- |
| `fixed_sequence.v1` | Fixed sequence | An authored order: entry item -> generic explanation -> no-help transfer -> review. It ignores observed option, confidence, time, and history. | The value of adaptation over a fixed instructional script. |
| `explanation_only.v1` | Explanation only | It may score the entry response, then serves the same generic conditional-logic explanation. It selects no discriminating probe and does not use a learner-state snapshot for its action. | The difference between generic answer explanation and diagnosis-led action. |
| `state_only_deterministic.v1` | State-only deterministic | It reads only the versioned learner-state snapshot and follows a fixed state-to-action table. It does not inspect response-specific distractor, rationale, confidence, or response time while selecting an action. | The contribution of immediate diagnostic evidence beyond persistent state. |
| `lumi_hybrid.v1` | Lumi hybrid | It uses scored entry evidence plus an origin-matching state snapshot to rank unconfirmed candidates, chooses an authored separating probe, chooses a candidate-linked micro-lesson, then requires unseen no-help verification before a bounded update. | The proposed inspectable adaptive path. |

All policies may use the same deterministic scorer, content pack, item budget,
session clock, and final verifier. This is important: a policy must not gain a
hidden advantage by receiving more questions, a larger teaching library, or a
different answer key.

The policy label describes an implementation comparison, not a claim that one
policy is a valid control condition for a clinical or educational intervention
study.

## 4. Isolated synthetic persona contract

Synthetic personas simulate response patterns for regression and policy
comparison. Each persona is generated from a frozen catalogue and has explicit
hidden ground-truth labels solely so the evaluator can check whether a
diagnosis/probe decision matched the simulator configuration.

```json
{
  "persona_id": "jr-sim-v1-p014",
  "synthetic": true,
  "evidence_origin": "synthetic_isolated",
  "namespace_id": "synthetic:jr-sim-v1:20260712:014",
  "generator_version": "jr-persona-generator.v1",
  "seed": 20260712014,
  "lineage": {
    "pack_id": "xingce.judgment-reasoning.v1",
    "pack_version": "1.0.0",
    "persona_catalog_hash": "sha256:..."
  },
  "hidden_ground_truth": {
    "primary_pattern": "M-DIR",
    "secondary_pattern": "M-READ",
    "initial_skill_band": "intro",
    "teaching_response_rule": "counterexample_sensitive"
  }
}
```

The evaluator, not the policy, may read `hidden_ground_truth`. The policy sees
only the same observable response contract a learner would generate: selected
option, optional rationale class, confidence, elapsed time, and whether help
was opened. Hidden labels MUST NOT be serialized in policy prompts, decision
records, public activity payloads, learner-state snapshots, or product UI.

The initial catalogue should deliberately include at least these patterns:

| Synthetic label | Observable design target | Negative/ambiguous cases required |
| --- | --- | --- |
| `M-DIR` | reverses `只有 A，才 B` / implication direction | correct entry by chance; a new sentence with different surface words |
| `M-ROLE` | treats a necessary condition as sufficient | wrong option that overlaps with direction error; a correct answer with low confidence |
| `M-INF` | accepts converse or affirming-consequent inference | correct rule-symbolization but invalid conclusion |
| `M-READ` | occasional attention/reading slip without stable logical misconception | one-off error that a probe should not overdiagnose |
| `NO_TARGET_CAUSE` | sound conditional reasoning under the tested skills | distractor selection by seeded noise; correct first response |

Persona simulation must be transparent: the response rule, noise rate,
confidence/time distribution, and whether teaching changes subsequent behavior
are all authored inputs. Never tune these rules using a private human learner
database. A persona's post-teaching response rule is a scenario assumption,
not evidence that a lesson works for people.

## 5. Frozen experiment manifest and leakage controls

Every report begins from a single immutable manifest. Its hash is the identity
of the experiment; changing any listed field starts a new run.

```json
{
  "protocol_version": "jr-experiment.v1",
  "run_id": "jr-exp-...",
  "pack": {"id": "xingce.judgment-reasoning.v1", "version": "1.0.0", "content_hash": "sha256:..."},
  "persona_catalog": {"generator_version": "jr-persona-generator.v1", "catalog_hash": "sha256:...", "seeds": [101, 102]},
  "policies": ["fixed_sequence.v1", "explanation_only.v1", "state_only_deterministic.v1", "lumi_hybrid.v1"],
  "item_budget": {"max_scored_items": 3, "max_probes": 1, "max_transfers": 1, "max_delayed_reviews": 1},
  "time_budget_seconds": 300,
  "delayed_review_offset_days": 3,
  "scorer_version": "jr-mcq-scorer.v1",
  "randomization": {"item_order_seed_rule": "hash(run, persona, role)", "policy_order": "counterbalanced"}
}
```

The runner MUST enforce all of the following:

1. **Same pack and item budget.** Each policy sees the same role-specific
   candidate set, budget, scorer, and teaching assets. A policy that elects not
   to probe records `not_used`; it does not receive an extra transfer item.
2. **Role separation.** Entry, probe, teaching example, immediate transfer,
   and delayed review have distinct item IDs and independence groups. A
   teaching example cannot reappear as unhinted transfer or delayed review.
3. **No answer leakage.** Before a response, the public payload, model
   context, policy input, trace, and UI exclude correct option, proof, full
   explanation, distractor mapping, hidden persona labels, and future item
   identifiers. The verifier may access private scorer material only after the
   answer is committed.
4. **No future leakage.** A decision can reference only events with a sequence
   number earlier than the decision. It may not inspect delayed-review outcome,
   a future transfer, or another policy's trajectory.
5. **Same seed, isolated replay.** The persona seed is held constant across
   policy arms for paired comparison, but every arm gets a fresh synthetic
   namespace/database. Re-running the same arm must reproduce decisions,
   events, and state deltas byte-for-byte except declared timestamps or run IDs.
6. **No hidden retry.** A timeout, failed tool call, or invalid response
   consumes only the budget specified in the manifest. Retries are explicit
   trace events and cannot silently search for a favorable answer.
7. **Origin barrier.** A run fails if any synthetic ID reaches a human local
   DB, review plan, learner-state projection, cohort query, or product-facing
   event stream.

## 6. Episode procedure

For each `(persona, policy, seed)` tuple, execute this sequence:

1. Create an empty, isolated synthetic namespace and record the manifest hash.
2. Present one unseen entry diagnostic. Store only observable response fields.
3. Score the entry and generate a ranked list of *unconfirmed* candidates.
4. Let the policy select the next action within the fixed budget. Record every
   eligible alternative and a machine-readable `why_selected` /
   `why_not_selected` rationale.
5. If selected, present exactly one authored probe. Score it and record whether
   it supports, refutes, or leaves each candidate unresolved. A probe never
   reveals a ground-truth label to the policy.
6. Provide the policy's selected teaching action. Record exposure separately;
   this is not independent learning evidence.
7. Present one unseen **unhinted** transfer item. The verifier decides whether
   the configured bounded state update is allowed or must be withheld. A
   correct assisted answer fails the independent-evidence gate.
8. At the manifest offset, present a distinct unhinted delayed-review item.
   It is retention evidence for the simulator trajectory, not a human retention
   finding.
9. Export redacted trace, decision ledger, content references, state-before /
   state-after receipts, and replay result. Destroy or retain the isolated DB
   only under the experiment artifact policy; never merge it into product data.

The maximum role count should be disclosed even when a policy finishes early.
For example, a fixed sequence that uses no probe still has the same maximum
scored-item ceiling; it must not obtain a second transfer to spend the unused
probe budget.

## 7. Metrics and how to report them

All metrics are descriptive engineering metrics. Report the denominator,
confidence interval method if any, seeds, and exclusions. Do not convert a
simulation percentage into a human learning claim.

| Metric | Unit and definition | Required stratification |
| --- | --- | --- |
| Diagnostic accuracy | Exact/top-k match between the final ranked candidate list and the simulator's hidden primary label. `M-READ` and `NO_TARGET_CAUSE` must be included. | persona pattern, ambiguity level, first-answer correctness |
| Diagnostic abstention/error | Share of runs that remain unresolved, overconfidently select the wrong candidate, or convert a candidate to a fact. | policy, cause label |
| Probe efficiency | Number of scored diagnostic items and elapsed simulated seconds until the final decision, under the fixed budget. | policy, persona pattern |
| Teaching-policy alignment | Whether the selected asset is authored for a candidate that the policy currently ranks, and whether the rationale cites existing evidence. | policy, selected cause, asset ID |
| Unhinted transfer | Correctness on the unseen immediate transfer with `hint_count = 0`, distinct independence group, and no post-answer leakage. Assisted or repeated items are reported separately as `not_independent`. | policy, persona pattern, pre/post teaching rule |
| Delayed retention | Correctness on the distinct no-help delayed item at the registered offset. | policy, persona pattern, offset day |
| State-update discipline | Rate of state updates that satisfy the verifier's independent-evidence rule; rate correctly withheld when it fails. | policy, transfer outcome, assistance status |
| Replay and provenance | Exact replay pass rate; missing hash/version/evidence-reference count; cross-origin violation count. | policy, run environment |
| Cost and reliability | Wall-clock time, deterministic tool calls, token/cost if an LLM is used, timeout/recovery rate. | policy, model/provider version |

For a paired comparison, publish per-seed outcomes and paired differences, not
only an aggregate average. A simple report might state: “Across the frozen
simulator catalogue, `lumi_hybrid.v1` selected the authored matching probe in
X/Y seeded trajectories; this is a simulator-policy result, not an estimate of
learner benefit.”

Do not report Brier score, expected calibration error, AUC, causal effect,
fairness gap, cohort rate, or superiority unless the data source and study
design actually justify the term. In the first application protocol they are
explicitly `unavailable` for human claims.

## 8. Audit gates and failure rules

The run is **invalid**, rather than a pass with a caveat, if any of these occur:

- pack, answer-key, scorer, persona-generator, policy, or manifest hash is
  missing or differs between paired arms;
- a draft/unreviewed or rights-uncleared item enters an application-facing run;
- an entry/probe/teaching item is reused as independent transfer or delayed
  review, or an item violates its declared independence group;
- a policy sees an answer key, proof, distractor mapping, hidden persona label,
  future response, or delayed-review result before it is eligible;
- a synthetic event or projection is written to a human namespace or affects a
  human review task, learner state, cohort/peer field, calibration, or product
  UI;
- a diagnosis is rendered/stored as confirmed psychological fact instead of an
  unconfirmed, supported, refuted, or insufficient hypothesis;
- an assisted, repeated, same-item, or non-scoreable answer commits a mastery
  update labelled independent;
- a decision lacks policy version, content reference, evidence references, or
  selectable-alternative rationale;
- replay changes an immutable trace/state receipt or cannot verify its hash
  chain; or
- the report suppresses failed seeds, timeouts, invalid paths, or exclusions.

On invalidation, preserve a redacted failure artifact, record the exact rule,
quarantine the affected run/content/policy version, and rerun only after a new
manifest version is created. Do not repair a trace in place and do not silently
drop the failed seed.

The following are reportable **policy failures** but not automatic corruption:
choosing no probe, abstaining, withholding a state update, exceeding a declared
time budget, or selecting an authored but unhelpful action. They must remain in
the denominator and be visible in the replay ledger.

## 9. Real-participant usability study boundary

If the portfolio includes people, call it a small **usability study**, not an
experiment on learning effectiveness. A minimum protocol should state the
local data location, consent, task script, deletion path, and whether any
recording occurs. Suitable observations include:

- Can a participant identify the current item, their response, confidence, and
  the next action?
- Can they distinguish an observation from an unconfirmed candidate cause?
- Can they find why a probe, lesson, or state-update receipt was chosen?
- Can they complete or defer a review task and understand the displayed
  consequence?

Do not use a small convenience sample to estimate diagnosis accuracy,
calibration, population misconceptions, causal impact, learning gain, or
fairness. Do not blend these observations with synthetic trajectories, and do
not let them change another participant's local learner state. Any broader
research or comparative efficacy claim needs a separately reviewed study
design, appropriate recruitment/consent, and a registered analysis plan.

## 10. Required report template

Each released application/portfolio report should use this structure. “Not run”
is an acceptable and preferred value where implementation is not yet ready.

```markdown
# Lumi judgment-reasoning policy comparison — <run id>

## Scope and non-claims
- Protocol version / manifest hash:
- Pack ID, version, content hash, review/rights status:
- Evaluated claim: reproducible policy mechanics only.
- Not claimed: human effect, retention, calibration, cohort/common-error rate,
  causality, fairness, or superiority.

## Reproducibility
- Code revision:
- Persona generator version / catalogue hash / seeds:
- Policy IDs and hashes:
- Scorer/verifier versions:
- Fresh isolated namespace/DB per arm: pass | fail
- Replay command/environment and hash result:

## Budget and anti-leakage checks
- Same pack, candidate set, item budget, time budget across arms: pass | fail
- Entry/probe/teach/transfer/review independence checks: pass | fail
- Answer/hidden-label/future-item leakage checks: pass | fail
- Human/synthetic origin-barrier check: pass | fail

## Descriptive results
| Policy | Seed count | Diagnostic top-1/top-k | Probe items / time | Unhinted transfer | Delayed review | Valid updates / withheld updates | Replay |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| fixed_sequence.v1 | | | | | | | |
| explanation_only.v1 | | | | | | | |
| state_only_deterministic.v1 | | | | | | | |
| lumi_hybrid.v1 | | | | | | | |

## Failures, exclusions, and audits
- Invalid runs and exact gate:
- Policy failures (kept in denominator):
- Timeouts/retries:
- Content/policy quarantines:
- Trace/replay artifact locations (redacted/local):

## Interpretation
State only what the frozen simulator showed. For example: “The hybrid policy
selected authored separating probes more often in this simulator catalogue.”
Do not state or imply that people learned more effectively.

## Follow-up
- Product defect or content-review action:
- New manifest required before rerun:
- Human usability question, if any (separate from this result):
```

## 11. Completion criteria for using the protocol

This protocol is ready to be implemented only after the first Domain Pack has
reviewed items with the required role separation, the proposed state/decision
contracts have a concrete origin-isolated implementation, and a runner can
produce the report artifacts without touching human data. Passing the protocol
is evidence of a reproducible simulated policy comparison; it is not a release
claim that Lumi teaches better than another system.
