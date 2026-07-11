# Lumi Mac demo script

Status: **P0.1 executable runbook; P0.2/P1/P2 scenes are listed separately as
future work and must not be demonstrated as current capability**

Current executable evidence: the evaluation harness retains verified success,
ambiguous, and offline integration replays in
`evals/reports/integration-*-trajectory-latest.json`, and validates the full
42-case domain contract matrix. The Mac shell and three core screens are now
captured and visually gated in `client/design-qa.md`. The same report records a
real visible first answer → targeted probe/help → cause-specific teaching →
independent verification flow, report refresh, offline/error fallbacks, and 409
recovery. Exact trace versions are evidence, not a stable product promise.

The evaluator also has black-box real-attempt and multi-step continuation gates.
The latter proves the versioned local HTTP state sequence and can supply the
backend trace for the probe/verification scene.

Target duration: 8–10 minutes. The narrative should show a closed learning loop
and its audit trail, not a generic chatbot conversation.

## Preflight

- [x] Run `python3 evals/run_all.py` in the current local repository.
- [x] Record the report path: `evals/reports/latest.json`.
- [x] Confirm `attempt_api`, `cohort_prior_guardrail`,
  `attempt_continuation`, `progressive_assistance`, and
  `misconception_dossier` pass in the freshly generated report.
- [x] Confirm local/offline mode is visible in the Mac client.
- [x] Use a synthetic learner identity and sanitized content.
- [x] Confirm `$HOME/Desktop/shenlun-agent-platform` is not a runtime dependency.

Mac shell evidence:

- visual QA: `client/design-qa.md`
- current screenshots: the allow-listed authentic P0.1 files in
  `client/design-qa.md`
- managed sidecar lifecycle: `cd desktop && npm run check:managed-app`
- local app: `desktop/src-tauri/target/debug/bundle/macos/Lumi.app`
- full verifier: `python3 scripts/verify_core.py`
- authoritative release run: the current `run_id` inside
  `evals/reports/latest.json`, generated after the final source change

## Scene 1 — establish the learner state (45 seconds)

Show the Today view before and after one completed local run.

Narration:

> Lumi is a local-first learning agent. Its structured learner state is the
> source of truth; chat memory cannot silently change learning state. The page
> shows only sidecar-backed run/skill counts. Today scheduling is not connected
> yet, so Lumi does not invent a task list.

Evidence to open:

- empty/connected comparison: `client/design-qa.md`
- KT/model version: `<VERSION>`
- local/cloud boundary indicator: `<SCREEN_OR_TRACE_FIELD>`

## Scene 2 — deliberately ambiguous Xingce error (2 minutes)

Use the growth-rate case. The learner selects a distractor compatible with more
than one cause. Show response time, confidence, answer revision, and option-to-
misconception evidence if available.

Expected behavior:

- Lumi does **not** state a certain cause.
- It ranks at least two hypotheses and labels every cause as unconfirmed.
- It reports sample-zero synthetic engineering-prior provenance; real cohort
  evidence is unavailable and no peer rate is shown.
- It chooses a discriminating probe instead of giving the answer.

Evidence:

- attempt ID: `<ATTEMPT_ID>`
- diagnosis trace ID: `<TRACE_ID>`
- ranked probabilities before probe: `<VALUES>`
- gate/report link: `<REPORT_PATH>`

## Scene 3 — probe, revise, and teach (2 minutes)

Answer the minimal discriminating probe. Show how authored evidence supports or
refutes individual candidates and changes the instructional focus. Then show
one cause-specific explanation or scaffolded prompt.

Expected behavior:

- The probe targets the difference between the leading hypotheses.
- The dossier changes candidate evidence status or abstains; it does not invent
  a confirmation or population probability.
- The tutor avoids answer leakage and records its policy/model tier.
- A low-cost model output cannot affect learning without its required verifier.

Evidence:

- policy decision ID: `<DECISION_ID>`
- model routing reason/tier: `<ROUTING_EVIDENCE>`
- verifier result: `<VERIFIER_RESULT>`
- teaching intervention ID/version: `<INTERVENTION>`

## Scene 4 — independent transfer and KT update (90 seconds)

Complete an isomorphic item without hints. Open the before/after state diff.

Expected behavior:

- Hinted work is not counted as independent transfer.
- The mastery delta links to exactly the triggering evidence.
- BKT/PFA/IRT components, ensemble version, disagreement, and uncertainty remain inspectable.
- No review schedule is claimed in P0.1; that independent store is P0.2.

Evidence:

- verification attempt ID: `<ATTEMPT_ID>`
- intervention outcome: `<TRUE_FALSE_OR_INCONCLUSIVE>`
- mastery before/after: `<VALUES>`
- formula/policy version: `<VERSION>`
- scheduled review: `unavailable in P0.1`

## Scene 5 — trace and replay evidence (90 seconds)

Open the local trace/replay API or release JSON and locate:

1. triggering observation;
2. policy decision and reason;
3. tool/model names and versions;
4. verifier result;
5. learner state before/after;
6. evaluation result;
7. privacy/cloud disclosure.

Replay the persisted frames and show that the hash chain verifies without
invoking a model or writing new learning evidence. There is no Agent Lab UI in
P0.1.

Evidence:

- original trace hash: `<SHA256>`
- replay trace hash: `<SHA256>`
- mutation assertion: `<RESULT>`

## Scene 6 — safe degradation (60 seconds)

Stop the sidecar or return an invalid health contract. The client must disable
the write path, show unavailable state, and never substitute demo history. As a
separate backend check, run the deterministic offline fixture and verify zero
model calls plus hash-valid replay. Item quarantine is not a P0.1 UI capability.

Evidence:

- offline fixture ID: `<CASE_ID>`
- invalid/offline UI state: `client/design-qa.md`
- unchanged state proof: `<STATE_HASH_BEFORE_AFTER>`
- cloud operation disclosure: `<NONE_OR_DISCLOSURE>`

## Scene 7 — cross-domain contract breadth (60 seconds)

Use release/CLI evidence for one Shenlun and Interview representative trajectory.
The current client does not expose those paths, so do not present this as a
cross-domain UI flow. Keep scoring evidence domain-specific and do not imply
production Shenlun source reuse.

- Shenlun trace: `<TRACE_ID>`
- Interview trace: `<TRACE_ID>`
- shared contract version: `<VERSION>`

## Future scenes — do not demo as current

- P0.2: evidence-cited Today plan and independent ReviewSchedule transitions.
- P0.3/P0.4: Study Pack and Shenlun process-coach UI.
- P1: durable jobs, Agent Lab, longitudinal KT, confirmed preference memory,
  registries, and bounded background workers.
- P2: consented analytics, eligible cohort priors, delayed retention, coach view,
  and policy replay.

## Closing claim

Use only after the release report supports it:

> This demo proves the mechanics of an auditable, local learning-agent loop on
> the listed representative fixtures. It does not yet prove population learning
> gains; those require a preregistered pilot with delayed-retention outcomes.
