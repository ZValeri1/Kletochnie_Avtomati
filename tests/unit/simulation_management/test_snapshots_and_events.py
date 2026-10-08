import asyncio
import threading

import pytest

from tests.support import config, status_value, symbol, value


def session(snapshot=None):
    session_class = symbol(
        "backend.simulation_management.session", "SimulationSession"
    )
    return session_class.create(
        simulation_id="sim-a",
        configuration=config(),
        initial_snapshot=snapshot
        or {"simulation_id": "sim-a", "revision": 0, "atoms": [{"id": 0}]},
        random_state=("rng", 0),
    )


def test_snapshot_factory_returns_an_immutable_detached_dto():
    factory_class = symbol(
        "backend.simulation_management.snapshots", "SnapshotFactory"
    )
    mutable_snapshot = {
        "simulation_id": "sim-a",
        "revision": 0,
        "atoms": [{
            "id": 0,
            "site_key": "lattice:0,0",
            "coordinate": [0.0, 0.0],
            "site_kind": "lattice",
            "metal_relation": "boundary",
            "visual_state": "boundary",
        }],
        "counts": {"n0": 1, "n_atoms": 1, "n_v": 0, "n_i": 0, "n_as": 0},
        "configuration": {
            "dimensions": [2, 2],
            "field_dimensions": [6, 6],
            "contour": None,
            "profile": "fe_co60_physical",
            "initialization_mode": "ordered",
            "n_v": 0,
            "n_i": 0,
            "n_as": 0,
            "random_parameters": {},
            "seed_init": 11,
            "seed_sim": 12,
            "q_max_ev": 0.0,
            "q_thr_ev": 20.0,
            "weights": {
                "lattice_vacancy": 0.7,
                "lattice_interstitial": 0.2,
                "interstitial_vacancy_r1": 0.9,
                "interstitial_vacancy_r2": 0.3,
                "interstitial_interstitial": 1.0,
                "boundary_external": 0.02,
                "external_external": 1.0,
                "external_interstitial": 0.2,
                "interstitial_external": 1.0,
                "external_metal": 0.0,
                "shell_r1": 0.75,
                "shell_r2": 0.25,
                "vacancy": 0.8,
                "interstitial": 0.2,
                "external": 0.05,
            },
        },
    }
    target = session(mutable_snapshot)

    dto = factory_class.create(target)
    mutable_snapshot["atoms"][0]["coordinate"][0] = 99.0

    assert value(dto, "schema_version") == 1
    assert value(dto, "simulation_id") == "sim-a"
    assert tuple(value(value(dto, "atoms")[0], "coordinate")) == (0.0, 0.0)
    assert value(value(dto, "history_capabilities"), "retained_action_count") == 0
    assert value(value(dto, "history_capabilities"), "history_limit") == 100
    assert value(value(dto, "history_capabilities"), "history_truncated") is False
    assert value(dto, "phase") == "PREPARATION"
    assert value(dto, "config_locked") is False
    weights = value(value(dto, "configuration"), "weights")
    assert value(weights, "from_lattice_vacancy") == 0.8
    assert value(weights, "from_interstitial_vacancy") == 0.8
    assert value(weights, "from_interstitial_shell_r1") == 0.75
    assert value(weights, "from_interstitial_inside") == 0.95
    assert value(weights, "from_interstitial_outside") == 0.05


def test_snapshot_atoms_expose_site_kind_and_metal_relation_from_topology():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    async def scenario():
        manager = manager_class()
        created = await manager.create(config())
        snapshot = await manager.get_snapshot(created.simulation_id)
        await manager.close()
        return snapshot

    snapshot = asyncio.run(scenario())
    atom = snapshot.atoms[0]
    assert atom.site_key.startswith("lattice:")
    assert atom.site_kind == "lattice"
    assert atom.metal_relation in {"interior", "boundary"}
    assert atom.metal_relation not in {"bridge", "hollow"}


def test_failed_session_snapshot_contains_only_a_structured_public_error():
    factory_class = symbol(
        "backend.simulation_management.snapshots", "SnapshotFactory"
    )
    target = session()
    target.record_failure(code="STEP_FAILED", message="calculation failed")

    dto = factory_class.create_summary(target)

    assert status_value(dto) == "FAILED"
    assert value(value(dto, "error"), "code") == "STEP_FAILED"
    assert "traceback" not in dto.model_dump(mode="json")


