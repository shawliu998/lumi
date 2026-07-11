# Lumi P0.2 client design QA

## P0.2 final contract gate — 2026-07-11

This section supersedes the P0.1 capability conclusions below while retaining
their hashes for the existing artifact gate. All P0.2 writes remain confined to
`client/`; the browser used the real `0.2.0` SidecarApplication and real SQLite
storage. Only the calendar date came from the explicit QA-only state harness in
`qa/sidecar_clock_harness.py`; production ignores `?qa-date=`.

### Final contract and truth boundaries

- Overview reads only real TodayPlan and ReviewSchedule data. Before creation it
  says `今天尚未生成计划`; a created plan with no evidence is honestly empty.
- `no_pending_review_tasks` is a separate empty state: `当前没有待处理复习`.
  The captured real response had one eligible/recent evidence item, all schedule
  tasks completed, and `overdue_catch_up_count=0`; it was not described as a
  workload guardrail block.
- Activity references require the exact
  `novelty_status=same_fixture_retest_not_novel_item`. 今日计划 and Report both say
  `同题组独立复测` and `不构成未见平行题上的迁移验证`.
- Task and nested schedule-window contracts require `policy_offset_days`,
  `base_due_on`, `initial_due_on`, and `scheduling_adjustment`. Legacy
  `base_offset_days` and `applied_offset_days` are rejected. An
  `overdue_catch_up` is labeled as a missed fixed window and overdue catch-up,
  never as an actual +1/+3 execution date.
- Workload basis requires nonnegative `eligible_evidence_count`,
  `recent_evidence_count`, and `overdue_catch_up_count`.
  `max_non_accepted_tasks` 只限制今日计划中尚未接受的任务数量；已接受任务
  全部优先展示且不占用该上限。
  Candidates persist into the independent ReviewSchedule. The former
  `max_new_tasks` key is rejected by the exact-key adapter.
- Skip preserves the task in ReviewSchedule for fair rotation across later
  study days. Postpone dates are only the earliest restored due/rotation-entry
  date; copy explicitly preserves budget, fair-rotation, and accepted-commitment
  constraints and promises no same-day display.
- Only `availability=launchable` plus the current growth-rate fixture enables
  launch. User-marked completion is explicitly not learning-effect evidence and
  does not update KT. ReviewSchedule remains independent from `技能证据`.
- Create and task commands use opaque Web Crypto randomness. The ID alphabet is
  intentionally letter-only after the `c_` prefix so Web Crypto output cannot
  accidentally resemble a phone, national ID, token prefix, timestamp, task,
  plan, or action name rejected by the public-identifier boundary.

### Final adversarial-audit closure

- New persisted learning identifiers use one closed client profile module:
  run IDs are exactly `r_` plus 40 `A–P` characters and assistance/plan command
  IDs are exactly `c_` plus 40 `A–P` characters. Each value encodes 20 bytes
  from `crypto.getRandomValues`. There is no timestamp, `Math.random`, UUID, or
  fallback path. UUIDs, semantic strings, wrong prefixes, length deviations,
  characters outside `A–P`, and common token-shaped values are rejected.
  Request IDs remain transport-only and are outside this persisted identifier
  profile.
- TodayPlan/ReviewSchedule evidence defaults to strict Chinese labels:
  `独立验证结果`, `首答评分`, `本轮完成记录`, and `候选错因证据`. An unknown
  kind/semantic pair becomes the non-interpretive `记录证据`. Raw semantic,
  event-kind, and JSON-pointer values are no longer used as the primary learner
  copy.
- Every evidence row uses a default-closed native `details` disclosure titled
  `查看证据详情`. Opening it reveals the recorded run ID, event sequence/type,
  SHA-256 evidence hash, and JSON pointer. This preserves auditability without
  presenting a debug panel by default. Existing historical run IDs were not
  rewritten, and no student answer was submitted for this audit.
