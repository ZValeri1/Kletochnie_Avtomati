"""Implicit regular geometry. Memory depends on axis lengths, not field volume."""
from collections.abc import Mapping, Set
from functools import lru_cache
from itertools import product
from math import prod


def key_at(kind, point):
    return kind + ":" + ",".join(f"{value / 2:g}" for value in point)


@lru_cache(maxsize=16384)
def parse_key(key):
    kind, values = key.split(":")
    point = tuple(float(value) * 2 for value in values.split(","))
    if any(not value.is_integer() for value in point):
        raise ValueError("Off-grid position")
    return kind, tuple(int(value) for value in point)


class RegularSites(Mapping):
    __hash__ = object.__hash__
    __eq__ = object.__eq__
    def __init__(self, dimensions, offset, field):
        self.dimensions, self.offset, self.field = dimensions, offset, field

    @lru_cache(maxsize=16384)
    def __getitem__(self, key):
        from backend.atomic_model.topology import Site
        try:
            kind, point = parse_key(key)
            parity = {"lattice": 0, "interstitial": 1}[kind]
            if len(point) != len(self.field) or any(
                value % 2 != parity or not 0 <= value <= 2 * (size - 1) - parity
                for value, size in zip(point, self.field)
            ) or key_at(kind, point) != key:
                raise ValueError("Off-grid position")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise KeyError(key) from None
        inside = all(2 * low <= value <= 2 * (low + size - 1)
                     for value, low, size in zip(point, self.offset, self.dimensions))
        boundary = kind == "lattice" and any(value in (2 * low, 2 * (low + size - 1))
                     for value, low, size in zip(point, self.offset, self.dimensions))
        return Site(kind, point, ("boundary" if boundary else "interior") if inside else "outside")

    def __iter__(self):
        for kind, parity in (("lattice", 0), ("interstitial", 1)):
            for point in product(*(range(parity, 2 * size - 1, 2) for size in self.field)):
                yield key_at(kind, point)

    def __len__(self):
        return prod(self.field) + prod(size - 1 for size in self.field)


class RegularGraph(Mapping):
    __hash__ = object.__hash__
    __eq__ = object.__eq__
    def __init__(self, sites, movement=False):
        self.sites, self.movement = sites, movement

    @lru_cache(maxsize=16384)
    def __getitem__(self, key):
        site = self.sites[key]
        candidates = []
        if self.movement or site.kind == "lattice":
            for axis in range(site.dimension):
                for delta in (-2, 2):
                    point = list(site.half_units)
                    point[axis] += delta
                    candidates.append(key_at(site.kind, point))
        opposite = "interstitial" if site.kind == "lattice" else "lattice"
        candidates.extend(key_at(opposite, tuple(a + b for a, b in zip(site.half_units, delta)))
                          for delta in product((-1, 1), repeat=site.dimension))
        return frozenset(key for key in candidates if key in self.sites)

    def __iter__(self):
        return iter(self.sites)

    def __len__(self):
        return len(self.sites)


class MetalKeys(Set):
    def __init__(self, dimensions, offset, boundary=False):
        self.dimensions, self.offset, self.boundary = dimensions, offset, boundary

    def __contains__(self, key):
        try:
            kind, point = parse_key(key)
            return kind == "lattice" and len(point) == len(self.dimensions) and all(
                value % 2 == 0 and 2 * low <= value <= 2 * (low + size - 1)
                for value, low, size in zip(point, self.offset, self.dimensions)
            ) and (not self.boundary or any(value in (2 * low, 2 * (low + size - 1))
                for value, low, size in zip(point, self.offset, self.dimensions)))
        except (ValueError, TypeError, AttributeError):
            return False

    def __iter__(self):
        if not self.boundary:
            for point in product(*(range(low, low + size) for low, size in zip(self.offset, self.dimensions))):
                yield key_at("lattice", tuple(2 * value for value in point))
        else:
            # Enumerate faces only, with deterministic duplicate suppression at edges.
            for axis in range(len(self.dimensions)):
                for edge in (self.offset[axis], self.offset[axis] + self.dimensions[axis] - 1):
                    ranges = [range(low + (i < axis), low + size - (i < axis))
                              if i != axis else (edge,)
                              for i, (low, size) in enumerate(zip(self.offset, self.dimensions))]
                    for point in product(*ranges):
                        yield key_at("lattice", tuple(2 * value for value in point))

    def __len__(self):
        return prod(self.dimensions) - (prod(size - 2 for size in self.dimensions) if self.boundary else 0)

    @classmethod
    def _from_iterable(cls, values):
        return frozenset(values)


class IdealAtoms(Mapping):
    """Atom IDs match the legacy lexicographic site-key ordering exactly."""
    def __init__(self, dimensions, offset):
        self.axes = tuple(tuple(sorted(range(low, low + size), key=str)) for low, size in zip(offset, dimensions))
        self.ranks = tuple({value: i for i, value in enumerate(axis)} for axis in self.axes)
        self.dimensions, self.offset = dimensions, offset

    def __getitem__(self, atom_id):
        if not isinstance(atom_id, int) or not 0 <= atom_id < len(self):
            raise KeyError(atom_id)
        point = []
        for axis in reversed(self.axes):
            atom_id, digit = divmod(atom_id, len(axis))
            point.append(2 * axis[digit])
        return key_at("lattice", tuple(reversed(point)))

    def atom_at(self, key):
        if key not in MetalKeys(self.dimensions, self.offset):
            raise KeyError(key)
        _, point = parse_key(key)
        atom_id = 0
        for rank, value, size in zip(self.ranks, point, self.dimensions):
            atom_id = atom_id * size + rank[value // 2]
        return atom_id

    def __iter__(self):
        return iter(range(len(self)))

    def __len__(self):
        return prod(self.dimensions)


class IdealOccupied(Mapping):
    def __init__(self, atoms):
        self.atoms = atoms

    def __getitem__(self, key):
        return self.atoms.atom_at(key)

    def __iter__(self):
        return iter(MetalKeys(self.atoms.dimensions, self.atoms.offset))

    def __len__(self):
        return len(self.atoms)
