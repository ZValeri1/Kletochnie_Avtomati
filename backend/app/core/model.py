"""Authoritative qualitative gamma-irradiation lattice model."""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass
from collections import defaultdict
from typing import Literal

SiteKind = Literal["lattice", "interstitial", "bridge", "hollow"]


@dataclass(frozen=True)
class Site:
    kind: SiteKind
    coordinate: tuple[float, ...]
    support_keys: tuple[str, ...] = ()
    normal: tuple[int, ...] | None = None

    @property
    def key(self) -> str:
        values = ",".join(f"{value:g}" for value in self.coordinate)
        return f"{self.kind}:{values}"


@dataclass
class Atom:
    atom_id: int
    site_key: str


@dataclass(frozen=True)
class EventCandidate:
    event_type: str
    destination_key: str
    partner_id: int | None = None
    direction_weight: float = 1.0


class GammaIrradiationModel:
    """Single-owner model state used by the HTTP and WebSocket boundaries."""

    PHYSICAL_Q_MAX_EV = 82.0
    CASCADE_Q_MAX_EV = 300.0
    DEFAULT_THRESHOLDS = {
        "shift": 12.0, "swap": 25.0, "frenkel_create": 40.0, "knock": 50.0,
        "surface_shift": 9.0, "surface_swap": 20.0, "surface_frenkel_create": 30.0,
        "surface_knock": 37.5, "surface_out": 60.0, "recombine_d1": 4.0,
        "fill_d2": 4.0, "interstitial_hop": 6.0, "to_surface": 12.0,
        "replacement_knock": 45.0, "surface_hop": 3.0, "surface_return_d1": 6.0,
        "surface_fill_d2": 8.0, "surface_push": 10.0, "to_interstitial": 18.0,
        "replacement_return": 20.0,
    }
    DEFAULT_WEIGHTS = {
        "shift": 1.0, "frenkel_create": 0.2, "knock": 0.1, "swap": 0.05,
        "surface_out": 0.01, "recombine_d1": 0.9, "fill_d2": 0.3,
        "interstitial_hop": 1.0, "to_surface": 0.01, "replacement_knock": 0.1,
        "surface_hop": 1.0, "surface_return_d1": 0.4, "surface_fill_d2": 0.2,
        "surface_push": 0.1, "to_interstitial": 0.2, "replacement_return": 0.05,
    }

    def __init__(
        self,
        dimensions: tuple[int, ...] = (30, 30),
        moved_atoms: int = 0,
        seed_init: int | None = None,
        seed_sim: int | None = None,
        profile: str = "fe_co60_physical",
        q_max_ev: float | None = None,
        frenkel_threshold_ev: float = 40.0,
        recombine_threshold_ev: float = 4.0,
        moved_surface_atoms: int = 0,
        defect_concentration: float | None = None,
        thresholds: dict[str, float] | None = None,
        weights: dict[str, float] | None = None,
    ) -> None:
        if len(dimensions) not in (2, 3) or any(size < 2 for size in dimensions):
            raise ValueError("dimensions must have two or three axes with at least two nodes")
        self.dimensions = dimensions
        self.profile = profile
        self.seed_init = seed_init
        self.seed_sim = seed_sim
        self.moved_atoms = moved_atoms
        self.moved_surface_atoms = moved_surface_atoms
        self.defect_concentration = defect_concentration
        default_q_max = self.CASCADE_Q_MAX_EV if profile == "cascade_test" else self.PHYSICAL_Q_MAX_EV
        self.q_max_ev = q_max_ev if q_max_ev is not None else default_q_max
        self.frenkel_threshold_ev = frenkel_threshold_ev
        self.recombine_threshold_ev = recombine_threshold_ev
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.thresholds["frenkel_create"] = frenkel_threshold_ev
        self.thresholds["recombine_d1"] = recombine_threshold_ev
        self.weights = {**self.DEFAULT_WEIGHTS, **(weights or {})}
        if min(self.q_max_ev, self.frenkel_threshold_ev, self.recombine_threshold_ev) < 0:
            raise ValueError("energy configuration cannot be negative")
        if any(value < 0 for value in self.thresholds.values()):
            raise ValueError("event thresholds cannot be negative")
        if any(value < 0 for value in self.weights.values()):
            raise ValueError("event weights cannot be negative")
        self._init_rng = random.Random(seed_init)
        self._sim_rng = random.Random(seed_sim)
        self.revision = 0
        self.act_number = 0
        self.total_dose_ev = 0.0
        self._neighbors: dict[str, dict[str, float]] = defaultdict(dict)
        self.sites = self._build_sites()
        self.atoms: dict[int, Atom] = {}
        self._occupied: dict[str, int] = {}
        self.events: list[dict] = []
        self._initialize_ideal()
        if defect_concentration is None:
            self.initialize_exact(moved_atoms, moved_surface_atoms)
        else:
            self.initialize_random(defect_concentration)
        self._history: list[dict] = []
        self._history_cursor = -1
        self._commit_history()

    def _build_sites(self) -> dict[str, Site]:
        sites: dict[str, Site] = {}
        interstitials: list[Site] = []
        surface_sites: list[Site] = []

        def add(
            kind: SiteKind,
            coordinate: tuple[float, ...],
            supports: tuple[str, ...] = (),
            normal: tuple[int, ...] | None = None,
        ) -> Site:
            site = Site(kind, coordinate, supports, normal)
            sites[site.key] = site
            return site

        def lattice_key(coordinate: tuple[int, ...]) -> str:
            return Site("lattice", tuple(float(value) for value in coordinate)).key

        lattice_ranges = [range(size) for size in self.dimensions]
        cell_ranges = [range(size - 1) for size in self.dimensions]
        for coordinate in self._cartesian(lattice_ranges):
            add("lattice", tuple(float(value) for value in coordinate))
        for coordinate in self._cartesian(cell_ranges):
            support_coordinates = self._cartesian([range(value, value + 2) for value in coordinate])
            interstitials.append(
                add(
                    "interstitial",
                    tuple(value + 0.5 for value in coordinate),
                    tuple(lattice_key(item) for item in support_coordinates),
                )
            )
        if len(self.dimensions) == 2:
            nx, ny = self.dimensions
            for x in range(nx - 1):
                for y, normal in ((-0.5, (0, -1)), (ny - 0.5, (0, 1))):
                    surface_sites.append(add("bridge", (x + 0.5, y), (lattice_key((x, 0 if y < 0 else ny - 1)), lattice_key((x + 1, 0 if y < 0 else ny - 1))), normal))
            for y in range(ny - 1):
                for x, normal in ((-0.5, (-1, 0)), (nx - 0.5, (1, 0))):
                    surface_sites.append(add("bridge", (x, y + 0.5), (lattice_key((0 if x < 0 else nx - 1, y)), lattice_key((0 if x < 0 else nx - 1, y + 1))), normal))
        else:
            nx, ny, nz = self.dimensions
            face_specs = (
                (0, -0.5, (-1, 0, 0), (ny - 1, nz - 1)), (0, nx - 0.5, (1, 0, 0), (ny - 1, nz - 1)),
                (1, -0.5, (0, -1, 0), (nx - 1, nz - 1)), (1, ny - 0.5, (0, 1, 0), (nx - 1, nz - 1)),
                (2, -0.5, (0, 0, -1), (nx - 1, ny - 1)), (2, nz - 0.5, (0, 0, 1), (nx - 1, ny - 1)),
            )
            for axis, outward, normal, spans in face_specs:
                fixed = 0 if outward < 0 else self.dimensions[axis] - 1
                other_axes = [index for index in range(3) if index != axis]
                for first in range(spans[0]):
                    for second in range(spans[1]):
                        coordinate = [0.0, 0.0, 0.0]
                        coordinate[axis] = outward
                        coordinate[other_axes[0]] = first + 0.5
                        coordinate[other_axes[1]] = second + 0.5
                        supports = []
                        for da in (0, 1):
                            for db in (0, 1):
                                point = [0, 0, 0]
                                point[axis] = fixed
                                point[other_axes[0]] = first + da
                                point[other_axes[1]] = second + db
                                supports.append(lattice_key(tuple(point)))
                        surface_sites.append(add("hollow", tuple(coordinate), tuple(supports), normal))
        for site in interstitials + surface_sites:
            for support in site.support_keys:
                self._link(site.key, support)
        for site in interstitials:
            cell = tuple(int(value - 0.5) for value in site.coordinate)
            for axis, limit in enumerate(self.dimensions):
                for delta in (-1, 1):
                    target = list(cell)
                    target[axis] += delta
                    if 0 <= target[axis] < limit - 1:
                        key = Site("interstitial", tuple(value + 0.5 for value in target)).key
                        self._link(site.key, key)
        for index, left in enumerate(surface_sites):
            for right in surface_sites[index + 1 :]:
                shared_supports = len(set(left.support_keys) & set(right.support_keys))
                if shared_supports == 2:
                    self._link(left.key, right.key, 1.0 if left.normal == right.normal else 0.5)
        return sites

    def _link(self, left: str, right: str, weight: float = 1.0) -> None:
        self._neighbors[left][right] = weight
        self._neighbors[right][left] = weight

    def neighbors(self, site_key: str) -> dict[str, float]:
        if site_key not in self.sites:
            raise ValueError("Site does not exist")
        return dict(self._neighbors[site_key])

    def supports(self, site_key: str) -> tuple[str, ...]:
        if site_key not in self.sites:
            raise ValueError("Site does not exist")
        return self.sites[site_key].support_keys

    @staticmethod
    def _cartesian(ranges: list[range]):
        if not ranges:
            yield ()
            return
        def visit(index: int, prefix: tuple[int, ...]):
            if index == len(ranges):
                yield prefix
                return
            for value in ranges[index]:
                yield from visit(index + 1, prefix + (value,))
        yield from visit(0, ())

    def _initialize_ideal(self) -> None:
        for atom_id, site in enumerate(self._sites_of_kind("lattice")):
            self.atoms[atom_id] = Atom(atom_id=atom_id, site_key=site.key)
            self._occupied[site.key] = atom_id

    def _sites_of_kind(self, kind: SiteKind) -> list[Site]:
        return [site for site in self.sites.values() if site.kind == kind]

    def _is_surface_lattice(self, site: Site) -> bool:
        return any(value == 0 or value == limit - 1 for value, limit in zip(site.coordinate, self.dimensions))

    def initialize_exact(self, moved_atoms: int, moved_surface_atoms: int = 0) -> None:
        if moved_atoms < 0 or moved_surface_atoms < 0:
            raise ValueError("moved atom counts cannot be negative")
        sources = [
            atom.atom_id
            for atom in self.atoms.values()
            if not self._is_surface_lattice(self.sites[atom.site_key])
        ]
        if len(sources) < moved_atoms:
            raise ValueError(f"moved_atoms exceeds available interior atoms ({len(sources)})")
        destinations = [site for site in self._sites_of_kind("interstitial") if site.key not in self._occupied]
        if len(destinations) < moved_atoms:
            raise ValueError(f"moved_atoms exceeds interstitial capacity ({len(destinations)})")
        for atom_id, destination in zip(
            self._init_rng.sample(sources, moved_atoms), self._init_rng.sample(destinations, moved_atoms)
        ):
            self._relocate(atom_id, destination.key)

        if moved_surface_atoms:
            candidates = [
                (self._occupied[support], site.key)
                for site in self._sites_of_kind("bridge") + self._sites_of_kind("hollow")
                if site.key not in self._occupied
                for support in site.support_keys
                if support in self._occupied and self._is_surface_lattice(self.sites[support])
            ]
            self._init_rng.shuffle(candidates)
            selected: list[tuple[int, str]] = []
            selected_sources: set[int] = set()
            selected_destinations: set[str] = set()
            for atom_id, destination in candidates:
                if atom_id in selected_sources or destination in selected_destinations:
                    continue
                selected.append((atom_id, destination))
                selected_sources.add(atom_id)
                selected_destinations.add(destination)
                if len(selected) == moved_surface_atoms:
                    break
            if len(selected) != moved_surface_atoms:
                raise ValueError(f"moved_surface_atoms exceeds available surface capacity ({len(selected)})")
            for atom_id, destination in selected:
                self._relocate(atom_id, destination)

    def initialize_random(self, concentration: float) -> None:
        if not 0.0 <= concentration <= 1.0:
            raise ValueError("defect_concentration must be between 0 and 1")
        capacity = min(
            len([site for site in self._sites_of_kind("lattice") if not self._is_surface_lattice(site)]),
            len(self._sites_of_kind("interstitial")),
        )
        while True:
            moved = sum(self._init_rng.random() < concentration for _ in self.atoms)
            if moved <= capacity:
                self.initialize_exact(moved)
                return

    def _relocate(self, atom_id: int, destination_key: str) -> None:
        if destination_key in self._occupied:
            raise ValueError("destination is occupied")
        atom = self.atoms[atom_id]
        del self._occupied[atom.site_key]
        atom.site_key = destination_key
        self._occupied[destination_key] = atom_id

    def _history_state(self) -> dict:
        return {
            "atom_sites": {atom_id: atom.site_key for atom_id, atom in self.atoms.items()},
            "act_number": self.act_number,
            "total_dose_ev": self.total_dose_ev,
            "events": list(self.events),
        }

    def _restore_history_state(self, state: dict) -> None:
        self._occupied.clear()
        for atom_id, site_key in state["atom_sites"].items():
            self.atoms[int(atom_id)].site_key = site_key
            self._occupied[site_key] = int(atom_id)
        self.act_number = state["act_number"]
        self.total_dose_ev = state["total_dose_ev"]
        self.events = list(state["events"])

    def _commit_history(self) -> None:
        del self._history[self._history_cursor + 1 :]
        self._history.append(self._history_state())
        self._history_cursor = len(self._history) - 1

    def undo(self) -> dict:
        if self._history_cursor == 0:
            raise ValueError("No earlier model state")
        self._history_cursor -= 1
        self._restore_history_state(self._history[self._history_cursor])
        self.revision += 1
        return self.snapshot()

    def redo(self) -> dict:
        if self._history_cursor >= len(self._history) - 1:
            raise ValueError("No later model state")
        self._history_cursor += 1
        self._restore_history_state(self._history[self._history_cursor])
        self.revision += 1
        return self.snapshot()

    def available_destinations(self, atom_id: int) -> list[dict]:
        if atom_id not in self.atoms:
            raise ValueError("Atom does not exist")
        kind = self.sites[self.atoms[atom_id].site_key].kind
        allowed = "interstitial" if kind == "lattice" else "lattice"
        return [
            self._site_payload(site)
            for site in self._sites_of_kind(allowed)
            if site.key not in self._occupied
        ]

    def move(self, atom_id: int, destination_key: str) -> dict:
        if destination_key not in {site["key"] for site in self.available_destinations(atom_id)}:
            raise ValueError("Destination is not a free compatible site")
        source_key = self.atoms[atom_id].site_key
        self._relocate(atom_id, destination_key)
        self.act_number += 1
        self.revision += 1
        event = {
            "act": self.act_number,
            "revision": self.revision,
            "target_atom_id": atom_id,
            "energy_ev": 0.0,
            "event_type": "manual_move",
            "source": source_key,
            "destinations": [destination_key],
            "metrics": self.metrics(),
        }
        self.events.append(event)
        self._commit_history()
        return event

    def _energy(self) -> float:
        return self.q_max_ev * self._sim_rng.betavariate(1, 4)

    @staticmethod
    def direction_multiplier(cosine: float) -> float:
        return 0.5 + 0.35 * cosine + 0.15 * cosine * cosine

    def _candidate_groups(self, atom_id: int) -> dict[str, list[EventCandidate]]:
        atom = self.atoms[atom_id]
        site = self.sites[atom.site_key]
        neighbours = self.neighbors(site.key)
        groups: dict[str, list[EventCandidate]] = defaultdict(list)

        def free_neighbours(kind: SiteKind) -> list[str]:
            return [key for key in neighbours if self.sites[key].kind == kind and key not in self._occupied]

        def occupied_neighbours(kind: SiteKind) -> list[tuple[str, int]]:
            return [
                (key, self._occupied[key])
                for key in neighbours
                if self.sites[key].kind == kind and key in self._occupied
            ]

        state = self._atom_state(atom)
        if state in {"correct", "surface"}:
            prefix = "surface_" if state == "surface" else ""
            for destination in free_neighbours("interstitial"):
                groups[f"{prefix}shift"].append(EventCandidate(f"{prefix}shift", destination))
                groups[f"{prefix}frenkel_create"].append(
                    EventCandidate(f"{prefix}frenkel_create", destination)
                )
                groups[f"{prefix}knock"].append(EventCandidate(f"{prefix}knock", destination))
            if state == "surface":
                for destination in free_neighbours("bridge") + free_neighbours("hollow"):
                    groups["surface_out"].append(EventCandidate("surface_out", destination))
        elif state == "interstitial":
            for destination in free_neighbours("lattice"):
                groups["recombine_d1"].append(EventCandidate("recombine_d1", destination))
            for destination in free_neighbours("interstitial"):
                groups["interstitial_hop"].append(EventCandidate("interstitial_hop", destination))
            for destination, partner_id in occupied_neighbours("lattice"):
                groups["swap"].append(EventCandidate("swap", destination, partner_id))
                groups["replacement_knock"].append(
                    EventCandidate("replacement_knock", destination, partner_id)
                )
            for destination in self._vacancies_within(site.key, 2.0):
                if destination not in {candidate.destination_key for candidate in groups["recombine_d1"]}:
                    groups["fill_d2"].append(EventCandidate("fill_d2", destination))
            for destination in self._nearest_free_surface_sites(site):
                groups["to_surface"].append(EventCandidate("to_surface", destination))
        else:
            for destination in free_neighbours(site.kind):
                groups["surface_hop"].append(EventCandidate("surface_hop", destination))
            for destination in free_neighbours("lattice"):
                groups["surface_return_d1"].append(EventCandidate("surface_return_d1", destination))
            for destination, partner_id in occupied_neighbours(site.kind):
                groups["surface_push"].append(EventCandidate("surface_push", destination, partner_id))
                groups["replacement_return"].append(
                    EventCandidate("replacement_return", destination, partner_id)
                )
            for destination in self._vacancies_within(site.key, 2.0):
                if destination not in {candidate.destination_key for candidate in groups["surface_return_d1"]}:
                    groups["surface_fill_d2"].append(EventCandidate("surface_fill_d2", destination))
            for destination in self._nearest_free_sites("interstitial", site):
                groups["to_interstitial"].append(EventCandidate("to_interstitial", destination))
            groups["surface_knock"].extend(groups["surface_hop"])
        return groups

    def _nearest_free_surface_sites(self, source: Site) -> list[str]:
        free = [
            site for site in self._sites_of_kind("bridge") + self._sites_of_kind("hollow")
            if site.key not in self._occupied
        ]
        if not free:
            return []
        distance = min(self._distance(source, site) for site in free)
        return [site.key for site in free if self._distance(source, site) == distance]

    def _nearest_free_sites(self, kind: SiteKind, source: Site) -> list[str]:
        free = [site for site in self._sites_of_kind(kind) if site.key not in self._occupied]
        if not free:
            return []
        distance = min(self._distance(source, site) for site in free)
        return [site.key for site in free if self._distance(source, site) == distance]

    def _vacancies_within(self, source_key: str, maximum_distance: float) -> list[str]:
        source = self.sites[source_key]
        return [
            site.key
            for site in self._sites_of_kind("lattice")
            if site.key not in self._occupied and self._distance(source, site) <= maximum_distance
        ]

    def _event_type_weights(self, atom_id: int, energy: float) -> dict[str, float]:
        state = self._atom_state(self.atoms[atom_id])
        groups = self._candidate_groups(atom_id)
        active = {
            event_type: candidates
            for event_type, candidates in groups.items()
            if candidates and energy >= self.thresholds.get(event_type, math.inf)
        }
        if not active:
            return {}
        if state == "interstitial" and "recombine_d1" in active:
            local = {key: value for key, value in active.items() if key != "recombine_d1"}
            if not local:
                return {"recombine_d1": 1.0}
            local_sum = sum(self.weights.get(key, 1.0) for key in local)
            return {
                "recombine_d1": 0.9,
                **{key: 0.1 * self.weights.get(key, 1.0) / local_sum for key in local},
            }
        if state == "surface_defect":
            reserved = "surface_return_d1" if "surface_return_d1" in active else "surface_fill_d2"
            if reserved in active:
                mass = 0.4 if reserved == "surface_return_d1" else 0.2
                local = {key: value for key, value in active.items() if key != reserved}
                if not local:
                    return {reserved: 1.0}
                local_sum = sum(self.weights.get(key, 1.0) for key in local)
                return {reserved: mass, **{key: (1 - mass) * self.weights.get(key, 1.0) / local_sum for key in local}}
        raw = {
            key: self.weights.get(key, self.weights.get(key.removeprefix("surface_"), 1.0))
            for key in active
        }
        total = sum(raw.values())
        return (
            {key: value / total for key, value in raw.items() if value > 0}
            if total > 0
            else {key: 1.0 / len(raw) for key in raw}
        )

    def probability_outcomes(self, atom_id: int, energy: float) -> list[dict]:
        if atom_id not in self.atoms:
            raise ValueError("Atom does not exist")
        type_weights = self._event_type_weights(atom_id, energy)
        groups = self._candidate_groups(atom_id)
        outcomes: list[dict] = []
        for event_type, type_weight in type_weights.items():
            candidates = groups[event_type]
            local_total = sum(candidate.direction_weight for candidate in candidates)
            for candidate in candidates:
                outcomes.append(
                    {
                        "event_type": event_type,
                        "probability": type_weight * candidate.direction_weight / local_total,
                        "destinations": [candidate.destination_key],
                    }
                )
        return outcomes or [{"event_type": "no_change", "probability": 1.0, "destinations": []}]

    def _choose_weighted(self, values: list[tuple[object, float]]) -> object:
        point = self._sim_rng.random() * sum(weight for _, weight in values)
        for value, weight in values:
            point -= weight
            if point <= 0:
                return value
        return values[-1][0]

    def _choose_event(self, atom_id: int, energy: float) -> EventCandidate | None:
        weights = self._event_type_weights(atom_id, energy)
        if not weights:
            return None
        event_type = self._choose_weighted(list(weights.items()))
        candidates = self._candidate_groups(atom_id)[str(event_type)]
        return self._choose_weighted([(candidate, candidate.direction_weight) for candidate in candidates])

    def _apply_candidate(self, atom_id: int, candidate: EventCandidate) -> list[str]:
        if candidate.partner_id is None:
            self._relocate(atom_id, candidate.destination_key)
            return [candidate.destination_key]
        source_key = self.atoms[atom_id].site_key
        partner = self.atoms[candidate.partner_id]
        if partner.site_key != candidate.destination_key:
            raise ValueError("Atomic event target changed before commit")
        del self._occupied[source_key]
        del self._occupied[candidate.destination_key]
        self.atoms[atom_id].site_key = candidate.destination_key
        partner.site_key = source_key
        self._occupied[candidate.destination_key] = atom_id
        self._occupied[source_key] = candidate.partner_id
        return [candidate.destination_key, source_key]

    def _cascade_candidates(self, origin_key: str) -> list[tuple[int, str]]:
        """Return forward-only atom displacements seeded from one cascade branch."""
        origin = self.sites[origin_key]
        options: list[tuple[int, str]] = []
        for support_key in self.neighbors(origin_key):
            if self.sites[support_key].kind != "lattice" or support_key not in self._occupied:
                continue
            atom_id = self._occupied[support_key]
            for destination_key in self.neighbors(support_key):
                destination = self.sites[destination_key]
                if destination.kind != "interstitial" or destination_key in self._occupied:
                    continue
                # The model flow direction is +X; reverse cascade branches are not valid.
                if destination.coordinate[0] < origin.coordinate[0]:
                    continue
                options.append((atom_id, destination_key))
        return options

    def _process_cascade(self, origin_key: str, available_energy: float) -> list[dict]:
        if available_energy <= 0:
            return []
        queue: list[tuple[float, int, str, float]] = [(-available_energy, 0, origin_key, available_energy)]
        sequence = 1
        records: list[dict] = []
        while queue and len(records) < 64:
            _, _, source_key, branch_energy = heapq.heappop(queue)
            options = self._cascade_candidates(source_key)
            if branch_energy < 12 or not options:
                records.append({"status": "dissipated", "source": source_key, "energy_ev": branch_energy})
                continue
            atom_id, destination_key = self._choose_weighted([(item, 1.0) for item in options])
            if atom_id not in self.atoms or destination_key in self._occupied:
                records.append({"status": "conflict_cancelled", "source": source_key, "energy_ev": branch_energy})
                continue
            self._relocate(atom_id, destination_key)
            remaining = max(0.0, branch_energy - 12.0)
            child_energy = remaining * 0.5
            records.append(
                {
                    "status": "committed",
                    "atom_id": atom_id,
                    "source": source_key,
                    "destination": destination_key,
                    "energy_ev": branch_energy,
                    "child_energy_ev": child_energy,
                }
            )
            if child_energy > 0:
                heapq.heappush(queue, (-child_energy, sequence, destination_key, child_energy))
                sequence += 1
        return records

    def step(self, forced_energy: float | None = None) -> dict:
        energy = self._energy() if forced_energy is None else forced_energy
        target_id = self._sim_rng.choice(list(self.atoms))
        candidate = self._choose_event(target_id, energy)
        event_type = candidate.event_type if candidate else "no_change"
        destinations = self._apply_candidate(target_id, candidate) if candidate else []
        cascade = []
        if candidate and candidate.event_type in {"knock", "surface_knock", "replacement_knock"}:
            cascade = self._process_cascade(
                candidate.destination_key,
                max(0.0, energy - self.thresholds.get(candidate.event_type, 0.0)),
            )
        self.act_number += 1
        self.total_dose_ev += energy
        self.revision += 1
        event = {
            "act": self.act_number,
            "revision": self.revision,
            "target_atom_id": target_id,
            "energy_ev": energy,
            "event_type": event_type,
            "destinations": destinations,
            "cascade": cascade,
            "deltas": {"atom_ids": [target_id] + ([candidate.partner_id] if candidate and candidate.partner_id is not None else [])},
            "metrics": self.metrics(),
        }
        self.events.append(event)
        self._commit_history()
        return event

    @staticmethod
    def _distance(left: Site, right: Site) -> float:
        return sum(abs(a - b) for a, b in zip(left.coordinate, right.coordinate))

    def metrics(self) -> dict:
        lattice = self._sites_of_kind("lattice")
        vacancies = sum(site.key not in self._occupied for site in lattice)
        interstitials = sum(
            self.sites[atom.site_key].kind == "interstitial" for atom in self.atoms.values()
        )
        surface_defects = sum(
            self.sites[atom.site_key].kind in {"bridge", "hollow"} for atom in self.atoms.values()
        )
        correct = len(self.atoms) - interstitials - surface_defects
        groups = [correct, vacancies, interstitials, surface_defects]
        total = sum(groups)
        entropy = 0.0 if total == 0 else -sum(
            count * math.log(count / total) for count in groups if count
        )
        return {
            "correct": correct,
            "vacancies": vacancies,
            "interstitials": interstitials,
            "surface_defects": surface_defects,
            "defects": vacancies + interstitials + surface_defects,
            "entropy": entropy,
            "dose_ev_per_atom": self.total_dose_ev / len(self.atoms),
        }

    def snapshot(self) -> dict:
        return {
            "revision": self.revision,
            "dimensions": self.dimensions,
            "mode": "2d" if len(self.dimensions) == 2 else "3d",
            "config": {
                "profile": self.profile,
                "moved_atoms": self.moved_atoms,
                "moved_surface_atoms": self.moved_surface_atoms,
                "defect_concentration": self.defect_concentration,
                "q_max_ev": self.q_max_ev,
                "frenkel_threshold_ev": self.frenkel_threshold_ev,
                "recombine_threshold_ev": self.recombine_threshold_ev,
                "thresholds": self.thresholds,
                "weights": self.weights,
            },
            "atoms": [
                {
                    "id": atom.atom_id,
                    "site": self._site_payload(self.sites[atom.site_key]),
                    "state": self._atom_state(atom),
                }
                for atom in sorted(self.atoms.values(), key=lambda item: item.atom_id)
            ],
            "vacancies": [self._site_payload(site) for site in self._sites_of_kind("lattice") if site.key not in self._occupied],
            "metrics": self.metrics(),
            "act": self.act_number,
            "history_index": self._history_cursor,
            "history_length": len(self._history),
            "can_undo": self._history_cursor > 0,
            "can_redo": self._history_cursor < len(self._history) - 1,
        }

    def export_state(self) -> dict:
        return {
            "format_version": 1,
            "config": {
                "dimensions": self.dimensions,
                "profile": self.profile,
                "moved_atoms": self.moved_atoms,
                "moved_surface_atoms": self.moved_surface_atoms,
                "defect_concentration": self.defect_concentration,
                "seed_init": self.seed_init,
                "seed_sim": self.seed_sim,
                "q_max_ev": self.q_max_ev,
                "frenkel_threshold_ev": self.frenkel_threshold_ev,
                "recombine_threshold_ev": self.recombine_threshold_ev,
                "thresholds": self.thresholds,
                "weights": self.weights,
            },
            "state": self._history_state(),
            "history": self._history,
            "history_cursor": self._history_cursor,
            "revision": self.revision,
        }

    @classmethod
    def from_export(cls, export: dict) -> "GammaIrradiationModel":
        if export.get("format_version") != 1:
            raise ValueError("Unsupported project format")
        config = export["config"]
        model = cls(
            dimensions=tuple(config["dimensions"]),
            moved_atoms=config.get("moved_atoms", 0),
            moved_surface_atoms=config.get("moved_surface_atoms", 0),
            defect_concentration=config.get("defect_concentration"),
            seed_init=config.get("seed_init"),
            seed_sim=config.get("seed_sim"),
            profile=config.get("profile", "fe_co60_physical"),
            q_max_ev=config.get("q_max_ev"),
            frenkel_threshold_ev=config.get("frenkel_threshold_ev", 40.0),
            recombine_threshold_ev=config.get("recombine_threshold_ev", 4.0),
            thresholds=config.get("thresholds"),
            weights=config.get("weights"),
        )
        model._history = export.get("history", [export["state"]])
        model._history_cursor = export.get("history_cursor", len(model._history) - 1)
        model._restore_history_state(export["state"])
        model.revision = export.get("revision", 0)
        return model

    @staticmethod
    def _site_payload(site: Site) -> dict:
        return {"kind": site.kind, "coordinate": site.coordinate, "key": site.key}

    def _atom_state(self, atom: Atom) -> str:
        site = self.sites[atom.site_key]
        if site.kind == "interstitial":
            return "interstitial"
        if site.kind in {"bridge", "hollow"}:
            return "surface_defect"
        return "surface" if self._is_surface_lattice(site) else "correct"
