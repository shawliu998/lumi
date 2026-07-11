# Client QA artifact status

Only files beginning with `p01-authentic-` are current P0.1 release evidence.
Their exact allow-list, dimensions, and SHA-256 hashes are recorded in
`../design-qa.md` and enforced by `../../scripts/check_client_artifacts.py`.

The older `overview-*`, `tools-*`, `reports-*`, and `comparison-*` files are
superseded visual-history captures from an earlier synthetic UI draft. They may
contain placeholder profiles, tasks, dates, or report counts and must not be
used as learner, product-capability, or portfolio evidence. They are retained
only to make the visual iteration auditable until a later history-cleanup
commit deliberately removes binary artifacts.
