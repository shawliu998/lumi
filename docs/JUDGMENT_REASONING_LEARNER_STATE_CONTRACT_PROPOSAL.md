# Judgment-reasoning learner-state and decision contract (proposal)

**Status:** proposed contract for the first `xingce.judgment` application
demo. It describes an additive implementation plan; it does not describe an
implemented database, API, UI, model calibration, or measured learning effect.

**Product scope:** Lumi — *Inspectable Adaptive Learning Agent*, beginning with
Chinese civil-service-exam judgment reasoning. The first pack should cover a
small set of owned or explicitly licensed logical-reasoning items. Shenlun,
Interview, mutable question-bank folders, and cohort analytics are outside this
proposal.

## 1. Purpose and non-claims

The contract makes this chain inspectable:

```text
observable response
  -> ranked, unconfirmed diagnostic hypotheses
  -> a selected diagnostic or teaching action and its rationale
  -> independent verification
  -> an evidence-bounded learner-state snapshot and review decision
```

It is deliberately narrower than a general learner model. In particular, the
first demo must **not** claim any of the following:

- that a hypothesis is the learner's true psychological cause;
- calibrated mastery, item parameters, forgetting curves, or population rates;
- a causal teaching effect, long-term retention, or advantage over a tutor
  baseline;
- that a correct answer after teaching proves durable mastery;
- that seeded or evaluation trajectories are human learning evidence.

`MUST`, `MUST NOT`, and `SHOULD` below describe requirements for an eventual
implementation of this proposal.

## 2. Contract principles

1. **Facts, inferences, and decisions are separate.** A selected option or
   elapsed time is an observation; a misconception is an inference; choosing a
   probe is a policy decision. The UI and stored contract must not merge them.
2. **Trace remains source evidence.** Existing append-only, hash-chained run
   events and immutable content snapshots remain the evidence source. A
   learner-state projection is rebuildable and never replaces a trace.
3. **One authoritative committer.** Only the learner-state update service may
   create a new state snapshot. Content packs, model output, a tutor message,
   the review scheduler, and the UI may propose or display a change but may not
   commit one themselves.
4. **Uncertainty survives.** Candidate causes stay `unconfirmed` even when
   evidence supports them. A probe may support, refute, or leave a candidate
   unresolved; it does not turn an authored label into ground truth.
5. **Independent evidence has a stricter gate.** Help, worked examples, and
   same-item retries may be useful event evidence, but cannot independently
   establish transfer or raise authoritative mastery.
6. **Local and isolated by provenance.** Human local data, evaluation fixtures,
   and seeded synthetic demo data are physically and logically separate.

## 3. Namespaces and provenance isolation

Every run, event, snapshot, decision, and review task has a mandatory
`evidence_origin` and `namespace_id`.

| Origin | Namespace rule | Permitted use | Forbidden projection |
| --- | --- | --- | --- |
| `human_local_interactive` | One local learner namespace, e.g. `human:<local-learner-id>` | The learner's local workspace, skill state, and review plan | Evaluation reports, synthetic baselines, cohort priors, or another local learner |
| `evaluation_fixture` | Ephemeral/reproducible evaluation namespace, e.g. `eval:<suite>:<run>` | Deterministic contract and regression tests | Human learner state, human review plan, cohort/peer statistics, or product history |
| `synthetic_isolated` | Seeded demo namespace and separate DB/path, e.g. `synthetic:<generator-version>:<seed>` | Demo personas, replay, and offline policy comparisons | Human learner state, human review plan, cohort/peer statistics, calibration, causal/fairness/effect claims |

The namespace is part of every primary or unique key. An implementation MUST
fail closed when a reference crosses origins. A `human_local_interactive`
projection may only reference human-local evidence from the same namespace.
The first demo has no consented population-data pathway; all `cohort`, `peer`,
`common_error_rate`, and `calibration` fields therefore remain unavailable.

`learner_id` is a local pseudonymous identifier, not a name, email, or cloud
account. Content rights/provenance and learner-evidence provenance are distinct:
an item may have `local_versioned_export` provenance while an attempt has
`human_local_interactive` provenance.

## 4. Versioned domain-pack requirements

