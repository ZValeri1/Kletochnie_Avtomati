"""Revision 4 (17.10.2026) of the CA rules: tuned to the Monte Carlo behaviour.

No instant (athermal) recombination of all close pairs after every act; a
pair recombines only when its interstitial is hit.  Adatoms are targets and
move over the outside positions, never back into the metal.
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


def test_revision_4_switches():
    assert C.INSTANT_RECOMBINATION is False
    assert C.MOBILE_ADATOMS is True


def test_adatoms_are_targets():
    topology, state = ideal(5)
    atom = state.occupied["lattice:5,5"]
    state.relocate(atom, "interstitial:4.5,4.5")
    assert atom in C.target_atoms(topology, state)
    assert len(C.target_atoms(topology, state)) == 25


def test_close_pair_survives_until_its_interstitial_is_hit():
    topology, state = ideal()
    # a far displacement of another atom does not relax the close pair
    a = state.occupied["lattice:14,14"]
    state.relocate(a, "interstitial:14.5,14.5")
    b = state.occupied["lattice:10,10"]
    flights, recombinations = C.ca_act_moves(topology, state, b, 30.0, 23.0, 0)
    assert flights and not recombinations
    # hitting the interstitial makes it recombine with the nearest vacancy
    flights, recombinations = C.ca_act_moves(topology, state, a, 30.0, 23.0, 0)
    assert flights == []
    assert recombinations == [(a, "interstitial:14.5,14.5", "lattice:14,14")]


def test_hit_adatom_moves_outside_only_and_stays_in_contact():
    topology, state = ideal(5)
    atom = state.occupied["lattice:9,7"]
    state.relocate(atom, "interstitial:9.5,7.5")
    assert topology.sites["interstitial:9.5,7.5"].metal_relation == "outside"
    for act in range(8):
        dest = C.adatom_destination(
            topology, state.occupied, atom, state.atoms[atom], 30.0, act)
        if dest is None:
            continue
        assert topology.sites[dest].metal_relation == "outside"
        trial = dict(state.occupied)
        del trial[state.atoms[atom]]
        trial[dest] = atom
        topology.validate_occupancy(trial)


def test_defects_keep_growing_without_instant_recombination():
    engine = SimulationEngine()
    result = engine.create_initial_state(dict(CONFIG), RandomSource(1))
    state, rng = result.state, RandomSource(2)
    for _ in range(600):
        step = engine.step(state, rng)
        state = step.state
        if step.event.result_reason == "BELOW_THRESHOLD":
            assert step.event.operation == "no_change"
    # without athermal relaxation interstitials exceed the Pease limit
    assert step.metrics.n_i > 0.0433 * 100 + 1


def test_outside_atoms_stay_within_five_percent_of_lattice_length():
    assert C.outside_depth_limit(Topology.create((20, 20))) == 1
    assert C.outside_depth_limit(Topology.create((100, 100))) == 5
    topology, state = ideal(20)
    atom = state.occupied["lattice:39,30"]          # boundary atom of the +x face
    state.relocate(atom, "interstitial:39.5,30.5")  # first outside position
    for act in range(16):
        dest = C.adatom_destination(
            topology, state.occupied, atom, state.atoms[atom], 82.0, act)
        if dest is not None:
            assert C.outside_depth(topology, dest) <= 1
