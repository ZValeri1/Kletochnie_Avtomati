"""Measure real manager throughput including complete journal, metrics and undo history.

Example: python scripts/benchmark_scaling.py --size 1000 --steps 10000 --runs 4
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.simulation_management.manager import SimulationManager


async def benchmark(args):
    manager = SimulationManager(max_parallel_simulations=args.runs)
    try:
        started = time.perf_counter()
        summaries = [await manager.create({"dimensions": [args.size, args.size],
            "seed_init": 41, "seed_sim": 42 + i, "method": args.method}) for i in range(args.runs)]
        initialization_seconds = time.perf_counter() - started

        async def advance(simulation_id, steps):
            session = manager.sessions[simulation_id]
            target = session.revision + steps
            while session.revision < target:
                if args.mode == "batch":
                    await manager.advance_batch(simulation_id, session.revision, target - session.revision)
                else:
                    await manager.step_for_research(simulation_id, session.revision)

        warmup = time.perf_counter()
        await asyncio.gather(*(advance(summary.simulation_id, 64) for summary in summaries))
        warmup_seconds = time.perf_counter() - warmup
        started = time.perf_counter()
        await asyncio.gather(*(advance(summary.simulation_id, args.steps) for summary in summaries))
        elapsed = time.perf_counter() - started
        trajectories = []
        for summary in summaries:
            session = manager.sessions[summary.simulation_id]
            physical = session.state.transition_copy(include_history=False).to_dict()
            digest = hashlib.sha256(json.dumps({"state": physical, "rng": session.random_source.get_state()}, sort_keys=True).encode()).hexdigest()
            trajectories.append({"sha256": digest, "events": len(session.state.events),
                "metric_points": len(session.state.metrics_points), "final_metrics": session.state.metrics_points[-1],
                "changed_atoms": len(list(session.state.atoms.changed_keys()))})
        output = {"size": args.size, "runs": args.runs, "steps_per_run": args.steps,
            "method": args.method, "mode": args.mode, "initialization_seconds": initialization_seconds,
            "worker_warmup_seconds": warmup_seconds, "seconds": elapsed,
            "total_acts_per_second": args.steps * args.runs / elapsed,
            "average_acts_per_second_per_run": args.steps / elapsed,
            "worker_pids": sorted(manager.process_compute.worker_pids), "trajectories": trajectories}
        print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
        if args.output:
            Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--steps", type=int, default=10000)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--method", choices=("monte_carlo", "cellular_automata"), default="monte_carlo")
    parser.add_argument("--mode", choices=("batch", "thread"), default="batch")
    parser.add_argument("--output")
    asyncio.run(benchmark(parser.parse_args()))
