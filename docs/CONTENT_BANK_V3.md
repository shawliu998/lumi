# Lumi core-320 practice bank

## Product scope

The internal v3 bank contains exactly 320 stable QuestionVersions:

- bank version: `1.0.1`;
- generator version: `lumi.practice-generator.v3.0.1`;
- generated SHA-256:
  `854ba5e483454718408cfbf8b428881333130d2224cfd4b5db3499cd54baf117`.

| Practice scope | Questions | Diagnostic units | Ordinary/near-transfer pool | Delayed-only reserve |
| --- | ---: | ---: | ---: | ---: |
| `xingce.verbal.core` | 80 | 8 | 64 | 16 |
| `xingce.judgment.core` | 80 | 8 | 64 | 16 |
| `xingce.quantitative.core` | 80 | 8 | 64 | 16 |
| `xingce.data-analysis.core` | 80 | 8 | 64 | 16 |

`xingce.mixed.core` reuses these four pools; it is not a fifth 80-question
bank. Every learner session remains fixed at eight slots.

The earlier growth-rate v2 package remains as a regression and focused-practice
artifact. It is not counted inside core-320 and is not the default client entry.

## Why the repository does not contain a 320-item JSON dump

The repository boundary prohibits committing bulk question-bank dumps. Lumi
therefore stores:

- deterministic module generators and semantic/numeric verification adapters;
- a version manifest with expected counts and the SHA-256 of the complete
  generated bank;
- safe samples and a reproducible materialization script;
- no raw OCR, copied source questions, or mutable factory working files.

At load time, the four generators materialize the same 320 QuestionVersions,
run their oracles, recompute the bank digest, and fail closed if it differs from
the manifest. Stable IDs, question version, generator version, evidence family,
material group, answer mapping, and intervention assets remain replayable.

To export the bulk bank outside Git for inspection or exchange:

```bash
python3 scripts/materialize_practice_bank.py
```

The default output is under the current user's local Lumi application-data
directory. The script rejects output paths inside this Git workspace, rechecks
the resolved path after directory creation, writes through collision-safe atomic
temporary files, and records each output file's SHA-256 and byte size.

## Eight-item ordering

Within a module, each eight-item block pairs four diagnostic units twice. The
two versions use different evidence families and material groups, so the policy
can distinguish a repeated observable error from a single miss without adding a
ninth item. Mixed practice interleaves two questions from each module in its
first eight-item block.

Each module balances the correct answer key at 20 A, 20 B, 20 C, and 20 D. The
deterministic schedule is not the question's local index modulo four; the first
mixed eight contain A/B/C/D twice, so the question ID does not reveal the key.
Delayed-only versions are excluded from ordinary recommendations and become
eligible only through a validation event.

Every version has its own material group. Definition items are checked so the
stem cannot repeat the full correct option verbatim, and numeric validators fail
closed on zero division, inconsistent congruences, tied winners, and invalid
ratio inputs. Ordinary and delayed evidence-family sets are disjoint.

## Content and rights boundary

The two user-provided PDFs are used only to identify the high-level Xingce topic
structure. Prompts, scenarios, parameters, choices, explanations, error
signatures, and interventions are generated as original internal content. No
PDF source text, original question, OCR dump, character set, or number set is
included.

Skipping a pre-expansion usability gate does not change the publication status:
the bank remains `published_internal`, `internal_mvp_only`, and
`human_review_required_before_external_release`. Those markers do not block
internal generation, local practice, automated scoring, or engineering tests.

## Authority boundaries

- Deterministic adapters, not an LLM, own scoring and answer keys.
- Error signatures describe selected distractors, not mental states.
- Candidate causes remain ranked, withdrawable hypotheses.
- Reading an explanation or answering a probe is not positive mastery evidence.
- Near transfer and delayed validation must use unexposed, independent evidence.
- The mutable `$HOME/Documents/xingcetiku` factory is not read or modified by
  this bank; Lumi consumes only its own versioned generated contract.