- Readability remediation raises planning notice body to 9px, task reason to
  9.5px, task definitions to 9px, evidence labels to 9.5px, report note to 10px,
  ReviewSchedule rows to 9.5px, table headers/reasons to 9px, and schedule-window
  supporting copy to 8.5px. The shell, radii, borders, neutral surfaces, violet
  selection, and density remain aligned to the Khanmigo source.

Browser DOM evidence at `1280 × 720`: task evidence `details=3`, `open=0`,
labels were exactly the three mapped Chinese labels; report evidence
`details=6`, `open=0`; `documentElement.scrollWidth=innerWidth=1280`. Opening
one row yielded exactly `运行编号 / 事件序号 / 事件类型 / 证据哈希 / JSON 指针`.
At `640 × 720`, task and report content measured
`scrollWidth=clientWidth=560`, while page width stayed 640. Task content used
vertical scrolling (`scrollHeight=852`, `clientHeight=647`); report content was
`664/647`. Console warning/error logs were `[]`.

### Real browser path and state evidence

The accepted fresh database was `/tmp/lumi-p02-sol-final-v2.sqlite3`. It was
created after the final novelty contract landed so no client fixture or adapter
shim was involved.

1. Connected empty: zero runs, zero schedule tasks, no TodayPlan; Overview
   displayed `今天尚未生成计划`.
2. Created an empty plan with no evidence. The response remained empty and no
   demo task appeared.
3. Completed the real first-answer → probe → targeted teaching → independent
   verification path. Run `mac-mrgb60no-3mhknr` completed with 15 events and 15
   replay frames; all candidate causes remained `候选 / 未确认` without
   probabilities.
4. On the injected +3 date, creating 今日计划 generated one real delayed-retention
   task and one persisted ReviewSchedule item. 今日计划 showed every contract field,
   three structured event refs, the fixed window, fair-rotation consequence,
   and the same-fixture retest limit.
5. Report → `复习记录` displayed the same independent schedule task, evidence
   refs, and novelty limit without writing it as KT.
6. With Sidecar date advanced past the visible plan, accepting the old task
   returned real `409 historical_plan_read_only`. UI showed a restrained conflict
   state and re-read instead of treating the write as success.
   A stale-clock create for an uncreated older date also exercised the same
   refresh branch through the current process's `409 plan_date_mismatch`.
   Deterministic adapter/UI regression additionally classifies the newer
   create-side `historical_plan_read_only` code as that same recoverable conflict.
7. Accepted and user-marked the sole task complete. The next plan returned
   `status=empty`, `empty_reason=no_pending_review_tasks`,
   `eligible_evidence_count=1`, `recent_evidence_count=1`, and
   `overdue_catch_up_count=0`.
8. Stopping the service produced the offline fail-closed state. The QA-only
   `qa/sidecar_error_harness.py` then kept health/report connected while returning
   HTTP 500 for planning, producing the separate error state. Neither state used
   cached/demo planning data.
9. A second real completed run (`mac-mrgbtft2-bemhcj`, 15 events / 15 frames)
   produced another delayed-retention task. The task was accepted on 2026-07-19
   and carried into the next local study date as an accepted commitment.
10. On 2026-07-20, create with a 5-minute budget returned real HTTP 409
    `budget_below_accepted_commitment`. DOM retained one create form, preserved
    the input value `5`, showed zero task cards, and exposed the exact error code
    through `data-code`. A direct GET returned 404 `schedule_not_found`, proving
    the rejected create made no TodayPlan write.
11. The same visible form was changed to 60 minutes and resubmitted. Creation
    succeeded with one task in state `accepted`. The raw basis contained
    `max_non_accepted_tasks=3`, no legacy workload-limit key, one accepted task,
    and zero non-accepted tasks. UI explicitly states that all accepted tasks are
    shown first and only remaining non-accepted tasks consume the limit.

