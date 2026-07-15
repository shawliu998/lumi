# Lumi Mac 客户端视觉与交互 QA

> Status note: this is a dated v1 visual/contract baseline plus a 2026-07-14
> growth-rate lesson delta. Its screenshots and mandatory continuation evidence
> are historical and must not be presented as visual QA for the current
> Core-320 direct-practice UI. The owner removed volunteer acceptance as an
> internal expansion prerequisite; usability and fresh visual/accessibility
> records remain separate evidence before a broader learner rollout.

## 2026-07-15 full-window redesign status

- Current implementation uses a real resizable Tauri content area, a 216/64px
  sidebar, three primary destinations, a single-action home, a fixed-eight
  focus workspace, and source-backed learning records. The historical 900 × 526
  shell described below is no longer the current implementation.
- The old `smart-practice.css` was removed and the old global stylesheet was
  reduced to a small reset. Current semantic tokens and component rules live in
  `src/styles/tokens.css` and `src/styles/redesign.css`.
- Current deterministic evidence: 30 client tests pass, the Vite production
  build and debug `Lumi.app` bundle pass, desktop configuration/managed-sidecar checks pass, and
  `python3 scripts/verify_core.py` passes all 13 gates.
- Fresh screenshots are still pending. The required in-app Browser runtime
  failed during initialization with `Cannot redefine property: process`; the
  build did not silently switch to an unapproved Playwright CLI. Therefore all
  images under `qa/` remain explicitly classified as historical before-state
  evidence, not current after-state QA.
- The current Core-320 safe question contract exposes `prompt/options` but no
  versioned material or chart projection. Long prompts use the tested scrollable
  single-column DOM; a claimed data-analysis split view awaits a real contract,
  fixture, and visual evidence.

## 2026-07-14 growth-rate lesson delta

- Added a full-window lesson workspace with the confirmed learner-visible flow:
  method card/worked example → answer → immediate feedback or optional hint →
  next item. There is no mandatory Feynman response or numbered diagnosis flow.
- Cause probabilities, diagnosis decisions, and numeric KT deltas remain in the
  local trace but were removed from the primary learner UI.
- The client consumes safe `/v1/lessons` projections and sends every scored
  response through the existing attempt/continuation API. Completion requires
  four scored answers and two consecutive verified transfers; reading alone is
  inert.
- At that checkpoint, `npm test` covered six policy/state tests. The current
  Core-320 client suite has 22 passing tests and its production build passes;
  this dated section still does not supply current screenshots.
- Fresh visual and interaction evidence is still pending. The in-app Browser
  runtime failed during setup with an environment-level process binding
  conflict, so no screenshot from this build is claimed or substituted with a
  different browser automation surface.

## Historical v1 comparison target

- Source visual truth:
  - Overview: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-9e126b71-77af-418b-94da-e3a343119661.png`
  - Tools: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-4bc3f416-174d-498a-95e6-7c0838df466a.png`
  - Reports: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-b3bb8c34-cfad-4b7c-8d1f-bf58dc5928d8.png`
- Implementation screenshots:
  - `qa/overview-1440x1024.png`
  - `qa/tools-1440x1024.png`
  - `qa/reports-1440x1024.png`
- Viewport: `1440 × 1024` CSS pixels.
- State: desktop, expanded sidebar, default light appearance; overview default state, tools “全部” state, reports “技能掌握 / 行测 / 全部模块 / 全部判断” state.
- Final shell: native `900 × 526` app window centered on the blue desktop canvas. No `zoom` and no whole-window `transform: scale` remain.

## Full-view comparison evidence

The left side of each comparison is the supplied reference; the right side is the approved pre-rename client baseline. The current Lumi build keeps the same implementation shell, normalized to the same `900 × 526` crop; the name-only change is verified separately below.

- `qa/comparison-overview-full.png`
- `qa/comparison-tools-full.png`
- `qa/comparison-reports-full.png`

The comparisons confirm the shared 166px sidebar, 47px top bar where present, 19–20px content inset, white work area, light-blue desktop frame, compact section rhythm, restrained violet selection color, border hierarchy, three-column tool grid, and dense skill table.

## Focused comparison evidence

- Overview search, actions, subject cards, and assignment table: `qa/comparison-overview-focus.png`
- Tool filters, search, card anatomy, and grid rhythm: `qa/comparison-tools-focus.png`
- Report tabs, filters, group/header order, skill rows, and mastery tracks: `qa/comparison-reports-focus.png`

Focused review was required because the full-view composites are too small to judge Chinese system-font weight, one-pixel borders, row order, and compact control spacing reliably.

## Required fidelity surfaces

### Fonts and typography

- Uses the macOS system stack: `-apple-system`, `BlinkMacSystemFont`, `SF Pro Text`, `PingFang SC`, `Helvetica Neue`, Arial, sans-serif.
- Page titles, section titles, navigation, table headers, secondary labels, and captions follow the reference’s compact hierarchy; no display font, marketing-size hero text, artificial tracking, or synthetic font style is used.
- Chinese copy was checked for wrapping and truncation at the final viewport. Tool descriptions remain readable and course-card metadata truncates intentionally on one line.

### Spacing and layout rhythm

- App shell is `900 × 526`; sidebar `166px`; top bar `47px`; main content inset `19px`; tool grid is three columns with `19px` horizontal rhythm and `90px` cards.
- Overview uses the reference’s main/side split, compact quick actions, three subject cards, and dense table.
- Tools intentionally omits the top bar, matching its source screen.
- Reports uses the corrected sequence `group row → column header → skill rows`, matching the source anatomy.
- No hidden persistent controls, horizontal overflow, overlapping copy, or clipped primary action was observed.

### Colors and visual tokens

- Canvas `#ddf1ff`, work area `#ffffff`, primary text `#24252c`, restrained violet `#5b55f5`, neutral borders `#dedfe4`, and subtle selected backgrounds follow the reference balance.
- No gradients, glass, glow, decorative neural graphics, or layered card effects remain.
- Mastery tracks use discrete solid segments rather than an invented percentage or decorative chart.

