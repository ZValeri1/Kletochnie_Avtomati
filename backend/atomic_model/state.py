from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from backend.atomic_model.errors import StateInvariantError, TopologyError
from backend.atomic_model.topology import Topology
from backend.atomic_model.sparse_map import SparseMap
from backend.atomic_model.payload_copy import copy_payload


@dataclass
class SimulationState:
    atoms: dict[int, str]
    occupied: dict[str, int]
    act_number: int = 0
    revision: int = 0
    events: list[dict] = field(default_factory=list)
    metrics_points: list[dict] = field(default_factory=list)
    configuration: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.atoms, SparseMap):
            self.atoms = SparseMap(self.atoms)
        if not isinstance(self.occupied, SparseMap):
            self.occupied = SparseMap(self.occupied)
        self._validated = None
        self._local = None
        self._changed_sites = set()
        self._metrics = None
        self._metric_signature = None
        self._metric_topology = None
        self._ids = None
        self._ids_version = None

    def signature(self):
        if not isinstance(self.atoms, SparseMap) or not isinstance(self.occupied, SparseMap):
            return None
        return (id(self.atoms), self.atoms.version, id(self.occupied), self.occupied.version)

    def atom_ids(self):
        version = (id(self.atoms), self.atoms.keys_version) if isinstance(self.atoms, SparseMap) else None
        if version is None or version != self._ids_version:
            from backend.atomic_model.regular_grid import IdealAtoms
            self._ids = (range(len(self.atoms)) if isinstance(self.atoms, SparseMap)
                         and isinstance(self.atoms.baseline, IdealAtoms) and self.atoms.keys_version == 0
                         else tuple(sorted(self.atoms)))
            self._ids_version = version
        return self._ids

    @classmethod
    def create_ideal(cls, topology: Topology, configuration: dict | None = None):
        from backend.atomic_model.regular_grid import IdealAtoms, IdealOccupied, RegularSites
        if isinstance(topology.sites, RegularSites):
            atoms = IdealAtoms(topology.dimensions, topology.metal_domain.offset)
            state = cls(atoms=SparseMap(atoms), occupied=SparseMap(IdealOccupied(atoms)), configuration=deepcopy(configuration or {}))
            state._validated = (topology, state.signature())
            state._metrics = {"n_correct": len(atoms), "n_v": 0, "n_i": 0, "n_as": 0, "d": 0, "s": 0.0}
            state._metric_signature = state.signature()
            state._metric_topology = topology
            return state
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

    def __deepcopy__(self, memo):
        copied = self.transition_copy(include_history=False)
        memo[id(self)] = copied
        copied.events = deepcopy(self.events, memo)
        copied.metrics_points = deepcopy(self.metrics_points, memo)
        return copied

    def transition_copy(self, *, include_history: bool = True):
        copied = type(self)(
            atoms=self.atoms.fork() if isinstance(self.atoms, SparseMap) else dict(self.atoms),
            occupied=self.occupied.fork() if isinstance(self.occupied, SparseMap) else dict(self.occupied),
            act_number=self.act_number,
            revision=self.revision,
            events=list(self.events) if include_history else [],
            metrics_points=list(self.metrics_points) if include_history else [],
            configuration=copy_payload(self.configuration),
        )
        signature = self.signature()
        if self._validated is not None and signature is not None and self._validated[1] == signature:
            copied._validated = (self._validated[0], copied.signature())
        if self._local is not None and signature is not None and self._local[1] == signature:
            copied._local = (self._local[0], copied.signature())
            copied._changed_sites = self._changed_sites.copy()
        if self._metric_signature == signature and signature is not None:
            copied._metrics = self._metrics
            copied._metric_signature = copied.signature()
            copied._metric_topology = self._metric_topology
        if self._ids_version == (id(self.atoms), getattr(self.atoms, "keys_version", None)):
            copied._ids = self._ids
            copied._ids_version = (id(copied.atoms), copied.atoms.keys_version)
        return copied

    def relocate(self, atom_id: int, destination_key: str) -> None:
        if atom_id not in self.atoms:
            raise StateInvariantError("UNKNOWN_ATOM")
        if destination_key in self.occupied:
            raise StateInvariantError("SITE_OCCUPIED")
        source = self.atoms[atom_id]
        signature = self.signature()
        trusted = next((item for item in (self._validated, self._local)
                        if item is not None and signature is not None and item[1] == signature), None)
        metric_values = self._metrics if self._metric_signature == signature else None
        del self.occupied[source]
        self.atoms[atom_id] = destination_key
        self.occupied[destination_key] = atom_id
        if trusted is not None:
            topology = trusted[0]
            # Validate destination even for a direct relocate outside EventExecutor.
            if destination_key not in topology.sites:
                return
            self._changed_sites.update((source, destination_key))
            self._local = (topology, self.signature())
            if metric_values is not None:
                from backend.atomic_model.metrics import MetricsCalculator
                values = dict(metric_values)
                for key, sign in ((source, -1), (destination_key, 1)):
                    site = topology.sites[key]
                    category = "n_as" if site.metal_relation == "outside" else "n_i" if site.kind == "interstitial" else "n_correct"
                    values[category] += sign
                    if key in topology.metal_domain.lattice_keys:
                        values["n_v"] -= sign
                self._metrics = MetricsCalculator.from_counts(values).model_dump()
                self._metric_signature = self.signature()
                self._metric_topology = topology

    def relocate_many(self, changes) -> None:
        changes = dict(changes)
        if len(changes) <= 1:
            for atom_id, destination in changes.items():
                if self.atoms.get(atom_id) != destination:
                    self.relocate(atom_id, destination)
            return
        sources = {atom_id: self.atoms[atom_id] for atom_id in changes}
        if len(set(changes.values())) != len(changes) or any(
            destination in self.occupied and self.occupied[destination] not in changes
            for destination in changes.values()
        ):
            raise StateInvariantError("SITE_OCCUPIED")
        signature = self.signature()
        trusted = self._validated if self._validated and self._validated[1] == signature else None
        for source in sources.values():
            del self.occupied[source]
        for atom_id, destination in changes.items():
            self.atoms[atom_id] = destination
            self.occupied[destination] = atom_id
        if trusted and all(destination in trusted[0].sites for destination in changes.values()):
            self._changed_sites.update(sources.values())
            self._changed_sites.update(changes.values())
            self._local = (trusted[0], self.signature())

    def validate(self, topology: Topology) -> None:
        signature = self.signature()
        if signature is not None and self._validated == (topology, signature):
            return
        if signature is not None and self._local == (topology, signature):
            try:
                topology.validate_changed_occupancy(self.occupied, self._changed_sites)
            except TopologyError as error:
                raise StateInvariantError(error.code) from error
            self._validated = (topology, signature)
            self._changed_sites.clear()
            self._local = None
            return
        from backend.atomic_model.regular_grid import IdealAtoms, IdealOccupied
        if (isinstance(self.atoms, SparseMap) and isinstance(self.atoms.baseline, IdealAtoms)
                and isinstance(self.occupied, SparseMap) and isinstance(self.occupied.baseline, IdealOccupied)
                and self.atoms.baseline.dimensions == topology.dimensions
                and self.atoms.baseline.offset == topology.metal_domain.offset
                and self.occupied.baseline.atoms.dimensions == topology.dimensions
                and self.occupied.baseline.atoms.offset == topology.metal_domain.offset):
            # Untouched entries are bijective by construction; audit the overlays.
            changed_sites = set(self.occupied.changed_keys())
            for atom_id in self.atoms.changed_keys():
                old = self.atoms.baseline.get(atom_id)
                if old is not None:
                    changed_sites.add(old)
                new = self.atoms.get(atom_id)
                if new is not None:
                    changed_sites.add(new)
                    if new not in topology.sites or self.occupied.get(new) != atom_id:
                        raise StateInvariantError("OCCUPANCY_MISMATCH")
            if len(self.atoms) != len(self.occupied):
                raise StateInvariantError("OCCUPANCY_MISMATCH")
            for site in changed_sites:
                occupant = self.occupied.get(site)
                if occupant is not None and self.atoms.get(occupant) != site:
                    raise StateInvariantError("OCCUPANCY_MISMATCH")
            try:
                topology.validate_changed_occupancy(self.occupied, changed_sites)
            except TopologyError as error:
                raise StateInvariantError(error.code) from error
            self._validated = (topology, signature)
            return
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
        if signature is not None:
            self._validated = (topology, signature)

    def to_dict(self) -> dict:
        from backend.atomic_model.regular_grid import IdealAtoms, IdealOccupied
        if (isinstance(self.atoms, SparseMap) and isinstance(self.atoms.baseline, IdealAtoms)
                and isinstance(self.occupied, SparseMap) and isinstance(self.occupied.baseline, IdealOccupied)
                and len(self.atoms.baseline) >= 10000):
            return {
                "storage": "sparse_regular_v1",
                "dimensions": self.atoms.baseline.dimensions, "offset": self.atoms.baseline.offset,
                "atoms": {key: self.atoms.get(key) for key in self.atoms.changed_keys()
                          if self.atoms.get(key) != self.atoms.baseline.get(key)},
                "occupied": {key: self.occupied.get(key) for key in self.occupied.changed_keys()
                             if self.occupied.get(key) != self.occupied.baseline.get(key)},
                "act_number": self.act_number, "revision": self.revision,
                "events": deepcopy(self.events), "metrics_points": deepcopy(self.metrics_points),
                "configuration": deepcopy(self.configuration),
            }
        return {
            "atoms": dict(self.atoms),
            "occupied": dict(self.occupied),
            "act_number": self.act_number,
            "revision": self.revision,
            "events": deepcopy(self.events),
            "metrics_points": deepcopy(self.metrics_points),
            "configuration": deepcopy(self.configuration),
        }

    @classmethod
    def from_dict(cls, payload):
        if payload.get("storage") == "sparse_regular_v1":
            from backend.atomic_model.regular_grid import RegularSites
            config = deepcopy(payload["configuration"])
            topology = Topology.create(config["dimensions"], contour=config.get("contour"))
            if (not isinstance(topology.sites, RegularSites)
                    or tuple(payload["dimensions"]) != topology.dimensions
                    or tuple(payload["offset"]) != topology.metal_domain.offset):
                raise StateInvariantError("INVALID_SPARSE_BASELINE")
            state = cls.create_ideal(topology, config)
            for field_name, parse in (("atoms", int), ("occupied", str)):
                target = getattr(state, field_name)
                for raw_key, value in payload[field_name].items():
                    key = parse(raw_key)
                    if value is None:
                        target.pop(key, None)
                    else:
                        target[key] = int(value) if field_name == "occupied" else value
            state.act_number = payload.get("act_number", 0)
            state.revision = payload.get("revision", 0)
            state.events = deepcopy(payload.get("events", []))
            state.metrics_points = deepcopy(payload.get("metrics_points", []))
            state.validate(topology)
            return state
        if payload.get("storage") is not None:
            raise StateInvariantError("UNKNOWN_STATE_STORAGE")
        return cls(
            atoms={int(key): value for key, value in payload["atoms"].items()},
            occupied={key: int(value) for key, value in payload["occupied"].items()},
            act_number=payload.get("act_number", 0), revision=payload.get("revision", 0),
            events=deepcopy(payload.get("events", [])), metrics_points=deepcopy(payload.get("metrics_points", [])),
            configuration=deepcopy(payload.get("configuration", {})),
        )
