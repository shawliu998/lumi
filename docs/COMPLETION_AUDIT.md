# Lumi completion audit

This is the live requirement-to-evidence audit for the local Lumi objective.
`complete` means the stated engineering scope has direct reproducible evidence;
it does not mean content release, learner usability, retention efficacy, or
production distribution has been proved.

## Current decision — smart-practice v3 Core-320 is the default

The four-module internal engineering expansion is complete. External content
release, population learning claims, and production distribution are **not
ready**. The default internal MVP is direct practice rather than a mandatory
lesson sequence. A learner selects verbal, judgment, quantitative, data
analysis, or mixed practice, enters a fixed eight-slot session, and supplies
only an answer for each scored question:

```text
start fixed 8 (early exit allowed)
→ answer a normal question
→ correct: folded explanation / continue
→ first observed error signature: one light correction / continue
→ same signature in independent evidence + material families:
     one controlled microtutorial, or one optional structured probe if ambiguous
→ unseen near transfer after 2–4 other scored questions
→ cross-session delayed validation no earlier than 24 hours
→ factual group summary → one-click next fixed-eight group;
  pending checks return inside later practice
```

A probe consumes one of the eight slots and may be skipped. An error, tutorial,
probe, or late validation event never creates a ninth slot; unfinished policy
work carries into a later session. Reading feedback, viewing a tutorial, and
answering a probe are not positive learning evidence. Error signatures are
observed option patterns; their possible causes remain withdrawable hypotheses.

The service still exposes `/v1/lessons`, the stepwise `/v1/attempts` flow, and
the v2 growth-rate package. Those contracts are retained as historical or
focused regression evidence. They are not the default learner path and must
not be cited as evidence for the Core-320 product scope.

## 2026-07-15 internal Core-320 checkpoint

| Area | Engineering status | Reproducible evidence | Open release work |
| --- | --- | --- | --- |
| Versioned four-module content | complete for internal mechanics | v1.0.1 manifest SHA-256 `854ba5e483454718408cfbf8b428881333130d2224cfd4b5db3499cd54baf117`; 320 generated QuestionVersions, 80 per module, 32 diagnostic units, 64 ordinary/near plus 16 delayed-only versions per module; answer keys remain 20/20/20/20 without a question-ID modulo leak; definition-answer verbatim leaks are 0/10; domain suite 76/76 | a human content expert must check every stem, option, key, explanation, signature mapping, and intervention before external release; rights status must also be approved |
| Fixed-eight and next-scope policy | complete for deterministic rules | `engine/hermes_practice/`; engine suite 41/41 covers eight slots, early exit, independent repetition, optional probe, near transfer, the 24-hour boundary, final-slot carry-over, replacement validation, exclusion of non-independent errors, conservative next-scope fallback, cross-session/cross-family redirect, recovery evidence and recent-question soft avoidance | simulated clocks and frozen evidence prove mechanics, not real delayed retention or recommendation benefit |
| Loopback HTTP, read models and replay | complete for deterministic local tests | service suite 43/43 covers all five scopes, scope-conflict handling, cross-process serialization, atomic persistence, interrupted recovery, semantic replay, safe projections, five GET-only report/history/wrong-question/profile/overview contracts, restart rebuild, no shadow tables and fail-closed metadata | real learner outcomes remain unmeasured; a future content version needs retained old content or an explicit migration |
| Default client path | complete for internal mechanics | module and mixed selectors; exact bank ID/version/SHA pin; final-slot probe truncation; save/close/start race guards; interrupted-session resume; factual score and wrong-question report; real empty-state wrong book and profile; conservative one-click next group; client suite 24/24 and production build pass | fresh visual/accessibility evidence could not be captured because the in-app browser binding failed; this does not block internal development but remains required before a broader learner rollout |
| Near-transfer mechanics | complete for deterministic policy | unseen, unhinted, independent selection after a 2–4 scored-item gap; late events defer instead of extending the session | needs a real learner trajectory showing that intervention and transfer feel continuous |
| Delayed validation | policy complete; real evidence missing | deterministic tests reject 23h59m and allow an independent candidate at or after 24h | no real wall-clock, cross-session learner validation has completed; no retention claim is allowed |
| Local privacy and auditability | complete for tested mechanics | loopback-only service, safe pre-answer projection, bank/scope/policy versions, reason codes, append-only trace and restart replay | a separate privacy review is still required before any future cloud boundary is enabled |
| macOS packaged app | complete for current ARM64 internal mechanics | sidecar and managed-app checks pass; the frozen runtime contains the Core-320 manifest, exposes all five scopes, starts under Tauri, and terminates cleanly | notarization, universal binaries, release signing and production distribution are not established |

