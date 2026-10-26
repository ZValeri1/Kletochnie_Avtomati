"""Repeatable warm-engine benchmark; identical seeds, counts and trajectories.

python scripts/benchmark_compute.py --backend cuda --dimensions 20 20 --runs 4
--engine-root can point at a clean reference checkout for --backend legacy.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["cpu", "cuda", "auto", "legacy"], default="auto")
    parser.add_argument("--dimensions", type=int, nargs="+", default=[20, 20])
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--engine-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine_root))
    from backend.atomic_model.engine import SimulationEngine
    from backend.atomic_model.events import RandomSource
    backend = None
    if args.backend != "legacy":
        from backend.atomic_model.acceleration import ComputeBackend
        backend = ComputeBackend(args.backend)
        if args.backend == "cuda" and backend.status()["backend"] != "cuda":
            raise RuntimeError(backend.status()["reason"])
    engine = SimulationEngine(**({"compute_backend": backend} if backend else {}))
    initial_start = time.perf_counter()
    size = math.prod(args.dimensions)
    initial = engine.create_initial_state({"dimensions": args.dimensions,
        "initialization_mode": "explicit_defective", "n_v": size//2, "n_i": size//2,
        "seed_init": 41, "seed_sim": 42}, RandomSource(42)).state
    # Compile/upload outside the timed steady-state loop. Record startup separately.
    engine.probabilities(initial, next(iter(initial.atoms)), 82)
    startup_seconds = time.perf_counter() - initial_start

    def run(index):
        state, rng = initial.transition_copy(include_history=False), RandomSource(42+index)
        for _ in range(args.steps):
            state = engine.step(state.transition_copy(include_history=False), rng).state
        digest = hashlib.sha256(json.dumps({"state": state.to_dict(),
            "rng": rng.get_state()}, sort_keys=True).encode()).hexdigest()
        return digest

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.runs) as pool:
        hashes = list(pool.map(run, range(args.runs)))
    elapsed = time.perf_counter()-start
    print(json.dumps({"backend": args.backend, "dimensions": args.dimensions,
        "runs": args.runs, "steps_per_run": args.steps, "seconds": elapsed,
        "acts_per_second": args.steps*args.runs/elapsed, "startup_seconds": startup_seconds,
        "trajectory_hashes": hashes, "device": backend.status() if backend else None}, indent=2))


if __name__ == "__main__":
    main()
