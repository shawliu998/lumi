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
