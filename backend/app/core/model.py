"""Authoritative qualitative gamma-irradiation lattice model."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

SiteKind = Literal["lattice", "interstitial", "bridge", "hollow"]


@dataclass(frozen=True)
class Site:
    kind: SiteKind
    coordinate: tuple[float, ...]

    @property
    def key(self) -> str:
        values = ",".join(f"{value:g}" for value in self.coordinate)
        return f"{self.kind}:{values}"


@dataclass
class Atom:
    atom_id: int
    site_key: str


class GammaIrradiationModel:
    """Single-owner model state used by the HTTP and WebSocket boundaries."""

    PHYSICAL_Q_MAX_EV = 82.0
    CASCADE_Q_MAX_EV = 300.0

    def __init__(
        self,
        dimensions: tuple[int, ...] = (30, 30),
        moved_atoms: int = 0,
        seed_init: int | None = None,
        seed_sim: int | None = None,
        profile: str = "fe_co60_physical",
    ) -> None:
        if len(dimensions) not in (2, 3) or any(size < 2 for size in dimensions):
            raise ValueError("dimensions must have two or three axes with at least two nodes")
        self.dimensions = dimensions
        self.profile = profile
        self._init_rng = random.Random(seed_init)
        self._sim_rng = random.Random(seed_sim)
        self.revision = 0
        self.act_number = 0
        self.total_dose_ev = 0.0
        self.sites = self._build_sites()
        self.atoms: dict[int, Atom] = {}
        self._occupied: dict[str, int] = {}
        self.events: list[dict] = []
        self._initialize_ideal()
        self.initialize_exact(moved_atoms)

    def _build_sites(self) -> dict[str, Site]:
        sites: dict[str, Site] = {}
        lattice_ranges = [range(size) for size in self.dimensions]
        cell_ranges = [range(size - 1) for size in self.dimensions]
        for coordinate in self._cartesian(lattice_ranges):
            site = Site("lattice", tuple(float(value) for value in coordinate))
            sites[site.key] = site
        for coordinate in self._cartesian(cell_ranges):
            site = Site("interstitial", tuple(value + 0.5 for value in coordinate))
            sites[site.key] = site
        return sites

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

    def initialize_exact(self, moved_atoms: int) -> None:
        if moved_atoms < 0:
            raise ValueError("moved_atoms cannot be negative")
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

    def _relocate(self, atom_id: int, destination_key: str) -> None:
        if destination_key in self._occupied:
            raise ValueError("destination is occupied")
        atom = self.atoms[atom_id]
        del self._occupied[atom.site_key]
        atom.site_key = destination_key
        self._occupied[destination_key] = atom_id

    def _energy(self) -> float:
        q_max = self.CASCADE_Q_MAX_EV if self.profile == "cascade_test" else self.PHYSICAL_Q_MAX_EV
        return q_max * self._sim_rng.betavariate(1, 4)

    def step(self, forced_energy: float | None = None) -> dict:
        energy = self._energy() if forced_energy is None else forced_energy
        target_id = self._sim_rng.choice(list(self.atoms))
        event_type = "no_change"
        destinations: list[str] = []
        # The first vertical slice supports the normative Frenkel creation event.
        if energy >= 40 and self.sites[self.atoms[target_id].site_key].kind == "lattice":
            free = [site for site in self._sites_of_kind("interstitial") if site.key not in self._occupied]
            if free:
                destination = self._sim_rng.choice(free)
                self._relocate(target_id, destination.key)
                event_type = "frenkel_create"
                destinations = [destination.key]
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
            "metrics": self.metrics(),
        }
        self.events.append(event)
        return event

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
        }

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
