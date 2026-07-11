from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .machine import AgentRuntime
from .models import DeterministicProvider, ModelRouter
from .state import AgentState
from .store import EventStore
from .synthetic import synthetic_registry


def build_runtime(database: str | Path) -> AgentRuntime:
    return AgentRuntime(
        registry=synthetic_registry(),
        store=EventStore(database),
        router=ModelRouter(DeterministicProvider()),
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Lumi local agent runtime")
    result.add_argument("--db", default="hermes-runtime.sqlite3", help="SQLite trace database")
    commands = result.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run an offline two-cycle learning demo")
    demo.add_argument("--interrupt-after", type=int)
    demo.add_argument("--run-id")
    replay = commands.add_parser("replay", help="replay a stored run without invoking tools/models")
    replay.add_argument("run_id")
    resume = commands.add_parser("resume", help="resume an interrupted run")
    resume.add_argument("run_id")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    runtime = build_runtime(args.db)
    if args.command == "replay":
        frames = runtime.replay(args.run_id)
        print(json.dumps({"run_id": args.run_id, "verified": True, "frames": frames}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "resume":
        state = runtime.resume(args.run_id)
        result = runtime.run(state)
    else:
        state = AgentState(
            run_id=args.run_id or AgentState("placeholder", "placeholder", "placeholder").run_id,
            learner_id="synthetic-learner",
            domain="xingce",
            goal="master base-period growth calculations",
            max_cycles=2,
            context={"answer": "B", "item_id": "synthetic-growth-001"},
        )
        result = runtime.run(state, interrupt_after=args.interrupt_after)
    events = runtime.store.events(result.state.run_id)
    summary = {
        "run_id": result.state.run_id,
        "status": result.state.status.value,
        "phase": result.state.phase.value,
        "cycle": result.state.cycle,
        "steps": result.state.step_count,
        "events": len(events),
        "trace_verified": runtime.store.verify(result.state.run_id),
        "model_tiers": [
            call["tier"]
            for event in events
            for call in event.payload.get("model_calls", [])
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
