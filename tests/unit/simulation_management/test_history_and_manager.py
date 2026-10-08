import asyncio
import threading

import pytest

from tests.support import call, config, status_value, symbol, value


def new_manager(max_parallel_simulations: int = 2):
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    return manager_class(max_parallel_simulations=max_parallel_simulations)


def test_history_restores_state_and_rng_and_discards_an_old_redo_branch():
    history_class = symbol(
        "backend.simulation_management.history", "SimulationHistory"
    )
    history = history_class(initial_state={"revision": 0}, random_state=("rng", 0))
    history.commit(state={"revision": 1}, random_state=("rng", 1))

    initial = history.undo()
    restored = history.redo()
    history.undo()
    history.commit(state={"revision": 2}, random_state=("rng", 2))

    assert value(initial, "state") == {"revision": 0}
    assert value(initial, "random_state") == ("rng", 0)
    assert value(restored, "state") == {"revision": 1}
    assert value(restored, "random_state") == ("rng", 1)
    assert history.can_redo is False


def test_history_protects_initial_and_retains_only_the_last_100_actions():
    history_class = symbol(
        "backend.simulation_management.history", "SimulationHistory"
    )
    history = history_class(initial_state={"action": 0}, random_state=("rng", 0))

    for action in range(1, 102):
        history.commit(
            state={"action": action},
            random_state=("rng", action),
            source_revision=action,
        )

    exported = history.export()

    assert history.retained_action_count == 100
    assert history.history_limit == 100
    assert history.history_truncated is True
    assert len(exported["checkpoints"]) == 101
    assert exported["checkpoints"][0]["state"] == {"action": 0}
    assert exported["checkpoints"][1]["state"] == {"action": 2}
    assert exported["checkpoints"][-1]["source_revision"] == 101


def test_history_commit_does_not_recopy_existing_event_log_entries():
    history_class = symbol(
        "backend.simulation_management.history", "SimulationHistory"
    )
    state_class = symbol("backend.atomic_model.state", "SimulationState")

    class CopyProbe:
        copies = 0

        def __deepcopy__(self, memo):
            self.copies += 1
            return self

    old_event = CopyProbe()
    initial = state_class(
        atoms={1: "lattice:0,0"},
        occupied={"lattice:0,0": 1},
        events=[old_event],
        metrics_points=[],
    )
    history = history_class(initial, random_state=("rng", 0))
    copies_after_initial_checkpoint = old_event.copies
    events = [old_event]

    for action in range(1, 151):
        events.append({"revision": action})
        history.commit(
            state=state_class(
                atoms={1: f"lattice:{action},0"},
                occupied={f"lattice:{action},0": 1},
                act_number=action,
                revision=action,
                events=list(events),
                metrics_points=[{"revision": action}],
            ),
            random_state=("rng", action),
            source_revision=action,
        )

    assert old_event.copies == copies_after_initial_checkpoint
    assert history.checkpoint_count <= 4
    assert history.undo().state.act_number == 149
    assert history.redo().state.act_number == 150


def test_session_exposes_the_complete_p4_command_matrix():
    session_class = symbol(
        "backend.simulation_management.session", "SimulationSession"
    )
    status_class = symbol(
        "backend.simulation_management.session", "SimulationStatus"
    )
    expected = {
        "PREPARATION": {
            "configure", "boundary", "add", "remove", "move", "start",
            "step", "run", "undo", "redo", "destinations",
        },
        "PAUSED": {
            "step", "run", "move", "diagnostics", "destinations", "undo",
            "redo", "reset", "stop",
        },
        "RUNNING": {"run", "pause", "stop", "undo", "redo"},
        "PAUSED_WITH_ERROR": {
            "retry", "undo", "reset", "acknowledge", "diagnostics",
            "destinations",
        },
        "STOPPED": {"reset"},
        "FAILED": {"reset"},
    }

    assert set(status_class) == {status_class[name] for name in expected}
    for status_name, commands in expected.items():
        assert session_class.allowed_commands(status_class[status_name]) == commands


def test_manager_creates_unique_isolated_simulations():
    manager = new_manager()

    left = call(manager.create, config(seed_sim=21))
    right = call(manager.create, config(seed_sim=22))
    call(manager.step, value(left, "simulation_id"), expected_revision=0)

    left_snapshot = call(manager.get_snapshot, value(left, "simulation_id"))
    right_snapshot = call(manager.get_snapshot, value(right, "simulation_id"))

    assert value(left, "simulation_id") != value(right, "simulation_id")
    assert value(left_snapshot, "revision") == 1
    assert value(right_snapshot, "revision") == 0


