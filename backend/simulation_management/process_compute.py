"""Persistent CPU workers; exchange changed atoms and complete event batches only."""
from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor

_sessions = {}
_engine = None


def _compute(simulation_id, expected_revision, initial, count):
    global _engine
    from backend.atomic_model.acceleration import ComputeBackend
    from backend.atomic_model.engine import SimulationEngine
    from backend.atomic_model.events import RandomSource
    from backend.atomic_model.state import SimulationState
    if _engine is None:
        _engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    if initial is not None:
        state = SimulationState.from_dict(initial[0])
        topology = _engine._topology(state.configuration)
        state.validate(topology)
        rng = RandomSource(state.configuration["seed_sim"])
        rng.set_state(initial[1])
        _sessions[simulation_id] = (expected_revision, state, rng)
    revision, state, rng = _sessions[simulation_id]
    if revision != expected_revision:
        raise RuntimeError("Worker revision mismatch")
    rows = []
    previous_random_core = None
    error = None
    started = time.perf_counter()
    for _ in range(count):
        try:
            result = _engine.step(state.transition_copy(include_history=False), rng)
            state = result.state
            event = state.events[-1]
            changes = [(atom_id, state.atoms.get(atom_id)) for atom_id in dict.fromkeys(event["affected_atom_ids"])]
            random_version, random_words, gaussian = rng.get_state()
            random_core, random_index = random_words[:-1], random_words[-1]
            # MT19937 changes its 624-word vector only at a twist; each draw
            # usually changes just the index. Send each vector once per batch.
            packed_random = (random_version, random_core if random_core != previous_random_core else None,
                             random_index, gaussian)
            previous_random_core = random_core
            rows.append((event, state.metrics_points[-1], changes, packed_random))
            revision += 1
        except Exception as failure:
            error = (type(failure).__name__, str(failure))
            break
        if time.perf_counter() - started >= 0.05:
            break
    _sessions[simulation_id] = (revision, state.transition_copy(include_history=False), rng)
    return rows, error, os.getpid()


def _remove(simulation_id):
    _sessions.pop(simulation_id, None)


class ProcessCompute:
    def __init__(self, workers):
        self.count = max(1, min(workers, os.cpu_count() or 1))
        self.pools = {}
        self.owners = {}
        self.revisions = {}
        self.worker_pids = set()

    def _pool(self, simulation_id):
        if simulation_id not in self.owners:
            self.owners[simulation_id] = min(range(self.count), key=lambda lane: list(self.owners.values()).count(lane))
        index = self.owners[simulation_id]
        if index not in self.pools:
            self.pools[index] = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return self.pools[index]

    async def advance(self, session, count=64):
        if count < 1:
            raise ValueError("Batch size must be positive")
        initial = None
        if self.revisions.get(session.simulation_id) != session.revision:
            initial = (session.state.transition_copy(include_history=False).to_dict(), session.random_source.get_state())
        pool = self._pool(session.simulation_id)
        try:
            rows, error, pid = await asyncio.get_running_loop().run_in_executor(
                pool, _compute, session.simulation_id, session.revision, initial, min(count, 64))
        except BaseException:
            self.revisions.pop(session.simulation_id, None)
            raise
        self.worker_pids.add(pid)
        self.revisions[session.simulation_id] = session.revision + len(rows)
        decoded = []
        random_core = None
        for event, point, changes, packed in rows:
            version, core, index, gaussian = packed
            if core is not None:
                random_core = core
            decoded.append((event, point, changes, (version, random_core + (index,), gaussian)))
        return decoded, error

    async def remove(self, simulation_id):
        if simulation_id in self.owners:
            await asyncio.get_running_loop().run_in_executor(self._pool(simulation_id), _remove, simulation_id)
            self.owners.pop(simulation_id, None)
        self.revisions.pop(simulation_id, None)

    async def close(self):
        await asyncio.gather(*(asyncio.to_thread(pool.shutdown, wait=True, cancel_futures=True)
                               for pool in self.pools.values()))
        self.pools.clear()
