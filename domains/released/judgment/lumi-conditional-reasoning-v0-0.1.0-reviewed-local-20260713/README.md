# Lumi Conditional Reasoning Pack (draft)

`lumi-conditional-reasoning-v0` is an original, deliberately narrow Domain
Pack for the first Lumi demonstration: identifying whether a learner reverses
a conditional, confuses a necessary condition with a sufficient one, or applies
an invalid conditional inference.

It is **not** a question-bank import and is not a production activity. Every
record is `draft_unreviewed`; the validator intentionally rejects any attempt
to mark it release-ready before human logic and editorial/rights review.

The v0 scope includes only:

- `只有 A，才 B` → `B → A`;
- `只要 A，就 B` → `A → B`;
- necessary-versus-sufficient roles; and
- direct, converse, contrapositive, and inverse inference.

It excludes `除非`, biconditionals, multi-premise arguments, truth-teller
puzzles, set relations, and real exam content. The pack is self-contained and
licensed as described in [LICENSE-CONTENT.md](LICENSE-CONTENT.md), subject to
the stated human-review gate.

Validate the pack from `domains/`:

```bash
python -m hermes_domains.reasoning_pack
```

The command reports deterministic SHA-256 checksums for the manifest and all
content artifacts. It validates the draft; it does not publish, register, or
otherwise expose the pack to the product catalog.