def test_batch_uses_reproducible_unique_derived_seeds():
    left_manager = new_manager()
    right_manager = new_manager()

    left = call(left_manager.create_batch, config(), count=3, master_seed=91)
    right = call(right_manager.create_batch, config(), count=3, master_seed=91)

    left_seeds = [value(summary, "seed_sim") for summary in left]
    right_seeds = [value(summary, "seed_sim") for summary in right]
    assert left_seeds == right_seeds
    assert len(set(left_seeds)) == 3


def test_revision_conflict_does_not_change_the_snapshot():
    conflict_error = symbol(
        "backend.simulation_management.errors", "RevisionConflictError"
    )
    manager = new_manager()
    created = call(manager.create, config())
    simulation_id = value(created, "simulation_id")
    before = call(manager.get_snapshot, simulation_id)

    with pytest.raises(conflict_error):
        call(manager.step, simulation_id, expected_revision=7)

    after = call(manager.get_snapshot, simulation_id)
    assert value(after, "revision") == value(before, "revision")
    assert value(after, "atoms") == value(before, "atoms")


def test_lifecycle_transitions_are_scoped_to_one_simulation():
    manager = new_manager()
    left = call(manager.create, config())
    right = call(manager.create, config())
    left_id = value(left, "simulation_id")
    right_id = value(right, "simulation_id")

    assert status_value(call(manager.run, left_id)) == "RUNNING"
    assert status_value(call(manager.pause, left_id)) == "PAUSED"
    assert status_value(call(manager.stop, left_id)) == "STOPPED"
    right_summary = next(
        item
        for item in call(manager.list)
        if value(item, "simulation_id") == right_id
    )
    assert status_value(right_summary) == "PREPARATION"


def test_unknown_or_stopped_simulation_rejects_step_without_side_effects():
    command_error = symbol(
        "backend.simulation_management.errors", "InvalidSimulationCommandError"
    )
    manager = new_manager()
    created = call(manager.create, config())
    simulation_id = value(created, "simulation_id")
    call(manager.start, simulation_id, expected_revision=0)
    call(manager.stop, simulation_id)

    with pytest.raises(command_error):
        call(manager.step, simulation_id, expected_revision=0)
    with pytest.raises(command_error):
        call(manager.step, "missing", expected_revision=0)

    assert status_value(call(manager.list)[0]) == "STOPPED"


def test_session_failure_keeps_the_last_valid_snapshot():
    session_class = symbol(
        "backend.simulation_management.session", "SimulationSession"
    )
    snapshot = {"simulation_id": "sim-a", "revision": 2, "atoms": []}
    session = session_class.create(
        simulation_id="sim-a",
        configuration=config(),
        initial_snapshot=snapshot,
        random_state=("rng", 2),
    )

    session.record_failure(code="INVALID_STATE", message="invalid state")

    assert status_value(session) == "FAILED"
    assert value(session, "last_valid_snapshot") == snapshot
    assert value(value(session, "error"), "code") == "INVALID_STATE"


def test_undo_redo_restores_rng_and_a_new_step_removes_redo():
    manager = new_manager()
    created = call(manager.create, config(seed_sim=77))
    simulation_id = value(created, "simulation_id")
    first = call(manager.step, simulation_id, expected_revision=0)
    first_snapshot = value(first, "snapshot")

    undone = call(manager.undo, simulation_id)
    assert value(undone, "revision") == value(first_snapshot, "revision") + 1
    replayed = call(
        manager.step,
        simulation_id,
        expected_revision=value(undone, "revision"),
    )
    snapshot = call(manager.get_snapshot, simulation_id)

    assert value(value(replayed, "event"), "operation") == value(
        value(first, "event"), "operation"
    )
    assert value(value(replayed, "snapshot"), "atoms") == value(first_snapshot, "atoms")
    assert value(value(replayed, "snapshot"), "revision") == value(undone, "revision") + 1
    assert value(value(snapshot, "history_capabilities"), "can_redo") is False


