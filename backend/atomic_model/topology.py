from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from types import MappingProxyType
from typing import Literal

from backend.atomic_model.errors import TopologyError

SiteKind = Literal["lattice", "interstitial"]
MetalRelation = Literal["interior", "boundary", "outside"]


@dataclass(frozen=True)
class MovementField:
    dimensions: tuple[int, ...]

    def contains(self, coordinates: tuple[float, ...]) -> bool:
        return len(coordinates) == len(self.dimensions) and all(
            0 <= coordinate < size for coordinate, size in zip(coordinates, self.dimensions)
        )

    def distance_to_boundary(self, coordinates: tuple[float, ...]) -> float:
        if not self.contains(coordinates):
            raise TopologyError("POSITION_OUTSIDE_FIELD")
        return min(
            min(coordinate, size - 1 - coordinate)
            for coordinate, size in zip(coordinates, self.dimensions)
        )


@dataclass(frozen=True)
class MetalDomain:
    dimensions: tuple[int, ...]
    offset: tuple[int, ...]
    lattice_keys: frozenset[str]
    boundary_keys: frozenset[str]
    contour: tuple[tuple[int, int], ...] | None = None


@dataclass(frozen=True)
class Site:
    kind: SiteKind
    half_units: tuple[int, ...]
    metal_relation: MetalRelation

    @property
    def coordinate(self) -> tuple[float, ...]:
        return tuple(value / 2 for value in self.half_units)

    @property
    def key(self) -> str:
        values = ",".join(f"{value / 2:g}" for value in self.half_units)
        return f"{self.kind}:{values}"

    @property
    def dimension(self) -> int:
        return len(self.half_units)


def _site_key(kind: SiteKind, coordinates: tuple[int, ...]) -> str:
    return Site(kind, tuple(2 * value for value in coordinates), "outside").key


def _segments_cross(
    first: tuple[tuple[int, int], tuple[int, int]],
    second: tuple[tuple[int, int], tuple[int, int]],
) -> bool:
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second
    if ax == bx and cx == dx:
        return ax == cx and max(min(ay, by), min(cy, dy)) <= min(max(ay, by), max(cy, dy))
    if ay == by and cy == dy:
        return ay == cy and max(min(ax, bx), min(cx, dx)) <= min(max(ax, bx), max(cx, dx))
    if ax == bx:
        return min(cx, dx) <= ax <= max(cx, dx) and min(ay, by) <= cy <= max(ay, by)
    return min(ax, bx) <= cx <= max(ax, bx) and min(cy, dy) <= ay <= max(cy, dy)