### Image quality and asset fidelity

- The reference screens contain no required photographic or illustrative assets. Lumi therefore uses no placeholder artwork or generated decoration.
- All interface icons use the installed open-source Phosphor family. No emoji, handcrafted SVG, CSS illustration, robot, sparkle, or copied Khan Academy mark is present.
- Final handoff screenshots are genuine PNG files (`1440 × 1024`, 8-bit RGB), not JPEG payloads with a `.png` extension.

### Copy and content

- Product copy is specific and evidence-led: “最近 3 次作答有 2 次公式方向相反，暂列为待确认”, “证据不足时显示暂不判断”, and “记录保存在此 Mac”.
- Removed generic AI copy, fictional day counts, “学习闭环”, fake score percentages, unsupported predictions, and the earlier “42 条领域闭环”.
- Report totals reconcile with the rendered mock data: `3 个有记录模块 · 8 个技能 · 129 次已评分作答`.
- Today’s plan reconciles with progress: four tasks, one initially completed.

### Product brand

- The formal user-facing product name is `Lumi` in the sidebar identity, brand-button accessible name, document title, `application-name`, and page description metadata.
- `Hermes` remains only in internal adapter names, environment variables, schema versions, and the local service identity. These established technical contracts were intentionally not renamed.
- No replacement logo, placeholder mark, decorative asset, or additional visual treatment was introduced. The existing book icon, typography, spacing, and brand-row dimensions are unchanged.
- Browser DOM verification at `1440 × 1024` returned `title="Lumi 学习"`, `aria-label="Lumi 学习"`, visible brand text `Lumi`, and description `Lumi 本机学习与技能验证`.
- Name-only regression geometry remained exact: app shell `900 × 526`, sidebar `166px`, report top bar `47px`, tools cards `≈218.7 × 90`, three tool columns, and no horizontal overflow on overview, tools, or reports.

## Interaction and accessibility evidence

Browser-tested primary interactions:

1. Overview local search accepts “基期量” and shows a three-record result state.
2. Starting the “基期量” task changes the task row to “进行中” and the primary action to “继续基期量验证”.
3. Tool filtering, keyword search, favorite toggle, favorites-only view, no-result state, and clear-filter action all update correctly.
4. “错因辨析” opens a three-step flow with no fake 4/6-question selector: initial answer, targeted probe, teaching plus independent verification, then the completed result.
5. Report module/judgment filters recompute visible totals; the tested data-module result is `1 模块 / 3 技能 / 42 次作答`, and the verify-only result is `1 技能 / 12 次作答`.
6. Subject filtering exposes an honest empty state and “清除筛选” restores the full `3 / 8 / 129` view.
7. Skill groups and skill evidence details expand/collapse; learning-activity and review-record tabs render their own content.
8. Global search and sidebar collapse/expand states work.

### Local sidecar and continuation evidence