def test_history_navigation_restores_journal_metrics_rng_and_uses_monotonic_revision():
    manager = new_manager()
    created = call(manager.create, config(seed_sim=83))
    simulation_id = value(created, "simulation_id")
    call(manager.step, simulation_id, expected_revision=0)
    session = manager.sessions[simulation_id]
    first_events = list(session.state.events)
    first_metrics = list(session.state.metrics_points)
    first_rng = session.random_source.get_state()
    call(manager.step, simulation_id, expected_revision=1)

    undone = call(manager.undo, simulation_id, expected_revision=2)

    assert value(undone, "revision") == 3
    assert session.state.events == first_events
    assert session.state.metrics_points == first_metrics
    assert session.random_source.get_state() == first_rng
    redone = call(manager.redo, simulation_id, expected_revision=3)
    assert value(redone, "revision") == 4
    assert session.state.act_number == 2


def test_stale_history_command_is_rejected_without_moving_the_cursor():
    conflict_error = symbol(
        "backend.simulation_management.errors", "RevisionConflictError"
    )
    manager = new_manager()
    created = call(manager.create, config())
    simulation_id = value(created, "simulation_id")
    call(manager.step, simulation_id, expected_revision=0)
    session = manager.sessions[simulation_id]
    before = session.history.export()

    with pytest.raises(conflict_error):
        call(manager.undo, simulation_id, expected_revision=0)

    assert session.history.export() == before
    assert session.revision == 1


def test_undo_while_running_finishes_one_inflight_step_and_stays_paused():
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class BlockingEngine(engine_class):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()
            self.step_count = 0

        def step(self, source, random_source):
            self.step_count += 1
            self.started.set()
            if not self.release.wait(timeout=2):
                raise TimeoutError("test barrier was not released")
            return super().step(source, random_source)

    async def scenario():
        engine = BlockingEngine()
        manager = new_manager()
        manager.engine = engine
        created = await manager.create(config())
        simulation_id = created.simulation_id
        await manager.run(simulation_id)
        assert await asyncio.to_thread(engine.started.wait, 1)
        requested_revision = manager.sessions[simulation_id].revision
        undo_task = asyncio.create_task(
            manager.undo(simulation_id, expected_revision=requested_revision)
        )
        await asyncio.sleep(0)
        engine.release.set()
        snapshot = await asyncio.wait_for(undo_task, timeout=2)
        session = manager.sessions[simulation_id]
        outcome = (
            status_value(session),
            session.state.act_number,
            session.revision,
        )
        await manager.close()
        return snapshot, engine.step_count, outcome

    snapshot, step_count, outcome = asyncio.run(scenario())
    assert step_count == 1
    assert outcome[0] == "PAUSED"
    assert snapshot.status == "PAUSED"
    assert outcome[1] == 0
    assert outcome[2] == 3


def test_redo_while_running_uses_the_safe_pause_barrier_without_an_extra_step():
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class SwitchableBlockingEngine(engine_class):
        def __init__(self):
            super().__init__()
            self.block = False
            self.started = threading.Event()
            self.release = threading.Event()
            self.step_count = 0

        def step(self, source, random_source):
            self.step_count += 1
            if self.block:
                self.started.set()
                if not self.release.wait(timeout=2):
                    raise TimeoutError("test barrier was not released")
            return super().step(source, random_source)

    async def scenario():
        engine = SwitchableBlockingEngine()
        manager = new_manager()
        manager.engine = engine
        created = await manager.create(config(seed_sim=31))
        simulation_id = created.simulation_id
        await manager.step(simulation_id, expected_revision=0)
        await manager.undo(simulation_id, expected_revision=1)
        engine.block = True
        await manager.run(simulation_id)
        assert await asyncio.to_thread(engine.started.wait, 1)
        requested_revision = manager.sessions[simulation_id].revision
        redo_task = asyncio.create_task(
            manager.redo(simulation_id, expected_revision=requested_revision)
        )
        await asyncio.sleep(0)
        engine.release.set()
        snapshot = await asyncio.wait_for(redo_task, timeout=2)
        session = manager.sessions[simulation_id]
        outcome = (
            status_value(session),
            session.state.act_number,
            session.revision,
            session.history.can_redo,
        )
        await manager.close()
        return snapshot, engine.step_count, outcome

    snapshot, step_count, outcome = asyncio.run(scenario())
    assert step_count == 2
    assert outcome == ("PAUSED", 1, 5, False)
    assert snapshot.status == "PAUSED"