The first pack uses a new, independent namespace such as
`xingce.judgment-reasoning.v1`. It SHOULD start with a small number of
hand-authored or licensed items, not a full question bank.

Each item needs a versioned `ContentRef` and authored metadata:

```json
{
  "content_ref": {
    "pack_id": "xingce.judgment-reasoning.v1",
    "pack_version": "1.0.0",
    "item_id": "jr.necessary-condition.01",
    "content_signature": "sha256:...",
    "role": "diagnostic_first|probe|transfer|delayed_review"
  },
  "skill_links": [
    {"skill_id": "xingce.judgment.logic.necessary_condition", "weight": 0.8},
    {"skill_id": "xingce.judgment.logic.symbolize", "weight": 0.2}
  ],
  "difficulty": {"band": "intro", "status": "author_estimate_unvalidated"},
  "rights": {"license_or_authorship": "owned_or_cleared", "distribution": "demo_local"}
}
```

The pack MUST provide:

- a directed skill graph and content-to-skill links (the Q-matrix);
- distractor-to-observation mappings and a subtype-specific misconception
  taxonomy;
- two or more authored candidate probes when a diagnosis needs disambiguation;
- short, reviewed teaching assets (definition, positive/negative example,
  contrast, or reasoning prompt), each tied to a candidate cause;
- an independently scoreable, unseen transfer item; and
- a delayed-review item whose text and content signature differ from the first
  and immediate transfer items.

Generated content may be proposed later, but the first demo MUST use only
versioned content that has an answer/ambiguity check. The correct answer and
full explanation stay in private scorer content and are never returned in a
pre-answer public activity payload.

## 5. Concrete contract entities

The entities are logical contracts. They may initially be JSON projections over
the current event store rather than independent tables, but identifiers and
references are mandatory from the first implementation.

### 5.1 `EvidenceEvent`

One immutable observation or derived deterministic scoring result.

```json
{
  "schema_version": "lumi.evidence-event.v1",
  "event_id": "evt_...",
  "namespace_id": "human:local-01",
  "evidence_origin": "human_local_interactive",
  "run_id": "run_...",
  "trace_ref": {"run_id": "run_...", "seq": 4, "event_hash": "..."},
  "content_ref": {"pack_id": "xingce.judgment-reasoning.v1", "item_id": "jr.necessary-condition.01", "content_signature": "sha256:...", "role": "diagnostic_first"},
  "kind": "attempt|score|probe_response|hint|intervention_exposure|verification",
  "observed": {
    "response_ref": "redacted/local pointer",
    "selected_option": "B",
    "correct": false,
    "response_time_seconds": 74,
    "confidence": 0.8,
    "hint_count": 0,
    "independently_answered": true,
    "attempt_ordinal": 1
  },
  "skill_evidence": [
    {"skill_id": "xingce.judgment.logic.necessary_condition", "weight": 0.8, "observation": "reversed_implication"}
  ],
  "producer": {"kind": "deterministic_scorer", "version": "xingce_mcq_v1"},
  "occurred_at": "RFC3339"
}
```

`EvidenceEvent` MUST be append-only, reference an existing verified trace
event, and never contain a silently inferred cause as an observed fact.

### 5.2 `DiagnosisHypothesis`

An explicitly uncertain candidate explanation for one diagnostic episode.

```json
{
  "schema_version": "lumi.diagnosis-hypothesis.v1",
  "hypothesis_id": "dxh_...",
  "namespace_id": "human:local-01",
  "episode_id": "episode_...",
  "skill_id": "xingce.judgment.logic.necessary_condition",
  "cause_id": "necessary_sufficient_reversal",
  "status": "unconfirmed|supported|refuted|insufficient",
  "rank": 1,
  "probability": 0.55,
  "uncertainty": 0.67,
  "evidence_refs": ["evt_..."],
  "prior": {"kind": "engineering_prior", "version": "jr-taxonomy.v1", "sample_size": 0},
  "model": {"name": "hierarchical-cause-baseline", "version": "v3"},
  "created_from_snapshot_id": "lss_..."
}
```

`probability` is a ranking score within the episode, not a clinical or causal
probability. `supported` means only that the stated probe rule supported the
candidate; it MUST still be displayed as unconfirmed.

### 5.3 `DiagnosticPlan` and `PolicyDecision`

