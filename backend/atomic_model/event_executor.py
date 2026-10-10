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

    def execute_cascade(
        self,
        topology: Topology,
        source: SimulationState,
        candidates: list[EventCandidate],
    ) -> ExecutionResult:
        """Apply a cascade chain (multiple displacements) as a single act.

        Used by the cellular automata method for R2-R3 cascades
        (Kinchin-Pease model). All candidates are applied sequentially
        to one state copy; act_number and revision increment once.

        Args:
            topology: lattice topology
            source: current state (read-only)
            candidates: list of EventCandidate from cascade_chain()

        Returns:
            ExecutionResult with all affected atoms and sites.

        Raises:
            InvalidEventError: if candidates list is empty or any
                displacement violates invariants.
        """
        if not candidates:
            raise InvalidEventError("EMPTY_CASCADE")

        state = source.transition_copy()
        affected_atoms: list[int] = []
        affected_sites: list[str] = []

        for candidate in candidates:
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
            except StateInvariantError as error:
                raise InvalidEventError(str(error)) from error

            affected_atoms.append(candidate.atom_id)
            affected_sites.extend([candidate.source_key, candidate.destination_key])

        # Single act increment for the whole cascade
        state.act_number += 1
        state.revision += 1
        try:
            state.validate(topology)
        except StateInvariantError as error:
            raise InvalidEventError(str(error)) from error

        return ExecutionResult(
            state=state,
            affected_atom_ids=tuple(affected_atoms),
            affected_site_ids=tuple(affected_sites),
        )
