# Lumi Mac demo script

Status: **Core-320 internal demo is executable; current visual/usability evidence
is not claimed**

Current executable evidence: Core-320 exposes 320 versioned questions through
verbal, judgment, quantitative, data-analysis, and mixed scopes. The four
deterministic suites pass 76/41/43/24 tests, the client production build passes,
and the ARM64 debug app manages its packaged sidecar. The screenshots in
`client/design-qa.md` predate this UI and are historical only.

The legacy evaluator still provides black-box real-attempt and multi-step
continuation gates. They remain backend regression evidence, not the current
learner journey.

## Current Core-320 demo (5–7 minutes)

Preflight:

- start the local service and client, or open
  `desktop/src-tauri/target/debug/bundle/macos/Lumi.app`;
- confirm `/v1/capabilities` reports 320 questions, 80 per module, and five
  scopes;
- use a resettable local demo learner; answer manually and do not describe the
  run as a usability study.

1. Select one of 言语、判断、数量、资料分析, or 综合. Show that the session target
   is fixed at eight and that answer is the only required input.
2. Answer one question correctly: Lumi advances and keeps the explanation
   folded. Answer another incorrectly: Lumi gives the smallest relevant
   correction and records an observable option signature, not a certain mental
   cause.
3. Continue ordinary questions. If the same signature recurs across independent
   material/evidence families, show the controlled microtutorial or optional
   skippable probe. It consumes no extra slot beyond the fixed eight.
4. Show any pending unseen transfer as an ordinary later item; if it cannot fit,
   show that it carries into a later session. Do not simulate or claim a real
   24-hour retention result during the demo.
5. Complete or end early, open the factual summary and trace, then switch module
   or enter mixed practice to show that exposure, hypotheses, and pending checks
   remain in one shared local learner record.

Closing claim:

> This demo proves the deterministic mechanics of a local, auditable,
> four-module direct-practice loop. It does not prove human content approval,
> usability, population learning gains, or delayed retention.

## Historical v1 diagnostic regression demo

The remainder is retained only for inspecting the older mandatory
answer→probe→teaching→verification state machine.

### Preflight

- [x] Run `python3 evals/run_all.py` in the current local repository.
- [x] Record the report path: `evals/reports/latest.json`.
- [x] Confirm `attempt_api`, `cohort_prior_guardrail`, and
  `attempt_continuation` pass in the current report.
- [x] Confirm local/offline mode is visible in the Mac client.
- [x] Use a synthetic learner identity and sanitized content.
- [x] Confirm `$HOME/Desktop/shenlun-agent-platform` is not a runtime dependency.

Mac shell evidence:

- visual QA: `client/design-qa.md`
- overview: `client/qa/overview-1440x1024.png`
- tools: `client/qa/tools-1440x1024.png`
- reports: `client/qa/reports-1440x1024.png`
- managed sidecar lifecycle: `cd desktop && npm run check:managed-app`
- local app: `desktop/src-tauri/target/debug/bundle/macos/Lumi.app`
- full verifier: `python3 scripts/verify_core.py`
- legacy regression run: `evals/reports/latest.json` (`run-20260714T120838Z`)

### Scene 1 — establish the learner state (45 seconds)

Show the Today view and skill map.

Narration:

> Lumi is a local-first learning agent. Its structured learner state is the
> source of truth; chat memory cannot silently change mastery. This skill has low
> evidence and visible uncertainty, so the agent chooses a diagnostic task.

Evidence to open:

- learner-state snapshot: `<ARTIFACT_PATH_OR_TRACE_ID>`
- KT/model version: `<VERSION>`
- local/cloud boundary indicator: `<SCREEN_OR_TRACE_FIELD>`

### Scene 2 — deliberately ambiguous Xingce error (2 minutes)

Use the growth-rate case. The learner selects a distractor compatible with more
than one cause. Show response time, confidence, answer revision, and option-to-
misconception evidence if available.

Expected behavior:

- Lumi does **not** state a certain cause.
- It ranks at least two hypotheses with cohort and personal evidence separated.
- It reports sample size/source version for the cohort prior.
- It chooses a discriminating probe instead of giving the answer.

Evidence:

- attempt ID: `<ATTEMPT_ID>`
- diagnosis trace ID: `<TRACE_ID>`
- ranked probabilities before probe: `<VALUES>`
- gate/report link: `<REPORT_PATH>`

### Scene 3 — probe, revise, and teach (2 minutes)

Answer the minimal discriminating probe. Show how evidence changes hypothesis
probabilities. Then show one cause-specific explanation or scaffolded prompt.

Expected behavior:

- The probe targets the difference between the leading hypotheses.
- The diagnosis revises or abstains; it is not rewritten without evidence.
- The tutor avoids answer leakage and records its policy/model tier.
- A low-cost model output cannot affect learning without its required verifier.

Evidence:

- policy decision ID: `<DECISION_ID>`
- model routing reason/tier: `<ROUTING_EVIDENCE>`
- verifier result: `<VERIFIER_RESULT>`
- teaching intervention ID/version: `<INTERVENTION>`

### Scene 4 — independent transfer and KT update (90 seconds)

Complete an isomorphic item without hints. Open the before/after state diff.

Expected behavior:

- Hinted work is not counted as independent transfer.
- The mastery delta links to exactly the triggering evidence.
- BKT/PFA/IRT components, ensemble version, disagreement, and uncertainty remain inspectable.
- Review scheduling is based on evidence and forgetting risk.

Evidence:

- verification attempt ID: `<ATTEMPT_ID>`
- intervention outcome: `<TRUE_FALSE_OR_INCONCLUSIVE>`
- mastery before/after: `<VALUES>`
- formula/policy version: `<VERSION>`
- scheduled review: `<SCHEDULE_RECORD>`

### Scene 5 — Agent Lab trajectory (90 seconds)

Open the exact trajectory and locate, without searching source code:

1. triggering observation;
2. policy decision and reason;
3. tool/model names and versions;
4. verifier result;
5. learner state before/after;
6. evaluation result;
7. privacy/cloud disclosure.

Replay the trajectory in dry-run mode and show that persisted learner state did
not mutate. Compare the replay hash/state diff with the original.

Evidence:

- original trace hash: `<SHA256>`
- replay trace hash: `<SHA256>`
- mutation assertion: `<RESULT>`

### Scene 6 — safe degradation (60 seconds)

Disable network access and open an item with conflicting/insufficient scoring
evidence. Lumi should retain local practice/history/baseline KT, quarantine the
item, avoid mastery mutation, and explain what is unavailable.

Evidence:

- offline fixture ID: `<CASE_ID>`
- quarantine reason: `<REASON>`
- unchanged state proof: `<STATE_HASH_BEFORE_AFTER>`
- cloud operation disclosure: `<NONE_OR_DISCLOSURE>`

### Scene 7 — cross-domain breadth (60 seconds)

Show one completed representative trajectory each for Shenlun and Interview.
Keep scoring evidence domain-specific while showing that both write the same
learning-event contract. Do not imply production Shenlun source reuse.

- Shenlun trace: `<TRACE_ID>`
- Interview trace: `<TRACE_ID>`
- shared contract version: `<VERSION>`

### Closing claim

Use only after the release report supports it:

> This demo proves the mechanics of an auditable, local learning-agent loop on
> the listed representative fixtures. It does not yet prove population learning
> gains; those require a preregistered pilot with delayed-retention outcomes.
