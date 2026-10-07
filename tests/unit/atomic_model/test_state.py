"""Occupancy and contact invariants shared by initialization and events."""

import pytest

from backend.atomic_model.errors import StateInvariantError
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology


@pytest.mark.parametrize("dimensions", [(3, 3), (3, 3, 3)])
def test_isolated_external_atom_is_rejected_and_contact_chain_is_accepted(dimensions):
    topology = Topology.create(dimensions)
    metal = sorted(topology.metal_domain.lattice_keys)[0]
    outside = next(
        key for key in topology.contact_neighbors(metal)
        if topology.sites[key].metal_relation == "outside"
        and topology.sites[key].kind == "lattice"
    )
    further = next(
        key for key in topology.contact_neighbors(outside)
        if key != metal and topology.sites[key].metal_relation == "outside"
        and key not in topology.contact_neighbors(metal)
    )

    with pytest.raises(StateInvariantError, match="DISCONNECTED_ATOM"):
        SimulationState.from_positions(topology, {0: metal, 1: further})

    state = SimulationState.from_positions(topology, {0: metal, 1: outside, 2: further})
    assert len(state.atoms) == 3
    assert len(state.atoms) != len(topology.metal_domain.lattice_keys)


def test_duplicate_site_and_unknown_site_have_stable_codes():
    topology = Topology.create((3, 3))
    site = sorted(topology.metal_domain.lattice_keys)[0]
    with pytest.raises(StateInvariantError, match="SITE_OCCUPIED"):
        SimulationState.from_positions(topology, {0: site, 1: site})
    with pytest.raises(StateInvariantError, match="UNKNOWN_SITE"):
        SimulationState.from_positions(topology, {0: "lattice:999,999"})


@pytest.mark.parametrize("dimensions", [(3, 3), (3, 3, 3)])
def test_external_interstitial_needs_an_occupied_contact_path(dimensions):
    topology = Topology.create(dimensions)
    ideal = SimulationState.create_ideal(topology)
    attached = next(
        key for key, site in topology.sites.items()
        if site.kind == "interstitial"
        and site.metal_relation == "outside"
        and topology.contact_neighbors(key) & ideal.occupied.keys()
    )
    far = next(
        key for key, site in topology.sites.items()
        if site.kind == "interstitial"
        and site.metal_relation == "outside"
        and not topology.contact_neighbors(key) & ideal.occupied.keys()
    )
    atom_id = max(ideal.atoms) + 1
    connected = SimulationState.from_positions(topology, {**ideal.atoms, atom_id: attached})
    assert connected.atoms[atom_id] == attached
    assert len(connected.atoms) == len(topology.metal_domain.lattice_keys) + 1
    with pytest.raises(StateInvariantError, match="DISCONNECTED_ATOM"):
        SimulationState.from_positions(topology, {**ideal.atoms, atom_id: far})