At `640 × 720`, `documentElement.scrollWidth=640`; the 今日计划 screen measured
`scrollWidth=560`, `clientWidth=560`, `scrollHeight=771`, and
`clientHeight=647`, proving vertical scrolling without page-level horizontal
overflow. At `1280 × 720`, the final empty screen measured
`documentElement.scrollWidth=1280` and screen `scrollWidth=clientWidth=732`.
The final budget-retry success state also measured `innerWidth=1280`,
`documentElement.scrollWidth=1280`, and screen
`scrollWidth=clientWidth=732`; connected console warning/error logs were `[]`.

### P0.2 inspected PNG evidence

All files below are RGB PNGs opened and inspected. The comparisons place
the supplied Khanmigo reference and exact `900 × 526` Lumi app crop in one
`1816 × 562` image before judging layout, density, borders, typography, and
restrained violet selection.

- `qa/p02-overview-connected-not-created-1280x720.png` — `8446cd16c0175669ba1ffb7b4aed7bb740750ba837e3b73dce603f3e4d31fe92`
- `qa/p02-practice-final-contract-1280x720.png` — `0e99b462521349942b344c19ed9f7adee3b2670aa6ee444cb01e0b48df66d92e`
- `qa/p02-practice-evidence-collapsed-1280x720.png` — `7efab3cb9b354121722f31aa34e26b15673a7990f7aa8f1432935ea704d03806`
- `qa/p02-practice-evidence-expanded-1280x720.png` — `01746c13d5cb6f5a956120d33d347474155644fd596624602591d1287b88b979`
- `qa/p02-report-review-schedule-1280x720.png` — `3bb17d786f73b2ad13cdc2a1d82ee941cc9fe9d7b5ccce86c442e516095885e3`
- `qa/p02-historical-plan-conflict-1280x720.png` — `90cd288f0476137fc0a6880bbf05767c9b3c17cecb285c1c36e749c6db21ac34`
- `qa/p02-no-pending-review-1280x720.png` — `872533e3cbff49627bcc5967c8b4e34ead70aea526fe3d02d8b925dc3a6abd99`
- `qa/p02-offline-fail-closed-1280x720.png` — `5d1e74d08a5406c6cf6a9eb99a1a6fe41a8b20ffd7bbf731d59ad3082083adfc`
- `qa/p02-error-500-fail-closed-1280x720.png` — `5e7ffde72761118006578783c995feebddc48a019aaf806f28d3ed9b59ad22a0`
- `qa/p02-practice-narrow-640x720.png` — `d93c4f4cc98855223a97a7346277ab5ef81d32a0a217de855097fd07cf6a4787`
- `qa/p02-report-readable-narrow-640x720.png` — `1747102b09b628713d3d3ab33782c835a2e7ae72463e98617d43771ac0bdd298`
- `qa/p02-compare-overview-khanmigo.png` — `11a426974f1cd2ef90d66f2d8deebedad9c67ab294d92a4ba20803b64a0cff0c`
- `qa/p02-compare-practice-khanmigo.png` — `b153a738687297e9c2f7469d6b2d5620b95b4ba356dc14b6b15e3a00f5d1b35b`
- `qa/p02-compare-report-khanmigo.png` — `f86dd14dbc1198fe57413f8d55da76e78a6edf454151390a29b98651985cc528`
- `qa/p02-budget-below-accepted-retry-1280x720.png` — `ec8fe5aafbddd37e6d3ebece2dfc0a131c47f2c1a3e02aaff6f01f4f815676c7`
- `qa/p02-budget-retry-success-1280x720.png` — `5535f93974297ced1530307bb537c4a1cc982e00d57690eac0c27e7421c816b4`
- `qa/p02-compare-budget-conflict-khanmigo.png` — `eda0507315dc27276c45fb8b69abbc343e5ac1b0d8c1362d3a03e4e37d571209`

