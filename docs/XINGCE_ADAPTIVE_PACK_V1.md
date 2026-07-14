# Xingce Adaptive Pack v1

`lumi.xingce-adaptive-pack.v1` is the authoring contract for each canonical
Xingce subtype. It is a reusable closed loop, not a shared question template:
the subtype binding fixes the response form, deterministic scorer, and the
type-specific error dimensions declared in the coverage matrix.

Every pack must supply an immutable logical payload containing:

1. one or more entry diagnostics with at least two competing, **unconfirmed**
   candidate causes;
2. an authored minimal probe that can support, refute, or leave each relevant
   candidate insufficient—never confirm it;
3. a teaching asset explicitly targeted to an authored candidate;
4. an unseen, no-hint independent transfer in a different independence group;
5. a no-hint delayed-review item bound to the transfer; and
6. a deterministic scorer and checksum for every authored record.

The coverage matrix also binds form-specific evidence. A graphic item therefore
cannot be silently replaced by text: its pack needs an immutable visual asset,
checksum, and meaningful alternative text. Material items must retain their
material snapshot/checksum and unit/scope metadata. Current-affairs and legal
types retain their versioned, authoritative-source cutoff.

Drafts stay `draft_unreviewed`, have `runtime_registration` set to
`forbidden_until_human_review`, and are suitable only for authoring and isolated
evaluation. A release requires two approved attestations from different human
reviewers—one logic reviewer and one editorial/rights reviewer—before its
runtime registration can become `allowed_after_human_review`.

The deterministic policy receives scorer observations and can produce a state
proposal only after the unseen, unassisted transfer. It must retain the pack,
record, candidate, policy, and evidence references. The eventual learner-state
committer remains a separate single writer; an entry, probe, or assisted answer
is never a KT update.

The validator is at
`domains/hermes_domains/xingce_adaptive_pack.py`. Its regression suite checks
the authoring profile for all 31 declared subtypes without treating fixtures as
reviewed content.
