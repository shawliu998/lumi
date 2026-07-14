# P0.3.1 five-minute learner acceptance

P0.3.1 is release-ready only after this script is completed by a real local
learner in the current signed `Lumi.app`. It is an experience check, not a
request to optimize the answers or manufacture a mastery result.

## Start condition

The sidecar status says `本机服务已连接` and the user follows either path:

- `训练工具` → `错因辨析`; or
- global search → `错因辨析`.

Both paths must load the same versioned 2023 materials-analysis first item and
distinct transfer item. The panel first says `查看首题（尚未创建记录）`.
Opening that question must leave the run count unchanged; a learner record is
created only by `提交首答并创建本机记录`.

## Learner path

1. Read the material, choose an answer and confidence, then submit the first
   answer. The next visible state shows the scored first answer and a ranked
   list of *candidate / unconfirmed* causes.
2. Select the formula in the short probe, optionally explain the reasoning, and
   submit it. The next state shows a targeted explanation and a different,
   unseen transfer question. The transfer state offers no assistance control.
3. Choose an answer and confidence for the transfer question, then submit it.
   The result view shows both questions, the learner's answers, the candidate
   cause state, a mastery receipt, a review-schedule receipt, and verified trace
   / replay counts. Long material and the primary action must remain reachable
   at a 640-pixel-wide viewport.

## Required truthful outcomes

- A wrong, assisted, or inconclusive independent transfer shows a withheld KT
  receipt with zero delta and creates exactly one `independent_retry` task.
- A correct, no-help independent transfer shows one committed KT receipt and
  creates exactly one `delayed_retention` task.
- Reopening, refreshing, or replaying a completed run neither duplicates its
  learning record nor its review task.
- Any invalid binding, stale continuation, offline sidecar, or error response
  names the problem and provides a safe recovery path. It must not display a
  cached answer, invented diagnosis, KT update, or review task.

## Release evidence required

Record the run ID, trace/replay verification, the result view, the review task,
and the current Mac bundle signature. Deterministic test fixtures and automated
browser interaction may validate contracts and layout, but must never provide or
submit the learner's answers. A prior v1 run may be retained as regression
evidence but cannot pass this v2 acceptance gate.