Visible comparison result: the existing Khanmigo-like shell proportions,
single-pixel dividers, compact system typography, neutral canvas, modest corner
radii, and information density remain continuous. No gradient, glow, emoji
icon, avatar assistant, floating chat bubble, decorative hero card, or invented
metric was introduced.

Adversarial readability comparison history: the earlier P2 audit found
ReviewSchedule rows at 7.5px and report notes at 8.5px, plus primary evidence
rendered as raw service enums. The implementation raised the measured text
sizes above, replaced primary enums with strict Chinese labels, added collapsed
technical disclosures, recaptured desktop/narrow states, and regenerated all
affected side-by-side comparisons. Post-fix inspection found no remaining
actionable P0/P1/P2 typography, spacing, color-token, icon/image, copy, or
responsive-layout difference. The Khanmigo source has no analogous evidence
disclosure, so the dedicated collapsed/expanded implementation captures are the
focused-region evidence rather than a false state-to-state source comparison.

Budget-conflict comparison findings: no actionable P0/P1/P2 differences. The
source has no analogous accepted-commitment error, so the combined image is used
for shell and density comparison rather than false state-level fidelity. A
focused source-region comparison was not useful for that reason; the full-size
implementation capture keeps the alert and editable form text legible.

- Typography: system-family hierarchy, compact weights, line height, and small
  control labels remain consistent with the existing source-derived shell.
- Spacing/layout: the alert occupies one restrained row; the three-field form
  keeps the established grid, border, radius, and vertical rhythm without
  displacing persistent navigation.
- Color/tokens: neutral surfaces, one-pixel borders, violet primary action, and
  muted conflict icon preserve existing tokens; no warning glow or heavy danger
  treatment was introduced.
- Image/icon fidelity: no new raster asset, decorative mark, emoji, or custom
  drawing was added; the state reuses the existing Phosphor information icon.
- Copy: the alert says to increase available time, confirms accepted priority
  and zero write, and leaves the form visibly retryable without promising that
  a low-budget plan exists.

### Closed backend compatibility boundary

An earlier temporary QA database and Sidecar process exposed two pre-final
boundaries: stored ReviewSchedule rows lacked `novelty_status` and the current
workload-limit key, and stale-clock create returned `plan_date_mismatch`. Those
observations are retained as iteration history, not current release blockers.
The final backend now migrates the legacy novelty/workload projections with
auditable events, invalidates obsolete command receipts, and exposes the newer
create-side `historical_plan_read_only` guard. Runtime, HTTP, and release-eval
regressions cover both migrations and the two stale-clock response paths. The
client still recognizes both conflict codes and fails closed if required truth
fields are absent; it never invents a migration result.

### Verification

- `npm test`: 39 deterministic client tests pass, including exact-key attacks,
  novelty/fair-rotation copy regression, opaque ID generation, no-pending empty
  reason, workload-key rejection, closed ID profiles, evidence mapping/detail
  disclosure, readable P0.2 font floors, 409-only budget retry classification,
  and create/task conflict classification.
- `npm run build`: Vite production build passes; 4,577 modules transformed.
- `git diff --check -- client`: passes.

P0.2 final result: passed; the earlier compatibility boundary above is closed by
the final backend migration and stale-clock gates.

## Retained P0.1 artifact-gate record

## Scope and visual source

This QA covers only `/Users/a1-6/Documents/peikao/client`. It does not claim
backend, desktop-shell, evaluation, or production-repository changes.

The three supplied Khanmigo screens remain the visual source of truth:

- Overview: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-9e126b71-77af-418b-94da-e3a343119661.png`
- Tools: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-4bc3f416-174d-498a-95e6-7c0838df466a.png`
- Reports: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-b3bb8c34-cfad-4b7c-8d1f-bf58dc5928d8.png`

The current client keeps the established Lumi shell: compact macOS system
type, restrained violet selection, one-pixel neutral borders, white work area,
light-blue desktop canvas, Phosphor icons, and dense table/list anatomy. It adds
no gradient, glow, decorative card stack, invented illustration, or generic AI
marketing copy.

## Final inspected PNG evidence

Only the following current artifacts are handoff evidence:

- `qa/p01-authentic-overview-empty-real-1280x720.png`
  - real `0.2.0` sidecar with a fresh empty database
  - neutral `本机学习者`, `训练范围未设置`, and `考试目标未设置`
  - zero runs, zero report skills, and no generated task rows
- `qa/p01-authentic-overview-connected-real-1280x720.png`
  - the same real sidecar after one completed run
  - exactly one run and one report skill from the service
  - task orchestration remains explicitly unavailable
- `qa/p01-authentic-report-connected-real-1280x720.png`
  - real `trace-summary-v1` response after the completed run
  - `技能证据`, explicit verification counts, and completed-run count
  - no client-derived longitudinal mastery category
- `qa/p01-authentic-probe-assistance-real-1280x720.png`
  - current real `0.2.0` `awaiting_probe` run after one persisted assistance write
  - visible `1 / 6` ladder, returned `retry` content, policy version, and
    `工程策略未校准` evidence label
- `qa/p01-authentic-dossier-probe-real-1280x720.png`
  - the same current real run with the inspector returned to the dossier top
  - first-answer observation, ranked candidates, and repeated `尚未确认` copy
- `qa/p01-authentic-independent-verification-real-1280x720.png`
  - the same current real run after submitting probe text `120÷100`
  - targeted teaching, explicit no-assistance boundary, independent question,
    selected answer/confidence, and enabled submit action
- `qa/p01-authentic-comparison-overview-connected.png`
  - supplied overview source and current `900 × 526` app crop side by side
- `qa/p01-authentic-comparison-report-connected.png`
  - supplied report source and current `900 × 526` app crop side by side
- `qa/p01-authentic-comparison-tools-probe-assistance.png`
  - supplied Khanmigo tools source and current probe-assistance crop side by side
- `qa/p01-authentic-comparison-tools-dossier-probe.png`
  - supplied Khanmigo tools source and current dossier crop side by side
- `qa/p01-authentic-comparison-tools-independent-verification.png`
  - supplied Khanmigo tools source and current independent-verification crop
    side by side

All eleven files were opened and visually inspected. They are true 8-bit RGB PNG
files. SHA-256:

- empty overview: `f03e6eeac188c81a754a5dae9fbd26e91cb73d5346a4b8fb830f0e5d89ecde5a`
- connected overview: `9522b0710a49308d10d8ba164a7a6179b9c2a20eecc5b5fb4e44d7823d6e4c17`
- connected report: `a0b5635f937d3ca043d5be27e24c8bf761288f86a05e09149b443546f42ed8df`
- probe assistance: `c5589eb345b5da30525c48bb3b65352a0053b438f523b0ae179859973667e073`
- dossier at probe: `ff41d5ccabd6f9f2013b4ec43d0186cf7cce2503d7d5098f1992fdfc9f2b2efb`
- independent verification: `0e64c969db81b6d8cae28d993155ee90f9d0072e5cd135d56c6bd85dde06bd1b`
- overview comparison: `37c9a14fc596e163fedf931cd00ef2bc279af8ce6518d698637fb67ad88973b0`
- report comparison: `a0faa0759a5f65d54f9ce196cbed044bc9b6ae1846b39f0e52caca44805e49ad`
- tools/assistance comparison: `83feee7225414b2312db69701edf690b20addc0ef67cc6615312516ec3e54f29`
- tools/dossier comparison: `fff5ed58d816d67f0fd0bcc5e50d8b1cd77fa404e2a1f348e048601f60a896c4`
- tools/verification comparison: `4ca7249234acdfabcc2ca1d2ac68d5cd753f9d242b1c0441947533dc3171f0f3`

## Truthfulness gates

### Identity, profile, dates, and overview

- No profile API or confirmed user settings are available in P0.1. The sidebar
  and profile utility therefore use `本机学习者` and do not imply a saved personal
  dossier.
- The top scope reads `训练范围未设置`; the overview reads `考试目标未设置`.
- The displayed calendar date is generated from the local current date. No
  fixed study date or regional exam target remains in product copy.
- Overview counts come only from `/v1/health` and `/v1/skills/report`.
- With an empty real sidecar, the overview shows a connected empty state. With
  no service, it shows unavailable counts. It never substitutes local fixtures,
  generated history, or a generated daily plan.
- Task orchestration has no current API and is labeled unavailable instead of
  being inferred from report items.

### Tool entry and write boundary

- Only `错因辨析` is enabled, and only while the real `0.2.0` loopback sidecar
  is connected.
- It maps to the single supported fixture
  `xingce.data-analysis.growth-rate.synthetic-01`.
- The remaining tool cards are disabled and labeled `分阶段开放`; clicking them
  cannot create a run or open the growth fixture.
- Initial answer and independent verification expose no assistance action.
- Probe assistance writes only the strict service body: `phase`,
  `expected_version`, `expected_state`, `prompt_instance_id`, `action`,
  `elapsed_time_seconds`, and `command_id`. The client never chooses a level,
  evidence weight, or independence claim.

### Dossier and continuation boundary

- The adapter accepts only `unconfirmed_hypothesis`,
  `supported_hypothesis`, and `refuted_hypothesis`.
- `confirmed`, missing, and unknown claim statuses fail closed in both API and
  adapter tests.
- Supported and refuted candidates still display `尚未确认` and keep supporting
  and refuting event references separate.
- Cohort evidence is always shown as unavailable and is never converted into a
  peer error rate or popularity claim.
- `state`, `learning_status`, and `next_action` are parsed as one continuation
  contract. Unknown or mismatched combinations fail closed.
- `processing_probe` and `processing_verification` remove the old prompt and all
  continuation inputs. Their only actionable recovery is `重新开始本题`, which
  clears the client run and creates a fresh run only after a new initial answer.

Processing evidence used a strict client-side contract harness, not a persisted
run claim. DOM assertions recorded:

- `data-service-state="processing_probe"`
- `data-learning-status="processing_probe_response"`
- `data-next-action="restart_attempt_after_processing_failure"`
- old prompt absent
- probe submit button count `0`
- assistance ladder count `0`
- restart action count `1`

After the restart action, the DOM returned to the initial-answer stage with no
processing dossier or stale prompt.

### Report semantics

- `/v1/skills/report` is treated as `trace-summary-v1`.
- The main tab is `技能证据`, not a longitudinal mastery view.
- Rows show only service-backed `run_count`, `verified_transfers`, and
  `failed_or_inconclusive`.
- `latest_mastery`, `latest_uncertainty`, and `average_mastery_delta` do not
  drive categories, colors, thresholds, or stability copy.
- When expanded, those raw fields are explicitly labeled as recent single-run
  trace evidence, not longitudinal mastery.
- Missing `null`, `undefined`, or empty raw fields remain unavailable; they are
  not converted into fabricated zero values.

## Real sidecar browser path

Browser QA ran at `http://127.0.0.1:1420/` against the real local sidecar at
`http://127.0.0.1:8765` using a fresh database.

