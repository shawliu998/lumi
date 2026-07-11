# Lumi P0.1 client design QA

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