The planner produces an inspectable action proposal. The committed decision
records what was selected and why other available actions were not selected.

```json
{
  "schema_version": "lumi.policy-decision.v1",
  "decision_id": "pd_...",
  "namespace_id": "human:local-01",
  "episode_id": "episode_...",
  "decision_type": "select_probe|select_teaching|select_verification|schedule_review",
  "state_snapshot_id": "lss_...",
  "candidate_actions": [
    {
      "action_id": "probe.jr.direction.02",
      "kind": "probe",
      "targets": ["necessary_sufficient_reversal", "conditional_rule_not_applied"],
      "authored_discrimination_score": 0.82,
      "eligibility": "eligible",
      "reason": "Separates direction reversal from rule non-application."
    }
  ],
  "selected_action_id": "probe.jr.direction.02",
  "selection_reason": {
    "policy_version": "judgment-diagnostic-policy.v1",
    "basis": ["dxh_...", "evt_..."],
    "why_selected": "Highest authored discrimination among eligible probes.",
    "why_not_selected": [{"action_id": "probe.jr.premise.01", "reason": "Does not distinguish the top two candidates."}],
    "calibration_status": "author_policy_unvalidated"
  },
  "committed_at": "RFC3339"
}
```

The initial score is an authored deterministic ranking, **not** a claim that
expected information gain has been estimated from a learner population. A
policy decision MUST have evidence references, policy/version identifiers, and
an origin-matching state snapshot. A model may draft wording but cannot make an
unverifiable learner-state decision.

### 5.4 `Intervention` and `VerificationResult`

```json
{
  "schema_version": "lumi.intervention.v1",
  "intervention_id": "int_...",
  "namespace_id": "human:local-01",
  "decision_id": "pd_...",
  "asset_ref": {"pack_id": "xingce.judgment-reasoning.v1", "asset_id": "teach.arrow-counterexample.01", "content_signature": "sha256:..."},
  "strategy": "arrow_counterexample",
  "target_hypothesis_ids": ["dxh_..."],
  "exposure_evidence_refs": ["evt_..."],
  "assistance_level": 0,
  "policy_version": "judgment-teaching-policy.v1"
}
```

```json
{
  "schema_version": "lumi.verification-result.v1",
  "verification_id": "vr_...",
  "namespace_id": "human:local-01",
  "intervention_id": "int_...",
  "attempt_evidence_ref": "evt_...",
  "verification_kind": "unseen_transfer|delayed_retention",
  "unseen_from": ["sha256:first", "sha256:probe"],
  "independent": true,
  "hint_count": 0,
  "scorer": {"name": "exact_option_v1", "version": "1"},
  "outcome": "passed|failed|inconclusive",
  "state_update_eligibility": "eligible|withheld",
  "withheld_reason": null
}
```

### 5.5 `LearnerSkillState` and `LearnerStateSnapshot`

`LearnerSkillState` is a current projection for one learner namespace and one
skill. `LearnerStateSnapshot` records an atomic before/after state change across
all affected skills.

```json
{
  "schema_version": "lumi.learner-skill-state.v1",
  "state_id": "lss_...",
  "namespace_id": "human:local-01",
  "learner_id": "local-01",
  "skill_id": "xingce.judgment.logic.necessary_condition",
  "state_version": 7,
  "mastery": {
    "value": 0.42,
    "uncertainty": 0.58,
    "evidence_count": 3,
    "status": "evidence_limited|independent_transfer_supported|needs_recheck",
    "model": {"name": "bkt-pfa-rasch-ensemble", "version": "v1", "calibration_status": "engineering_unvalidated"}
  },
  "active_hypothesis_refs": ["dxh_..."],
  "latest_verification_ref": "vr_...",
  "review_status": {"next_review_task_ref": "rt_...", "basis": "independent_retry"},
  "evidence_window": {"included_event_refs": ["evt_..."], "excluded_event_refs": ["evt_assisted_..."], "exclusion_reasons": ["assisted_practice_not_mastery_credit"]},
  "created_at": "RFC3339"
}
```