def _validated_contour(
    contour: Iterable[tuple[int, int]], dimensions: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    try:
        vertices = tuple(tuple(point) for point in contour)
    except (TypeError, ValueError) as error:
        raise TopologyError("INVALID_METAL_DOMAIN") from error
    if len(vertices) < 5 or vertices[0] != vertices[-1]:
        raise TopologyError("INVALID_METAL_DOMAIN")
    if any(
        len(point) != 2
        or any(type(value) is not int for value in point)
        or any(not 0 <= point[axis] < dimensions[axis] for axis in range(2))
        for point in vertices
    ):
        raise TopologyError("INVALID_METAL_DOMAIN")
    edges = list(zip(vertices, vertices[1:]))
    if len(set(vertices[:-1])) != len(vertices) - 1:
        raise TopologyError("INVALID_METAL_DOMAIN")
    if any(
        left == right or ((left[0] == right[0]) == (left[1] == right[1]))
        for left, right in edges
    ):
        raise TopologyError("INVALID_METAL_DOMAIN")
    for index in range(len(edges)):
        before = edges[index - 1]
        after = edges[index]
        if (
            before[0][0] == before[1][0] == after[1][0]
            and (before[1][1] - before[0][1]) * (after[1][1] - after[0][1]) < 0
        ) or (
            before[0][1] == before[1][1] == after[1][1]
            and (before[1][0] - before[0][0]) * (after[1][0] - after[0][0]) < 0
        ):
            raise TopologyError("INVALID_METAL_DOMAIN")
    for i, first in enumerate(edges):
        for j in range(i + 1, len(edges)):
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if _segments_cross(first, edges[j]):
                raise TopologyError("INVALID_METAL_DOMAIN")
    area2 = sum(left[0] * right[1] - right[0] * left[1] for left, right in edges)
    if area2 == 0:
        raise TopologyError("INVALID_METAL_DOMAIN")
    return vertices


def _inside_polygon(
    half_point: tuple[int, int], contour: tuple[tuple[int, int], ...]
) -> bool:
    x, y = half_point
    inside = False
    for (ax, ay), (bx, by) in zip(contour, contour[1:]):
        if (ax == bx and x == 2 * ax and 2 * min(ay, by) <= y <= 2 * max(ay, by)) or (
            ay == by and y == 2 * ay and 2 * min(ax, bx) <= x <= 2 * max(ax, bx)
        ):
            return True
        if ax == bx and (2 * ay > y) != (2 * by > y) and x < 2 * ax:
            inside = not inside
    return inside


class Topology:
    __slots__ = (
        "metal_domain",
        "movement_field",
        "dimensions",
        "sites",
        "contact_graph",
        "movement_graph",
        "shortest_path_graph",
        "_frozen",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Topology is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        metal_domain: MetalDomain,
        movement_field: MovementField,
        sites: dict[str, Site],
        contact_graph: dict[str, set[str]],
        movement_graph: dict[str, set[str]],
    ) -> None:
        self.metal_domain = metal_domain
        self.movement_field = movement_field
        self.dimensions = metal_domain.dimensions
        self.sites: Mapping[str, Site] = MappingProxyType(dict(sites))
        self.contact_graph: Mapping[str, frozenset[str]] = MappingProxyType(
            {key: frozenset(value) for key, value in contact_graph.items()}
        )
        self.movement_graph: Mapping[str, frozenset[str]] = MappingProxyType(
            {key: frozenset(value) for key, value in movement_graph.items()}
        )
        self.shortest_path_graph = self.movement_graph
        self._frozen = True

    @classmethod
    def create(
        cls,
        dimensions: tuple[int, ...] | list[int],
        contour: Iterable[tuple[int, int]] | None = None,
    ) -> Topology:
        dimensions = tuple(dimensions)
        if len(dimensions) not in (2, 3) or any(
            type(size) is not int or size < 2 for size in dimensions
        ):
            raise TopologyError("INVALID_METAL_DOMAIN")
        if len(dimensions) == 3 and contour is not None:
            raise TopologyError("INVALID_METAL_DOMAIN")
        if len(dimensions) == 2:
            contour = _validated_contour(
                contour
                if contour is not None
                else (
                    (0, 0),
                    (dimensions[0] - 1, 0),
                    (dimensions[0] - 1, dimensions[1] - 1),
                    (0, dimensions[1] - 1),
                    (0, 0),
                ),
                dimensions,
            )
        field_size = 3 * max(dimensions)
        field = MovementField((field_size,) * len(dimensions))
        offset = tuple((field_size - size) // 2 for size in dimensions)
        metal_points = {
            tuple(offset[axis] + value for axis, value in enumerate(point))
            for point in product(*(range(size) for size in dimensions))
            if len(dimensions) == 3
            or _inside_polygon(tuple(2 * value for value in point), contour)
        }
        if not metal_points:
            raise TopologyError("INVALID_METAL_DOMAIN")
        connected = {next(iter(metal_points))}
        queue = deque(connected)
        while queue:
            point = queue.popleft()
            for axis in range(len(dimensions)):
                for delta in (-1, 1):
                    neighbor = tuple(
                        value + (delta if index == axis else 0)
                        for index, value in enumerate(point)
                    )
                    if neighbor in metal_points and neighbor not in connected:
                        connected.add(neighbor)
                        queue.append(neighbor)
        if connected != metal_points:
            raise TopologyError("INVALID_METAL_DOMAIN")
        metal_keys = frozenset(_site_key("lattice", point) for point in metal_points)
        boundary_keys = frozenset(
            _site_key("lattice", point)
            for point in metal_points
            if any(
                tuple(
                    point[index] + (delta if index == axis else 0)
                    for index in range(len(dimensions))
                )
                not in metal_points
                for axis in range(len(dimensions))
                for delta in (-1, 1)
            )
        )
        domain = MetalDomain(dimensions, offset, metal_keys, boundary_keys, contour)
        sites: dict[str, Site] = {}
        contacts: dict[str, set[str]] = {}
        movements: dict[str, set[str]] = {}

        def add(site: Site) -> None:
            sites[site.key] = site
            contacts[site.key] = set()
            movements[site.key] = set()

        def link(graph: dict[str, set[str]], left: str, right: str) -> None:
            graph[left].add(right)
            graph[right].add(left)

        for point in product(*(range(size) for size in field.dimensions)):
            key = _site_key("lattice", point)
            relation: MetalRelation = (
                "boundary"
                if key in boundary_keys
                else "interior" if key in metal_keys else "outside"
            )
            add(Site("lattice", tuple(2 * value for value in point), relation))
        for cell in product(*(range(size - 1) for size in field.dimensions)):
            half_units = tuple(2 * value + 1 for value in cell)
            if len(dimensions) == 2:
                local = tuple(2 * (cell[axis] - offset[axis]) + 1 for axis in range(2))
                relation = "interior" if _inside_polygon(local, contour) else "outside"
            else:
                relation = (
                    "interior"
                    if all(
                        tuple(cell[axis] + delta[axis] for axis in range(3)) in metal_points
                        for delta in product((0, 1), repeat=3)
                    )
                    else "outside"
                )
            site = Site("interstitial", half_units, relation)
            add(site)
            for delta in product((0, 1), repeat=len(dimensions)):
                support = _site_key(
                    "lattice",
                    tuple(cell[axis] + delta[axis] for axis in range(len(dimensions))),
                )
                link(contacts, site.key, support)
                link(movements, site.key, support)
        for point in product(*(range(size) for size in field.dimensions)):
            left = _site_key("lattice", point)
            for axis in range(len(dimensions)):
                if point[axis] + 1 < field.dimensions[axis]:
                    other = list(point)
                    other[axis] += 1
                    right = _site_key("lattice", tuple(other))
                    link(contacts, left, right)
                    link(movements, left, right)
        for cell in product(*(range(size - 1) for size in field.dimensions)):
            left = Site("interstitial", tuple(2 * value + 1 for value in cell), "outside").key
            for axis in range(len(dimensions)):
                if cell[axis] + 1 < field.dimensions[axis] - 1:
                    other = list(cell)
                    other[axis] += 1
                    right = Site(
                        "interstitial", tuple(2 * value + 1 for value in other), "outside"
                    ).key
                    link(movements, left, right)
        return cls(domain, field, sites, contacts, movements)

    def _site(self, site_key: str) -> Site:
        try:
            return self.sites[site_key]
        except KeyError as error:
            if (
                isinstance(site_key, str)
                and site_key.partition(":")[0] in ("lattice", "interstitial")
                and ":" in site_key
                and site_key.count(",") + 1 != len(self.dimensions)
            ):
                raise TopologyError("DIMENSION_MISMATCH") from error
            raise TopologyError("UNKNOWN_SITE") from error

    def site_at(self, coordinates: tuple[float, ...], kind: SiteKind) -> str | None:
        coordinates = tuple(coordinates)
        if len(coordinates) != len(self.dimensions):
            raise TopologyError("DIMENSION_MISMATCH")
        if not self.movement_field.contains(coordinates):
            raise TopologyError("POSITION_OUTSIDE_FIELD")
        half_units = tuple(round(value * 2) for value in coordinates)
        if any(abs(value * 2 - half) > 1e-9 for value, half in zip(coordinates, half_units)):
            return None
        key = Site(kind, half_units, "outside").key
        return key if key in self.sites else None

    def classify(self, site_key: str) -> tuple[SiteKind, MetalRelation]:
        site = self._site(site_key)
        return site.kind, site.metal_relation

    def contact_neighbors(self, site_key: str) -> frozenset[str]:
        self._site(site_key)
        return self.contact_graph[site_key]

    def axial_interstitial_neighbors(self, site_key: str) -> frozenset[str]:
        site = self._site(site_key)
        if site.kind != "interstitial":
            return frozenset()
        return frozenset(
            key for key in self.movement_graph[site_key]
            if self.sites[key].kind == "interstitial"
        )

    def manhattan_distance(self, source: str, target: str) -> float:
        left, right = self._site(source), self._site(target)
        if left.dimension != right.dimension:
            raise TopologyError("DIMENSION_MISMATCH")
        return sum(abs(a - b) for a, b in zip(left.half_units, right.half_units)) / 2

    def shell(self, source: str, radius: int) -> frozenset[str]:
        origin = self._site(source)
        if radius not in (1, 2):
            raise TopologyError("UNSUPPORTED_SHELL")
        return frozenset(
            key for key, site in self.sites.items()
            if key != source
            # A contour is a square in 2D and a cube in 3D.  Sites on the
            # other sub-lattice are shifted by half a cell, so their contour
            # radii are 0.5 and 1.5 instead of 1 and 2.
            and max(
                abs(a - b) for a, b in zip(origin.half_units, site.half_units)
            )
            == (2 * radius if site.kind == origin.kind else 2 * radius - 1)
        )

    def all_shortest_paths(self, source: str, target: str) -> tuple[tuple[str, ...], ...]:
        origin = self._site(source)
        destination = self._site(target)

        def distance(left: Site, right: Site) -> int:
            return sum(abs(a - b) for a, b in zip(left.half_units, right.half_units))

        total = distance(origin, destination)

        @lru_cache(maxsize=None)
        def paths(current: str) -> tuple[tuple[str, ...], ...]:
            if current == target:
                return ((target,),)
            here = self.sites[current]
            used = distance(origin, here)
            result = []
            for neighbor in sorted(self.shortest_path_graph[current]):
                next_site = self.sites[neighbor]
                next_used = distance(origin, next_site)
                if next_used <= used or (
                    used + distance(here, next_site) + distance(next_site, destination)
                    != total
                ):
                    continue
                result.extend((current,) + suffix for suffix in paths(neighbor))
            return tuple(result)

        result = paths(source)
        if not result:
            raise TopologyError("NO_PATH")
        return result

    def validate_occupancy(self, occupied: Mapping[str, int]) -> None:
        for key in occupied:
            self._site(key)
        if len(set(occupied.values())) != len(occupied):
            raise TopologyError("SITE_OCCUPIED")
        roots = self.metal_domain.lattice_keys & occupied.keys()
        reached = set(roots)
        queue = deque(roots)
        while queue:
            for neighbor in self.contact_graph[queue.popleft()]:
                if neighbor in occupied and neighbor not in reached:
                    reached.add(neighbor)
                    queue.append(neighbor)
        if any(
            key not in reached
            for key in occupied
            if key not in self.metal_domain.lattice_keys
        ):
            raise TopologyError("DISCONNECTED_ATOM")

    def near_field_boundary(self, site_key: str, warning_distance: float) -> bool:
        return self.movement_field.distance_to_boundary(
            self._site(site_key).coordinate
        ) <= warning_distance

    def neighbors(self, site_key: str) -> dict[str, float]:
        self._site(site_key)
        return {key: 1.0 for key in self.movement_graph[site_key]}

    @staticmethod
    def distance(left: Site, right: Site) -> float:
        if left.dimension != right.dimension:
            raise TopologyError("DIMENSION_MISMATCH")
        return sum(abs(a - b) for a, b in zip(left.half_units, right.half_units)) / 2
