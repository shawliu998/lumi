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

## 2. Write the reviewer attestation JSON

Place this next to the completed workbook and replace every placeholder with
facts entered by the two human reviewers:

```json
{
  "release_version": "0.1.0-reviewed-local-YYYYMMDD",
  "reviewer_attestations": [
    {
      "review_kind": "logic",
      "reviewer_id": "stable-human-reviewer-id",
      "reviewed_at": "YYYY-MM-DD",
      "status": "approved"
    },
    {
      "review_kind": "editorial_rights",
      "reviewer_id": "a-different-stable-human-reviewer-id",
      "reviewed_at": "YYYY-MM-DD",
      "status": "approved"
    }
  ]
}
```

Do not invent IDs, dates, or approvals. Do not mark a row as approved merely to
clear a formula. If either reviewer asks for revision, amend the draft, refresh
its deterministic checksums, and review the amended payload again.

## 3. Produce a separate release copy

The tool copies rather than mutates the authoring draft. Run it only after the
workbook and JSON above are complete:

```bash
PYTHONPATH=domains python3 domains/tools/create_reviewed_xingce_release.py \
  --source domains/content/xingce/<module>/<pack-id> \
  --output domains/released/<module>/<pack-id>-<review-version> \
  --review-workbook /absolute/path/to/completed-review.xlsx \
  --attestations /absolute/path/to/attestations.json
```

The command refuses a missing workbook, missing or duplicated reviewers,
non-approved status, missing dates, invalid artifacts, or any reviewed manifest
whose hash does not bind the two attestations. A successful output contains
`review-evidence.json`, including the completed workbook SHA-256. It still needs
the normal released-pack regression tests and a voluntary human-local browser
walkthrough before the coverage matrix can move that subtype to `released`.
