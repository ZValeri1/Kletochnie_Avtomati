import hashlib
import json
import pickle

import pytest

from backend.atomic_model.acceleration import ComputeBackend
from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import RandomSource
from backend.atomic_model.metrics import MetricsCalculator
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology


@pytest.mark.parametrize("method,size,expected", [
    ("monte_carlo", 4, "7db9f2901089b9f58f4719cc5845b08919d7c0eba364ee11dd5204ef6ab20041"),
    ("monte_carlo", 8, "8bef62e2ff2a8e1424493ba3305bd5fb15cbbd27ee094c6c32237beb13aa0e1f"),
    ("cellular_automata", 4, "a523b202fda2bb338277df887543b1c14a15f0a673fc85b84342af884b251d4a"),
    ("cellular_automata", 8, "d8892cbbbc50bac48375593ab3731a0185adda0657dfe38aaef84c194b5948c9"),
])
def test_trajectory_matches_pre_optimization_golden(method, size, expected):
    engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    rng = RandomSource(42)
    state = engine.create_initial_state({"dimensions": [size, size], "seed_init": 41,
        "seed_sim": 42, "method": method}, rng).state
    rows = []
    for _ in range(100):
        state = engine.step(state.transition_copy(include_history=False), rng).state
        rows.append({k: v for k, v in state.events[-1].items() if k not in ("event_id", "timestamp")})
    payload = {"atoms": dict(state.atoms), "metrics": state.metrics_points[-1], "rng": rng.get_state(), "events": rows}
    assert hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() == expected


def test_million_atom_state_is_implicit_and_copy_on_write():
    engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    rng = RandomSource(42)
    state = engine.create_initial_state({"dimensions": [1000, 1000], "seed_init": 41, "seed_sim": 42}, rng).state
    original = state.transition_copy()
    for _ in range(100):
        state = engine.step(state.transition_copy(include_history=False), rng).state
    assert len(state.atoms) == 1_000_000
    assert len(list(original.atoms.changed_keys())) == 0
    assert len(list(state.atoms.changed_keys())) < 100
    serialized = state.to_dict()
    assert serialized["storage"] == "sparse_regular_v1"
    assert len(json.dumps(serialized)) < 100_000
    restored = SimulationState.from_dict(json.loads(json.dumps(serialized)))
    topology = engine._topology(state.configuration)
    assert MetricsCalculator().calculate(topology, state) == MetricsCalculator().calculate(topology, restored)
    assert {key: restored.atoms[key] for key in state.atoms.changed_keys()} == {key: state.atoms[key] for key in state.atoms.changed_keys()}
    assert len(pickle.dumps(state.transition_copy(include_history=False))) < 200_000


def test_local_connectivity_and_incremental_metrics_match_full_audit():
    engine = SimulationEngine(compute_backend=ComputeBackend("cpu"))
    rng = RandomSource(157)
    result = engine.create_initial_state({"dimensions": [5, 5], "seed_init": 41, "seed_sim": 157,
        "initialization_mode": "explicit_defective", "n_v": 5, "n_i": 3, "n_as": 3}, rng)
    state, topology = result.state, result.topology
    for _ in range(100):
        state = engine.step(state.transition_copy(include_history=False), rng).state
        full = SimulationState(atoms=dict(state.atoms), occupied=dict(state.occupied), configuration=state.configuration)
        full.validate(topology)
        assert MetricsCalculator().calculate(topology, full) == MetricsCalculator().calculate(topology, state)


def test_implicit_sites_neighbors_and_shells_match_coordinate_reference():
    topology = Topology.create((3, 4))
    sites = dict(topology.sites)
    for key, site in sites.items():
        for radius in (1, 2):
            expected = frozenset(other for other, target in sites.items() if other != key and
                max(abs(a - b) for a, b in zip(site.half_units, target.half_units)) ==
                (2 * radius if site.kind == target.kind else 2 * radius - 1))
            assert topology.shell(key, radius) == expected
        for neighbor in topology.contact_neighbors(key):
            assert key in topology.contact_neighbors(neighbor)
