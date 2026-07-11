# Lumi release evidence

- Run: `run-20260711T051110Z`
- Generated: `2026-07-11T05:11:10.387175+00:00`
- Overall: **PASS**
- Counts: 13 pass / 0 fail / 0 pending

| Gate | Status | Evidence summary |
| --- | --- | --- |
| `contracts` | **PASS** | 3 schemas and canonical fixture validated |
| `fixtures` | **PASS** | 42/42 domain fixtures resolve and cover every required path/mode exactly once |
| `engine_tests` | **PASS** | deterministic engine tests passed |
| `integration_surfaces` | **PASS** | domain contracts and offline runtime demo/replay surfaces passed their real probes |
| `attempt_api` | **PASS** | real POST /v1/attempts preserves zero-cause correctness, unconfirmed error candidates, PII redaction, fail-closed fields, and verified replay |
| `cohort_prior_guardrail` | **PASS** | privacy/size guardrails pass and the real attempt trace uses sample_size=0 synthetic engineering priors without cohort claims |
| `attempt_continuation` | **PASS** | real HTTP session advances awaiting_probe → awaiting_verification → completed; illegal/stale writes fail closed and KT appears only after independent verification |
| `trace` | **PASS** | computed engine trajectory is contract-valid and replay evidence is locatable |
| `diagnosis` | **PASS** | real engine diagnosis is ranked, normalized, uncertain, and provenance-linked |
| `kt` | **PASS** | real KT update is bounded, versioned, and linked to one evidence event |
| `teaching_transfer` | **PASS** | success, ambiguous, and offline domain→engine→runtime loops persist teaching, independent transfer, KT, reflection, and verified replay evidence |
| `privacy` | **PASS** | local trace privacy contract and static secret scan passed; no cloud operations detected |
| `readonly_boundary` | **PASS** | no code dependency or symlink enters the production Shenlun repository |

The JSON report beside this file is authoritative and contains hashes, command output, missing matrix entries, and computed evidence.
