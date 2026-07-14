# Lumi explainable learning engine

This directory contains a dependency-free Python baseline for knowledge tracing,
misconception diagnosis, and post-teaching verification. It is intentionally a
transparent baseline: no neural knowledge-tracing model is claimed or trained.

The engine combines three interpretable signals:

- BKT: posterior mastery after a correct/incorrect observation;
- PFA: success/failure practice counts;
- Rasch/1PL IRT: learner ability relative to item difficulty.

Misconception diagnosis combines one versioned prior, a learner-history
likelihood ratio, and evidence likelihoods such as an authored distractor
pattern. The v3 output uses neutral `prior_*` fields: sample-zero synthetic
taxonomies are labelled `engineering_prior`, while `cohort_prior` is reserved
for privacy-reviewed aggregates that pass the minimum-sample policy. The
formula avoids accidentally squaring the cold-start prior.
Every output includes provenance and uncertainty and remains a ranked
hypothesis, never a causal label.

`hermes_kt.cohort.build_cohort_priors` accepts privacy-reviewed aggregate cause
counts only. It applies a minimum-attempt threshold and empirical-Bayes
shrinkage toward the versioned engineering taxonomy. Small or unreviewed
aggregates fail closed: their counts do not affect diagnosis and outputs are
labelled `engineering_prior`, never `cohort_prior`.

Run the tests with only the Python standard library:

```bash
python -m unittest discover -s tests -v
```

`hermes_kt.tool_api.HermesKTTool` is a JSON-friendly boundary for a future Agent
tool. Production persistence and model calibration are deliberately outside this
baseline.

`hermes_kt.assistance` defines the six-level evidence policy. Its weights are
explicit engineering policy values, not population calibration. Assisted or
hinted verification returns an inconclusive result and leaves the authoritative
mastery state unchanged; a fresh independent item is required for transfer
credit.

Model routing is policy-only: complex or ambiguous diagnosis is routed to a
strong model, ordinary explanation to a balanced model, and low-cost output is
never allowed to update mastery directly. All generated diagnosis must pass the
local schema guardrail; low-cost conclusions additionally require an independent
verification item.
