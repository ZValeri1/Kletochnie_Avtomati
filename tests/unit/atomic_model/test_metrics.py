import math

from backend.atomic_model.metrics import MetricsCalculator
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology
from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import RandomSource


def test_ordered_lattice_has_zero_defects_and_zero_entropy():
    topology = Topology.create((4, 4))
    state = SimulationState.create_ideal(topology)

    metrics = MetricsCalculator().calculate(topology, state)

    assert metrics.model_dump() == {
        "n_correct": 16,
        "n_v": 0,
        "n_i": 0,
        "n_as": 0,
        "d": 0,
        "s": 0.0,
    }
    assert all(math.isfinite(value) for value in metrics.model_dump().values())


def test_external_interstitial_is_counted_only_as_external_defect():
    topology = Topology.create((4, 4))
    state = SimulationState.create_ideal(topology)
    source = "lattice:4,4"
    destination = "interstitial:3.5,4.5"
    state.relocate(state.occupied[source], destination)
    state.validate(topology)

    metrics = MetricsCalculator().calculate(topology, state)

    assert metrics.n_correct == 15
    assert metrics.n_v == 1
    assert metrics.n_i == 0
    assert metrics.n_as == 1
    assert metrics.d == 2
    assert math.isclose(metrics.s, -(15 * math.log(15 / 17) + 2 * math.log(1 / 17)))


def test_boundary_lattice_atom_is_correct_and_storage_order_is_irrelevant():
    topology = Topology.create((4, 4))
    ordered = SimulationState.create_ideal(topology)
    reversed_state = SimulationState.from_positions(
        topology, dict(reversed(list(ordered.atoms.items())))
    )

    left = MetricsCalculator().calculate(topology, ordered)
    right = MetricsCalculator().calculate(topology, reversed_state)

    assert left == right
    assert left.n_correct == len(topology.metal_domain.lattice_keys)


def test_initial_physical_and_manual_actions_append_typed_metric_points():
    engine = SimulationEngine()
    random_source = RandomSource(19)
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 18,
            "seed_sim": 19,
            "q_max_ev": 0,
            "q_thr_ev": 20,
        },
        random_source,
    )
    assert initial.state.metrics_points == [
        {
            "n_correct": 16,
            "n_v": 0,
            "n_i": 0,
            "n_as": 0,
            "d": 0,
            "s": 0.0,
            "revision": 0,
            "act_number": 0,
            "origin": "initialization",
        }
    ]

    stepped = engine.step(initial.state, random_source)
    assert len(stepped.state.metrics_points) == 2
    assert stepped.state.metrics_points[-1]["origin"] == "physical_act"
    assert stepped.state.metrics_points[-1]["act_number"] == 1

    source_key = next(iter(stepped.topology.metal_domain.boundary_keys))
    atom_id = stepped.state.occupied[source_key]
    destination = next(
        outcome.destination_site
        for outcome in engine.probabilities(stepped.state, atom_id, 30)
        if outcome.selectable and outcome.operation == "boundary_external"
    )
    edited = engine.move(stepped.state, atom_id, destination)
    assert len(edited.state.metrics_points) == 3
    assert edited.state.metrics_points[-1]["origin"] == "manual_edit"
    assert edited.state.metrics_points[-1]["act_number"] == 1
