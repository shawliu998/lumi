# Lumi v0 product specification

This is the target product specification. The verified P0.2 slice is narrower:
one visible Xingce learning path, a same-fixture review activity, per-run KT, and
an evidence-cited TodayPlan/ReviewSchedule. It does not yet provide Agent Lab,
full Shenlun/Interview practice, calibrated forgetting or cohort priors,
unseen-item transfer evidence, or population learning-effect results.

## Product statement

Lumi is a local-first macOS learning agent for Chinese civil-service exam
preparation. It unifies Xingce, Shenlun, and Interview practice, estimates why a
learner is struggling, teaches the smallest useful concept, and verifies that the
learner can transfer it independently.

The v0 is both a useful study product and an inspectable AI-system portfolio. It
must show how observations become hypotheses, how hypotheses change a learner
model, why an intervention is selected, and whether that intervention worked.

## Intended user and job

The initial user is one learner on one Mac who wants an active coach rather than
a passive question bank. The user should be able to say a goal such as “improve
data-analysis accuracy this week,” complete mixed practice, receive targeted
diagnosis, and return later to a schedule based on mastery and forgetting risk.

## v0 outcomes

1. Run a full observe → diagnose → plan → teach → probe → verify → update loop.
2. Exercise that loop on representative subtypes from every major exam module.
3. Maintain a versioned skill graph, misconception taxonomy, learner state, and
   intervention history with uncertainty and evidence.
4. Use cohort/common-error statistics as a cold-start prior while allowing the
   learner's evidence to dominate with experience.
5. Expose an Agent Lab where a reviewer can inspect trajectories, tool calls,
   state deltas, model disagreement, and evaluation results.
6. Keep practice data and core learner state available offline on macOS.

## Core experience

### Today

Lumi proposes a short plan with a reason for each activity, expected duration,
and an explicit success criterion. The learner can accept, edit, or defer it.

### Practice workspace

The workspace records answer, duration, answer changes, confidence, hints,
scratch work where available, and domain-specific evidence. It supports objective
Xingce items, long-form Shenlun responses, and recorded/transcribed Interview
responses without forcing them into one scoring scheme.

For the current complete-bank Xingce access slice, discovery has three ordinary
study-software entry modes over one checksum-bound local export:

1. **套卷练习** — browse 1,054 source papers, filter by year, region label and
   exam type, then open the integrity-verified ready set of one paper;
2. **按题型练习** — choose one of six classified modules or the explicit
   unclassified group;
3. **按知识点练习** — choose one of 30 released subtype facets that has ready
   content.

All three modes may also combine year and region-label filters. They share
the same answer-redacted detail and post-submission scoring contract; none is a
second copy of the bank. The current export exposes 77,695 ready records, of
which 68,321 are practiceable with the installed offline asset pack. Another
9,374 remain resource-gated and 484 records remain quarantined. Of the ready
records, 28,569 map to a non-empty released subtype and 49,126 remain honestly
unclassified. The all-status source totals are 28,821 and 49,358 respectively;
review-quarantined records never enter product discovery.

This is a content-access and practice-mechanics release. The “知识点” label is
the reviewed subtype browse facet, not a claim of fine-grained skill inference.
Full-bank practice does not write KT, confirm a misconception, or schedule
Today/Review. Of the 1,054 papers, 925 have all currently collected records in
ready state and 129 exclude one or more review records; this does not prove
official-paper completeness. Nine papers without a unique source order remain
visible in the directory but are closed to whole-paper mode. No
human learning effect, exhaustive classification, public asset redistribution,
or complete-paper guarantee follows from these counts.

### Tutor

The tutor prefers diagnostic questions and graduated hints over answer dumping.
It states uncertainty when the evidence cannot separate causes. A short lesson is
followed by an isomorphic probe, a transfer item, or a scheduled delayed review.

### Skill map and error dossier

The learner can inspect mastery range, evidence count, forgetting risk,
prerequisites, suspected misconceptions, supporting observations, and past
verification outcomes. The UI distinguishes observed facts from inferences.

### Agent Lab

The lab shows the agent plan, tool calls, structured outputs, guardrail decisions,
KT state changes, latency, model/provider, and reward/evaluation signals. A run is
replayable from captured inputs without silently mutating learner state.

## Agent behavior contract

Lumi operates with bounded autonomy:

- It may choose exercises, ask diagnostic questions, generate explanations,
  schedule local reviews, and update evidence-backed learner state.
- It must request confirmation before deleting learning data, exporting private
  records, sending content to a cloud provider, or changing global study goals.
- It must never represent a probabilistic error cause as a fact.
- It must not increase mastery only because the learner read an explanation;
  mastery requires independent evidence.
- It must disclose when content, scoring, or verification is model-generated.

## Representative adaptive-loop v0 coverage

Coverage is breadth-first for loop validation, not full-catalog completion:

- Xingce: one subtype each from verbal, judgment, quantitative, data analysis,
  and common-knowledge/political-theory modules.
- Shenlun: summarization, comprehensive analysis, recommendations, official
  writing, and essay samples.
- Interview: comprehensive analysis, organization/planning, interpersonal, and
  emergency-response samples.

Each sample path must produce domain evidence, at least one diagnosis hypothesis,
a teaching decision, a verification event, and an auditable learner-state update.

## Non-goals for v0

- Blind migration or public redistribution of mutable/raw question-bank assets;
  product resources require a versioned, checksum-bound, rights-scoped export.
- Production multi-user accounts, social features, or cloud sync.
- Autonomous high-stakes scoring claims.
- Training a large sequence KT model before sufficient real trajectories exist.
- Video posture analysis; interview audio/transcript and rubric evidence are
  sufficient for the initial loop.
- Modifying or deploying the shared Shenlun production repository.

## Success signals

- All representative paths pass the functional gates in `EVALUATION.md`.
- A reviewer can explain any recommendation from recorded evidence and policy.
- Diagnosis calibration improves after a confirming probe.
- Immediate independent transfer and delayed retention exceed a no-personalized-
  intervention baseline in offline replay or controlled pilot data.
- The app remains useful when cloud models are unavailable, with reduced but
  clearly described capability.