- API base uses `VITE_HERMES_API_BASE`; the fallback is `http://127.0.0.1:8765` and the adapter rejects non-loopback HTTP targets.
- Browser origin `http://127.0.0.1:1420` was tested against a temporary sidecar at `127.0.0.1:8766`.
- Startup validates `GET /v1/health` as `service=hermes-local-sidecar` and `local_only=true`, then reads `GET /v1/skills/report`.
- Initial `POST /v1/attempts` submitted the visible answer, confidence and elapsed time. The tested wrong answer entered `awaiting_probe`, `state_version=5`, with three ranked Chinese candidate labels and probabilities under “候选线索（未确认）”. No cause ID was exposed as user-facing copy.
- Probe submission used the returned optimistic version and entered `awaiting_verification`, `state_version=9`. The UI displayed the returned teaching prompt and an independent verification input; no mastery delta was shown at either pre-completion stage.
- Independent verification entered `completed`, `state_version=14`. The result showed verification passed, mastery delta `+0.247`, and a verified trace/replay of `14 events / 14 frames`.
- Direct report checks returned `skill_count=0` after both the initial answer and probe. Only after completed verification did the report return one skill with one verified transfer; the browser report then displayed `1 个技能 · 1 次本机运行` from the local service.
- A deliberate same-version conflict advanced the probe externally before the page submitted its stale version. The page received `409 stale_version`, displayed “训练状态已变化”, explained why it would not repeat the write, and returned to a clean “开始作答” state through “重新开始”.
- Offline startup displayed `本机服务未连接 / 演示数据`; an invalid health contract displayed `本机服务响应异常 / 演示数据`. Neither state silently presented demo records as local evidence.
- At `1440 × 1024`, the native app remained `900 × 526`. Probe, teaching/verification and completed panels had no horizontal overflow (`body scrollWidth = clientWidth = 309`; content width `281`). The panel header is fixed and only the body scrolls when needed.

Accessibility checks:

- Interactive filters expose `aria-pressed`; tabs expose selected state; expandable rows expose `aria-expanded`.
- Inputs and selects have accessible labels; favorite actions name both add/remove states.
- Keyboard focus indicators remain visible, state is not communicated by color alone, and reduced-motion preference disables nonessential motion.

## Build and runtime evidence

- `npm run build`: passed with Vite 6.4.2; 4,571 modules transformed.
- Browser console error/warning check after final implementation: `[]`.
- Prohibited-style scan found no gradient, whole-window `zoom`, whole-window `transform: scale`, Sparkle import, or banned AI-marketing phrases in `src` or `index.html`.
- Final integration preview used `http://127.0.0.1:1420/` with `VITE_HERMES_API_BASE=http://127.0.0.1:8766`.

## Screenshot infrastructure note

The in-app Browser capture path intermittently displayed black compositor tiles when multiple screenshots were requested in close succession. DOM snapshots, computed layout, interaction state, build output, and console state remained stable, so this was isolated to the screenshot composition/preview layer rather than the application DOM or CSS. During diagnosis, the capture API also returned JPEG payloads despite PNG filenames, which made the desktop preview path less reliable.

A later attempt to capture the completed continuation side panel closed the browser tab inside the same capture layer. Per the QA gate, no capture from that failure is retained or presented as evidence. The new states are instead evidenced by the live DOM states, real API versions and responses, computed overflow geometry, trace/replay counts, report transition, and empty console. The already approved clean true-PNG default-page captures remain the visual-regression evidence because the three default surfaces and native shell were not replaced.

Mitigation used for the final evidence:

- Removed all whole-window `zoom` and `transform: scale` rules and retained the native 900 × 526 reference shell.
- Retried each page until a complete capture was obtained.
- Re-encoded each selected handoff file as a true PNG.
- Opened and visually inspected all three final PNGs plus the full and focused side-by-side comparisons.
- Discarded the black-tile capture attempts; none is used as final evidence.

## Comparison history

### Iteration 1 — existing runnable draft

- **[P1] Major-region proportions drifted from the references.** The previous draft used a 220px sidebar, 58px top bar, and a much larger free-form app shell. It also showed the top bar on the tools page. Evidence: `qa/overview-v1.png` and the original implementation.
- **[P1] Several controls looked interactive but did nothing.** The global search redirected to tools, tool-card “打开” actions were inert, report tabs/filters did not change content, and skill rows did not expand.
- **[P1] Report and plan data did not reconcile.** The old summary said 13 skills / 142 evidence records while rendering 8 skills / 129 attempts; progress showed four tasks while the table listed three.
- **[P2] Visual language was less disciplined.** Large tool icons, redundant card actions, excessive status color, and generic AI-flavored copy weakened the educational-product tone.

Fixes: rebuilt the shared shell to the measured reference anatomy; removed the tools top bar and large card icons; implemented all named states; replaced unsupported metrics with reconcilable records; rewrote copy around observable evidence.

Post-fix evidence: `qa/overview-1440x1024.png`, `qa/tools-1440x1024.png`, `qa/reports-1440x1024.png`.

### Iteration 2 — first report comparison

- **[P2] Report table anatomy was reversed.** The implementation placed the column header before the group row; the source places the group row first.

Fix: moved the three-column header inside each expanded group, immediately after its group disclosure row.

Post-fix evidence: `qa/comparison-reports-full.png` and `qa/comparison-reports-focus.png`.

### Iteration 3 — capture artifact gate

