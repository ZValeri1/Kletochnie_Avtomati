import asyncio
import json
import threading
from copy import deepcopy

import pytest

from tests.support import call, config, symbol, value


def project_export(project_id="project-a", revision=1):
    events = []
    metrics = [{"revision": revision, "act_number": 0, "origin": "initialization", "d": 0, "s": 0.0}]
    state = {
        "atoms": {"0": "lattice:0,0"},
        "occupied": {"lattice:0,0": 0},
        "act_number": 0,
        "revision": revision,
        "events": events,
        "metrics_points": metrics,
        "configuration": {},
    }

    def simulation(simulation_id, seed):
        return {
            "simulation_id": simulation_id,
            "revision": revision,
            "configuration": config(seed_sim=seed),
            "state": deepcopy(state),
            "random_state": [1, 2, 3],
            "history": {
                "cursor": 0,
                "limit": 100,
                "history_truncated": False,
                "checkpoints": [
                    {
                        "state": deepcopy(state),
                        "random_state": [1, 2, 3],
                        "source_revision": 0,
                    }
                ],
            },
            "events": deepcopy(events),
            "metrics": deepcopy(metrics),
            "last_valid_snapshot": {},
        }

    return {
        "schema_version": 1,
        "application_version": "1.0.0",
        "project_id": project_id,
        "simulations": [simulation("sim-a", 31), simulation("sim-b", 32)],
    }


def test_project_store_round_trip_preserves_multiple_simulations(tmp_path):
    store_class = symbol("backend.data_research.project_store", "ProjectStore")
    store = store_class(root=tmp_path)
    source = project_export()

    metadata = store.save(source, overwrite=False)
    restored = store.load("project-a")

    assert value(metadata, "project_id") == "project-a"
    assert restored == source
    assert [item["simulation_id"] for item in restored["simulations"]] == [
        "sim-a",
        "sim-b",
    ]


def test_project_store_rejects_traversal_and_unsupported_data(tmp_path):
    store_class = symbol("backend.data_research.project_store", "ProjectStore")
    data_error = symbol("backend.data_research.errors", "ProjectDataError")
    store = store_class(root=tmp_path)

    with pytest.raises(data_error):
        store.load("../outside")

    damaged = tmp_path / "damaged"
    damaged.mkdir()
    (damaged / "manifest.json").write_text(
        json.dumps({"schema_version": 999, "project_id": "damaged"}),
        encoding="utf-8",
    )
    with pytest.raises(data_error):
        store.load("damaged")


def test_overwrite_false_preserves_existing_project_and_true_replaces_it(tmp_path):
    store_class = symbol("backend.data_research.project_store", "ProjectStore")
    conflict_error = symbol("backend.data_research.errors", "ProjectConflictError")
    store = store_class(root=tmp_path)
    original = project_export(revision=1)
    replacement = project_export(revision=4)
    store.save(original, overwrite=False)

    with pytest.raises(conflict_error):
        store.save(replacement, overwrite=False)
    assert store.load("project-a") == original

    store.save(replacement, overwrite=True)
    assert store.load("project-a") == replacement


def test_failed_atomic_save_leaves_the_old_project_readable(tmp_path, monkeypatch):
    store_module = __import__(
        "backend.data_research.project_store", fromlist=["ProjectStore"]
    )
    store = store_module.ProjectStore(root=tmp_path)
    original = project_export(revision=1)
    store.save(original, overwrite=False)

    def fail_replace(*_args, **_kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)
    storage_error = symbol(
        "backend.data_research.errors", "StorageUnavailableError"
    )
    with pytest.raises(storage_error, match="Project storage is unavailable"):
        store.save(project_export(revision=5), overwrite=True)

    assert store.load("project-a") == original


