# Client QA artifact status

Files beginning with `p02-` are the current P0.2 planning-flow evidence. The
authoritative paths, dimensions, hashes, real/test boundaries, DOM metrics, and
Khanmigo side-by-side comparisons are recorded in `../design-qa.md` and enforced
by `../../scripts/check_client_artifacts.py`.

Only files beginning with `p01-authentic-` are current P0.1 release evidence.
Their exact allow-list, dimensions, and SHA-256 hashes are recorded in
`../design-qa.md` and enforced by `../../scripts/check_client_artifacts.py`.

The older `overview-*`, `tools-*`, `reports-*`, and `comparison-*` files are
superseded visual-history captures from an earlier synthetic UI draft. They may
contain placeholder profiles, tasks, dates, or report counts and must not be
used as learner, product-capability, or portfolio evidence. They are retained
only to make the visual iteration auditable until a later history-cleanup
commit deliberately removes binary artifacts.

`sidecar_clock_harness.py` is a QA-only date injection boundary. It launches
the real local `SidecarApplication` and real SQLite database while replacing
only `today_provider`. The Vite development client accepts a matching
`?qa-date=YYYY-MM-DD` parameter only when `import.meta.env.DEV` is true. These
two explicit test seams are used solely for dated fair-rotation and historical
plan browser QA; production builds ignore the client query parameter.

`sidecar_error_harness.py` is a QA-only transport-state harness. It returns the
supported health/report contracts while injecting HTTP 500 for planning reads,
so browser QA can distinguish a connected error response from an offline
transport failure. It contains no plan or learner fixtures and is not a product
service entry point.
