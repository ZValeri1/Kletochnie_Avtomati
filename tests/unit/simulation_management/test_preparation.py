"""P2 lifecycle and atomic manual-edit acceptance cases."""

import pytest

from backend.atomic_model.initialization import InitializationCounts
from backend.atomic_model.errors import InitializationError, StateInvariantError, TopologyError
from backend.atomic_model.events import RandomSource
from backend.simulation_management.errors import PreparationCommandError
from backend.simulation_management.manager import SimulationManager
from backend.simulation_management.session import SimulationSession
from tests.support import call, config, status_value


def _created():
    manager = SimulationManager()
    summary = call(manager.create, config())
    session = manager.sessions[summary.simulation_id]
    return manager, summary.simulation_id, session


def _outside_contact(session):
    return next(
        neighbor
        for metal in sorted(session.topology.metal_domain.lattice_keys)
        for neighbor in session.topology.contact_neighbors(metal)
        if session.topology.sites[neighbor].metal_relation == "outside"
        and neighbor not in session.state.occupied
    )


def test_preparation_add_remove_and_move_do_not_count_as_irradiation_acts():
    manager, simulation_id, session = _created()
    assert status_value(call(manager.get_summary, simulation_id)) == "PREPARATION"
    outside = _outside_contact(session)
    added = call(manager.add_atom, simulation_id, expected_revision=0, destination_key=outside)
    new_id = max(session.state.atoms)
    assert added.event.operation == "manual_edit"
    assert session.state.act_number == 0
    assert InitializationCounts.from_state(session.topology, session.state).n_as == 1
    assert added.snapshot.counts.n_as == 1

    removed = call(manager.remove_atom, simulation_id, expected_revision=1, atom_id=new_id)
    assert removed.event.operation == "manual_edit"
    assert session.state.act_number == 0
    assert InitializationCounts.from_state(session.topology, session.state).n_as == 0
    assert removed.snapshot.counts.n_as == 0

    source = next(
        key for key in session.topology.metal_domain.lattice_keys
        if session.topology.sites[key].metal_relation == "interior"
    )
    destination = next(
        key for key in session.topology.contact_neighbors(source)
        if session.topology.sites[key].kind == "interstitial"
    )
    moved = call(
        manager.move, simulation_id, expected_revision=2,
        atom_id=session.state.occupied[source], destination_key=destination,
    )
    assert moved.event.operation == "manual_edit"
    assert session.state.act_number == 0
    assert session.state.events[-1]["q_n"] is None


def test_manual_edit_preview_reports_before_and_after_without_committing_state():
    manager = SimulationManager()
    random_source = RandomSource(12)
    initial = manager.engine.create_initial_state(config(), random_source)
    simulation_id = "preview-simulation"
    session = SimulationSession.create(
        simulation_id,
        initial.state.configuration,
        {},
        random_source.get_state(),
        state=initial.state,
        topology=initial.topology,
        random_source=random_source,
    )
    manager.sessions[simulation_id] = session
    source = next(
        key for key in session.topology.metal_domain.lattice_keys
        if session.topology.sites[key].metal_relation == "interior"
    )
    destination = next(
        key for key in session.topology.contact_neighbors(source)
        if session.topology.sites[key].kind == "interstitial"
    )
    state_before = session.state.to_dict()
    history_before = session.history.retained_action_count

    preview = call(
        manager.preview_edit,
        simulation_id,
        expected_revision=0,
        action="move",
        atom_id=session.state.occupied[source],
        destination_key=destination,
    )

    assert preview.revision == 0
    assert preview.action == "move"
    assert preview.counts_before.n_atoms == 16
    assert preview.counts_after.n_atoms == 16
    assert preview.metrics_before.n_v == 0
    assert preview.metrics_after.n_v == 1
    assert preview.metrics_after.n_i == 1
    assert session.state.to_dict() == state_before
    assert session.revision == 0
    assert session.history.retained_action_count == history_before


def test_boundary_edit_and_initialization_configuration_lock_on_first_step():
    manager, simulation_id, session = _created()
    contour = ((0, 0), (3, 0), (3, 2), (2, 2), (2, 3), (0, 3), (0, 0))
    edited = call(
        manager.edit_metal_boundary, simulation_id, expected_revision=0, contour=contour
    )
    assert edited.revision == 1
    assert session.topology.metal_domain.contour == contour
    assert session.state.act_number == 0
    assert session.history.can_undo

    stepped = call(manager.step, simulation_id, expected_revision=1)
    assert stepped.snapshot.status == "PAUSED"
    assert session.has_started
    with pytest.raises(PreparationCommandError, match="BOUNDARY_LOCKED"):
        call(manager.edit_metal_boundary, simulation_id, expected_revision=2, contour=contour)
    with pytest.raises(PreparationCommandError, match="EDIT_NOT_ALLOWED"):
        call(manager.add_atom, simulation_id, expected_revision=2, destination_key=_outside_contact(session))
    with pytest.raises(PreparationCommandError, match="EDIT_NOT_ALLOWED"):
        call(manager.configure_initialization, simulation_id, expected_revision=2,
             initialization={"initialization_mode": "ordered"})


