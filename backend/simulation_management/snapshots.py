from __future__ import annotations

from copy import deepcopy

from backend.atomic_model.events import EventEngine
from backend.atomic_model.initialization import InitializationCounts
from backend.atomic_model.metrics import MetricsCalculator
from backend.contracts.simulation import (
    AtomSnapshot,
    DefectCounts,
    HistoryCapabilities,
    SimulationMetrics,
    SimulationConfiguration,
    SimulationSnapshot,
    SimulationSummary,
)


class SnapshotFactory:
    @classmethod
    def create(cls, session) -> SimulationSnapshot:
        if (
            session.status.value == "FAILED"
            and isinstance(session.last_valid_snapshot, SimulationSnapshot)
        ):
            history = session.history
            return session.last_valid_snapshot.model_copy(
                update={
                    "revision": session.revision,
                    "status": session.status.value,
                    "phase": (
                        "SIMULATION"
                        if getattr(session, "has_started", False)
                        else "PREPARATION"
                    ),
                    "config_locked": getattr(session, "has_started", False),
                    "history_capabilities": HistoryCapabilities(
                        can_undo=history.can_undo,
                        can_redo=history.can_redo,
                        retained_action_count=history.retained_action_count,
                        history_limit=history.history_limit,
                        history_truncated=history.history_truncated,
                    ),
                    "error": session.error,
                }
            )
        if session.state is None:
            raw = deepcopy(session.last_valid_snapshot)
            dimensions = tuple(raw.get("dimensions", session.configuration.get("dimensions", (4, 4))))
            atoms = tuple(
                AtomSnapshot(
                    id=item["id"],
                    site_key=item["site_key"],
                    coordinate=tuple(item["coordinate"]),
                    site_kind=item["site_kind"],
                    metal_relation=item["metal_relation"],
                    visual_state=item["visual_state"],
                )
                for item in raw.get("atoms", [])
            )
            metrics = SimulationMetrics.model_validate(
                raw.get(
                    "metrics",
                    {
                        "n_correct": len(atoms),
                        "n_v": 0,
                        "n_i": 0,
                        "n_as": 0,
                        "d": 0,
                        "s": 0.0,
                    },
                )
            )
            return SimulationSnapshot(
                simulation_id=session.simulation_id,
                revision=raw.get("revision", 0),
                status=session.status.value,
                phase=(
                    "SIMULATION"
                    if getattr(session, "has_started", False)
                    else "PREPARATION"
                ),
                config_locked=getattr(session, "has_started", False),
                configuration=SimulationConfiguration.model_validate(
                    raw["configuration"]
                ),
                dimensions=dimensions,
                atoms=atoms,
                vacancies=tuple(raw.get("vacancies", [])),
                metrics=metrics,
                counts=DefectCounts.model_validate(raw["counts"]),
                history_capabilities=HistoryCapabilities(
                    can_undo=session.history.can_undo,
                    can_redo=session.history.can_redo,
                    retained_action_count=getattr(
                        session.history, "retained_action_count", 0
                    ),
                    history_limit=getattr(session.history, "history_limit", 100),
                    history_truncated=getattr(
                        session.history, "history_truncated", False
                    ),
                ),
                error=getattr(session, "error", None),
            )

        state = session.state
        topology = session.topology
        metrics = MetricsCalculator().calculate(topology, state)
        counts = InitializationCounts.from_state(topology, state)
        atoms = tuple(
            AtomSnapshot(
                id=atom_id,
                site_key=site_key,
                coordinate=topology.sites[site_key].coordinate,
                site_kind=topology.sites[site_key].kind,
                metal_relation=topology.sites[site_key].metal_relation,
                visual_state=cls._visual_state(topology, site_key),
            )
            for atom_id, site_key in sorted(state.atoms.items())
        )
        vacancies = tuple(
            site.coordinate
            for site in topology.sites.values()
            if site.key in topology.metal_domain.lattice_keys and site.key not in state.occupied
        )
        return SimulationSnapshot(
            simulation_id=session.simulation_id,
            revision=getattr(session, "revision", state.revision),
            status=session.status.value,
            phase="SIMULATION" if getattr(session, "has_started", False) else "PREPARATION",
            config_locked=getattr(session, "has_started", False),
            configuration=cls._configuration(session.configuration, topology),
            dimensions=topology.movement_field.dimensions,
            atoms=atoms,
            vacancies=vacancies,
            metrics=metrics,
            counts=DefectCounts(**counts.__dict__),
            history_capabilities=HistoryCapabilities(
                can_undo=session.history.can_undo,
                can_redo=session.history.can_redo,
                retained_action_count=getattr(
                    session.history, "retained_action_count", 0
                ),
                history_limit=getattr(session.history, "history_limit", 100),
                history_truncated=getattr(
                    session.history, "history_truncated", False
                ),
            ),
            error=getattr(session, "error", None),
        )

    @staticmethod
    def create_summary(session) -> SimulationSummary:
        return SimulationSummary(
            simulation_id=session.simulation_id,
            status=session.status.value,
            revision=session.revision,
            seed_init=session.configuration.get("seed_init"),
            seed_sim=session.configuration.get("seed_sim"),
            source_project_id=getattr(session, "source_project_id", None),
            source_simulation_id=getattr(session, "source_simulation_id", None),
            last_valid_snapshot=deepcopy(session.last_valid_snapshot),
            error=session.error,
        )

    @staticmethod
    def _configuration(configuration: dict, topology) -> SimulationConfiguration:
        effective_weights = {
            **EventEngine.DEFAULT_OPERATION_WEIGHTS,
            "shell_r1": EventEngine.DEFAULT_SHELL_WEIGHTS[1],
            "shell_r2": EventEngine.DEFAULT_SHELL_WEIGHTS[2],
            **EventEngine.DEFAULT_POSITION_WEIGHTS,
            **configuration.get("weights", {}),
        }
        return SimulationConfiguration(
            dimensions=tuple(configuration["dimensions"]),
            field_dimensions=topology.movement_field.dimensions,
            contour=configuration.get("contour"),
            profile=configuration["profile"],
            initialization_mode=configuration["initialization_mode"],
            n_v=configuration.get("n_v", 0),
            n_i=configuration.get("n_i", 0),
            n_as=configuration.get("n_as", 0),
            random_parameters=deepcopy(configuration.get("random_parameters", {})),
            seed_init=configuration["seed_init"],
            seed_sim=configuration["seed_sim"],
            q_max_ev=configuration["q_max_ev"],
            q_thr_ev=configuration["q_thr_ev"],
            weights=effective_weights,
        )

    @staticmethod
    def _visual_state(topology, site_key: str) -> str:
        site = topology.sites[site_key]
        if site.metal_relation == "outside":
            return "external"
        if site.kind == "interstitial":
            return "interstitial"
        if site.metal_relation == "boundary":
            return "boundary"
        return "correct"