Observed path:

1. Opened the only enabled `错因辨析` card.
2. Submitted an incorrect initial answer with high confidence.
3. Received a real `awaiting_probe` dossier with three ranked, unconfirmed
   hypotheses and an event-sourced targeted prompt.
4. Requested the real first help level. The service returned ordinal `1`,
   action `retry`, policy `assistance-evidence-policy.v1`, and the visible
   `工程策略未校准` calibration label.
5. Submitted probe text `120÷100`. The ratio candidate became supported and the
   other returned candidates became refuted; every candidate remained a
   hypothesis and visibly unconfirmed.
6. Entered independent verification. Assistance control count was `0`.
7. Submitted the correct independent answer. The run completed with verified
   trace/replay and the sidecar health count advanced from zero to one.
8. Opened the report. It showed one completed run, one skill, one independent
   verification pass, and zero failed-or-inconclusive verifications.

The expanded report DOM states:

- tab `技能证据`
- summary `1 个有记录模块 · 1 个技能 · 1 次已完成本机运行`
- evidence `1 次通过 · 0 次未通过或不确定`
- raw value disclaimer `均为最近单次 run 证据，非纵向掌握`

### Current core-flow visual recapture

The final visual gate used a fresh browser tab against the still-running real
`0.2.0` sidecar. The database already contained the one completed QA run above;
the capture then created a new real run and stopped at independent verification
after saving the requested visual states. It did not use a demo submission path
or a client fixture screenshot.

