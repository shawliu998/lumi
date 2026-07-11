# Lumi P0.3 Study Pack design QA

## Source baseline

- Khanmigo overview reference: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-9e126b71-77af-418b-94da-e3a343119661.png`
- Khanmigo tools reference: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-4bc3f416-174d-498a-95e6-7c0838df466a.png`
- Khanmigo reports reference: `/var/folders/21/lq2y7qwx7nz2czy8zxyyc6480000gn/T/codex-clipboard-b3bb8c34-cfad-4b7c-8d1f-bf58dc5928d8.png`

The source states are not Study Pack screens, so comparison is limited to the
shared education-product shell, information density, typography, navigation,
table/disclosure treatment, restrained purple accent, and absence of decorative
AI imagery. It is not claimed as a pixel-identical state clone.

## Browser evidence

| State | Viewport | Evidence | Result |
| --- | --- | --- | --- |
| connected list | 1280×720 | `client/qa/p03-materials-list-final-1280x720.png` | passed |
| published detail | 1280×720 | `client/qa/p03-materials-published-final-1280x720.png` | passed |
| active practice before answer | 1280×720 | `client/qa/p03-practice-active-final-1280x720.png` | passed; answer/explanation/citations absent |
| active practice before answer | 640×720 | `client/qa/p03-practice-active-final-640x720.png` | passed; no horizontal overflow; sidebar copy hidden cleanly |
| offline | 1280×720 | `client/qa/p03-materials-offline-final-1280x720.png` | passed; import unavailable and retry explicit |
| connected service error | 1280×720 | `client/qa/p03-materials-error-final-640x720.png` | passed; fail-closed error and retry explicit |
| quarantined pack | 1280×720 | `client/qa/p03-materials-quarantined-final-1280x720.png` | passed; zero contents and no publish/practice action |

DOM/browser checks also verified:

- `documentElement.scrollWidth === clientWidth` at 1280 and 640;
- active practice is `overflow:auto`, `min-height:0`, and uses 19px/14px
  horizontal padding at desktop/narrow widths;
- pre-answer textarea is empty and no `.practice-reveal` or
  `.practice-cited-context` exists;
- the product-default QA database still contains zero Study Pack attempts;
- 640px responsive navigation retains explicit accessible names after hidden
  copy was replaced by icon-only presentation;
- connected browser console contained no warning or error entries during the
  real published-pack launch.

## Same-input comparisons

- `client/qa/p03-compare-list-khanmigo.png`
- `client/qa/p03-compare-published-khanmigo.png`
- `client/qa/p03-compare-practice-khanmigo.png`

Visible review: Lumi preserves the reference's ordinary education-software
grammar—persistent left navigation, quiet top bar, white content canvas, thin
neutral borders, compact tables/disclosures, small-radius controls, and one
restrained purple accent. No gradient, glass, glow, robot/brain imagery,
decorative chat bubble, CSS/div art, oversized marketing type, or visible
engineering jargon remains in the Study Pack flow.

## Iteration history

1. Initial implementation exposed `artifact` copy, a CSS status dot, clipped
   sidebar connection text at 640px, tiny low-contrast Study Pack text, and a
   non-scrolling practice container.
2. Sol replaced engineering copy and CSS art, improved Study Pack text sizes and
   contrast, added semantic tables/lists/focus handling, made practice content
   independently scrollable, and closed response/citation/retry integrity gaps.
3. Browser QA found a React StrictMode lifecycle bug that left practice launch
   permanently loading; Sol re-armed all async lifecycle guards and added a
   regression test.
4. Browser QA then found unnamed icon-only controls at 640px; Sol added stable
   accessible names and regression coverage without changing the visual layout.

## Final result

`blocked` for the full revealed/completed browser matrix only. Connected,
offline, error, quarantine, published, and active pre-answer states pass. The
revealed answer, long explanation/citation bottom reachability, and three-item
completed summary must be exercised by an actual learner entering answers.
Automation deliberately did not type or submit a learner answer, so those states
remain unclaimed rather than being simulated as human evidence.