def test_recoverable_step_error_rolls_back_rng_and_retry_matches_control():
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class FailOnceEngine(engine_class):
        def __init__(self):
            super().__init__()
            self.failed = False

        def step(self, source, random_source):
            if not self.failed:
                self.failed = True
                random_source.random()
                raise RuntimeError("temporary calculation failure")
            return super().step(source, random_source)

    failing = new_manager()
    failing.engine = FailOnceEngine()
    created = call(failing.create, config(seed_sim=97, q_max_ev=82))
    simulation_id = created.simulation_id
    session = failing.sessions[simulation_id]
    state_before = session.state.to_dict()
    rng_before = session.random_source.get_state()

    with pytest.raises(RuntimeError, match="temporary calculation failure"):
        call(failing.step, simulation_id, expected_revision=0)

    assert status_value(session) == "PAUSED_WITH_ERROR"
    assert session.state.to_dict() == state_before
    assert session.random_source.get_state() == rng_before
    assert session.revision == 0
    assert session.error.recoverable is True
    assert session.error.revision == 0

    retried = call(failing.retry, simulation_id, expected_revision=0)
    control = new_manager()
    control_created = call(control.create, config(seed_sim=97, q_max_ev=82))
    expected = call(control.step, control_created.simulation_id, expected_revision=0)

    assert retried.event.operation == expected.event.operation
    assert retried.event.source_atom_id == expected.event.source_atom_id
    assert retried.event.destination_site == expected.event.destination_site
    assert retried.event.q_n == expected.event.q_n
    assert retried.snapshot.atoms == expected.snapshot.atoms
    assert status_value(session) == "PAUSED"
    assert session.error is None


def test_scheduler_timeout_is_recoverable_and_cannot_mutate_live_rng():
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    scheduler_class = symbol(
        "backend.simulation_management.scheduler", "SimulationScheduler"
    )
    timeout_error = symbol(
        "backend.simulation_management.errors", "SimulationTimeoutError"
    )

    class BlockingEngine(engine_class):
        def __init__(self):
            super().__init__()
            self.release = threading.Event()

        def step(self, source, random_source):
            random_source.random()
            self.release.wait(timeout=1)
            return super().step(source, random_source)

    engine = BlockingEngine()
    manager = manager_class(
        engine=engine,
        scheduler=scheduler_class(command_timeout_seconds=0.01),
    )
    created = call(manager.create, config(seed_sim=101))
    session = manager.sessions[created.simulation_id]
    state_before = session.state.to_dict()
    rng_before = session.random_source.get_state()

    try:
        with pytest.raises(timeout_error):
            call(manager.step, created.simulation_id, expected_revision=0)
    finally:
        engine.release.set()

    assert status_value(session) == "PAUSED_WITH_ERROR"
    assert session.state.to_dict() == state_before
    assert session.random_source.get_state() == rng_before
    assert session.error.recoverable is True


def test_acknowledge_clears_a_recoverable_error_without_changing_physics():
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class FailingEngine(engine_class):
        def step(self, source, random_source):
            raise RuntimeError("temporary failure")

    manager = new_manager()
    manager.engine = FailingEngine()
    created = call(manager.create, config())
    session = manager.sessions[created.simulation_id]
    before = session.state.to_dict()
    with pytest.raises(RuntimeError, match="temporary failure"):
        call(manager.step, created.simulation_id, expected_revision=0)

    summary = call(manager.acknowledge, created.simulation_id, expected_revision=0)

    assert status_value(summary) == "PAUSED"
    assert session.state.to_dict() == before
    assert session.error is None
    assert session.revision == 1


def test_undo_from_recoverable_error_clears_error_and_stays_paused():
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class FailSecondStepEngine(engine_class):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def step(self, source, random_source):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("temporary second-step failure")
            return super().step(source, random_source)

    manager = new_manager()
    manager.engine = FailSecondStepEngine()
    created = call(manager.create, config())
    simulation_id = created.simulation_id
    call(manager.step, simulation_id, expected_revision=0)
    session = manager.sessions[simulation_id]
    with pytest.raises(RuntimeError, match="temporary second-step failure"):
        call(manager.step, simulation_id, expected_revision=1)

    snapshot = call(manager.undo, simulation_id, expected_revision=1)

    assert snapshot.status == "PAUSED"
    assert session.state.act_number == 0
    assert session.error is None
    assert session.pending_retry is None
    assert session.revision == 2


