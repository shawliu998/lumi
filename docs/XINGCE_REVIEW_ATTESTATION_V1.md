# Xingce review attestation v1

After two humans complete the workbook, create a small JSON file with a
`release_version` and exactly two `reviewer_attestations`: one `logic` and one
`editorial_rights`. Each must use a different stable reviewer ID, `status` of
`approved`, and the review date. The release tool refuses absent, duplicated,
undated, or non-approved attestations and binds the supplied workbook SHA-256
inside `review-evidence.json`. It creates a new release copy; it never alters
the authored draft.
