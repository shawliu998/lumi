from __future__ import annotations

import argparse
import json
from typing import Sequence

from hermes_runtime.store import EventStore

from .loop import SCENARIOS, run_scenario


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run the real Lumi domain→KT→runtime integration loop")
    result.add_argument("--db", default="integration-trace.sqlite3")
    commands = result.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("scenario", choices=sorted(SCENARIOS))
    run.add_argument("--fixture", default="xingce/data_analysis_growth.json")
    run.add_argument("--run-id")
    replay = commands.add_parser("replay")
    replay.add_argument("run_id")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "replay":
        store = EventStore(args.db)
        frames = list(store.replay(args.run_id))
        output = {
            "run_id": args.run_id,
            "trace_verified": store.verify(args.run_id),
            "frames": frames,
        }
        store.close()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    session, result = run_scenario(
        args.scenario,
        args.db,
        fixture_path=args.fixture,
        run_id=args.run_id,
    )
    artifacts = result.state.artifacts
    events = session.store.events(result.state.run_id)
    output = {
        "run_id": result.state.run_id,
        "scenario": args.scenario,
        "status": result.state.status.value,
        "steps": result.state.step_count,
        "diagnosis_decision": artifacts["diagnose"][-1]["decision"],
        "verification_effective": artifacts["verify"][-1]["verification"]["effective"],
        "mastery_delta": artifacts["update"][-1]["mastery_delta"],
        "outcome": artifacts["reflect"][-1]["outcome"],
        "trace_verified": session.store.verify(result.state.run_id),
        "model_calls_recorded": sum(len(event.payload.get("model_calls", [])) for event in events),
    }
    session.store.close()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