def test_invalid_manual_edit_is_atomic_and_external_reentry_is_forbidden():
    manager, simulation_id, session = _created()
    far = next(
        key for key, site in session.topology.sites.items()
        if site.metal_relation == "outside"
        and not session.topology.contact_neighbors(key) & session.state.occupied.keys()
    )
    before = session.state.to_dict()
    with pytest.raises(StateInvariantError, match="DISCONNECTED_ATOM"):
        call(manager.add_atom, simulation_id, expected_revision=0, destination_key=far)
    assert session.state.to_dict() == before
    assert session.revision == 0
    assert not session.history.can_undo

    outside = _outside_contact(session)
    call(manager.add_atom, simulation_id, expected_revision=0, destination_key=outside)
    outside_atom = session.state.occupied[outside]
    metal = next(
        key for key in session.topology.metal_domain.lattice_keys
        if session.topology.sites[key].metal_relation == "interior"
    )
    call(manager.remove_atom, simulation_id, expected_revision=1,
         atom_id=session.state.occupied[metal])
    before = session.state.to_dict()
    with pytest.raises(StateInvariantError, match="EXTERNAL_REENTRY_FORBIDDEN"):
        call(manager.move, simulation_id, expected_revision=2,
             atom_id=outside_atom, destination_key=metal)
    assert session.state.to_dict() == before
    assert session.revision == 2


def test_configure_initialization_rebuilds_preparation_state_and_start_locks_it():
    manager, simulation_id, session = _created()
    changed = call(
        manager.configure_initialization,
        simulation_id,
        expected_revision=0,
        initialization={
            "initialization_mode": "explicit_defective",
            "n_v": 2,
            "n_i": 1,
            "n_as": 0,
            "seed_init": 47,
        },
    )
    assert changed.revision == 1
    assert InitializationCounts.from_state(session.topology, session.state).n_atoms == 15
    started = call(manager.start, simulation_id)
    assert status_value(started) == "PAUSED"
    assert session.has_started
    with pytest.raises(PreparationCommandError, match="EDIT_NOT_ALLOWED"):
        call(manager.remove_atom, simulation_id, expected_revision=1,
             atom_id=next(iter(session.state.atoms)))


def test_preparation_history_restores_the_matching_boundary_and_configuration():
    manager, simulation_id, session = _created()
    original_keys = session.topology.metal_domain.lattice_keys
    contour = ((0, 0), (3, 0), (3, 2), (2, 2), (2, 3), (0, 3), (0, 0))
    call(manager.edit_metal_boundary, simulation_id, expected_revision=0, contour=contour)
    edited_keys = session.topology.metal_domain.lattice_keys
    assert edited_keys != original_keys
    undone = call(manager.undo, simulation_id)
    assert undone.revision == 2
    assert session.topology.metal_domain.lattice_keys == original_keys
    assert "contour" not in session.configuration
    redone = call(manager.redo, simulation_id)
    assert redone.revision == 3
    assert session.topology.metal_domain.lattice_keys == edited_keys
    assert session.configuration["contour"] == list(contour)


def test_running_blocks_manual_move_and_paused_move_preserves_act_number():
    manager, simulation_id, session = _created()
    call(manager.run, simulation_id)
    source = next(
        key for key in session.topology.metal_domain.lattice_keys
        if session.topology.sites[key].metal_relation == "interior"
    )
    destination = next(
        key for key in session.topology.contact_neighbors(source)
        if session.topology.sites[key].kind == "interstitial"
    )
    with pytest.raises(PreparationCommandError, match="SIMULATION_NOT_PAUSED"):
        call(manager.move, simulation_id, expected_revision=session.revision,
             atom_id=session.state.occupied[source], destination_key=destination)
    call(manager.pause, simulation_id)
    act_before = session.state.act_number
    moved = call(manager.move, simulation_id, expected_revision=session.revision,
                 atom_id=session.state.occupied[source], destination_key=destination)
    assert moved.event.operation == "manual_edit"
    assert session.state.act_number == act_before


def test_infeasible_creation_never_registers_a_partial_session():
    manager = SimulationManager()
    with pytest.raises(InitializationError, match="INITIAL_CONFIGURATION_INFEASIBLE"):
        call(
            manager.create,
            config(
                dimensions=[2, 2],
                initialization_mode="explicit_defective",
                n_i=999,
            ),
        )
    assert manager.sessions == {}