```json
{
  "schema_version": "lumi.learner-state-snapshot.v1",
  "snapshot_id": "lssnap_...",
  "namespace_id": "human:local-01",
  "trigger": {"run_id": "run_...", "verification_id": "vr_..."},
  "previous_state_refs": ["lss_..."],
  "next_state_refs": ["lss_..."],
  "state_delta": [{"skill_id": "xingce.judgment.logic.necessary_condition", "mastery_delta": 0.04, "commit_status": "committed"}],
  "committer": {"name": "learner_state_updater", "policy_version": "judgment-state-update.v1"},
  "evidence_refs": ["evt_...", "vr_...", "pd_..."],
  "trace_verification": {"run_id": "run_...", "verified": true},
  "created_at": "RFC3339"
}
```

The first demo may show mastery as an explicitly uncalibrated engineering
estimate. The UI should lead with `status`, evidence count, uncertainty, and
the receipt—not an unsupported percentage interpretation.

### 5.6 `ReviewTask`

A review task is a future action, not proof of retention.

```json
{
  "schema_version": "lumi.review-task.v1",
  "task_id": "rt_...",
  "namespace_id": "human:local-01",
  "source_snapshot_id": "lssnap_...",
  "skill_id": "xingce.judgment.logic.necessary_condition",
  "kind": "independent_retry|delayed_retention",
  "due_at": "RFC3339",
  "item_selector": {"pack_id": "xingce.judgment-reasoning.v1", "role": "delayed_review", "excludes_content_signatures": ["sha256:first", "sha256:transfer"]},
  "success_criterion": "unhinted independently scored response",
  "skip_consequence": "state remains evidence_limited; no mastery promotion",
  "policy": {"version": "judgment-review-policy.v1", "calibration_status": "author_policy_unvalidated"}
}
```

## 6. Snapshot and state-update invariants

An implementation MUST enforce the following at the committer boundary, not
only in UI text or prompt instructions.

1. Every state delta has a verified hash-chain trace, origin-matching evidence
   references, a content reference, and model/policy versions.
2. A snapshot is append-only. Existing snapshot values and evidence links cannot
   be edited; a correction creates a superseding snapshot with a reason.
3. Snapshot versions increase monotonically per `(namespace_id, learner_id,
   skill_id)` and use compare-and-append semantics. A stale request cannot
   silently overwrite a newer projection.
4. A verification item must differ in content signature from its first item and
   all items designated as teaching examples for that episode.
5. A mastery increase requires: deterministic scorer pass, zero hints on that
   verification item, `independently_answered=true`, an eligible unseen transfer
   result, and a validated state-update rule.
6. A failed, assisted, non-independent, stale, or unresolved verification has
   `commit_status=withheld` and `mastery_delta=0`. It may produce a diagnostic
   or scheduling decision with its evidence plainly recorded.
7. First answers, probes, teaching exposure, and same-item retries never
   independently establish mastery. They can update hypothesis evidence only.
8. A correct initial answer may create a retention probe plan; it does not
   bypass the verification rule or create an error cause.
9. Each diagnosis episode has at least two candidate causes before a
   disambiguating probe is selected, unless an explicit deterministic
   `no_error`/`insufficient_evidence` rule explains why it does not.
10. A policy decision references the exact state snapshot and candidate action
    set used at decision time. Candidate actions and `why_not_selected` cannot
    be regenerated after the fact.
11. All `cause_id` values must come from the content pack's versioned taxonomy;
    free-form model labels are display suggestions, not state keys.
12. A review task is idempotent on its source snapshot and task kind. Replaying
    a completed run cannot create a second task.
13. Completion of a review task only creates new evidence. It changes state
    only after the same verifier/committer gate; a task due date does not create
    retention credit.
14. No evidence with `evaluation_fixture` or `synthetic_isolated` origin is
    readable by, aggregable with, or writable into a human projection.
15. Human state must not affect cohort priors in this demo. Such fields remain
    absent or `unavailable`, never zero-filled as a real rate.
16. No LLM output may directly set `commit_status=committed`, a mastery number,
    a state version, or a review task. It can only emit constrained proposals
    that deterministic code validates.

## 7. Reference state transitions for the demo

The demo has one deterministic episode shape, while retaining evidence for
alternative outcomes:

```text
start
  -> first independent attempt
  -> score + candidate hypotheses (all unconfirmed)
  -> select authored discriminating probe
  -> probe evidence supports/refutes/leaves candidates unresolved
  -> select target teaching asset or request more evidence
  -> learner sees teaching asset
  -> unseen, unhinted transfer
  -> verifier
       pass: committed state snapshot + delayed-retention task
       fail: withheld snapshot (delta 0) + independent-retry task
       assisted/inconclusive: withheld snapshot (delta 0) + fresh independent task
  -> later delayed-review attempt is a new episode, not an implicit success
```

The planner must be allowed to abstain: `insufficient_evidence` is preferable
to an overconfident diagnosis or a generic explanation disguised as adaptation.

## 8. Additive migration and compatibility boundary

### 8.1 What remains unchanged

- Existing internal `hermes_*` package, schema, sidecar, and endpoint names
  remain valid implementation contracts. The public name continues to be
  Lumi; a cosmetic rename must not invalidate stored evidence.
- Existing SQLite trace events, immutable content snapshots, replay semantics,
  scheduling records, and their hash chains remain immutable.
- Existing data-analysis P0.3 activity and its local-only content stay a
  separate legacy/experimental activity. It is neither rewritten nor reclassified
  as judgment-reasoning evidence.
- Existing `evaluation_fixture` behavior remains test-only. Existing synthetic
  fixtures remain representative contract material, not human evidence.
- `$HOME/Desktop/shenlun-agent-platform` remains read-only and no new demo
  behavior depends on mutable source files under `$HOME/Documents/xingcetiku`.

### 8.2 What the eventual migration adds

1. A new judgment-reasoning pack and product-activity metadata, with a new pack
   and skill namespace (`xingce.judgment.*`). The current product-activity
   validator must be generalized rather than copied with a second data-analysis
   exception.
2. Additive projection records for the entities in section 5, scoped by
   namespace and linked back to traces. No historical trace event is rewritten.
3. A projection-builder version, such as `learner-state-projection.v1`, so a
   future corrected policy can build a new projection rather than alter prior
   state receipts.
4. Additive service responses and client view models. Existing callers must
   continue to receive existing fields; unknown new fields are optional until a
   versioned endpoint is introduced.
5. A separate, resettable demo database/path for seeded learners. It must not
   share SQLite files, task IDs, learner IDs, or namespace identifiers with the
   human local database.

### 8.3 Historical-data rule

No old run is backfilled into the new learner model by inference. Historical
data-analysis runs may be replayed for audit but carry no judgment-reasoning
skill evidence. A user who starts the judgment demo begins with explicit
`evidence_limited` state and versioned engineering priors. This is more honest
than treating unrelated prior responses as evidence of logical-reasoning
mastery.

## 9. Retention, export, and deletion boundary

This proposal does not add a cloud service. The default is local storage of the
minimum evidence needed for replay, with existing redaction rules applied to
sensitive fields. Raw free-text reasoning should be optional, visibly retained,
and separated from compact scoring features where possible.

Before an implementation calls a feature "delete", it must define whether it
deletes an entire local namespace, derived projections, local content snapshots,
or a future export copy. Append-only trace integrity means individual
in-place event deletion is not a valid silent operation. Until an explicit
delete/export contract exists, the product must not imply selective erasure,
cloud synchronization, or data sharing.

## 10. Demo acceptance evidence (not efficacy evidence)

The first application demo is ready for a human walkthrough when it can show,
for one real local judgment-reasoning run:

1. a first answer with time, confidence, and deterministic scoring;
2. two or more clearly labelled unconfirmed candidate causes;
3. the selected probe plus its candidate set and selection rationale;
4. a targeted teaching action tied to the probe evidence;
5. a different, unhinted transfer item;
6. a verifier result and one atomic state-update receipt—or an explicit
   withheld receipt with zero delta;
7. one idempotent review task with a delayed item selector;
8. a replayable timeline linking all state/decision records to verified trace
   evidence; and
9. proof that a seeded/evaluation run cannot appear in the human workspace.

This evidence demonstrates inspectability and contract correctness. It does
not demonstrate improved learning outcomes. Any later comparison with fixed
sequence or explanation-only baselines must use a declared protocol, isolated
synthetic personas or consented data, and report limitations separately.