The four deterministic suites currently total 184 passing tests: 76 domain, 41
policy-engine, 43 service, and 24 client tests. Client production build,
sidecar lifecycle, managed debug-app lifecycle, and external-bank
materialization checks also pass.

## Remaining external-release and research gates

| Gate | Current status | Evidence required before release |
| --- | --- | --- |
| Manifest, scoring, evidence-family and intervention contracts | engineering pass | owner-approved content/correctness review plus a recorded source and rights decision for every externally shipped asset |
| Fixed-eight direct-practice HTTP journey | deterministic pass | retain the hash-verified trajectory as a release artifact after any later content revision |
| Continuous-practice reports and next-scope decision | deterministic pass | retain the versioned read-model and recommendation evidence; do not convert descriptive profile labels into mastery or outcome claims |
| Candidate causes remain hypotheses | deterministic pass | human review of learner-visible wording and one learner trace showing either tutorial or optional-probe behavior without psychological certainty claims |
| Real near-transfer experience | not measured | needed before making an experience or learning-effect claim; not an internal breadth prerequisite |
| Real delayed validation | not completed | the same local learner returns at least 24 hours later and receives an unseen, unhinted, independent item |
| Volunteer usability | intentionally not used as an expansion gate | conduct before a broader learner rollout if product-usability evidence is needed |
| Fresh visual/accessibility QA | not recorded for this checkpoint | complete before an external learner rollout; it does not invalidate deterministic Core-320 mechanics |
| Current full desktop app | ARM64 debug mechanics pass | add signing, notarization, universal build and release-channel QA before distribution |

Automated tests may satisfy engineering mechanics, but automation may not create
or submit learner answers to satisfy the volunteer, usability, near-transfer or
real delayed-validation gates.

## Historical regression evidence

| Capability | Retained status | Correct interpretation |
| --- | --- | --- |
| 42 Xingce/Shenlun/Interview success, ambiguous and offline fixtures | retained deterministic regression | representative contracts, not a production question bank |
| `/v1/lessons` and lesson UI | retained v1 regression | the method-card/worked-example flow is not the current default product |
| `/v1/attempts/{id}/responses` | retained v1 regression | ordered probe/verification continuation, not the continuous-practice experience |
| Earlier KT and diagnosis reports | retained experimental evidence | they do not silently drive v2 categorical product states or establish population calibration |
| Earlier client screenshots | retained historical evidence | they do not prove the current Core-320 visual/accessibility experience |
| Earlier `verify_core.py` reports | retained dated regression | an old v0/v2 pass does not cover Core-320 and cannot waive current human gates |

The production Shenlun repository remains read-only, and Lumi must continue to
consume only versioned Xingce exports rather than mutable question-bank working
files. These boundaries remain release invariants.

## Claims that remain prohibited

- population learning improvement or examination-score lift;
- calibrated cohort-level or psychological cause diagnosis;
- guessing detection or speed proficiency from the current evidence;
- delayed-retention lift or causal microtutorial effectiveness;
- externally cleared content or copyright status before human review;
- notarized, universal, or production-distributed macOS readiness;
- full Xingce content coverage.