def test_preparation_project_round_trip_keeps_phase_and_editability():
    manager, simulation_id, session = _created()
    payload = call(manager.export_project, "prepared", [simulation_id])
    restored = SimulationManager()
    imported = call(restored.import_project, payload)
    restored_id = imported[0].simulation_id
    restored_session = restored.sessions[restored_id]
    assert status_value(imported[0]) == "PREPARATION"
    assert not restored_session.has_started
    outside = _outside_contact(restored_session)
    result = call(
        restored.add_atom, restored_id, expected_revision=0,
        destination_key=outside,
    )
    assert result.snapshot.counts.n_as == 1


def test_manual_destinations_include_valid_same_kind_vacancy_only():
    manager, simulation_id, session = _created()
    vacant = next(
        key for key in session.topology.metal_domain.lattice_keys
        if session.topology.sites[key].metal_relation == "interior"
    )
    call(manager.remove_atom, simulation_id, expected_revision=0,
         atom_id=session.state.occupied[vacant])
    atom_id = next(iter(session.state.atoms))
    destinations = call(manager.destinations, simulation_id, atom_id)
    selectable = {item["key"] for item in destinations if item["selectable"]}
    blocked = {
        item["key"]: item["block_code"]
        for item in destinations
        if not item["selectable"]
    }
    occupied = next(
        key for key, occupant in session.state.occupied.items()
        if occupant != atom_id
    )
    disconnected = next(
        key for key, site in session.topology.sites.items()
        if key not in session.state.occupied
        and site.metal_relation == "outside"
        and not session.topology.contact_neighbors(key) & session.state.occupied.keys()
    )

    assert vacant in selectable
    assert occupied not in selectable
    assert blocked[occupied] == "SITE_OCCUPIED"
    assert blocked[disconnected] == "DISCONNECTED_ATOM"


def test_invalid_reconfiguration_and_boundary_leave_state_rng_and_history_unchanged():
    manager, simulation_id, session = _created()
    state_before = session.state.to_dict()
    rng_before = session.random_source.get_state()
    with pytest.raises(InitializationError, match="INVALID_DEFECT_COUNT"):
        call(
            manager.configure_initialization,
            simulation_id,
            expected_revision=0,
            initialization={"initialization_mode": "explicit_defective", "n_v": -1},
        )
    with pytest.raises(TopologyError, match="INVALID_METAL_DOMAIN"):
        call(
            manager.edit_metal_boundary,
            simulation_id,
            expected_revision=0,
            contour=((0, 0), (3, 0), (3, 3)),
        )
    assert session.state.to_dict() == state_before
    assert session.random_source.get_state() == rng_before
    assert session.revision == 0
    assert not session.history.can_undo


def test_three_dimensional_preparation_keeps_a_rectangular_domain():
    manager = SimulationManager()
    summary = call(manager.create, config(dimensions=[3, 3, 3]))
    session = manager.sessions[summary.simulation_id]
    outside = _outside_contact(session)
    added = call(
        manager.add_atom, summary.simulation_id, expected_revision=0,
        destination_key=outside,
    )
    assert added.snapshot.counts.n_as == 1
    with pytest.raises(TopologyError, match="INVALID_METAL_DOMAIN"):
        call(
            manager.edit_metal_boundary,
            summary.simulation_id,
            expected_revision=1,
            contour=((0, 0), (2, 0), (2, 2), (0, 2), (0, 0)),
        )
    assert session.revision == 1
    assert session.topology.metal_domain.contour is None


def test_missing_initial_seed_is_generated_and_saved_separately_from_simulation_seed():
    manager = SimulationManager()
    summary = call(manager.create, config(seed_init=None, seed_sim=None))
    session = manager.sessions[summary.simulation_id]
    assert isinstance(summary.seed_init, int)
    assert isinstance(summary.seed_sim, int)
    assert session.state.configuration["seed_init"] == summary.seed_init
    assert session.configuration["seed_sim"] == summary.seed_sim


def test_boundary_edit_cannot_reclassify_an_external_atom_as_metal():
    manager, simulation_id, session = _created()
    smaller = ((0, 0), (3, 0), (3, 2), (2, 2), (2, 3), (0, 3), (0, 0))
    call(manager.edit_metal_boundary, simulation_id, expected_revision=0, contour=smaller)
    before = session.state.to_dict()
    original_rectangle = ((0, 0), (3, 0), (3, 3), (0, 3), (0, 0))
    with pytest.raises(StateInvariantError, match="EXTERNAL_REENTRY_FORBIDDEN"):
        call(
            manager.edit_metal_boundary, simulation_id, expected_revision=1,
            contour=original_rectangle,
        )
    assert session.state.to_dict() == before
    assert session.revision == 1
