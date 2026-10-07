import math

from tests.support import call, symbol, value


def test_ten_thousand_steps_preserve_invariants():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    manager = manager_class(max_parallel_simulations=1)
    created = call(
        manager.create,
        {"dimensions": [8, 8], "seed_init": 101, "seed_sim": 102, "q_max_ev": 30},
    )
    simulation_id = value(created, "simulation_id")

    for revision in range(10_000):
        call(manager.step, simulation_id, expected_revision=revision)

    snapshot = call(manager.get_snapshot, simulation_id)
    atoms = value(snapshot, "atoms")
    positions = [value(atom, "coordinate") for atom in atoms]
    metrics = value(snapshot, "metrics")
    assert len(positions) == len(set(map(tuple, positions)))
    if isinstance(metrics, dict):
        numbers = metrics.values()
    elif hasattr(metrics, "model_dump"):
        numbers = metrics.model_dump().values()
    else:
        numbers = vars(metrics).values()
    assert all(math.isfinite(float(number)) for number in numbers)


def test_fifty_parallel_simulations_finish_without_mixing_state():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    manager = manager_class(max_parallel_simulations=4)
    summaries = call(
        manager.create_batch,
        {"dimensions": [5, 5], "q_max_ev": 30},
        count=50,
        master_seed=909,
    )

    call(manager.run_steps, [item.simulation_id for item in summaries], steps=100)
    snapshots = [call(manager.get_snapshot, item.simulation_id) for item in summaries]

    assert len({item.simulation_id for item in snapshots}) == 50
    assert all(item.revision == 100 for item in snapshots)
