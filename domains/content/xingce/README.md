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
by the desktop sidecar. The 694 MiB database remains outside Git; only its
version, lineage, counts, and checksums are committed here. The loader accepts
the export only after verifying `manifest.json`, `schema.sql`, `SHA256SUMS`, and
the SQLite file, and it reads only the export's `ready_*` views.

This release exposes 77,695 ready records in browse/search. Without the
separate offline asset release, it permits scoring for the 60,696 records that
do not depend on a bundled asset and keeps the other 16,999 fail-closed. Lumi
never follows source paths or image URLs implicitly. The 484 `needs_review`
records are not addressable through the product API. Nine of those records were
newly quarantined by the versioned pre-answer safety gate because source text
contained an explicit answer/analysis marker or a remote `INCLUDEPICTURE` field;
their source content is preserved for review rather than silently cleaned.

The same verified export supports three product entry modes without copying the
database into Git:

- **套卷**: 1,054 source papers with ready content, searchable by title and
  filterable by year, region label, and exam type;
- **题型**: six classified Xingce modules plus the explicit unclassified group;
- **知识点**: 30 released subtype facets with ready content, used as the current
  browse-level knowledge-point catalog.

The export currently exposes 27 year facets (2000–2026), 34 non-empty region
labels (31 province-level labels plus 国考, 广州, and 深圳), and six exam-type
facets. Paper and question results are
still `ready`-only and answer-redacted before submission. “知识点” here does not
claim a finer-grained skill diagnosis: 28,569 ready questions map to a released
subtype, while 49,126 remain honestly unclassified and are still discoverable
without a fabricated label. A paper entry may contain only the ready subset of
its collected questions; callers must use `ready_question_count`,
`all_collected_records_ready`, `sequence_status`, and the always-explicit
`official_completeness` instead of assuming completeness. Whole-paper mode is
closed for the nine papers that lack a unique source order.

Ordinary full-bank attempts are `practice_only` evidence proposals. They do not
write KT, confirm a misconception, or enter Today/Review. The adaptive learning
flow remains the only deterministic learner-state committer.

`offline-question-assets.release.v1.json` separately pins the content-addressed
offline resource pack. It unlocks 7,625 of the 16,999 asset-gated
questions: 3,822 have every attempt-required local image bundled, while 3,803
only had explanation-media or stale references and can be scored without them.
The remaining 9,374 fail closed (8,143 remote-only, 1,222 mixed dependencies,
and 9 rejected local placeholders). The asset catalog contains neither source
absolute paths nor remote URLs, never fetches implicitly, and makes no public
distribution-rights claim.