def test_project_import_is_atomic_and_collision_safe_with_deterministic_continuation():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    project_error = symbol("backend.data_research.errors", "ProjectDataError")

    async def scenario():
        manager = manager_class(max_parallel_simulations=2)
        first = await manager.create(config(seed_sim=901))
        second = await manager.create(config(seed_sim=902))
        await manager.step(first.simulation_id, first.revision)
        payload = await manager.export_project(
            "project-source", [first.simulation_id, second.simulation_id]
        )

        imported = await manager.import_project(payload)
        restored = imported[0]
        assert restored.simulation_id != first.simulation_id
        assert restored.source_project_id == "project-source"
        assert restored.source_simulation_id == first.simulation_id
        assert restored.status == "PAUSED"

        control_step = await manager.step(first.simulation_id, 1)
        restored_step = await manager.step(restored.simulation_id, 1)
        assert restored_step.event.q_n == control_step.event.q_n
        assert restored_step.event.source_atom_id == control_step.event.source_atom_id
        assert restored_step.event.operation == control_step.event.operation
        assert restored_step.snapshot.atoms == control_step.snapshot.atoms

        broken = deepcopy(payload)
        broken["simulations"][1]["state"]["occupied"] = {}
        clean_manager = manager_class(max_parallel_simulations=1)
        try:
            with pytest.raises(project_error):
                await clean_manager.import_project(broken)
            assert clean_manager.sessions == {}
        finally:
            await clean_manager.close()
            await manager.close()

    asyncio.run(scenario())


def test_project_round_trip_preserves_truncated_history_full_journal_and_metrics():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    async def scenario():
        source = manager_class(max_parallel_simulations=1)
        restored_manager = manager_class(max_parallel_simulations=1)
        try:
            summary = await source.create(config(dimensions=[2, 2], seed_sim=933))
            simulation_id = summary.simulation_id
            revision = summary.revision
            for _ in range(102):
                revision = (await source.step(simulation_id, revision)).revision
            payload = await source.export_project("history-project", [simulation_id])

            history = payload["simulations"][0]["history"]
            assert len(history["checkpoints"]) == 101
            assert history["history_truncated"] is True
            assert len(payload["simulations"][0]["events"]) == 102
            assert len(payload["simulations"][0]["metrics"]) == 103

            restored = (await restored_manager.import_project(payload))[0]
            restored_snapshot = await restored_manager.get_snapshot(restored.simulation_id)
            assert restored_snapshot.history_capabilities.retained_action_count == 100
            assert restored_snapshot.history_capabilities.history_truncated is True
            assert len((await restored_manager.metrics_series(restored.simulation_id)).points) == 103
            assert (await restored_manager.event_page(restored.simulation_id, 0, 200)).total == 102

            control_step = await source.step(simulation_id, revision)
            restored_step = await restored_manager.step(restored.simulation_id, revision)
            assert restored_step.event.q_n == control_step.event.q_n
            assert restored_step.event.source_atom_id == control_step.event.source_atom_id
        finally:
            await restored_manager.close()
            await source.close()

    asyncio.run(scenario())


def test_statistics_are_known_and_reproducible():
    calculator_class = symbol(
        "backend.data_research.statistics", "StatisticsCalculator"
    )
    calculator = calculator_class()
    series = [
        {"defects": 0.0},
        {"defects": 2.0},
        {"defects": 4.0},
        {"defects": 6.0},
    ]

    first = calculator.aggregate(series, bootstrap_seed=17, bootstrap_samples=500)
    second = calculator.aggregate(series, bootstrap_seed=17, bootstrap_samples=500)

    assert value(first, "mean")["defects"] == 3.0
    assert value(first, "minimum")["defects"] == 0.0
    assert value(first, "maximum")["defects"] == 6.0
    assert value(first, "percentiles")["defects"]["p50"] == 3.0
    assert value(first, "confidence_interval") == value(second, "confidence_interval")


