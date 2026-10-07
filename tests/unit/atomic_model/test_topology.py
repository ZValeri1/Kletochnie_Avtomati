"""Acceptance examples for the fixed metal domain and movement field."""

from backend.atomic_model.topology import Topology
from backend.atomic_model.state import SimulationState
from backend.atomic_model.errors import TopologyError
import pytest


def test_metal_domain_is_centered_in_a_fixed_three_l_field():
    topology = Topology.create((4, 3))

    assert topology.movement_field.dimensions == (12, 12)
    assert topology.metal_domain.dimensions == (4, 3)
    assert len(topology.metal_domain.lattice_keys) == 12
    assert len([site for site in topology.sites.values() if site.kind == "lattice"]) == 144
    assert len([site for site in topology.sites.values() if site.kind == "interstitial"]) == 121

    state = SimulationState.create_ideal(topology)
    assert len(state.atoms) == 12
    assert set(state.atoms.values()) == set(topology.metal_domain.lattice_keys)
    state.validate(topology)


def test_three_dimensional_field_has_lattice_and_cube_centers_everywhere():
    topology = Topology.create((3, 2, 2))
    assert topology.movement_field.dimensions == (9, 9, 9)
    assert len(topology.metal_domain.lattice_keys) == 12
    assert sum(site.kind == "lattice" for site in topology.sites.values()) == 9**3
    assert sum(site.kind == "interstitial" for site in topology.sites.values()) == 8**3
    assert {site.metal_relation for site in topology.sites.values()} == {
        "interior", "boundary", "outside"
    }
    with pytest.raises(AttributeError):
        topology.dimensions = (1, 1, 1)


@pytest.mark.parametrize("dimensions,expected", [((4, 4), 4), ((4, 4, 4), 8)])
def test_first_shell_includes_diagonal_interstitials(dimensions, expected):
    topology = Topology.create(dimensions)
    source = sorted(topology.metal_domain.lattice_keys)[0]
    diagonal = {
        key for key in topology.shell(source, 1)
        if topology.sites[key].kind == "interstitial"
    }
    assert len(diagonal) == expected
    assert len(topology.shell(source, 1)) == expected + 3 ** len(dimensions) - 1
    assert {topology.manhattan_distance(source, key) for key in diagonal} == {
        len(dimensions) / 2
    }


@pytest.mark.parametrize("dimensions,axial_count", [((3, 3), 4), ((3, 3, 3), 6)])
def test_interstitial_axial_neighbors_and_second_shell_paths(dimensions, axial_count):
    topology = Topology.create(dimensions)
    center = tuple(size // 2 for size in topology.movement_field.dimensions)
    interstitial = topology.site_at(tuple(value + 0.5 for value in center), "interstitial")
    assert len(topology.axial_interstitial_neighbors(interstitial)) == axial_count
    assert len(topology.shell(interstitial, 1)) == 3 ** len(dimensions) - 1 + 2 ** len(dimensions)
    assert all(topology.manhattan_distance(interstitial, key) == 1 for key in topology.axial_interstitial_neighbors(interstitial))
    assert not topology.axial_interstitial_neighbors(interstitial) & topology.contact_neighbors(interstitial)
    source = topology.site_at(center, "lattice")
    target = topology.site_at(tuple(value + (2 if index == 0 else 0) for index, value in enumerate(center)), "lattice")
    assert target in topology.shell(source, 2)
    paths = topology.all_shortest_paths(source, target)
    assert paths == ((source, topology.site_at(tuple(value + (1 if index == 0 else 0) for index, value in enumerate(center)), "lattice"), target),)


def test_two_dimensional_square_contours_match_the_coordinate_specification():
    topology = Topology.create((5, 5))
    lattice = topology.site_at((7, 7), "lattice")
    interstitial = topology.site_at((7.5, 7.5), "interstitial")

    assert [
        (
            sum(topology.sites[key].kind == "lattice" for key in topology.shell(lattice, radius)),
            sum(topology.sites[key].kind == "interstitial" for key in topology.shell(lattice, radius)),
        )
        for radius in (1, 2)
    ] == [(8, 4), (16, 12)]
    assert [
        (
            sum(topology.sites[key].kind == "lattice" for key in topology.shell(interstitial, radius)),
            sum(topology.sites[key].kind == "interstitial" for key in topology.shell(interstitial, radius)),
        )
        for radius in (1, 2)
    ] == [(4, 8), (12, 16)]


def test_orthogonal_contour_and_invalid_domains():
    contour = ((0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4), (0, 0))
    topology = Topology.create((5, 5), contour=contour)
    ox, oy = topology.metal_domain.offset
    assert topology.classify(f"lattice:{ox + 1},{oy + 1}") == ("lattice", "interior")
    assert topology.classify(f"lattice:{ox + 4},{oy + 4}") == ("lattice", "outside")
    assert topology.classify(f"lattice:{ox},{oy}") == ("lattice", "boundary")
    with pytest.raises(TopologyError, match="INVALID_METAL_DOMAIN"):
        Topology.create((5, 5), contour=contour[:-1])
    with pytest.raises(TopologyError, match="INVALID_METAL_DOMAIN"):
        Topology.create((5, 5), contour=((0, 0), (4, 0), (4, 4), (2, 4), (2, 2), (4, 2), (4, 0), (0, 0)))
    with pytest.raises(TopologyError, match="INVALID_METAL_DOMAIN"):
        Topology.create((5, 5), contour=((0, 0), (4, 0), (4, 4), (1, 4), (1, 1), (3, 1), (3, 3), (0, 3), (0, 0)))
    with pytest.raises(TopologyError, match="INVALID_METAL_DOMAIN"):
        Topology.create((3, 3, 3), contour=contour)


def test_three_dimensional_shortest_paths_exclude_longer_cube_center_detours():
    topology = Topology.create((3, 3, 3))
    source = topology.site_at((4, 4, 4), "lattice")
    target = topology.site_at((5, 5, 4), "lattice")
    paths = topology.all_shortest_paths(source, target)
    assert len(paths) == 2
    assert all(len(path) == 3 for path in paths)
    assert all(all(topology.sites[key].kind == "lattice" for key in path) for path in paths)


def test_two_dimensional_diagonal_has_all_three_manhattan_shortest_paths():
    topology = Topology.create((3, 3))
    source = topology.site_at((4, 4), "lattice")
    target = topology.site_at((5, 5), "lattice")
    paths = topology.all_shortest_paths(source, target)
    assert len(paths) == 3
    assert {path[1] for path in paths} == {
        "lattice:4,5", "lattice:5,4", "interstitial:4.5,4.5"
    }


def test_field_boundary_is_fixed_and_reported():
    topology = Topology.create((3, 3))
    with pytest.raises(TopologyError, match="POSITION_OUTSIDE_FIELD"):
        topology.site_at((-0.5, 0), "interstitial")
    edge = topology.site_at((0, 0), "lattice")
    assert topology.near_field_boundary(edge, 0)
    assert topology.movement_field.dimensions == (9, 9)
    with pytest.raises(TopologyError, match="DIMENSION_MISMATCH"):
        topology.classify("lattice:0,0,0")
    with pytest.raises(TopologyError, match="UNSUPPORTED_SHELL"):
        topology.shell(edge, 3)
