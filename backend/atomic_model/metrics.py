from __future__ import annotations

import math

from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology
from backend.contracts.simulation import MetricsPoint, SimulationMetrics


class MetricsCalculator:
    def calculate(self, topology: Topology, state: SimulationState) -> SimulationMetrics:
        signature = state.signature()
        if signature is not None and state._metric_signature == signature and state._metric_topology is topology and state._metrics is not None:
            return SimulationMetrics(**state._metrics)
        from backend.atomic_model.regular_grid import IdealAtoms, IdealOccupied
        from backend.atomic_model.sparse_map import SparseMap
        if (isinstance(state.atoms, SparseMap) and isinstance(state.atoms.baseline, IdealAtoms)
                and isinstance(state.occupied.baseline, IdealOccupied)
                and state.atoms.baseline.dimensions == topology.dimensions
                and state.atoms.baseline.offset == topology.metal_domain.offset):
            values = {"n_correct": len(state.atoms.baseline), "n_i": 0, "n_as": 0,
                      "n_v": sum(key in topology.metal_domain.lattice_keys and key not in state.occupied
                                 for key in state.occupied.changed_keys())}
            for atom_id in state.atoms.changed_keys():
                if atom_id in state.atoms.baseline:
                    values["n_correct"] -= 1
                key = state.atoms.get(atom_id)
                if key is not None:
                    site = topology.sites[key]
                    values["n_as" if site.metal_relation == "outside" else "n_i" if site.kind == "interstitial" else "n_correct"] += 1
            metrics = self.from_counts(values)
            state._metrics, state._metric_signature, state._metric_topology = metrics.model_dump(), signature, topology
            return metrics
        vacancies = sum(
            key not in state.occupied for key in topology.metal_domain.lattice_keys
        )
        correct = 0
        interstitials = 0
        external = 0
        for site_key in state.atoms.values():
            site = topology.sites[site_key]
            if site.metal_relation == "outside":
                external += 1
            elif site.kind == "interstitial":
                interstitials += 1
            else:
                correct += 1
        metrics = self.from_counts({"n_correct": correct, "n_v": vacancies, "n_i": interstitials, "n_as": external})
        state._metrics = metrics.model_dump()
        state._metric_signature = signature
        state._metric_topology = topology
        return metrics

    @staticmethod
    def from_counts(values) -> SimulationMetrics:
        correct, vacancies, interstitials, external = (values[key] for key in ("n_correct", "n_v", "n_i", "n_as"))
        groups = (correct, vacancies, interstitials, external)
        total = sum(groups)
        if total == 0:
            raise ValueError("Metrics require at least one structural category")
        entropy = -sum(
            count * math.log(count / total) for count in groups if count
        )
        return SimulationMetrics(
            n_correct=correct,
            n_v=vacancies,
            n_i=interstitials,
            n_as=external,
            d=vacancies + interstitials + external,
            s=max(0.0, entropy),
        )

    def point(
        self,
        topology: Topology,
        state: SimulationState,
        origin: str,
    ) -> MetricsPoint:
        metrics = self.calculate(topology, state)
        return MetricsPoint(
            **metrics.model_dump(),
            revision=state.revision,
            act_number=state.act_number,
            origin=origin,
        )