def test_invalid_committed_state_fails_only_its_own_simulation():
    state_error = symbol("backend.atomic_model.errors", "StateInvariantError")
    manager = new_manager()
    left = call(manager.create, config(seed_sim=1))
    right = call(manager.create, config(seed_sim=2))
    left_session = manager.sessions[left.simulation_id]
    last_valid = call(manager.get_snapshot, left.simulation_id)
    left_session.state.occupied.clear()

    with pytest.raises(state_error):
        call(manager.step, left.simulation_id, expected_revision=0)

    assert status_value(left_session) == "FAILED"
    assert left_session.error.recoverable is False
    failed_snapshot = call(manager.get_snapshot, left.simulation_id)
    assert failed_snapshot.status == "FAILED"
    assert failed_snapshot.atoms == last_valid.atoms
    assert failed_snapshot.vacancies == last_valid.vacancies
    assert failed_snapshot.metrics == last_valid.metrics
    assert failed_snapshot.error.code == "STATE_INVALID"
    right_result = call(manager.step, right.simulation_id, expected_revision=0)
    assert right_result.revision == 1


def test_reset_starts_a_clean_reproducible_trajectory_from_prepared_state():
    manager = new_manager()
    created = call(manager.create, config(seed_sim=109, q_max_ev=82))
    simulation_id = created.simulation_id
    session = manager.sessions[simulation_id]
    source = next(
        key for key in session.topology.metal_domain.lattice_keys
        if session.topology.sites[key].metal_relation == "interior"
    )
    destination = next(
        key for key in session.topology.contact_neighbors(source)
        if session.topology.sites[key].kind == "interstitial"
    )
    call(
        manager.move,
        simulation_id,
        expected_revision=0,
        atom_id=session.state.occupied[source],
        destination_key=destination,
    )
    prepared_atoms = dict(session.state.atoms)
    call(manager.start, simulation_id)
    first = call(manager.step, simulation_id, expected_revision=session.revision)
    revision_before_reset = session.revision

    reset_snapshot = call(
        manager.reset,
        simulation_id,
        expected_revision=revision_before_reset,
    )

    assert reset_snapshot.status == "PAUSED"
    assert session.state.atoms == prepared_atoms
    assert session.state.act_number == 0
    assert session.state.events == []
    assert len(session.state.metrics_points) == 1
    assert session.state.metrics_points[0]["origin"] == "initialization"
    assert session.history.retained_action_count == 0
    replayed = call(
        manager.step,
        simulation_id,
        expected_revision=reset_snapshot.revision,
    )
    assert replayed.event.operation == first.event.operation
    assert replayed.event.source_atom_id == first.event.source_atom_id
    assert replayed.event.destination_site == first.event.destination_site
    assert replayed.event.q_n == first.event.q_n


def test_action_journal_and_metrics_use_the_public_monotonic_revision():
    manager = new_manager()
    created = call(manager.create, config())
    simulation_id = created.simulation_id
    started = call(manager.start, simulation_id, expected_revision=0)
    result = call(
        manager.step,
        simulation_id,
        expected_revision=started.revision,
    )
    session = manager.sessions[simulation_id]

    assert result.revision == 2
    assert result.event.revision == 2
    assert session.state.events[-1]["revision"] == 2
    assert session.state.metrics_points[-1]["revision"] == 2


def test_manager_snapshot_reports_truncated_history_and_keeps_initial_reachable():
    manager = new_manager()
    created = call(manager.create, config())
    simulation_id = created.simulation_id
    session = manager.sessions[simulation_id]
    for _ in range(101):
        call(manager.step, simulation_id, expected_revision=session.revision)

    snapshot = call(manager.get_snapshot, simulation_id)

    assert snapshot.history_capabilities.retained_action_count == 100
    assert snapshot.history_capabilities.history_limit == 100
    assert snapshot.history_capabilities.history_truncated is True
    for _ in range(100):
        call(manager.undo, simulation_id, expected_revision=session.revision)
    assert session.state.act_number == 0
    assert session.state.events == []


def test_diagnostics_are_pause_only_and_do_not_change_the_trajectory():
    command_error = symbol(
        "backend.simulation_management.errors", "InvalidSimulationCommandError"
    )
    manager = new_manager()
    created = call(manager.create, config(q_max_ev=82))
    simulation_id = created.simulation_id
    session = manager.sessions[simulation_id]
    atom_id = next(iter(session.state.atoms))
    with pytest.raises(command_error):
        call(manager.probabilities, simulation_id, atom_id, 30)
    started = call(manager.start, simulation_id, expected_revision=0)
    before_state = session.state.to_dict()
    before_rng = session.random_source.get_state()
    before_history = session.history.export()

    outcomes = call(manager.probabilities, simulation_id, atom_id, 30)

    assert outcomes
    assert session.state.to_dict() == before_state
    assert session.random_source.get_state() == before_rng
    assert session.history.export() == before_history
    assert session.revision == started.revision