def test_event_hub_filters_by_simulation_and_preserves_revision_order():
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )

    async def scenario():
        hub = event_hub_class()
        left = await hub.subscribe("sim-a")
        right = await hub.subscribe("sim-b")
        await hub.publish(
            "sim-a",
            {
                "type": "status",
                "summary": {
                    "schema_version": 1,
                    "simulation_id": "sim-a",
                    "status": "PAUSED",
                    "revision": 1,
                },
            },
        )
        await hub.publish(
            "sim-b",
            {
                "type": "status",
                "summary": {
                    "schema_version": 1,
                    "simulation_id": "sim-b",
                    "status": "PAUSED",
                    "revision": 1,
                },
            },
        )
        await hub.publish(
            "sim-a",
            {
                "type": "status",
                "summary": {
                    "schema_version": 1,
                    "simulation_id": "sim-a",
                    "status": "PAUSED",
                    "revision": 2,
                },
            },
        )
        messages = [await left.receive(), await left.receive(), await right.receive()]
        await left.close()
        await right.close()
        return messages

    left_first, left_second, right = asyncio.run(scenario())
    assert [left_first["revision"], left_second["revision"]] == [1, 2]
    assert [left_first["message_id"], left_second["message_id"]] == [1, 2]
    assert left_first["schema_version"] == 1
    assert right["message_id"] == 1
    assert right["simulation_id"] == "sim-b"


def test_closed_event_subscription_does_not_break_publication():
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )

    async def scenario():
        hub = event_hub_class()
        disconnected = await hub.subscribe("sim-a")
        active = await hub.subscribe("sim-a")
        await disconnected.close()
        await hub.publish(
            "sim-a",
            {
                "type": "status",
                "summary": {
                    "schema_version": 1,
                    "simulation_id": "sim-a",
                    "status": "PAUSED",
                    "revision": 1,
                },
            },
        )
        message = await active.receive()
        await active.close()
        return message

    assert asyncio.run(scenario())["revision"] == 1


def test_successful_action_publishes_event_snapshot_and_status_in_order():
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    class RecordingEventHub(event_hub_class):
        def __init__(self):
            super().__init__()
            self.messages = []

        async def publish(self, simulation_id, message):
            published = await super().publish(simulation_id, message)
            self.messages.append(published)
            return published

    async def scenario():
        hub = RecordingEventHub()
        manager = manager_class(event_hub=hub)
        created = await manager.create(config())
        hub.messages.clear()
        await manager.step(created.simulation_id, expected_revision=0)
        messages = list(hub.messages)
        await manager.close()
        return messages

    messages = asyncio.run(scenario())
    assert [message["type"] for message in messages] == [
        "event", "snapshot", "status"
    ]
    assert [message["message_id"] for message in messages] == [2, 3, 4]
    assert {message["revision"] for message in messages} == {1}


def test_recoverable_failure_publishes_error_snapshot_and_status_in_order():
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class FailingEngine(engine_class):
        def step(self, source, random_source):
            raise RuntimeError("temporary failure")

    class RecordingEventHub(event_hub_class):
        def __init__(self):
            super().__init__()
            self.messages = []

        async def publish(self, simulation_id, message):
            published = await super().publish(simulation_id, message)
            self.messages.append(published)
            return published

    async def scenario():
        hub = RecordingEventHub()
        manager = manager_class(event_hub=hub, engine=FailingEngine())
        created = await manager.create(config())
        hub.messages.clear()
        try:
            await manager.step(created.simulation_id, expected_revision=0)
        except RuntimeError:
            pass
        messages = list(hub.messages)
        await manager.close()
        return messages

    messages = asyncio.run(scenario())
    assert [message["type"] for message in messages] == [
        "error", "snapshot", "status"
    ]
    assert messages[0]["error"]["recoverable"] is True
    assert messages[1]["snapshot"]["status"] == "PAUSED_WITH_ERROR"
    assert {message["revision"] for message in messages} == {0}


def test_manual_edit_publishes_event_then_snapshot_as_separate_messages():
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    class RecordingEventHub(event_hub_class):
        def __init__(self):
            super().__init__()
            self.messages = []

        async def publish(self, simulation_id, message):
            published = await super().publish(simulation_id, message)
            self.messages.append(published)
            return published

    async def scenario():
        hub = RecordingEventHub()
        manager = manager_class(event_hub=hub)
        created = await manager.create(config())
        hub.messages.clear()
        await manager.configure_initialization(
            created.simulation_id,
            expected_revision=0,
            initialization={"initialization_mode": "ordered"},
        )
        messages = list(hub.messages)
        await manager.close()
        return messages

    messages = asyncio.run(scenario())
    assert [message["type"] for message in messages] == ["event", "snapshot"]
    assert messages[0]["event"]["origin"] == "manual_edit"
    assert "snapshot" not in messages[0]
    assert messages[1]["snapshot"]["revision"] == 1


