# Xingce review attestation v1

This is the release path for every non-conditional-logic Xingce draft. It
exists to preserve a simple distinction:

- an authored `draft_unreviewed` pack is useful for content work and isolated
  evaluation, but is not learner-loadable;
- a `release_ready` copy binds two real review decisions to one immutable
  workbook and one immutable payload; and
- neither a test fixture nor a model-generated answer can substitute for a
  reviewer or a real learner browser run.

## 1. Complete the review workbook

Use the current multi-pack workbook, or a pack-specific workbook with the same
columns.

1. In **逐题审核**, the logic reviewer reviews every row and records one of
   `Approved` / `Needs revision`, their stable reviewer ID, notes, and date.
   They check the unique answer, fact or inference boundary, candidate-probe
   discrimination, targeted teaching, and independent transfer.
2. The editorial/rights reviewer independently reviews every row with the same
   fields. They check wording, source or rights evidence, reader clarity, and
   time-sensitive claims. For legal and current-affairs packs, they must check
   the source snapshot and cutoff rather than rely on recollection.
3. A pack remains blocked if any row is unreviewed or needs revision. A reviewer
   ID must name a real person and the two pack-level IDs must be different.
4. In **题包签署**, enter the two reviewer IDs and the actual review date only
   after the formulas show that every row for that pack is approved. Keep the
   completed `.xlsx` unchanged after it is signed; an edit changes its hash and
   requires a fresh review record.

The workbook is evidence of a review decision, not a batch permission to claim
that all 31 types are released. Review and release one concrete pack at a time.

## 2. Mechanically derive the reviewer attestation JSON

Do not hand-write a release attestation. After the two real reviewers have
completed the rows and the signing row, derive it directly from that exact
workbook:

```bash
PYTHONPATH=domains python3 domains/tools/verify_xingce_review_workbook.py \
  --source domains/content/xingce/<module>/<pack-id> \
  --review-workbook /absolute/path/to/completed-review.xlsx \
  --release-version 0.1.0-reviewed-local-YYYYMMDD \
  --output /absolute/path/to/attestations.json
```

The verifier requires every record of the selected pack exactly once, both
row-level conclusions to be `Approved`, the two row-level reviewer IDs and
dates to match the signing row, ISO dates, and two different reviewers. It
also hashes the exact workbook and the exact source `records.json`. It creates
the JSON only after all checks pass; it never fills in IDs, dates, or approvals.
If either reviewer asks for revision, amend the draft, refresh its deterministic
checksums, and review the amended payload again.

## 3. Produce a separate release copy

The tool copies rather than mutates the authoring draft. Run it only after the
workbook verifier above created the JSON:

```bash
PYTHONPATH=domains python3 domains/tools/create_reviewed_xingce_release.py \
  --source domains/content/xingce/<module>/<pack-id> \
  --output domains/released/<module>/<pack-id>-<review-version> \
  --review-workbook /absolute/path/to/completed-review.xlsx \
  --attestations /absolute/path/to/attestations.json
```

The command refuses a missing workbook, missing or duplicated reviewers,
non-approved status, missing dates, a hand-authored or stale attestation file,
invalid artifacts, or any reviewed manifest whose hash does not bind the two
attestations. A successful output contains
`review-evidence.json`, including the completed workbook SHA-256. It still needs
the normal released-pack regression tests and a voluntary human-local browser
walkthrough before the coverage matrix can move that subtype to `released`.