def test_statistics_aggregate_final_values_and_each_available_act_without_zero_fill():
    calculator_class = symbol(
        "backend.data_research.statistics", "StatisticsCalculator"
    )
    calculator = calculator_class()
    trajectories = [
        [
            {"act_number": 0, "d": 0.0, "s": 0.0},
            {"act_number": 1, "d": 2.0, "s": 0.2},
        ],
        [
            {"act_number": 0, "d": 0.0, "s": 0.0},
            {"act_number": 2, "d": 6.0, "s": 0.6},
        ],
    ]

    result = calculator.aggregate_trajectories(
        trajectories, bootstrap_seed=19, bootstrap_samples=200
    )

    assert result.final["d"].count == 2
    assert result.final["d"].mean == 4.0
    assert result.by_act[1]["d"].count == 1
    assert result.by_act[1]["d"].mean == 2.0
    assert result.by_act[1]["d"].confidence_interval == (2.0, 2.0)
    assert result.by_act[1]["d"].ci_informative is False


def test_experiment_keeps_successes_when_one_run_fails():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    service_class = symbol(
        "backend.data_research.experiments", "ExperimentService"
    )
    service = service_class(manager=manager_class(max_parallel_simulations=2))

    result = call(
        service.run,
        configurations=[config(seed_sim=1), config(dimensions=[1]), config(seed_sim=3)],
        steps=2,
        master_seed=44,
    )

    assert len(value(result, "successful_runs")) == 2
    assert len(value(result, "failed_runs")) == 1
    assert value(result, "aggregate") is not None


def test_experiment_master_seed_reproduces_derived_seeds_and_act_aggregates():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    service_class = symbol(
        "backend.data_research.experiments", "ExperimentService"
    )

    def execute():
        manager = manager_class(max_parallel_simulations=2)

        async def scenario():
            try:
                return await service_class(manager=manager).run(
                    configurations=[config()],
                    repetitions=3,
                    steps=2,
                    master_seed=772,
                )
            finally:
                await manager.close()

        return asyncio.run(scenario())

    first = execute()
    second = execute()
    first_seeds = [item["derived_seeds"] for item in first.successful_runs]
    second_seeds = [item["derived_seeds"] for item in second.successful_runs]

    assert first_seeds == second_seeds
    assert len({(item["seed_init"], item["seed_sim"]) for item in first_seeds}) == 3
    assert first.aggregate == second.aggregate
    assert 0 in first.aggregate.by_act
    assert 2 in first.aggregate.by_act


def test_running_experiment_can_be_cancelled_without_scheduling_new_steps():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    service_class = symbol(
        "backend.data_research.experiments", "ExperimentService"
    )
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")
    release_blocked_steps = threading.Event()

    class ControlledEngine(engine_class):
        allowed_seed = None
        seed_lock = threading.Lock()

        def step(self, state, random_source):
            seed = state.configuration["seed_sim"]
            with self.seed_lock:
                if self.allowed_seed is None:
                    self.allowed_seed = seed
            if seed != self.allowed_seed and state.act_number == 0:
                if not release_blocked_steps.wait(timeout=5):
                    raise TimeoutError("test barrier was not released")
            return super().step(state, random_source)

    manager = manager_class(max_parallel_simulations=2, engine=ControlledEngine())
    service = service_class(manager=manager)

    async def scenario():
        try:
            record = await service.start(
                configurations=[config() for _ in range(3)],
                steps=2,
                master_seed=55,
            )
            while not record.successful_runs and not record.task.done():
                await asyncio.sleep(0)
            completed_before_cancel = len(record.successful_runs)
            cancel_task = asyncio.create_task(service.cancel(record.experiment_id))
            while not record.cancel_requested:
                await asyncio.sleep(0)
            release_blocked_steps.set()
            await cancel_task
            return service.get_result(record.experiment_id), completed_before_cancel
        finally:
            await manager.close()

    result, completed_before_cancel = asyncio.run(scenario())

    assert result.status == "CANCELLED"
    assert len(result.successful_runs) >= completed_before_cancel >= 1
    assert result.completed_steps < 6
