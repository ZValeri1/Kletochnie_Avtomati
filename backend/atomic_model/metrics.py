from __future__ import annotations

import math

from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology
from backend.contracts.simulation import MetricsPoint, SimulationMetrics


class MetricsCalculator:
    def calculate(self, topology: Topology, state: SimulationState) -> SimulationMetrics:
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
