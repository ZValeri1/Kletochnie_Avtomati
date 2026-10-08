from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from backend.atomic_model.errors import StateInvariantError, TopologyError
from backend.atomic_model.topology import Topology


@dataclass
class SimulationState:
    atoms: dict[int, str]
    occupied: dict[str, int]
    act_number: int = 0
    revision: int = 0
    events: list[dict] = field(default_factory=list)
    metrics_points: list[dict] = field(default_factory=list)
    configuration: dict = field(default_factory=dict)

    @classmethod
    def create_ideal(cls, topology: Topology, configuration: dict | None = None):
        atoms = {
            atom_id: site_key
            for atom_id, site_key in enumerate(sorted(topology.metal_domain.lattice_keys))
        }
        return cls(
            atoms=atoms,
            occupied={site_key: atom_id for atom_id, site_key in atoms.items()},
            configuration=deepcopy(configuration or {}),
        )

    @classmethod
    def from_positions(cls, topology: Topology, positions: dict[int, str], **kwargs):
        state = cls(
            atoms=dict(positions),
            occupied={site_key: atom_id for atom_id, site_key in positions.items()},
            **kwargs,
        )
        state.validate(topology)
        return state

    def working_copy(self):
        return deepcopy(self)

    def transition_copy(self, *, include_history: bool = True):
        return type(self)(
            atoms=dict(self.atoms),
            occupied=dict(self.occupied),
            act_number=self.act_number,
            revision=self.revision,
            events=list(self.events) if include_history else [],
            metrics_points=list(self.metrics_points) if include_history else [],
            configuration=deepcopy(self.configuration),
        )

    def relocate(self, atom_id: int, destination_key: str) -> None:
        if atom_id not in self.atoms:
            raise StateInvariantError("UNKNOWN_ATOM")
        if destination_key in self.occupied:
            raise StateInvariantError("SITE_OCCUPIED")
        source = self.atoms[atom_id]
        del self.occupied[source]
        self.atoms[atom_id] = destination_key
        self.occupied[destination_key] = atom_id

    def validate(self, topology: Topology) -> None:
        if len(set(self.atoms.values())) != len(self.atoms):
            raise StateInvariantError("SITE_OCCUPIED")
        if any(site_key not in topology.sites for site_key in self.atoms.values()):
            raise StateInvariantError("UNKNOWN_SITE")
        expected = {site_key: atom_id for atom_id, site_key in self.atoms.items()}
        if self.occupied != expected:
            raise StateInvariantError("OCCUPANCY_MISMATCH")
        try:
            topology.validate_occupancy(self.occupied)
        except TopologyError as error:
            raise StateInvariantError(error.code) from error

    def to_dict(self) -> dict:
        return {
            "atoms": dict(self.atoms),
            "occupied": dict(self.occupied),
            "act_number": self.act_number,
            "revision": self.revision,
            "events": deepcopy(self.events),
            "metrics_points": deepcopy(self.metrics_points),
            "configuration": deepcopy(self.configuration),
        }
