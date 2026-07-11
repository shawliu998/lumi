# Lumi release evidence harness

This directory is the executable source of truth for Lumi v0 release evidence.
It deliberately distinguishes three outcomes:

- `pass`: the gate inspected authoritative evidence and its assertions succeeded;
- `fail`: evidence exists but is invalid, contradictory, or a command failed;
- `pending`: required product evidence or an integration surface does not exist yet.

`pending` is release-blocking by default. The runner never converts a missing
runtime, domain module, fixture, trace, or teaching policy into a synthetic pass.

## Run

```bash
python3 evals/run_all.py
```

Reports are written to `evals/reports/latest.json` and
`evals/reports/latest.md`. A timestamped JSON report and any computed golden
trajectory are retained beside them. Exit codes are:

- `0`: every required gate passed;
- `1`: at least one gate failed;
- `2`: no gate failed, but at least one required gate is pending.

For local harness development only, `--allow-pending` changes exit code `2` to
`0`; the report and overall status remain `pending`.

Useful options:

```bash
python3 evals/run_all.py --list
python3 evals/run_all.py --gate diagnosis --gate kt
python3 evals/run_all.py --no-write
python3 -m unittest discover -s evals/tests -v
```

## Gate inventory

| Gate | Evidence |
| --- | --- |
| `contracts` | JSON schema syntax and canonical contract examples |
| `fixtures` | 42 independently resolved domain/path/mode fixtures |
| `engine_tests` | deterministic engine test suite |
| `attempt_api` | black-box POST `/v1/attempts`, trace, and replay safety contract |
| `cohort_prior_guardrail` | minimum/privacy policy plus no-data engineering fallback |
| `attempt_continuation` | versioned probe/verification states and fail-closed writes |
| `today_plan_schedule` | real HTTP TodayPlan/ReviewSchedule branches, provenance, timing, commands, replay, and KT separation |
| `trace` | replayable observation → decision → state delta → evaluation record |
| `diagnosis` | ranked hypotheses, normalized uncertainty, cohort provenance |
| `kt` | bounded mastery, evidence link, versioned state transition |
| `teaching_transfer` | real success/ambiguous/offline domain→engine→runtime closures |
| `privacy` | redaction contract, local-default/source scan, cloud-bound disclosure |
| `readonly_boundary` | no code dependency or symlink into the production Shenlun repo |

The integration probe writes full replay evidence for all three modes to
`evals/reports/integration-*-trajectory-latest.json`. The compact release report
records their SHA-256 hashes and asserted outcomes.

The attempt API probe starts the real loopback sidecar on an ephemeral port. It
persists only hashed request descriptors and redacted responses in
`evals/reports/attempt-api-evidence-latest.json`; deliberate PII test strings
must never appear in that artifact. Stepwise continuation remains a separate
gate so an initial accepted POST cannot be mistaken for completed teaching.

The `today_plan_schedule` gate uses the production application and HTTP router
on ephemeral loopback ports with a deterministic injected local date. It proves
empty behavior plus all three real-attempt branches: failed evidence with an
unconfirmed candidate becomes a +1 cause probe, successful independent
verification becomes a fixed-unvalidated +3 retention check, and a correct
first answer with failed verification becomes a +1 generic retry. It also checks trace-resolvable
evidence references, strict budgets, persisted command receipts, cross-instance
CAS, skip/postpone resurface, historical-plan immutability, projection replay,
exam-deadline withholding, and user-marked completion that leaves learning
traces and skill state unchanged.

The task launch contract is deliberately honest about item novelty. The current
activity points back to the same versioned fixture, so every task carries
`same_fixture_retest_not_novel_item`; its success criterion says it is a
same-fixture independent retest, not evidence of transfer to an unseen parallel
item. Skipped work stays in ReviewSchedule and enters a fair queue. Neither skip
nor `postpone_until` promises that a task will be displayed on the very next
day. The gate proves three-task rotation, an eight-day stream of new failed-run
arrivals without starvation of the oldest skipped task, and next-day carry of
an accepted commitment ahead of competing work. `max_non_accepted_tasks` limits
only non-accepted Today work; every due accepted commitment is shown first and
does not consume that cap. If the daily budget cannot cover all due accepted
work, create returns the closed 409 error
`budget_below_accepted_commitment`, writes neither a TodayPlan nor a task event,
and permits retrying the same command ID with a sufficient budget. The rejected
response is the closed envelope `error.{code,message,request_id}` and is never a
partial TodayPlan document.

Scheduling windows distinguish the authored policy offset and base due date
from the initial presentation date. Evidence older than 14 days remains eligible
and is labeled `overdue_catch_up`; the UI/API must not imply that a catch-up task
was delivered on the original +1/+3 window. The gate seeds an
`evaluation_fixture` trajectory through the internal integration path (never
through a public run-creation endpoint) and proves it is absent from Today,
ReviewSchedule, health counts, skill projections, and misconception projections.
The former `POST /v1/runs` demo route must return the generic 404 envelope;
capabilities must advertise neither that route nor `offline-deterministic-path`.
The same black-box gate rejects phone/ID-shaped opaque command identifiers and
OpenAI, GitHub classic/fine-grained, Google, npm, and Slack token shapes without
echoing them or writing a transition. The compact evidence artifact is written to
`evals/reports/today-plan-evidence-latest.json`; `--no-write` creates no report
or evidence file.

Restart safety is also release-blocking. The probe repairs a deliberately
partial five-field schedule migration, upgrades the pre-novelty activity and
task-copy contract with an auditable migration record, verifies a second healthy
reopen makes zero data changes, and proves legacy create/transition receipts are
preserved but fail closed with `command_conflict` instead of replaying stale
task copy. It also exercises two Sidecars with skewed local dates so the old
process cannot mutate a historical plan after a newer TodayPlan exists. Once all
pending review tasks are completed, the next day is honestly empty with
`no_pending_review_tasks`; completed overdue tasks no longer inflate the pending
catch-up count.

The schemas are intentionally dependency-free at runtime: `run_all.py` includes
a small validator for the subset used here. Installing `jsonschema` is optional.
