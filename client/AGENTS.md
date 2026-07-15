# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Lumi visual source of truth

- The formal user-facing product name is **Lumi**. Keep `Hermes` only in
  internal API, schema, endpoint, and service identifiers where renaming would
  break the established local contract.

- The three Khanmigo screenshots supplied on 2026-07-11 are the visual source
  for overview, tools, and skill-report screens.
- Recreate their calm education-product layout, spacing, borders, typography,
  navigation proportions, tables, and restrained violet accent.
- Do not copy Khan Academy names, marks, course content, or proprietary assets.
- Avoid generic AI-dashboard styling: no gradients, glassmorphism, glow, robot or
  sparkle imagery, decorative neural graphs, excessive pills, or card nesting.
- On the home recommendation surface, do not use a colored vertical rail or a
  tinted rounded hero card. Use the approved editorial treatment: neutral rules,
  strong typography, generous whitespace, and color only for semantic status or
  the primary action.
- Prefer ordinary product UI: source lists, tabs, tables, filters, disclosure
  rows, real empty/loading/selected states, and one consistent icon family.
- The product canvas uses a pure white background. Brand assets are the green
  translucent orbital mark and the Lumi wordmark supplied on 2026-07-11; use
  transparent files in-product and render the white wordmark as a dark variant
  when it appears on white surfaces.

## Current product scope

- The first usable milestone is the **Xingce-only agent experience**, described
  by the owner as “粉笔行测的 agent 版”. Treat that phrase as a product benchmark,
  not permission to copy proprietary questions, assets, or exact interface.
- The current internal milestone is **Core-320**: verbal, judgment,
  quantitative, and data analysis each expose 80 versioned questions, with one
  mixed scope that reuses those pools. Common-knowledge/political-theory is
  deferred and must not be implied as available.
- Direct fixed-eight practice is the default learner path. Answer is the only
  required input; explanations stay folded, and tutorials or optional probes
  appear only when repeated independent evidence justifies them. Do not restore
  a mandatory staged diagnosis/Feynman flow or add a ninth slot for intervention.
- After question eight, show a concise evidence report with the scored result,
  at most one evidence-backed weakness, and real wrong-question details kept
  folded. The only primary terminal action is to start the next fixed-eight
  group; closing remains available through the workspace close control.
- Wrong-question and learner-profile surfaces read the local sidecar's replayed
  read models. Preserve `null` and empty collections as explicit no-evidence
  states; never substitute demo metrics or infer missing resumed-session detail.
- Keep scope selection, real visible questions, cross-session learner evidence,
  independent later verification, and factual summaries working before exposing
  Shenlun or Interview in the client.
- Do not use cross-domain placeholder tasks to make the product appear broader.
  The underlying versioned contracts may remain, but the current client should
  visibly promise only the Xingce loop it can execute.
