# Lumi repository collaboration rules

## Repository role

This repository is the source of truth for the new local-first Lumi learning
agent and its macOS client. New product code, learning models, agent runtime,
evaluation code, and versioned data contracts belong here.

## Hard boundaries

- `$HOME/Desktop/shenlun-agent-platform` is a shared production repository.
  It is read-only reference material. Never edit files, create or switch branches,
  stage, commit, rebase, reset, or push from that repository.
- `$HOME/Documents/xingcetiku` is a separate question-bank data factory.
  Changes there require an explicitly assigned task. Lumi consumes only
  versioned exports; it must not depend directly on mutable working files.
- Large source assets, model weights, raw OCR, audio, video, and question-bank
  dumps must not be committed here. Keep manifests, schemas, checksums, samples,
  and reproducible import scripts in Git; keep bulk artifacts outside Git.
- Do not connect or push a remote until the owner confirms that
  `shawliu998/zhishixingqiu.git` has been created and authorizes the operation.

## Engineering principles

- Local first: core practice, learner state, knowledge tracing, and trajectory
  inspection must work on one Mac without a server account.
- Auditable before clever: every diagnosis, mastery update, recommendation, and
  teaching intervention must retain evidence, model/version metadata, and a
  replayable decision record.
- Structured state is authoritative. Conversation memory may help the agent but
  never replaces learner, skill, attempt, diagnosis, or evaluation records.
- Model and provider boundaries must remain replaceable. Domain scoring and KT
  must not be hidden inside prompts.
- Treat inferred error causes as ranked hypotheses with uncertainty. Confirm them
  through targeted probes or later transfer performance.
- Optimize for independent transfer and delayed retention, not chat length or
  immediate user satisfaction.
- Preserve user data locally by default. Any future cloud call must be visible,
  scoped, redactable, and opt-in at the product boundary.

## Domain architecture

- One orchestrator owns learning goals and session policy.
- Xingce, Shenlun, and Interview are domain modules/tools with distinct evidence
  and scoring rules; they write through shared learning-event contracts.
- Shared services own learner state, skill graph, misconception hypotheses,
  knowledge tracing, scheduling, memory curation, and evaluation.
- Shenlun functionality may be reimplemented from documented concepts or stable
  interfaces, but no source migration from the production repository is assumed.

## Required delivery discipline

- Read the nearest `AGENTS.md` before changing a subtree.
- Keep changes within the task's assigned file scope; concurrent agents share the
  same working tree.
- Add deterministic tests for policy, state transition, data migration, and KT
  behavior. LLM evaluations supplement tests; they do not replace them.
- Record prompts, tools, inputs, outputs, model settings, costs/latency when
  available, and state deltas in a trace with sensitive fields redacted.
- Do not claim a learning loop is complete until it passes the representative
  end-to-end evaluation gates in `docs/EVALUATION.md`.