- **[P0] Some screenshot attempts showed large black compositor regions.** This affected reviewability of the captured evidence, although DOM snapshots and live interactions remained intact.

Fix: removed whole-window scaling, selected a clean retry for each page, normalized the outputs to real PNG, and visually reopened every final artifact. The final screenshot hashes are:

  - Overview: `4c9038277301b538e14a33235eae5766153f1910dda287afbb7fcf5f2e367e9c`
  - Tools: `3d5b9feae185e3456bbe6516c68800427051ab5d8c7f80f9285743ff14ce6576`
  - Reports: `d3f3242b9d089cf868284803e5e276eb160f874a94c57dd3e947165da70dc05f`

Post-fix evidence: the three final PNG files above and their regenerated comparison composites.

## Findings

No actionable P0, P1, or P2 findings remain in the three required screens at the tested desktop viewport.

## Open questions

None for the requested scope.

## Implementation checklist

- [x] Overview, tools, and reports match the source proportions and density.
- [x] Core controls have real selected, open, empty, in-progress, and completion states.
- [x] Sidecar health/report and the answer → probe → teaching → independent verification continuation use real local contracts.
- [x] Offline, invalid-contract, optimistic-conflict and restart states are explicit and recoverable.
- [x] Copy and quantities are auditable and internally consistent.
- [x] Build passes and the browser console has no warnings or errors.
- [x] Final screenshots and focused/full comparisons are clean true-PNG evidence.

## Follow-up polish

No P3 item is required for this handoff. The fixed 900 × 526 desktop shell at 1440 × 1024 is intentional because it preserves the supplied visual truth exactly; narrower breakpoints remain implemented separately.

final result: passed

---

# Home recommendation editorial redesign QA — 2026-07-15

## Comparison target

- Source visual truth: `/Users/a1-6/.codex/generated_images/019f65cb-c8ad-7731-972f-2d04c7b655de/exec-d79d7eea-547e-4510-a5e0-278614147209.png`
- Implementation target: `http://127.0.0.1:4173/`, `.home-recommendation`
- Intended viewport: 1440 × 1024, connected overview state
- Implementation screenshot: unavailable because the in-app Browser bootstrap failed before a tab could be opened (`Cannot redefine property: process`).

## Evidence completed

- Source mock was opened and inspected before implementation.
- The selected editorial structure was implemented in `src/HomeScreen.jsx` and `src/styles/redesign.css`.
- The vertical accent rail, tinted rounded panel, and purple kicker were removed.
- A neutral numbered kicker, horizontal rule, stronger title hierarchy, semantic status color, and a flat existing primary action were added.
- `npm test`: passed, 30 / 30 tests.
- `npm run build`: passed.
- `python3 scripts/check_client_artifacts.py`: passed, including the prohibited-style scan.
- `git diff --check`: passed.

## Full-view comparison evidence

Blocked. The source mock is available, but the implementation could not be captured in the required in-app Browser at the matching viewport and state.

## Focused comparison evidence

Blocked for the same reason. The focused recommendation region cannot be visually compared from code or build output alone.

## Findings

- [P0] Required browser-rendered QA evidence is missing.
  Location: home overview, `.home-recommendation`.
  Evidence: the local server returns HTTP 200, but the in-app Browser runtime fails during bootstrap before it can open or capture the page.
  Impact: typography, spacing, wrapping, responsive behavior, and final visual fidelity cannot be honestly approved from source code alone.
  Fix: restore the in-app Browser runtime or explicitly authorize a Playwright CLI fallback, then capture 1440 × 1024 and a narrow breakpoint, compare both with the selected mock, and fix any P1/P2 drift.

## Required fidelity surfaces

- Fonts and typography: implemented from the existing SF Pro / PingFang stack; visual confirmation blocked.
- Spacing and layout rhythm: implemented as a two-column editorial grid with neutral rules; visual confirmation blocked.
- Colors and visual tokens: source uses neutral ink, green status, and a primary action; implementation maps these to existing tokens and contains no gradient; visual confirmation blocked.
- Image quality and asset fidelity: no custom image assets are present in this component; Phosphor icons are retained.
- Copy and content: existing dynamic recommendation copy and action behavior are preserved; Clock icon added to the duration label.

## Comparison history

- Iteration 1: implementation completed; automated checks passed; visual comparison blocked before first capture because browser bootstrap failed.

## Implementation checklist

- [x] Replace the vertical purple rail and tinted rounded card.
- [x] Preserve dynamic recommendation content and the start-session action.
- [x] Use existing tokens and the existing icon family.
- [x] Pass tests, build, artifact scan, and whitespace validation.
- [ ] Capture and compare the rendered desktop and narrow layouts.
- [ ] Test the primary action and check the browser console.

## Follow-up polish

None can be classified until the rendered comparison is available.

final result: blocked
