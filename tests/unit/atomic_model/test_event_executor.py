from dataclasses import replace

import pytest

from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.errors import InvalidEventError
from backend.atomic_model.event_executor import EventExecutor
from backend.atomic_model.events import EventCandidate, RandomSource


def _candidate(outcome, atom_id: int) -> EventCandidate:
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


def _first(engine, state, operation: str, atom_id: int | None = None):
    atom_ids = [atom_id] if atom_id is not None else sorted(state.atoms)
    for candidate_atom_id in atom_ids:
        for outcome in engine.probabilities(state, candidate_atom_id, 30):
            if outcome.selectable and outcome.operation == operation:
                return candidate_atom_id, outcome
    raise AssertionError(f"No selectable {operation} candidate")


def _execute_first(engine, topology, state, operation: str, atom_id: int | None = None):
    selected_atom_id, outcome = _first(engine, state, operation, atom_id)
    result = EventExecutor().execute(
        topology, state, _candidate(outcome, selected_atom_id)
    )
    return result.state, selected_atom_id


def _scenario(operation: str):
    engine = SimulationEngine()
    initial = engine.create_initial_state(
        {
            "dimensions": [4, 4],
            "seed_init": 7,
            "seed_sim": 8,
            "q_max_ev": 40,
            "q_thr_ev": 20,
        },
        RandomSource(8),
    )
    topology = initial.topology
    state = initial.state
    if operation in {"lattice_interstitial", "boundary_external"}:
        return engine, topology, state, *_first(engine, state, operation)
    if operation in {
        "lattice_vacancy",
        "interstitial_vacancy",
        "interstitial_interstitial",
    }:
        state, interstitial_atom_id = _execute_first(
            engine, topology, state, "lattice_interstitial"
        )
        atom_id = (
            interstitial_atom_id
            if operation != "lattice_vacancy"
            else None
        )
        return engine, topology, state, *_first(engine, state, operation, atom_id)
    state, external_atom_id = _execute_first(
        engine, topology, state, "boundary_external"
    )
    if operation == "interstitial_external":
        return engine, topology, state, *_first(
            engine, state, operation, external_atom_id
        )
    state, external_atom_id = _execute_first(
        engine, topology, state, "interstitial_external", external_atom_id
    )
    return engine, topology, state, *_first(
        engine, state, operation, external_atom_id
    )


@pytest.mark.parametrize(
    "operation",
    [
        "lattice_vacancy",
        "lattice_interstitial",
        "interstitial_vacancy",
        "interstitial_interstitial",
        "boundary_external",
        "external_external",
        "external_interstitial",
        "interstitial_external",
    ],
)
def test_each_positive_operation_moves_exactly_one_atom_atomically(operation):
    _, topology, source, atom_id, outcome = _scenario(operation)
    before = source.to_dict()

    result = EventExecutor().execute(topology, source, _candidate(outcome, atom_id))

    assert source.to_dict() == before
    assert result.state.atoms[atom_id] == outcome.destination_site
    assert len(result.state.atoms) == len(source.atoms)
    assert result.affected_atom_ids == (atom_id,)
    assert result.affected_site_ids == (outcome.source_site, outcome.destination_site)
    result.state.validate(topology)


def test_executor_rejects_an_occupied_destination_without_mutating_source():
    _, topology, source, atom_id, outcome = _scenario("lattice_interstitial")
    occupied_destination = next(
        key for key in sorted(topology.metal_domain.lattice_keys)
        if key != outcome.source_site and key in source.occupied
    )
    invalid = replace(outcome, destination_site=occupied_destination)
    before = source.to_dict()

    with pytest.raises(InvalidEventError):
        EventExecutor().execute(topology, source, _candidate(invalid, atom_id))

    assert source.to_dict() == before
