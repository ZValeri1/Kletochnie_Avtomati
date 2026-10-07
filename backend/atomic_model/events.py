from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from typing import Any, Literal

from backend.atomic_model.errors import StateInvariantError, TopologyError
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology


class RandomSource:
    def __init__(self, seed: int | None = None) -> None:
        self.seed = seed
        self._random = random.Random(seed)

    def get_state(self):
        return self._random.getstate()

    def set_state(self, state) -> None:
        self._random.setstate(state)

    def random(self) -> float:
        return self._random.random()

    def choice(self, values):
        return self._random.choice(values)

    def sample(self, values, count: int):
        return self._random.sample(values, count)

    def shuffle(self, values) -> None:
        self._random.shuffle(values)

    def betavariate(self, alpha: float, beta: float) -> float:
        return self._random.betavariate(alpha, beta)


@dataclass(frozen=True)
class EventCandidate:
    operation: str
    atom_id: int
    source_key: str
    destination_key: str
    shell: int
    operation_weight: float
    shell_weight: float
    position_weight: float
    total_weight: float
    probability: float

@dataclass(frozen=True)
class ProbabilityOutcome:
    source_site: str
    source_coordinate: tuple[float, ...]
    source_kind: str
    destination_site: str
    destination_coordinate: tuple[float, ...]
    destination_kind: str
    destination_relation: str
    operation: str | None
    shell: int
    operation_weight: float
    shell_weight: float
    position_weight: float
    total_weight: float
    probability: float
    selectable: bool
    block_code: str | None
    q_test: float
    q_thr: float

