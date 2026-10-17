"""Revision 3 (16.10.2026) of the CA rules: literature-aligned damage model.

Kinchin & Pease 1955 (random Frenkel pairs, flight of 4-5 distances, Pease
capture model), Norgett-Robinson-Torrens 1975 (vacancy capture radius),
Voskoboynikov 2020 (E_d, cohesive energy).
"""
from backend.atomic_model import ca_rules as C
from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.events import RandomSource
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology

CONFIG = {
    "dimensions": [10, 10], "method": "cellular_automata",
    "profile": "fe_co60_physical", "q_max_ev": 82.0, "seed_init": 1, "seed_sim": 2,
}


def ideal(dim=10):
    topology = Topology.create((dim, dim))
    state = SimulationState.create_ideal(topology, dict(CONFIG, dimensions=[dim, dim]))
    return topology, state


def test_flight_length_follows_energy_halving_and_is_capped():
    assert C.flight_length(1.0) == 1
    assert C.flight_length(4.0) == 2
    assert C.flight_length(16.0) == 4
    assert C.flight_length(23.0) == 5          # ceil(log2 23) = 5
    assert C.flight_length(500.0) == C.MAX_FLIGHT == 5


def test_capture_zone_has_16_sites_in_2d():
    topology, state = ideal()
    key = "interstitial:14.5,14.5"
    free = {}  # nothing occupied -> every lattice site of the zone is free
    zone = C.capture_zone_vacancies(topology, free, key)
    assert len(zone) == 16
    # nearest (Chebyshev 0.5) sites come first
    assert set(zone[:4]) == {"lattice:14,14", "lattice:15,14", "lattice:14,15", "lattice:15,15"}


def test_uniform_target_excludes_adatoms():
    topology, state = ideal(5)
    atom = state.occupied["lattice:5,5"]  # a corner atom of the 5x5 metal
    state.relocate(atom, "interstitial:4.5,4.5")  # outside the metal -> adatom
    assert topology.sites["interstitial:4.5,4.5"].metal_relation == "outside"
    targets = C.metal_atoms(topology, state)
    assert atom not in targets
    assert len(targets) == 24


def test_close_pair_recombines_far_pair_is_stable():
    topology, state = ideal()
    atoms, occupied = dict(state.atoms), dict(state.occupied)
    # close pair: interstitial next to its vacancy -> recombines
    a = occupied.pop("lattice:14,14"); occupied["interstitial:14.5,14.5"] = a
    atoms[a] = "interstitial:14.5,14.5"
    moves = C.relax_unstable_pairs(topology, atoms, occupied)
    assert moves == [(a, "interstitial:14.5,14.5", "lattice:14,14")]
    # far pair (4.5 distances): stable
    atoms, occupied = dict(state.atoms), dict(state.occupied)
    a = occupied.pop("lattice:12,14"); occupied["interstitial:16.5,14.5"] = a
    atoms[a] = "interstitial:16.5,14.5"
    assert C.relax_unstable_pairs(topology, atoms, occupied) == []


def test_frenkel_pair_flies_four_and_a_half_distances_and_survives():
    topology, state = ideal()
    atom = state.occupied["lattice:12,14"]
    flights, recombinations = C.ca_act_moves(topology, state, atom, 30.0, 23.0, 0)
    assert len(flights) == 1 and not recombinations
    _, src, dst = flights[0]
    distance = C._chebyshev(topology, src, dst) / 2
    assert distance == 4.5
    assert topology.sites[dst].kind == "interstitial"


def test_no_move_of_stable_atoms_below_threshold_and_damage_accumulates():
    engine = SimulationEngine()
    result = engine.create_initial_state(dict(CONFIG), RandomSource(1))
    state, rng = result.state, RandomSource(2)
    d_values = []
    for _ in range(400):
        step = engine.step(state, rng)
        state = step.state
        d_values.append(step.metrics.d)
        if step.event.result_reason == "BELOW_THRESHOLD":
            assert step.event.operation == "no_change"
    # defects accumulate from a perfect lattice (Kinchin-Pease, sec. 3.3)
    assert max(d_values) > 2
    # interstitial concentration stays below Pease saturation ln2/16 = 4.3 %
    assert step.metrics.n_i <= 0.0433 * 100 + 1


def test_atom_leaves_surface_only_with_enough_energy():
    topology, state = ideal(5)
    # boundary atom of the far face along +x; act 0 travels towards +x
    atom = state.occupied["lattice:9,7"]
    low = C.flight_destination(topology, state.occupied, atom, "lattice:9,7", 4.0, 0)
    high = C.flight_destination(topology, state.occupied, atom, "lattice:9,7", 30.0, 0)
    assert topology.sites[high].metal_relation == "outside"
    assert low is None or topology.sites[low].metal_relation != "outside"
