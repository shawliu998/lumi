# Lumi domain slices

This subtree contains synthetic, deterministic domain slices for Xingce,
Shenlun, and structured Interview practice.  It deliberately has no runtime
dependency on the production Shenlun repository or on mutable question-bank
files.

It also owns the internal Xingce Core-320 v3 practice package. The package is
generated deterministically from four module adapters, pinned by
`practice_v3/manifest.json`, and exposes 80 versioned questions for each of
verbal, judgment, quantitative, and data analysis. The repository stores the
generators, schema, checksum, and safe samples—not a bulk question dump.
`scripts/materialize_practice_bank.py` can create a reviewable export outside
the repository and refuses in-repository output paths.

The 42 independently addressable fixtures (14 paths x `success`, `ambiguous`,
and `offline`) are not a benchmark of real candidates. They are small contract
tests proving that every representative module can emit the same learning-loop
shape:

`attempt -> score observations -> ranked cause hypotheses -> probe -> teach -> independent verification`

Important semantics:

- A score is an observed result produced by a deterministic adapter.
- A cause is always an unconfirmed hypothesis.  Fixture priors are synthetic
  engineering priors, not population statistics.
- `independent_verify` uses a different prompt and cannot be passed by replaying
  the teaching example.
- Cohort priors from real learners may replace synthetic priors only through a
  versioned data export with sample size and provenance.
- `ambiguous` requires multiple ranked candidates and a discriminating probe.
- `offline` records `provider_invoked: false`, expects zero cloud calls, and
  runs only the local deterministic scorer. Generative feedback is deferred;
  the fixture never fabricates a cloud result.

The success case owns the original task content. Ambiguous and offline cases
are constrained scenario overlays resolved by `load_fixture_document`; this
keeps content single-sourced while every scenario has a unique fixture ID,
response, execution policy, and replay semantics.

Run the domain contract suite from the repository root:

```bash
PYTHONPATH="$PWD:$PWD/domains" python3 -m unittest discover -s domains/tests -v
```
