from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache

from backend.atomic_model.errors import InvalidEventError, StateInvariantError, TopologyError
from backend.atomic_model.event_executor import EventExecutor
from backend.atomic_model.events import (
    EventEngine,
    EventRecord,
    ProbabilityOutcome,
    RandomSource,
)
from backend.atomic_model.initialization import Initializer
from backend.atomic_model.metrics import MetricsCalculator
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology
from backend.contracts.simulation import SimulationMetrics


@dataclass(frozen=True)
class InitialStateResult:
    topology: Topology
    state: SimulationState
    metrics: SimulationMetrics


@dataclass(frozen=True)
class StepResult:
    topology: Topology
    state: SimulationState
    event: EventRecord | dict
    metrics: SimulationMetrics


class SimulationEngine:
    def __init__(self) -> None:
        self.metrics_calculator = MetricsCalculator()
        self.executor = EventExecutor()
        self.initializer = Initializer()

    def create_initial_state(
        self, configuration: dict, random_source: RandomSource
    ) -> InitialStateResult:
        config = self._validated_configuration(configuration)
        topology = self._topology(config)
        state = self.initializer.build(topology, config)
        state.validate(topology)
        metrics = self.metrics_calculator.calculate(topology, state)
        state.metrics_points = [
            self.metrics_calculator.point(
                topology, state, "initialization"
            ).model_dump()
        ]
        return InitialStateResult(
            topology,
            state,
            metrics,
        )

    def step(
        self,
        source: SimulationState,
        random_source: RandomSource,
    ) -> StepResult:
        topology = self._topology(source.configuration)
        metrics_before = self.metrics_calculator.calculate(topology, source)
        rng_before = random_source.get_state()
        try:
            if not source.atoms:
                raise InvalidEventError("NO_ATOMS")
            atom_id = random_source.choice(sorted(source.atoms))
            q_n = source.configuration["q_max_ev"] * random_source.betavariate(1, 4)
            q_thr = source.configuration["q_thr_ev"]
            event_engine = EventEngine(source.configuration)
            if q_n < q_thr:
                state = source.transition_copy()
                state.act_number += 1
                state.revision += 1
                candidate = None
                reason = "BELOW_THRESHOLD"
            else:
                outcomes = event_engine.probabilities(
                    topology, source, atom_id, q_n
                )
                candidate = event_engine.choose(outcomes, atom_id, random_source)
                if candidate is None:
                    state = source.transition_copy()
                    state.act_number += 1
                    state.revision += 1
                    reason = "NO_POSITIVE_CANDIDATE"
                else:
                    execution = self.executor.execute(topology, source, candidate)
                    state = execution.state
                    reason = "APPLIED"
                    if len(state.atoms) != len(source.atoms):
                        raise InvalidEventError("INVARIANT_VIOLATION")
            state.validate(topology)
            metrics = self.metrics_calculator.calculate(topology, state)
            state.metrics_points.append(
                self.metrics_calculator.point(
                    topology, state, "physical_act"
                ).model_dump()
            )
            source_site = source.atoms[atom_id]
            destination_site = candidate.destination_key if candidate else None
            event = EventRecord.create(
                revision=state.revision,
                act_number=state.act_number,
                source_atom_id=atom_id,
                source_site=source_site,
                source_coordinate=topology.sites[source_site].coordinate,
                destination_site=destination_site,
                destination_coordinate=(
                    topology.sites[destination_site].coordinate
                    if destination_site is not None
                    else None
                ),
                operation=candidate.operation if candidate else "no_change",
                shell=candidate.shell if candidate else None,
                q_n=q_n,
                q_thr=q_thr,
                result_reason=reason,
                operation_weight=candidate.operation_weight if candidate else 0.0,
                shell_weight=candidate.shell_weight if candidate else 0.0,
                position_weight=candidate.position_weight if candidate else 0.0,
                total_weight=candidate.total_weight if candidate else 0.0,
                probability=candidate.probability if candidate else 1.0,
                affected_atom_ids=(atom_id,) if candidate else (),
                affected_site_ids=(source_site, destination_site) if candidate else (),
                metrics_before=metrics_before.model_dump(),
                metrics_after=metrics.model_dump(),
            )
            state.events.append(event.to_dict())
            return StepResult(topology, state, event, metrics)
        except Exception:
            random_source.set_state(rng_before)
            raise

    def move(self, source: SimulationState, atom_id: int, destination_key: str) -> StepResult:
        return self._manual_edit(source, "move", atom_id=atom_id, destination_key=destination_key)

    def add_atom(self, source: SimulationState, destination_key: str) -> StepResult:
        return self._manual_edit(source, "add", destination_key=destination_key)

    def remove_atom(self, source: SimulationState, atom_id: int) -> StepResult:
        return self._manual_edit(source, "remove", atom_id=atom_id)

    def _manual_edit(
        self,
        source: SimulationState,
        action: str,
        *,
        atom_id: int | None = None,
        destination_key: str | None = None,
    ) -> StepResult:
        topology = self._topology(source.configuration)
        metrics_before = self.metrics_calculator.calculate(topology, source)
        state = source.working_copy()
        source_key = state.atoms.get(atom_id) if atom_id is not None else None
        if action in {"move", "remove"} and source_key is None:
            raise StateInvariantError("UNKNOWN_ATOM")
        if action in {"move", "add"}:
            if destination_key not in topology.sites:
                raise StateInvariantError("UNKNOWN_SITE")
            if destination_key in state.occupied:
                raise StateInvariantError("SITE_OCCUPIED")
        if action == "move":
            if (
                topology.sites[source_key].metal_relation == "outside"
                and topology.sites[destination_key].metal_relation != "outside"
            ):
                raise StateInvariantError("EXTERNAL_REENTRY_FORBIDDEN")
            state.relocate(atom_id, destination_key)
        elif action == "add":
            atom_id = max(state.atoms, default=-1) + 1
            state.atoms[atom_id] = destination_key
            state.occupied[destination_key] = atom_id
        elif action == "remove":
            del state.atoms[atom_id]
            del state.occupied[source_key]
        else:
            raise ValueError("Unknown manual edit action")
        state.validate(topology)
        state.revision += 1
        metrics = self.metrics_calculator.calculate(topology, state)
        state.metrics_points.append(
            self.metrics_calculator.point(
                topology, state, "manual_edit"
            ).model_dump()
        )
        affected_sites = tuple(
            key for key in (source_key, destination_key) if key is not None
        )
        event = EventRecord.create(
            revision=state.revision,
            act_number=state.act_number,
            source_atom_id=atom_id,
            source_site=source_key,
            source_coordinate=(
                topology.sites[source_key].coordinate
                if source_key is not None
                else None
            ),
            destination_site=destination_key,
            destination_coordinate=(
                topology.sites[destination_key].coordinate
                if destination_key is not None
                else None
            ),
            operation="manual_edit",
            shell=None,
            q_n=None,
            q_thr=None,
            result_reason=action,
            operation_weight=0.0,
            shell_weight=0.0,
            position_weight=0.0,
            total_weight=0.0,
            probability=1.0,
            affected_atom_ids=(atom_id,),
            affected_site_ids=affected_sites,
            metrics_before=metrics_before.model_dump(),
            metrics_after=metrics.model_dump(),
            origin="manual_edit",
        )
        state.events.append(event.to_dict())
        return StepResult(topology, state, event, metrics)

    def probabilities(
        self, source: SimulationState, atom_id: int, q_test: float
    ) -> list[ProbabilityOutcome]:
        topology = self._topology(source.configuration)
        return EventEngine(source.configuration).probabilities(
            topology, source, atom_id, q_test
        )

    def destinations(self, source: SimulationState, atom_id: int) -> list[dict]:
        if atom_id not in source.atoms:
            raise StateInvariantError("UNKNOWN_ATOM")
        topology = self._topology(source.configuration)
        source_key = source.atoms[atom_id]
        source_outside = topology.sites[source_key].metal_relation == "outside"
        occupied_after_removal = dict(source.occupied)
        del occupied_after_removal[source_key]
        result = []
        for site in topology.sites.values():
            if site.key == source_key:
                continue
            block_code = None
            if site.key in occupied_after_removal:
                block_code = "SITE_OCCUPIED"
            elif source_outside and site.metal_relation != "outside":
                block_code = "EXTERNAL_REENTRY_FORBIDDEN"
            elif (
                site.key not in topology.metal_domain.lattice_keys
                and not topology.contact_neighbors(site.key) & occupied_after_removal.keys()
            ):
                block_code = "DISCONNECTED_ATOM"
            else:
                trial_occupied = {**occupied_after_removal, site.key: atom_id}
                try:
                    topology.validate_occupancy(trial_occupied)
                except TopologyError as error:
                    block_code = error.code
            result.append(
                {
                    "key": site.key,
                    "kind": site.kind,
                    "coordinate": site.coordinate,
                    "selectable": block_code is None,
                    "block_code": block_code,
                }
            )
        return result

    @staticmethod
    def _topology(configuration: dict) -> Topology:
        contour = configuration.get("contour")
        normalized_contour = (
            tuple(tuple(point) for point in contour) if contour is not None else None
        )
        return SimulationEngine._cached_topology(
            tuple(configuration["dimensions"]), normalized_contour
        )

    @staticmethod
    @lru_cache(maxsize=128)
    def _cached_topology(
        dimensions: tuple[int, ...],
        contour: tuple[tuple[int, int], ...] | None,
    ) -> Topology:
        return Topology.create(dimensions, contour=contour)

    @staticmethod
    def _validated_configuration(configuration: dict) -> dict:
        config = dict(configuration)
        config["dimensions"] = list(config.get("dimensions", (30, 30)))
        config.setdefault("profile", "fe_co60_physical")
        allowed = {
            "dimensions", "contour", "profile", "initialization_mode",
            "n_v", "n_i", "n_as", "random_parameters", "seed_init", "seed_sim",
            "q_max_ev", "q_thr_ev", "weights",
        }
        unknown = set(config) - allowed
        if unknown:
            raise ValueError(f"Unsupported configuration parameter: {sorted(unknown)[0]}")
        config.setdefault("initialization_mode", "ordered")
        if config.get("seed_init") is None:
            config["seed_init"] = secrets.randbits(63)
        config.setdefault("q_max_ev", 82.0)
        config.setdefault("q_thr_ev", 20.0)
        config.setdefault("weights", {})
        if not isinstance(config["dimensions"], list) or len(config["dimensions"]) not in (2, 3):
            raise ValueError("dimensions must contain two or three axes")
        if any(not isinstance(size, int) or isinstance(size, bool) or size < 2 for size in config["dimensions"]):
            raise ValueError("each dimension must contain at least two nodes")
        if config["profile"] != "fe_co60_physical":
            raise ValueError("Unsupported profile")
        if min(
            config["q_max_ev"],
            config["q_thr_ev"],
        ) < 0:
            raise ValueError("energy configuration cannot be negative")
        allowed_weights = {
            *EventEngine.DEFAULT_OPERATION_WEIGHTS,
            "shell_r1",
            "shell_r2",
            *EventEngine.DEFAULT_POSITION_WEIGHTS,
            *EventEngine.DEFAULT_SOURCE_PROBABILITIES,
        }
        if not isinstance(config["weights"], dict):
            raise ValueError("weights must be a mapping")
        if set(config["weights"]) - allowed_weights:
            raise ValueError("unsupported event weight")
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= value <= 1
            for value in config["weights"].values()
        ):
            raise ValueError("transition probabilities must be in the range 0..1")
        effective = EventEngine.effective_source_probabilities(config["weights"])
        for source_kind in ("lattice", "interstitial"):
            for left_suffix, right_suffix in (
                ("vacancy", "interstitial"),
                ("shell_r1", "shell_r2"),
                ("inside", "outside"),
            ):
                left = f"from_{source_kind}_{left_suffix}"
                right = f"from_{source_kind}_{right_suffix}"
                if abs(effective[left] + effective[right] - 1.0) <= 1e-9:
                    continue
                raise ValueError(f"{left} and {right} probabilities must sum to 1")
        return config