@pytest.mark.parametrize(
    "command,expected_status",
    [("pause", "PAUSED"), ("stop", "STOPPED")],
)
def test_continuous_run_suppresses_intermediate_frames_and_publishes_final_state(
    command, expected_status
):
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )
    engine_class = symbol("backend.atomic_model.engine", "SimulationEngine")

    class BlockingEngine(engine_class):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()

        def step(self, source, random_source):
            self.started.set()
            if not self.release.wait(timeout=2):
                raise TimeoutError("test barrier was not released")
            return super().step(source, random_source)

    class RecordingEventHub(event_hub_class):
        def __init__(self):
            super().__init__()
            self.messages = []

        async def publish(self, simulation_id, message):
            published = await super().publish(simulation_id, message)
            self.messages.append(published)
            return published

    async def scenario():
        hub = RecordingEventHub()
        engine = BlockingEngine()
        manager = manager_class(event_hub=hub, engine=engine)
        created = await manager.create(config())
        await manager.run(created.simulation_id, expected_revision=0)
        assert await asyncio.to_thread(engine.started.wait, 1)
        hub.messages.clear()
        finish = asyncio.create_task(getattr(manager, command)(created.simulation_id))
        await asyncio.sleep(0)
        engine.release.set()
        summary = await asyncio.wait_for(finish, timeout=2)
        messages = list(hub.messages)
        await manager.close()
        return summary, messages

    summary, messages = asyncio.run(scenario())
    assert status_value(summary) == expected_status
    assert [message["type"] for message in messages] == [
        "event", "snapshot", "status"
    ]
    assert messages[1]["snapshot"]["status"] == expected_status


def test_visual_run_publishes_an_event_and_snapshot_for_each_visible_frame():
    event_hub_class = symbol(
        "backend.simulation_management.event_hub", "EventHub"
    )
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    class RecordingEventHub(event_hub_class):
        def __init__(self):
            super().__init__()
            self.messages = []

        async def publish(self, simulation_id, message):
            published = await super().publish(simulation_id, message)
            self.messages.append(published)
            return published

    async def scenario():
        hub = RecordingEventHub()
        manager = manager_class(event_hub=hub)
        created = await manager.create(config())
        await manager.run(
            created.simulation_id,
            expected_revision=0,
            mode="visual",
            interval_ms=0,
        )
        for _ in range(100):
            if any(message["type"] == "event" for message in hub.messages):
                break
            await asyncio.sleep(0.01)
        session = manager.sessions[created.simulation_id]
        session.pause_requested = True
        if session.run_task is not None:
            await asyncio.wait_for(session.run_task, timeout=2)
        messages = list(hub.messages)
        await manager.close()
        return messages

    messages = asyncio.run(scenario())
    first_event = next(
        index for index, message in enumerate(messages) if message["type"] == "event"
    )
    assert messages[first_event + 1]["type"] == "snapshot"
    assert messages[first_event + 1]["snapshot"]["status"] == "RUNNING"
    assert messages[first_event]["event"]["metrics_after"]


def test_fast_run_executes_steps_without_the_scheduler_timeout():
    scheduler_class = symbol(
        "backend.simulation_management.scheduler", "SimulationScheduler"
    )
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    class RecordingScheduler(scheduler_class):
        def __init__(self):
            super().__init__()
            self.enforce_timeout_values = []

        async def submit(self, simulation_id, command, *, enforce_timeout=True):
            self.enforce_timeout_values.append(enforce_timeout)
            return await super().submit(
                simulation_id,
                command,
                enforce_timeout=enforce_timeout,
            )

    async def scenario():
        scheduler = RecordingScheduler()
        manager = manager_class(scheduler=scheduler)
        created = await manager.create(config())
        await manager.run(created.simulation_id, expected_revision=0, mode="fast")
        session = manager.sessions[created.simulation_id]
        for _ in range(100):
            if False in scheduler.enforce_timeout_values:
                break
            await asyncio.sleep(0.01)
        session.pause_requested = True
        if session.run_task is not None:
            await asyncio.wait_for(session.run_task, timeout=2)
        values = list(scheduler.enforce_timeout_values)
        await manager.close()
        return values

    assert False in asyncio.run(scenario())
