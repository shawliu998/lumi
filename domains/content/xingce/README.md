# Versioned Xingce content releases

This directory stores only release manifests, provenance, checksums, and
Lumi-owned learning metadata. It must not contain question-bank dumps or source
question text unless republication rights have been confirmed.

`p031-data-analysis-v1` is the first local P0.3.1 evaluation release. Its source
records were reviewed for text sufficiency and independently recalculated, but
their republication rights are unverified. Generate the local-only payload with:

```bash
python3 domains/tools/import_xingce_local_bundle.py
```

The importer reads the separate `~/Documents/xingcetiku` factory in place,
checks the pinned source-manifest and per-item signatures, and writes to
`domains/local_content/`, which is ignored by Git. It never writes to the source
factory. Any signature drift, missing A-D option, unresolved answer, or
image-dependent option fails closed.

The roles in the first release are intentional:

- `first_answer`: positive-growth base-amount question;
- `independent_transfer`: a different negative-growth change question;
- `reserve_*`: reviewed candidates for later diagnostic paths.

Skill labels remain versioned candidate annotations. They are not learner
diagnoses, population error rates, or evidence of mastery.

## Complete local question bank

`full-question-bank.release.v1.json` pins the immutable SQLite export consumed
by the desktop sidecar. The 687 MiB database remains outside Git; only its
version, lineage, counts, and checksums are committed here. The loader accepts
the export only after verifying `manifest.json`, `schema.sql`, `SHA256SUMS`, and
the SQLite file, and it reads only the export's `ready_*` views.

This release exposes all 77,704 ready records in browse/search. It permits
direct scoring only for the 60,703 records that do not depend on an unbundled
asset. The other 17,001 stay visible but fail closed until a separately hashed
offline asset release exists; Lumi never follows source paths or image URLs
implicitly. The 475 `needs_review` records are not addressable through the
product API.

Ordinary full-bank attempts are `practice_only` evidence proposals. They do not
write KT, confirm a misconception, or enter Today/Review. The adaptive learning
flow remains the only deterministic learner-state committer.
