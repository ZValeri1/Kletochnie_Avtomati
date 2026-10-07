"""P2 acceptance cases for independent initial defect categories."""

import pytest

from backend.atomic_model.errors import InitializationError
from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import RandomSource
from backend.atomic_model.initialization import Initializer, InitializationCounts
from backend.atomic_model.topology import Topology


@pytest.mark.parametrize("dimensions", [(4, 4), (3, 3, 3)])
def test_ordered_fills_only_metal_lattice(dimensions):
    topology = Topology.create(dimensions)
    state = Initializer().build(
        topology, {"initialization_mode": "ordered", "seed_init": 17}
    )
    counts = InitializationCounts.from_state(topology, state)
    assert counts.n0 == len(topology.metal_domain.lattice_keys)
    assert counts.n_atoms == counts.n0
    assert (counts.n_v, counts.n_i, counts.n_as) == (0, 0, 0)
    assert set(state.atoms.values()) == topology.metal_domain.lattice_keys
    state.validate(topology)


@pytest.mark.parametrize(
    "n_v,n_i,n_as",
    [(3, 0, 0), (0, 2, 1), (2, 1, 1)],
)
@pytest.mark.parametrize("dimensions", [(4, 4), (3, 3, 3)])
def test_explicit_counts_are_independent_and_can_change_total_atoms(
    dimensions, n_v, n_i, n_as
):
    topology = Topology.create(dimensions)
    state = Initializer().build(
        topology,
        {
            "initialization_mode": "explicit_defective",
            "seed_init": 23,
            "n_v": n_v,
            "n_i": n_i,
            "n_as": n_as,
        },
    )
    counts = InitializationCounts.from_state(topology, state)
    assert (counts.n_v, counts.n_i, counts.n_as) == (n_v, n_i, n_as)
    assert counts.n_atoms == counts.n0 - n_v + n_i + n_as
    state.validate(topology)


def test_symmetric_mode_requires_aggregate_balance():
    topology = Topology.create((4, 4))
    state = Initializer().build(
        topology,
        {
            "initialization_mode": "symmetric_defective",
            "seed_init": 29,
            "n_v": 2,
            "n_i": 1,
            "n_as": 1,
        },
    )
    counts = InitializationCounts.from_state(topology, state)
    assert counts.n_atoms == counts.n0
    assert (counts.n_v, counts.n_i, counts.n_as) == (2, 1, 1)
    with pytest.raises(InitializationError, match="INVALID_DEFECT_COUNT"):
        Initializer().build(
            topology,
            {"initialization_mode": "symmetric_defective", "n_v": 2, "n_i": 0, "n_as": 1},
        )


def test_three_dimensional_symmetric_and_random_modes_are_reproducible():
    topology = Topology.create((3, 3, 3))
    symmetric = {
        "initialization_mode": "symmetric_defective",
        "seed_init": 9, "n_v": 2, "n_i": 1, "n_as": 1,
    }
    balanced = Initializer().build(topology, symmetric)
    assert InitializationCounts.from_state(topology, balanced).n_atoms == 27
    random_config = {"initialization_mode": "random_defective", "seed_init": 61}
    assert Initializer().build(topology, random_config).to_dict() == Initializer().build(topology, random_config).to_dict()


def test_random_mode_replays_seed_and_can_draw_both_sides_of_n0():
    topology = Topology.create((4, 4))
    base = {
        "initialization_mode": "random_defective",
        "seed_init": 31,
        "random_parameters": {
            "vacancies": {"mu": 3, "sigma": 0},
            "interstitials": {"mu": 0, "sigma": 0},
            "adatoms": {"mu": 0, "sigma": 0},
        },
    }
    left = Initializer().build(topology, base)
    right = Initializer().build(topology, base)
    assert left.to_dict() == right.to_dict()
    assert InitializationCounts.from_state(topology, left).n_atoms < 16

    richer = {
        **base,
        "random_parameters": {
            "vacancies": {"mu": 0, "sigma": 0},
            "interstitials": {"mu": 2, "sigma": 0},
            "adatoms": {"mu": 1, "sigma": 0},
        },
    }
    grown = Initializer().build(topology, richer)
    assert InitializationCounts.from_state(topology, grown).n_atoms > 16


def test_impossible_counts_raise_without_a_partial_result():
    topology = Topology.create((2, 2))
    with pytest.raises(InitializationError, match="INITIAL_CONFIGURATION_INFEASIBLE"):
        Initializer().build(
            topology,
            {"initialization_mode": "explicit_defective", "n_v": 0, "n_i": 999},
        )


@pytest.mark.parametrize("seed", range(12))
def test_random_counts_remain_independent_across_seeds(seed):
    topology = Topology.create((4, 4))
    parameters = {
        "vacancies": {"mu": 1, "sigma": 0.5},
        "interstitials": {"mu": 1, "sigma": 0.5},
        "adatoms": {"mu": 1, "sigma": 0.5},
    }
    base = {"initialization_mode": "random_defective", "seed_init": seed}
    original = Initializer().build(topology, {**base, "random_parameters": parameters})
    changed = Initializer().build(
        topology,
        {
            **base,
            "random_parameters": {
                **parameters,
                "vacancies": {"mu": 4, "sigma": 0.5},
            },
        },
    )
    original_counts = InitializationCounts.from_state(topology, original)
    changed_counts = InitializationCounts.from_state(topology, changed)
    assert (original_counts.n_i, original_counts.n_as) == (
        changed_counts.n_i, changed_counts.n_as
    )
    assert Initializer().build(topology, {**base, "random_parameters": parameters}).to_dict() == original.to_dict()


def test_initial_seed_does_not_consume_the_physical_rng():
    configuration = {
        "dimensions": [4, 4],
        "initialization_mode": "random_defective",
        "seed_init": 101,
    }
    left_rng = RandomSource(1)
    right_rng = RandomSource(2)
    before_left = left_rng.get_state()
    before_right = right_rng.get_state()
    engine = SimulationEngine()
    left = engine.create_initial_state(configuration, left_rng)
    right = engine.create_initial_state(configuration, right_rng)
    assert left.state.atoms == right.state.atoms
    assert left_rng.get_state() == before_left
    assert right_rng.get_state() == before_right