@dataclass(frozen=True)
class EventRecord:
    event_id: str
    simulation_id: str | None
    revision: int
    act_number: int
    source_atom_id: int | None
    source_site: str | None
    source_coordinate: tuple[float, ...] | None
    destination_site: str | None
    destination_coordinate: tuple[float, ...] | None
    operation: str
    shell: int | None
    q_n: float | None
    q_thr: float | None
    result_reason: str
    operation_weight: float
    shell_weight: float
    position_weight: float
    total_weight: float
    probability: float
    affected_atom_ids: tuple[int, ...]
    affected_site_ids: tuple[str, ...]
    metrics_before: dict[str, Any]
    metrics_after: dict[str, Any]
    origin: Literal["physical_act", "manual_edit"] = "physical_act"

    @classmethod
    def create(cls, **values) -> "EventRecord":
        event_id = f"{values.get('origin', 'physical_act')}:{values['revision']}"
        return cls(event_id=event_id, simulation_id=None, **values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventEngine:
    DEFAULT_OPERATION_WEIGHTS = {
        "lattice_vacancy": 0.70,
        "lattice_interstitial": 0.20,
        "interstitial_vacancy_r1": 0.90,
        "interstitial_vacancy_r2": 0.30,
        "interstitial_interstitial": 1.00,
        "boundary_external": 0.02,
        "external_external": 1.00,
        "external_interstitial": 0.20,
        "interstitial_external": 1.00,
        "external_metal": 0.00,
    }
    DEFAULT_SHELL_WEIGHTS = {1: 0.75, 2: 0.25}
    DEFAULT_POSITION_WEIGHTS = {
        "vacancy": 0.80,
        "interstitial": 0.20,
        "external": 0.05,
    }

    def __init__(self, configuration: dict | None = None) -> None:
        configuration = configuration or {}
        self.q_thr = float(configuration.get("q_thr_ev", 20.0))
        self.weights = dict(configuration.get("weights") or {})

    def probabilities(
        self,
        topology: Topology,
        state: SimulationState,
        atom_id: int,
        q_test: float,
    ) -> list[ProbabilityOutcome]:
        if atom_id not in state.atoms:
            raise StateInvariantError("UNKNOWN_ATOM")
        if q_test < 0:
            raise ValueError("q_test cannot be negative")
        source_key = state.atoms[atom_id]
        source = topology.sites[source_key]
        raw: list[dict[str, Any]] = []
        for shell in (1, 2):
            for destination_key in sorted(topology.shell(source_key, shell)):
                destination = topology.sites[destination_key]
                operation = self._operation(source_key, destination_key, shell, topology)
                # Public field names are retained for schema compatibility,
                # but they now carry the three probability factors from the
                # model specification rather than arbitrary weights.
                operation_weight = self._type_probability(destination_key, topology)
                shell_weight = self._shell_weight(shell)
                position_weight = self._relation_probability(
                    source_key, destination_key, topology
                )
                total_weight = operation_weight * shell_weight * position_weight
                block_code = self._block_code(
                    topology,
                    state,
                    atom_id,
                    destination_key,
                    shell,
                    operation,
                    q_test,
                    total_weight,
                )
                raw.append(
                    {
                        "source_site": source_key,
                        "source_coordinate": source.coordinate,
                        "source_kind": source.kind,
                        "destination_site": destination_key,
                        "destination_coordinate": destination.coordinate,
                        "destination_kind": destination.kind,
                        "destination_relation": destination.metal_relation,
                        "operation": operation,
                        "shell": shell,
                        "operation_weight": operation_weight,
                        "shell_weight": shell_weight,
                        "position_weight": position_weight,
                        "total_weight": total_weight,
                        "selectable": block_code is None,
                        "block_code": block_code,
                        "q_test": float(q_test),
                        "q_thr": self.q_thr,
                    }
                )
        group_sizes: dict[tuple[str, int, str], int] = {}
        for item in raw:
            if not item["selectable"]:
                continue
            group = (
                item["destination_kind"],
                item["shell"],
                "outside" if item["destination_relation"] == "outside" else "inside",
            )
            group_sizes[group] = group_sizes.get(group, 0) + 1
        return [
            ProbabilityOutcome(
                **item,
                probability=(
                    item["total_weight"]
                    / group_sizes[
                        (
                            item["destination_kind"],
                            item["shell"],
                            "outside"
                            if item["destination_relation"] == "outside"
                            else "inside",
                        )
                    ]
                    if item["selectable"]
                    else 0.0
                ),
            )
            for item in raw
        ]

    def choose(
        self,
        outcomes: list[ProbabilityOutcome],
        atom_id: int,
        random_source: RandomSource,
    ) -> EventCandidate | None:
        selectable = [item for item in outcomes if item.selectable]
        if not selectable:
            return None
        point = random_source.random()
        for outcome in selectable:
            point -= outcome.probability
            if point < 0:
                return EventCandidate(
                    operation=outcome.operation,
                    atom_id=atom_id,
                    source_key=outcome.source_site,
                    destination_key=outcome.destination_site,
                    shell=outcome.shell,
                    operation_weight=outcome.operation_weight,
                    shell_weight=outcome.shell_weight,
                    position_weight=outcome.position_weight,
                    total_weight=outcome.total_weight,
                    probability=outcome.probability,
                )
        # Missing probability mass means that this activated atom does not
        # move during the current act.
        return None

    def candidates(
        self, topology: Topology, state: SimulationState, atom_id: int
    ) -> tuple[EventCandidate, ...]:
        outcomes = self.probabilities(topology, state, atom_id, self.q_thr)
        return tuple(
            EventCandidate(
                operation=item.operation,
                atom_id=atom_id,
                source_key=item.source_site,
                destination_key=item.destination_site,
                shell=item.shell,
                operation_weight=item.operation_weight,
                shell_weight=item.shell_weight,
                position_weight=item.position_weight,
                total_weight=item.total_weight,
                probability=item.probability,
            )
            for item in outcomes
            if item.selectable
        )

    def _block_code(
        self,
        topology: Topology,
        state: SimulationState,
        atom_id: int,
        destination_key: str,
        shell: int,
        operation: str | None,
        q_test: float,
        total_weight: float,
    ) -> str | None:
        if operation is None:
            return "UNSUPPORTED_TRANSITION"
        if destination_key in state.occupied:
            return "DESTINATION_OCCUPIED"
        if q_test < self.q_thr:
            return "BELOW_THRESHOLD"
        if total_weight <= 0:
            return "ZERO_PROBABILITY"
        trial = state.working_copy()
        try:
            trial.relocate(atom_id, destination_key)
            trial.validate(topology)
        except StateInvariantError:
            return "DISCONNECTED_RESULT"
        return None

    @staticmethod
    def _path_blocked(
        topology: Topology,
        state: SimulationState,
        source_key: str,
        destination_key: str,
    ) -> bool:
        try:
            paths = topology.all_shortest_paths(source_key, destination_key)
        except TopologyError:
            return True
        return any(
            site_key in state.occupied
            for path in paths
            for site_key in path[1:-1]
        )

    @staticmethod
    def _operation(
        source_key: str,
        destination_key: str,
        shell: int,
        topology: Topology,
    ) -> str | None:
        source = topology.sites[source_key]
        destination = topology.sites[destination_key]
        source_outside = source.metal_relation == "outside"
        destination_outside = destination.metal_relation == "outside"
        destination_metal = destination_key in topology.metal_domain.lattice_keys

        if source_outside and not destination_outside:
            return "external_metal"
        if source.kind == "lattice" and not source_outside:
            if destination_metal:
                return "lattice_vacancy"
            if destination_outside:
                return "boundary_external"
            if destination.kind == "interstitial" and not destination_outside:
                return "lattice_interstitial"
            return None
        if source.kind == "lattice" and source_outside:
            if destination.kind == "interstitial":
                return "external_interstitial"
            if destination_outside:
                return "external_external"
            return None
        if source.kind == "interstitial":
            if destination_metal:
                return "external_metal" if source_outside else "interstitial_vacancy"
            if destination.kind == "interstitial":
                return "external_interstitial" if source_outside else "interstitial_interstitial"
            if destination_outside and not source_outside:
                return "boundary_external"
            if source_outside and destination_outside:
                return "interstitial_external"
        return None

    def _type_probability(self, destination_key: str, topology: Topology) -> float:
        kind = "vacancy" if topology.sites[destination_key].kind == "lattice" else "interstitial"
        return float(self.weights.get(kind, self.DEFAULT_POSITION_WEIGHTS[kind]))

    def _shell_weight(self, shell: int) -> float:
        return float(
            self.weights.get(
                f"shell_r{shell}", self.DEFAULT_SHELL_WEIGHTS[shell]
            )
        )

    def _relation_probability(
        self, source_key: str, destination_key: str, topology: Topology
    ) -> float:
        source = topology.sites[source_key]
        destination = topology.sites[destination_key]
        if source.metal_relation == "outside":
            inside_probability = float(
                self.weights.get("external_metal", self.DEFAULT_OPERATION_WEIGHTS["external_metal"])
            )
            return inside_probability if destination.metal_relation != "outside" else 1.0 - inside_probability
        outside_probability = float(
            self.weights.get("external", self.DEFAULT_POSITION_WEIGHTS["external"])
        )
        return outside_probability if destination.metal_relation == "outside" else 1.0 - outside_probability
