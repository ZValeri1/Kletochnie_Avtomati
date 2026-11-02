import asyncio

from fastapi.testclient import TestClient

from backend.api.application import create_app
from backend.atomic_model.acceleration import ComputeBackend
from backend.atomic_model.engine import SimulationEngine
from backend.simulation_management.manager import SimulationManager
from backend.simulation_management.snapshots import SnapshotFactory


def test_compute_endpoint_reports_actual_backend_and_fallback(tmp_path, monkeypatch):
    app = create_app(projects_root=tmp_path)
    backend = ComputeBackend("auto")
    app.state.manager.engine.compute_backend = backend
    def missing(name):
        raise ModuleNotFoundError(name)
    monkeypatch.setattr("backend.atomic_model.acceleration.importlib.import_module", missing)
    with TestClient(app) as client:
        response = client.get("/api/compute")
        assert response.status_code == 200
        status = response.json()
        assert status["schema_version"] == 1
        assert status["preference"] == "auto"
        assert status["backend"] == "cpu"
        assert "ModuleNotFoundError" in status["reason"]
        assert status["cuda_batches"] == 0


def test_research_steps_keep_full_history_and_rng_without_rendering(monkeypatch):
    async def scenario():
        manager = SimulationManager(engine=SimulationEngine(compute_backend=ComputeBackend("cpu")))
        try:
            configuration = {"dimensions": [6, 6], "seed_init": 41, "seed_sim": 42,
                             "initialization_mode": "explicit_defective", "n_v": 5, "n_i": 5}
            left = await manager.create(configuration)
            right = await manager.create(configuration)
            for revision in range(50):
                await manager.step(left.simulation_id, revision)
            def no_render(*args):
                raise AssertionError("Research acts must not build render snapshots")
            with monkeypatch.context() as patch:
                patch.setattr(SnapshotFactory, "create", no_render)
                for revision in range(50):
                    assert await manager.step_for_research(right.simulation_id, revision) == revision + 1
            a, b = manager.sessions[left.simulation_id], manager.sessions[right.simulation_id]
            assert a.state.atoms == b.state.atoms
            assert a.state.metrics_points == b.state.metrics_points
            assert a.random_source.get_state() == b.random_source.get_state()
            assert len(a.state.events) == len(b.state.events) == 50
            for x, y in zip(a.state.events, b.state.events):
                assert x["event_id"].split(":", 1)[1] == y["event_id"].split(":", 1)[1]
                assert {k: v for k, v in x.items() if k not in {"simulation_id", "event_id"}} == \
                       {k: v for k, v in y.items() if k not in {"simulation_id", "event_id"}}
            assert a.history.export()["cursor"] == b.history.export()["cursor"]
            assert (await manager.get_snapshot(right.simulation_id)).revision == 50
        finally:
            await manager.close()
    asyncio.run(scenario())
