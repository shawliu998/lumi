# Lumi Local Agent Runtime

Dependency-light Python 3.11 runtime for an auditable local learning-agent loop:

`observe → diagnose → probe → teach → verify → update → reflect`

The runtime owns orchestration only. Domain scorers and the KT engine connect as
typed JSON tools; this package does not import their implementation. Every state
transition, tool input/output, model route, and state diff is appended to SQLite.
The trace is redacted, append-only, hash-chained, resumable, and replayable without
calling tools or models again.

## Run locally

```bash
cd $HOME/Documents/zhishixingqiu/runtime
python3 -m unittest discover -s tests -v
python3 -m hermes_runtime --db /tmp/hermes-demo.sqlite3 demo
python3 -m hermes_runtime --db /tmp/hermes-demo.sqlite3 replay RUN_ID
```

To demonstrate interruption and process-safe recovery:

```bash
python3 -m hermes_runtime --db /tmp/hermes-resume.sqlite3 demo --interrupt-after 4 --run-id demo-1
python3 -m hermes_runtime --db /tmp/hermes-resume.sqlite3 resume demo-1
```

## Integration boundary

Register one tool per phase (`learning.observe` through `learning.reflect`). A
`ToolSpec` declares input/output schemas, permitted phases, and a version. Tool
handlers receive only a JSON-compatible payload and `ToolContext`; adapters may
call an external process, local HTTP endpoint, or an in-process implementation.
The stable boundary keeps the runtime independent from domain and KT engines.

`ModelRouter` sends deterministic work to `light`, balanced work to `terra`, and
high-complexity or high-risk work to `sol`. Providers are replaceable; routing
reasons and available cost/latency/usage metadata are written into the trace.