The accepted core-flow sequence is:

1. `awaiting_probe` after an incorrect high-confidence `D` answer.
2. Persisted ordinal-one assistance with server action `retry`, policy
   `assistance-evidence-policy.v1`, and visible `1 / 6` progression.
3. The same event-sourced dossier at its top, showing the observed answer,
   candidate ranking, unavailable cohort evidence, and no confirmed cause.
4. `awaiting_verification` after `120÷100`, with supported/refuted evidence
   still labeled `尚未确认`; the independent-verification form contains no help
   control and remains the only next write.

All three full-state captures use the same `1280 × 720` viewport. Each
comparison uses the exact `900 × 526` Lumi app crop next to the Khanmigo tools
source normalized to `900 × 526`. The comparison is for shell, density,
typography, divider, card-grid, overlay, and restrained-accent continuity; the
Khanmigo source has no equivalent learning-dossier content.

## Availability, error, conflict, and overflow

- Empty connected: real sidecar, fresh database, no runs or report items.
- Connected: real sidecar, one completed run and one report item.
- Offline: service stopped; write CTA disabled, counts unavailable, no fallback.
- Invalid contract: strict health harness returned an unsupported contract; UI
  displayed `本机服务响应异常 / 训练不可用` and exposed no write path.
- Conflict: stale optimistic version produced `409 stale_version`; UI explained
  duplicate-write prevention and required restart.
- Processing: strict state harness removed the consumed prompt and required a
  fresh run as documented above.

Console warning/error logs were `[]` for connected, empty, offline, invalid
contract, and processing checks. At the final `1280 × 720` browser viewport,
connected report and overview measured `innerWidth=1280` and
`documentElement.scrollWidth=1280`. Inspector content remained vertical-scroll
only, with no horizontal overflow or clipped persistent action.

## Deterministic verification

- `npm test -- --run`: 16 tests pass, including missing-field and fabricated-
  cohort contract attacks.
- `npm run build`: Vite production build passes; 4,573 modules transformed.
- Root reported the broader evaluation gates separately: P0.1 eval `15/15`,
  Domains `25/25`, Integration `19/19`, Service `31/31`. This document does not
  claim ownership of those non-client suites.

The client source scan must remain empty for fabricated profile and legacy
fixture symbols named in the root task. The only literal `confirmed` cases are
malicious contract tests and rejected statuses, never accepted UI states.

## Screenshot capture note

The in-app capture compositor intermittently produced black tiles. Such files
were discarded. The dossier and independent-verification states were retried
once in a clean tab and accepted only after the full canvas rendered. Each final
PNG listed above came from a clean capture, was
re-encoded as RGB PNG, opened, and compared against the supplied visual source.
Strict processing evidence is DOM evidence only and is explicitly labeled as a
contract harness rather than persisted-state proof.

## Current result

No open client P0.1 truthfulness or visual blocker remains in the tested desktop
scope. Broader scheduling, profile, target-setting, longitudinal knowledge
tracking, and cohort products remain unavailable and are not simulated.

final result: passed
