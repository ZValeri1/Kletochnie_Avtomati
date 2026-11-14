import asyncio
import json

import pytest

from backend.atomic_model.acceleration import ComputeBackend
from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import RandomSource
from backend.simulation_management.manager import SimulationManager
from backend.simulation_management.errors import RevisionConflictError


def physical(state):
    return state.transition_copy(include_history=False).to_dict()


@pytest.mark.parametrize("method,q_max", [("monte_carlo", 82), ("cellular_automata", 1000)])
def test_process_batches_match_serial_and_resume_after_project_restore(method, q_max):
    async def scenario():
        manager = SimulationManager()
        try:
            config = {"dimensions": [100, 100], "seed_init": 41, "seed_sim": 42,
                      "method": method, "q_max_ev": q_max}
            summary = await manager.create(config)
            session = manager.sessions[summary.simulation_id]
            engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
            rng = RandomSource(42)
            serial = engine.create_initial_state(config, rng).state
            while session.state.act_number < 150:
                await manager.advance_batch(session.simulation_id, session.revision, 150 - session.state.act_number)
            for _ in range(150):
                serial = engine.step(serial.transition_copy(include_history=False), rng).state
            assert physical(session.state) == physical(serial)
            assert session.random_source.get_state() == rng.get_state()
            assert len(session.state.events) == 150
            assert len(session.state.metrics_points) == 151
            assert session.history.history_truncated
            if method == "cellular_automata":
                assert any(len(event["affected_atom_ids"]) > 1 for event in session.state.events)
            with pytest.raises(RevisionConflictError):
                await manager.advance_batch(session.simulation_id, -1)
            assert session.status.value == "PAUSED"
            await manager.undo(session.simulation_id, session.revision)
            before = physical(session.state)
            payload = json.loads(json.dumps(await manager.export_project("scaling", [session.simulation_id])))
            assert payload["simulations"][0]["history"]["format"] == "deltas_v1"
            assert len(json.dumps(payload)) < 6_000_000
            imported = (await manager.import_project(payload))[0]
            restored = manager.sessions[imported.simulation_id]
            assert physical(restored.state) == before
            await manager.redo(restored.simulation_id, restored.revision)
            assert physical(restored.state) == physical(serial)
            await manager.advance_batch(restored.simulation_id, restored.revision, 1)
            serial = engine.step(serial.transition_copy(include_history=False), rng).state
            assert physical(restored.state) == physical(serial)
            assert restored.random_source.get_state() == rng.get_state()
            await manager.remove(restored.simulation_id)
            assert restored.simulation_id not in manager.process_compute.owners
            # The original worker must resynchronize after undo, including its RNG.
            await manager.advance_batch(session.simulation_id, session.revision, 2)
            assert physical(session.state) == physical(serial)
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_large_fast_run_can_pause_and_undo_an_inflight_batch():
    async def scenario():
        manager = SimulationManager()
        try:
            summary = await manager.create({"dimensions": [1000, 1000], "seed_init": 41, "seed_sim": 42})
            session = manager.sessions[summary.simulation_id]
            await manager.run(session.simulation_id, session.revision, mode="fast")
            await asyncio.sleep(0.05)
            await manager.undo(session.simulation_id, session.revision)
            assert session.status.value == "PAUSED"
            assert session.history.can_redo
            snapshot = await manager.get_snapshot(session.simulation_id)
            assert snapshot.render_sampled
            assert len(snapshot.atoms) < 10000
            session.state.validate(session.topology)
        finally:
            await manager.close()
    asyncio.run(scenario())
