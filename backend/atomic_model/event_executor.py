from __future__ import annotations

from dataclasses import dataclass

from backend.atomic_model.errors import InvalidEventError, StateInvariantError
from backend.atomic_model.events import EventCandidate
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology


@dataclass(frozen=True)
class ExecutionResult:
    state: SimulationState
    affected_atom_ids: tuple[int, ...]
    affected_site_ids: tuple[str, ...]


class EventExecutor:
    ALLOWED_OPERATIONS = {
        "lattice_vacancy",
        "lattice_interstitial",
        "interstitial_vacancy",
        "interstitial_interstitial",
        "boundary_external",
        "external_external",
        "external_interstitial",
        "interstitial_external",
        "external_metal",
    }

    def execute(
        self,
        topology: Topology,
        source: SimulationState,
        candidate: EventCandidate,
    ) -> ExecutionResult:
        state = source.transition_copy()
        if candidate.atom_id not in state.atoms:
            raise InvalidEventError("Atom does not exist")
        if candidate.operation not in self.ALLOWED_OPERATIONS:
            raise InvalidEventError("Operation is not executable")
        if candidate.destination_key not in topology.sites:
            raise InvalidEventError("Destination does not exist")
        if state.atoms[candidate.atom_id] != candidate.source_key:
            raise InvalidEventError("Atomic event source changed before commit")
        if candidate.destination_key in state.occupied:
            raise InvalidEventError("Destination is occupied")
        try:
            state.relocate(candidate.atom_id, candidate.destination_key)
            state.act_number += 1
            state.revision += 1
            state.validate(topology)
        except StateInvariantError as error:
            raise InvalidEventError(str(error)) from error
        return ExecutionResult(
            state=state,
            affected_atom_ids=(candidate.atom_id,),
            affected_site_ids=(candidate.source_key, candidate.destination_key),
        )
