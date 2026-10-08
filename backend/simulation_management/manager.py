from __future__ import annotations

import asyncio
import random
import secrets
import uuid
from copy import deepcopy

from backend.atomic_model.engine import SimulationEngine
from backend.atomic_model.errors import StateInvariantError
from backend.atomic_model.events import EventRecord, RandomSource
from backend.atomic_model.initialization import InitializationCounts
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology
from backend.contracts.errors import ApplicationError
from backend.data_research.errors import ProjectDataError
from backend.data_research.export import JournalExporter
from backend.data_research.serialization import ProjectSerializer
from backend.contracts.simulation import (
    DefectCounts,
    JournalExport,
    PreparationEditPreview,
    SimulationEvent,
    StepResponse,
)
from backend.simulation_management.errors import (
    InvalidSimulationCommandError,
    PreparationCommandError,
    RevisionConflictError,
    SimulationNotFoundError,
    SimulationTimeoutError,
)
from backend.simulation_management.event_hub import EventHub
from backend.simulation_management.history import SimulationHistory
from backend.simulation_management.scheduler import SimulationScheduler
from backend.simulation_management.session import SimulationSession, SimulationStatus
from backend.simulation_management.snapshots import SnapshotFactory
from backend.contracts.simulation import (
    EventPage,
    MetricsPoint,
    MetricsSeries,
    ProbabilityOverlay,
    ProbabilityOutcome,
    SliceAtlas,
    SliceLayer,
    SliceSite,
)


class SimulationManager:
    def __init__(
        self,
        max_parallel_simulations: int = 2,
        *,
        engine: SimulationEngine | None = None,
        scheduler: SimulationScheduler | None = None,
        event_hub: EventHub | None = None,
    ) -> None:
        self.engine = engine or SimulationEngine()
        self.scheduler = scheduler or SimulationScheduler(max_parallel_simulations)
        self.event_hub = event_hub or EventHub()
        self.sessions: dict[str, SimulationSession] = {}

    async def create(self, configuration: dict):
        config = deepcopy(configuration)
        if config.get("seed_sim") is None:
            config["seed_sim"] = secrets.randbits(63)
        simulation_id = str(uuid.uuid4())
        random_source = RandomSource(config.get("seed_sim"))
        initial = self.engine.create_initial_state(config, random_source)
        config = deepcopy(initial.state.configuration)
        temporary = type("InitialSession", (), {})()
        temporary.simulation_id = simulation_id
        temporary.configuration = config
        temporary.status = SimulationStatus.PREPARATION
        temporary.state = initial.state
        temporary.topology = initial.topology
        temporary.history = type(
            "InitialHistory", (), {"can_undo": False, "can_redo": False}
        )()
        initial_snapshot = SnapshotFactory.create(temporary)
        session = SimulationSession.create(
            simulation_id,
            config,
            initial_snapshot,
            random_source.get_state(),
            state=initial.state,
            topology=initial.topology,
            random_source=random_source,
        )
        session.last_valid_snapshot = SnapshotFactory.create(session)
        self.sessions[simulation_id] = session
        await self.event_hub.publish(
            simulation_id,
            {"type": "snapshot", "snapshot": session.last_valid_snapshot.model_dump(mode="json")},
        )
        return SnapshotFactory.create_summary(session)

    async def create_batch(
        self, configuration: dict, count: int, master_seed: int
    ) -> list:
        if count < 1:
            raise ValueError("count must be positive")
        seed_source = random.Random(master_seed)
        result = []
        for _ in range(count):
            derived = deepcopy(configuration)
            derived["seed_init"] = seed_source.randrange(2**31)
            derived["seed_sim"] = seed_source.randrange(2**31)
            result.append(await self.create(derived))
        return result

    async def step(
        self,
        simulation_id: str,
        expected_revision: int,
    ) -> StepResponse:
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "step")
        self._ensure_revision(session, expected_revision)

        return await self._execute_step(session, expected_revision)

    async def _execute_step(
        self,
        session: SimulationSession,
        expected_revision: int,
        *,
        allow_running: bool = False,
        publish_updates: bool = True,
        publish_event_only: bool = False,
        enforce_timeout: bool = True,
    ) -> StepResponse | None:
        simulation_id = session.simulation_id

        async def execute():
            async with session.lock:
                if not (allow_running and session.status == SimulationStatus.RUNNING):
                    self._ensure_command_allowed(session, "step")
                self._ensure_revision(session, expected_revision)
                try:
                    session.state.validate(session.topology)
                except StateInvariantError as error:
                    self._mark_terminal_error(session, "STATE_INVALID", error)
                    await self._publish_error(session)
                    raise

                if not session.has_started:
                    session.trajectory_initial = session.history.current()

                working_state = session.state.transition_copy(include_history=False)
                working_random = RandomSource(session.configuration.get("seed_sim"))
                working_random.set_state(session.random_source.get_state())
                try:
                    result = await asyncio.to_thread(
                        self.engine.step,
                        working_state,
                        working_random,
                    )
                    result.state.validate(result.topology)
                except StateInvariantError as error:
                    self._mark_terminal_error(session, "STATE_INVALID", error)
                    await self._publish_error(session)
                    raise
                except Exception as error:
                    self._mark_recoverable_error(session, "step", error)
                    await self._publish_error(session)
                    raise
                self._reattach_journals(session.state, result.state)
                session.state = result.state
                session.topology = result.topology
                session.random_source.set_state(working_random.get_state())
                session.public_revision += 1
                event_payload = self._session_event_payload(
                    session, result.event
                )
                session.state.events[-1] = event_payload
                session.state.metrics_points[-1]["revision"] = session.public_revision
                session.has_started = True
                status_changed = session.status == SimulationStatus.PREPARATION
                if session.status == SimulationStatus.PREPARATION:
                    session.status = SimulationStatus.PAUSED
                session.error = None
                session.pending_retry = None
                session.history.commit(
                    result.state,
                    session.random_source.get_state(),
                    source_revision=session.public_revision,
                )
                if not publish_updates:
                    if publish_event_only:
                        event = self._event(session, event_payload)
                        await self.event_hub.publish(
                            simulation_id,
                            {
                                "type": "event",
                                "event": event.model_dump(mode="json"),
                            },
                        )
                    return None
                event = self._event(session, event_payload)
                snapshot = SnapshotFactory.create(session)
                session.last_valid_snapshot = snapshot
                response = StepResponse(
                    simulation_id=simulation_id,
                    revision=snapshot.revision,
                    event=event,
                    snapshot=snapshot,
                )
                await self.event_hub.publish(
                    simulation_id,
                    {
                        "type": "event",
                        "event": event.model_dump(mode="json"),
                    },
                )
                await self.event_hub.publish(
                    simulation_id,
                    {
                        "type": "snapshot",
                        "snapshot": snapshot.model_dump(mode="json"),
                    },
                )
                if status_changed:
                    await self._publish_status(session)
                return response

        try:
            return await self.scheduler.submit(
                simulation_id,
                execute,
                enforce_timeout=enforce_timeout,
            )
        except SimulationTimeoutError as error:
            async with session.lock:
                self._mark_recoverable_error(session, "step", error)
                await self._publish_error(session)
            raise

    async def move(
        self,
        simulation_id: str,
        expected_revision: int,
        atom_id: int,
        destination_key: str,
    ) -> StepResponse:
        return await self._manual_edit(
            simulation_id, expected_revision, "move", atom_id, destination_key
        )

    async def add_atom(
        self, simulation_id: str, expected_revision: int, destination_key: str
    ) -> StepResponse:
        return await self._manual_edit(
            simulation_id, expected_revision, "add_atom", destination_key
        )

    async def remove_atom(
        self, simulation_id: str, expected_revision: int, atom_id: int
    ) -> StepResponse:
        return await self._manual_edit(
            simulation_id, expected_revision, "remove_atom", atom_id
        )

    async def preview_edit(
        self,
        simulation_id: str,
        expected_revision: int,
        action: str,
        *,
        atom_id: int | None = None,
        destination_key: str | None = None,
        contour=None,
        dimensions=None,
    ) -> PreparationEditPreview:
        session = self._session(simulation_id)
        operation = {"add": "add_atom", "remove": "remove_atom"}.get(action, action)
        if action == "boundary":
            self._ensure_preparation_allowed(session, "BOUNDARY_LOCKED")
        else:
            self._ensure_manual_allowed(session, operation)
        self._ensure_revision(session, expected_revision)

        async with session.lock:
            if action == "boundary":
                self._ensure_preparation_allowed(session, "BOUNDARY_LOCKED")
            else:
                self._ensure_manual_allowed(session, operation)
            self._ensure_revision(session, expected_revision)
            metrics_before = self.engine.metrics_calculator.calculate(
                session.topology, session.state
            )
            counts_before = InitializationCounts.from_state(
                session.topology, session.state
            )

            if action == "boundary":
                configuration = deepcopy(session.configuration)
                if dimensions is not None:
                    configuration["dimensions"] = list(dimensions)
                if contour is not None:
                    configuration["contour"] = [tuple(point) for point in contour]
                topology = self.engine._topology(configuration)
                state = session.state.working_copy()
                if any(
                    session.topology.sites[key].metal_relation == "outside"
                    and key in topology.sites
                    and topology.sites[key].metal_relation != "outside"
                    for key in state.atoms.values()
                ):
                    raise StateInvariantError("EXTERNAL_REENTRY_FORBIDDEN")
                state.configuration = deepcopy(configuration)
                state.validate(topology)
            else:
                arguments = {
                    "add": (destination_key,),
                    "remove": (atom_id,),
                    "move": (atom_id, destination_key),
                }[action]
                result = getattr(self.engine, operation)(session.state, *arguments)
                topology = result.topology
                state = result.state
                state.validate(topology)

            metrics_after = self.engine.metrics_calculator.calculate(topology, state)
            counts_after = InitializationCounts.from_state(topology, state)
            return PreparationEditPreview(
                simulation_id=simulation_id,
                revision=session.revision,
                action=action,
                metrics_before=metrics_before,
                metrics_after=metrics_after,
                counts_before=DefectCounts(**counts_before.__dict__),
                counts_after=DefectCounts(**counts_after.__dict__),
            )

    async def configure_initialization(
        self, simulation_id: str, expected_revision: int, initialization: dict
    ) -> StepResponse:
        session = self._session(simulation_id)
        self._ensure_preparation_allowed(session)
        if session.revision != expected_revision:
            raise RevisionConflictError("Revision conflict")
        allowed = {
            "initialization_mode", "n_v", "n_i", "n_as", "random_parameters",
            "seed_init", "q_max_ev", "q_thr_ev", "weights",
        }
        if not isinstance(initialization, dict) or set(initialization) - allowed:
            raise PreparationCommandError("EDIT_NOT_ALLOWED")

        async def execute():
            async with session.lock:
                self._ensure_preparation_allowed(session)
                if session.revision != expected_revision:
                    raise RevisionConflictError("Revision conflict")
                config = {**deepcopy(session.configuration), **deepcopy(initialization)}
                initial = await asyncio.to_thread(
                    self.engine.create_initial_state, config, session.random_source
                )
                state = initial.state
                config = deepcopy(state.configuration)
                state.events = deepcopy(session.state.events)
                return await self._commit_preparation_change(
                    session, state, initial.topology, config, "configure"
                )

        return await self.scheduler.submit(simulation_id, execute)

    async def edit_metal_boundary(
        self,
        simulation_id: str,
        expected_revision: int,
        *,
        contour=None,
        dimensions=None,
    ) -> StepResponse:
        session = self._session(simulation_id)
        self._ensure_preparation_allowed(session, "BOUNDARY_LOCKED")
        if session.revision != expected_revision:
            raise RevisionConflictError("Revision conflict")
        async def execute():
            async with session.lock:
                self._ensure_preparation_allowed(session, "BOUNDARY_LOCKED")
                if session.revision != expected_revision:
                    raise RevisionConflictError("Revision conflict")
                config = deepcopy(session.configuration)
                if dimensions is not None:
                    config["dimensions"] = list(dimensions)
                if contour is not None:
                    config["contour"] = [tuple(point) for point in contour]
                topology = self.engine._topology(config)
                state = session.state.working_copy()
                if any(
                    session.topology.sites[key].metal_relation == "outside"
                    and key in topology.sites
                    and topology.sites[key].metal_relation != "outside"
                    for key in state.atoms.values()
                ):
                    raise StateInvariantError("EXTERNAL_REENTRY_FORBIDDEN")
                state.configuration = deepcopy(config)
                state.validate(topology)
                return await self._commit_preparation_change(
                    session, state, topology, config, "boundary"
                )

        return await self.scheduler.submit(simulation_id, execute)

    async def start(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "start")
        self._ensure_revision(session, expected_revision)
        async def execute():
            async with session.lock:
                self._ensure_command_allowed(session, "start")
                self._ensure_revision(session, expected_revision)
                session.state.validate(session.topology)
                session.trajectory_initial = session.history.current()
                session.has_started = True
                session.status = SimulationStatus.PAUSED
                session.public_revision += 1
                session.last_valid_snapshot = SnapshotFactory.create(session)
                return SnapshotFactory.create_summary(session)

        summary = await self.scheduler.submit(simulation_id, execute)
        await self._publish_snapshot(session)
        await self._publish_status(session)
        return summary

    async def _commit_preparation_change(
        self,
        session: SimulationSession,
        state: SimulationState,
        topology: Topology,
        configuration: dict,
        action: str,
    ) -> StepResponse:
        metrics_before = self.engine.metrics_calculator.calculate(
            session.topology, session.state
        )
        state.validate(topology)
        state.revision = session.state.revision + 1
        metrics_after = self.engine.metrics_calculator.calculate(topology, state)
        state.metrics_points.append(
            self.engine.metrics_calculator.point(
                topology, state, "manual_edit"
            ).model_dump()
        )
        event_payload = EventRecord.create(
            revision=state.revision,
            act_number=state.act_number,
            source_atom_id=None,
            source_site=None,
            source_coordinate=None,
            destination_site=None,
            destination_coordinate=None,
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
            affected_atom_ids=tuple(sorted(state.atoms)),
            affected_site_ids=(),
            metrics_before=metrics_before.model_dump(),
            metrics_after=metrics_after.model_dump(),
            origin="manual_edit",
        )
        session.public_revision += 1
        event_payload = self._session_event_payload(session, event_payload)
        state.metrics_points[-1]["revision"] = session.public_revision
        state.events.append(event_payload)
        session.state = state
        session.topology = topology
        session.configuration = deepcopy(configuration)
        session.history.commit(
            state,
            session.random_source.get_state(),
            source_revision=session.public_revision,
            force_checkpoint=action in {"configure", "boundary"},
        )
        snapshot = SnapshotFactory.create(session)
        session.last_valid_snapshot = snapshot
        event = self._event(session, event_payload)
        response = StepResponse(
            simulation_id=session.simulation_id,
            revision=snapshot.revision,
            event=event,
            snapshot=snapshot,
        )
        await self.event_hub.publish(
            session.simulation_id,
            {
                "type": "event",
                "event": event.model_dump(mode="json"),
            },
        )
        await self.event_hub.publish(
            session.simulation_id,
            {
                "type": "snapshot",
                "snapshot": snapshot.model_dump(mode="json"),
            },
        )
        return response

    @staticmethod
    def _ensure_preparation_allowed(
        session: SimulationSession, code: str = "EDIT_NOT_ALLOWED"
    ) -> None:
        if session.has_started or session.status != SimulationStatus.PREPARATION:
            raise PreparationCommandError(code)

    async def _manual_edit(
        self, simulation_id: str, expected_revision: int, operation: str, *args
    ) -> StepResponse:
        session = self._session(simulation_id)
        self._ensure_manual_allowed(session, operation)
        if session.revision != expected_revision:
            raise RevisionConflictError("Revision conflict")

        async def execute():
            async with session.lock:
                self._ensure_manual_allowed(session, operation)
                if session.revision != expected_revision:
                    raise RevisionConflictError("Revision conflict")
                working_state = session.state.transition_copy(include_history=False)
                result = await asyncio.to_thread(
                    getattr(self.engine, operation), working_state, *args
                )
                result.state.validate(result.topology)
                self._reattach_journals(session.state, result.state)
                session.state = result.state
                session.topology = result.topology
                session.public_revision += 1
                event_payload = self._session_event_payload(
                    session, result.event
                )
                session.state.events[-1] = event_payload
                session.state.metrics_points[-1]["revision"] = session.public_revision
                session.history.commit(
                    result.state,
                    session.random_source.get_state(),
                    source_revision=session.public_revision,
                )
                snapshot = SnapshotFactory.create(session)
                session.last_valid_snapshot = snapshot
                event = self._event(session, event_payload)
                response = StepResponse(
                    simulation_id=simulation_id,
                    revision=snapshot.revision,
                    event=event,
                    snapshot=snapshot,
                )
                await self.event_hub.publish(
                    simulation_id,
                    {
                        "type": "event",
                        "event": event.model_dump(mode="json"),
                    },
                )
                await self.event_hub.publish(
                    simulation_id,
                    {
                        "type": "snapshot",
                        "snapshot": snapshot.model_dump(mode="json"),
                    },
                )
                return response

        return await self.scheduler.submit(simulation_id, execute)

    @staticmethod
    def _ensure_manual_allowed(session: SimulationSession, operation: str) -> None:
        command = {"add_atom": "add", "remove_atom": "remove"}.get(
            operation, operation
        )
        if not session.allows(command):
            code = (
                "SIMULATION_NOT_PAUSED"
                if session.has_started and operation == "move"
                else "EDIT_NOT_ALLOWED"
            )
            raise PreparationCommandError(code)
        if not session.has_started:
            if session.status != SimulationStatus.PREPARATION:
                raise PreparationCommandError("EDIT_NOT_ALLOWED")
        elif operation != "move":
            raise PreparationCommandError("EDIT_NOT_ALLOWED")
        elif session.status != SimulationStatus.PAUSED:
            raise PreparationCommandError("SIMULATION_NOT_PAUSED")
    async def undo(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "undo")
        self._ensure_revision(session, expected_revision)
        was_running = session.status == SimulationStatus.RUNNING
        was_recovering = session.status == SimulationStatus.PAUSED_WITH_ERROR
        if was_running:
            await self._pause_for_history(session)
        clear_error_after_navigation = (
            was_recovering
            or session.status == SimulationStatus.PAUSED_WITH_ERROR
        )

        async def execute():
            async with session.lock:
                self._ensure_command_allowed(session, "undo")
                if not was_running:
                    self._ensure_revision(session, expected_revision)
                elif (
                    expected_revision is not None
                    and session.revision not in {expected_revision, expected_revision + 1}
                ):
                    raise RevisionConflictError("Revision changed during safe pause")
                checkpoint = session.history.undo()
                restored_configuration = deepcopy(checkpoint.state.configuration)
                restored_topology = self.engine._topology(restored_configuration)
                checkpoint.state.validate(restored_topology)
                session.state = checkpoint.state
                session.topology = restored_topology
                session.configuration = restored_configuration
                session.public_revision += 1
                session.random_source.set_state(checkpoint.random_state)
                if clear_error_after_navigation:
                    session.status = SimulationStatus.PAUSED
                    session.error = None
                    session.pending_retry = None
                snapshot = SnapshotFactory.create(session)
                session.last_valid_snapshot = snapshot
                await self.event_hub.publish(
                    simulation_id,
                    {"type": "snapshot", "snapshot": snapshot.model_dump(mode="json")},
                )
                if was_running or was_recovering:
                    await self._publish_status(session)
                return snapshot

        return await self.scheduler.submit(simulation_id, execute)

    async def redo(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "redo")
        self._ensure_revision(session, expected_revision)
        was_running = session.status == SimulationStatus.RUNNING
        was_recovering = session.status == SimulationStatus.PAUSED_WITH_ERROR
        requested_redo = session.history.peek_redo() if was_running else None
        if was_running:
            await self._pause_for_history(session)
        clear_error_after_navigation = (
            was_recovering
            or session.status == SimulationStatus.PAUSED_WITH_ERROR
        )

        async def execute():
            async with session.lock:
                self._ensure_command_allowed(session, "redo")
                if not was_running:
                    self._ensure_revision(session, expected_revision)
                elif (
                    expected_revision is not None
                    and session.revision not in {expected_revision, expected_revision + 1}
                ):
                    raise RevisionConflictError("Revision changed during safe pause")
                if was_running and not session.history.can_redo:
                    checkpoint = requested_redo
                    session.history.replace_current(checkpoint)
                else:
                    checkpoint = session.history.redo()
                restored_configuration = deepcopy(checkpoint.state.configuration)
                restored_topology = self.engine._topology(restored_configuration)
                checkpoint.state.validate(restored_topology)
                session.state = checkpoint.state
                session.topology = restored_topology
                session.configuration = restored_configuration
                session.public_revision += 1
                session.random_source.set_state(checkpoint.random_state)
                if clear_error_after_navigation:
                    session.status = SimulationStatus.PAUSED
                    session.error = None
                    session.pending_retry = None
                snapshot = SnapshotFactory.create(session)
                session.last_valid_snapshot = snapshot
                await self.event_hub.publish(
                    simulation_id,
                    {"type": "snapshot", "snapshot": snapshot.model_dump(mode="json")},
                )
                if was_running or was_recovering:
                    await self._publish_status(session)
                return snapshot

        return await self.scheduler.submit(simulation_id, execute)

    async def run(
        self,
        simulation_id: str,
        expected_revision: int | None = None,
        *,
        mode: str = "fast",
        interval_ms: int = 800,
    ):
        if mode not in {"visual", "fast"}:
            raise ValueError("run mode must be visual or fast")
        if not 0 <= interval_ms <= 5000:
            raise ValueError("run interval must be in the range 0..5000 ms")
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "run")
        self._ensure_revision(session, expected_revision)
        if session.status == SimulationStatus.RUNNING:
            return SnapshotFactory.create_summary(session)

        async def execute():
            async with session.lock:
                self._ensure_command_allowed(session, "run")
                self._ensure_revision(session, expected_revision)
                if not session.has_started:
                    session.trajectory_initial = session.history.current()
                session.has_started = True
                session.status = SimulationStatus.RUNNING
                session.run_mode = mode
                session.run_interval_seconds = interval_ms / 1000
                session.pause_requested = False
                session.public_revision += 1
                if session.run_task is None or session.run_task.done():
                    session.run_task = asyncio.create_task(self._run_loop(session))
                session.last_valid_snapshot = SnapshotFactory.create(session)
                return SnapshotFactory.create_summary(session)

        summary = await self.scheduler.submit(simulation_id, execute)
        await self._publish_snapshot(session)
        await self._publish_status(session)
        return summary

    async def pause(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "pause")
        self._ensure_revision(session, expected_revision, allow_stale=True)
        session.pause_requested = True
        run_task = session.run_task
        if run_task is not None and not run_task.done():
            await run_task
        else:
            session.status = SimulationStatus.PAUSED

        async def execute():
            async with session.lock:
                if session.status in {
                    SimulationStatus.PAUSED_WITH_ERROR,
                    SimulationStatus.FAILED,
                }:
                    return SnapshotFactory.create_summary(session)
                session.status = SimulationStatus.PAUSED
                session.public_revision += 1
                session.last_valid_snapshot = SnapshotFactory.create(session)
                return SnapshotFactory.create_summary(session)

        summary = await self.scheduler.submit(simulation_id, execute)
        await self._publish_snapshot(session)
        await self._publish_status(session)
        return summary

    async def stop(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "stop")
        self._ensure_revision(session, expected_revision, allow_stale=True)
        if session.status == SimulationStatus.RUNNING:
            session.pause_requested = True
            if session.run_task is not None and not session.run_task.done():
                await session.run_task
        await self.scheduler.cancel_pending(simulation_id)

        async def execute():
            async with session.lock:
                if session.status in {
                    SimulationStatus.PAUSED_WITH_ERROR,
                    SimulationStatus.FAILED,
                }:
                    return SnapshotFactory.create_summary(session)
                session.status = SimulationStatus.STOPPED
                session.public_revision += 1
                session.last_valid_snapshot = SnapshotFactory.create(session)
                return SnapshotFactory.create_summary(session)

        summary = await self.scheduler.submit(simulation_id, execute)
        await self._publish_snapshot(session)
        await self._publish_status(session)
        return summary

    async def retry(
        self, simulation_id: str, expected_revision: int | None = None
    ) -> StepResponse:
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "retry")
        self._ensure_revision(session, expected_revision)
        pending = session.pending_retry
        if pending is None:
            raise InvalidSimulationCommandError("No recoverable command to retry")
        command, _arguments = pending
        if command != "step":
            raise InvalidSimulationCommandError(
                f"Retry is not implemented for command {command}"
            )
        async with session.lock:
            self._ensure_command_allowed(session, "retry")
            self._ensure_revision(session, expected_revision)
            session.status = SimulationStatus.PAUSED
            session.error = None
        return await self._execute_step(session, session.revision)

    async def acknowledge(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "acknowledge")
        self._ensure_revision(session, expected_revision)

        async def execute():
            async with session.lock:
                self._ensure_command_allowed(session, "acknowledge")
                self._ensure_revision(session, expected_revision)
                session.status = SimulationStatus.PAUSED
                session.error = None
                session.pending_retry = None
                session.public_revision += 1
                session.last_valid_snapshot = SnapshotFactory.create(session)
                summary = SnapshotFactory.create_summary(session)
                await self._publish_snapshot(session)
                await self._publish_status(session)
                return summary

        return await self.scheduler.submit(simulation_id, execute)

    async def reset(
        self, simulation_id: str, expected_revision: int | None = None
    ):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "reset")
        self._ensure_revision(session, expected_revision)

        async def execute():
            async with session.lock:
                self._ensure_command_allowed(session, "reset")
                self._ensure_revision(session, expected_revision)
                checkpoint = deepcopy(session.trajectory_initial)
                if checkpoint is None:
                    raise InvalidSimulationCommandError(
                        "Simulation has no initial checkpoint"
                    )
                state = deepcopy(checkpoint.state)
                configuration = deepcopy(state.configuration)
                topology = self.engine._topology(configuration)
                state.act_number = 0
                state.revision = 0
                state.events = []
                state.metrics_points = []
                state.validate(topology)
                session.public_revision += 1
                point = self.engine.metrics_calculator.point(
                    topology, state, "initialization"
                ).model_dump()
                point["revision"] = session.public_revision
                state.metrics_points = [point]
                session.state = state
                session.topology = topology
                session.configuration = configuration
                session.random_source.set_state(checkpoint.random_state)
                session.error = None
                session.pending_retry = None
                session.pause_requested = False
                session.status = (
                    SimulationStatus.PAUSED
                    if session.has_started
                    else SimulationStatus.PREPARATION
                )
                session.history = SimulationHistory(
                    state,
                    checkpoint.random_state,
                    source_revision=session.public_revision,
                )
                snapshot = SnapshotFactory.create(session)
                session.last_valid_snapshot = snapshot
                await self.event_hub.publish(
                    simulation_id,
                    {
                        "type": "snapshot",
                        "snapshot": snapshot.model_dump(mode="json"),
                    },
                )
                await self._publish_status(session)
                return snapshot

        return await self.scheduler.submit(simulation_id, execute)

    async def remove(
        self, simulation_id: str, expected_revision: int | None = None
    ) -> None:
        session = self._session(simulation_id)
        self._ensure_revision(session, expected_revision)
        if session.status in {SimulationStatus.RUNNING, SimulationStatus.PAUSED}:
            await self.stop(simulation_id)
        else:
            await self.scheduler.cancel_pending(simulation_id)
            if session.run_task is not None and not session.run_task.done():
                session.run_task.cancel()
                await asyncio.gather(session.run_task, return_exceptions=True)
        self.sessions.pop(simulation_id, None)

    async def probabilities(self, simulation_id: str, atom_id: int, q_test: float):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "diagnostics")
        async with session.lock:
            self._ensure_command_allowed(session, "diagnostics")
            return self.engine.probabilities(session.state, atom_id, q_test)

    async def probability_overlay(
        self, simulation_id: str, atom_id: int, q_test: float
    ) -> ProbabilityOverlay:
        session = self._session(simulation_id)
        outcomes = await self.probabilities(simulation_id, atom_id, q_test)
        return ProbabilityOverlay(
            simulation_id=simulation_id,
            revision=session.revision,
            atom_id=atom_id,
            q_test=q_test,
            q_thr=session.configuration["q_thr_ev"],
            outcomes=tuple(ProbabilityOutcome.model_validate(item.__dict__) for item in outcomes),
        )

    async def event_page(
        self,
        simulation_id: str,
        offset: int,
        limit: int,
        *,
        origin: str | None = None,
        operation: str | None = None,
        act_from: int | None = None,
        act_to: int | None = None,
    ) -> EventPage:
        session = self._session(simulation_id)
        async with session.lock:
            filtered = [
                item
                for item in session.state.events
                if (origin is None or item["origin"] == origin)
                and (operation is None or item["operation"] == operation)
                and (act_from is None or item["act_number"] >= act_from)
                and (act_to is None or item["act_number"] <= act_to)
            ]
            events = tuple(
                SimulationEvent.model_validate(item)
                for item in filtered[offset : offset + limit]
            )
            return EventPage(
                simulation_id=simulation_id,
                revision=session.revision,
                offset=offset,
                limit=limit,
                total=len(filtered),
                events=events,
            )

    async def metrics_series(
        self,
        simulation_id: str,
        *,
        act_from: int | None = None,
        act_to: int | None = None,
    ) -> MetricsSeries:
        session = self._session(simulation_id)
        async with session.lock:
            points = (
                item
                for item in session.state.metrics_points
                if (act_from is None or item["act_number"] >= act_from)
                and (act_to is None or item["act_number"] <= act_to)
            )
            return MetricsSeries(
                simulation_id=simulation_id,
                revision=session.revision,
                points=tuple(
                    MetricsPoint.model_validate(item)
                    for item in points
                ),
            )

    async def journal_export(self, simulation_id: str) -> JournalExport:
        session = self._session(simulation_id)
        async with session.lock:
            snapshot = SnapshotFactory.create(session)
            return JournalExport.model_validate(
                JournalExporter.build(
                    simulation_id=simulation_id,
                    revision=session.revision,
                    configuration=snapshot.configuration.model_dump(mode="json"),
                    events=deepcopy(session.state.events),
                    metrics=deepcopy(session.state.metrics_points),
                    final_snapshot=snapshot.model_dump(mode="json"),
                )
            )

    async def slice_atlas(self, simulation_id: str) -> SliceAtlas:
        session = self._session(simulation_id)
        async with session.lock:
            if len(session.topology.movement_field.dimensions) != 3:
                raise InvalidSimulationCommandError("Z_SLICES_REQUIRE_3D")
            layers: dict[float, list[SliceSite]] = {}
            for site in session.topology.sites.values():
                z_coordinate = site.coordinate[2]
                layers.setdefault(z_coordinate, []).append(
                    SliceSite(
                        site_key=site.key,
                        coordinate=site.coordinate,
                        site_kind=site.kind,
                        metal_relation=site.metal_relation,
                        atom_id=session.state.occupied.get(site.key),
                        visual_state=SnapshotFactory._visual_state(
                            session.topology, site.key
                        ),
                    )
                )
            return SliceAtlas(
                simulation_id=simulation_id,
                revision=session.revision,
                axis="z",
                slices=tuple(
                    SliceLayer(
                        coordinate=coordinate,
                        sites=tuple(sorted(sites, key=lambda item: item.site_key)),
                    )
                    for coordinate, sites in sorted(layers.items())
                    if any(
                        site.metal_relation != "outside" or site.atom_id is not None
                        for site in sites
                    )
                ),
            )

    async def destinations(self, simulation_id: str, atom_id: int):
        session = self._session(simulation_id)
        self._ensure_command_allowed(session, "destinations")
        async with session.lock:
            self._ensure_command_allowed(session, "destinations")
            return self.engine.destinations(session.state, atom_id)

    async def list(self) -> list:
        return [SnapshotFactory.create_summary(item) for item in self.sessions.values()]

    async def get_snapshot(self, simulation_id: str):
        return SnapshotFactory.create(self._session(simulation_id))

    async def get_summary(self, simulation_id: str):
        return SnapshotFactory.create_summary(self._session(simulation_id))

    async def run_steps(self, simulation_ids: list[str], steps: int) -> None:
        for _ in range(steps):
            await asyncio.gather(
                *[
                    self.step(item, self._session(item).revision)
                    for item in simulation_ids
                ]
            )

    async def export_project(self, project_id: str, simulation_ids: list[str]) -> dict:
        simulations = []
        for simulation_id in simulation_ids:
            session = self._session(simulation_id)
            async with session.lock:
                history = session.history.export()
                snapshot = SnapshotFactory.create(session)
                simulations.append(
                    {
                        "simulation_id": simulation_id,
                        "revision": session.revision,
                        "status": session.status.value,
                        "has_started": session.has_started,
                        "configuration": deepcopy(session.configuration),
                        "state": session.state.to_dict(),
                        "random_state": session.random_source.get_state(),
                        "history": {
                            "cursor": history["cursor"],
                            "limit": history["limit"],
                            "history_truncated": history["history_truncated"],
                            "checkpoints": [
                                {
                                    "state": checkpoint["state"].to_dict(),
                                    "random_state": checkpoint["random_state"],
                                    "source_revision": checkpoint["source_revision"],
                                }
                                for checkpoint in history["checkpoints"]
                            ],
                        },
                        "events": deepcopy(session.state.events),
                        "metrics": deepcopy(session.state.metrics_points),
                        "last_valid_snapshot": snapshot.model_dump(mode="json"),
                        "source_project_id": session.source_project_id,
                        "source_simulation_id": session.source_simulation_id,
                    }
                )
        return {
            "schema_version": 1,
            "application_version": "1.0.0",
            "project_id": project_id,
            "simulations": simulations,
        }

    async def import_project(self, payload: dict) -> list:
        payload = ProjectSerializer.validate(payload)
        candidates: list[SimulationSession] = []
        reserved_ids = set(self.sessions)
        try:
            for item in payload["simulations"]:
                source_simulation_id = item["simulation_id"]
                simulation_id = source_simulation_id
                while simulation_id in reserved_ids:
                    simulation_id = str(uuid.uuid4())
                reserved_ids.add(simulation_id)
                config = deepcopy(item["configuration"])
                topology = Topology.create(
                    tuple(config["dimensions"]), contour=config.get("contour")
                )
                state = self._decode_state(item["state"])
                state.validate(topology)
                random_source = RandomSource(config.get("seed_sim"))
                random_source.set_state(self._tuple_tree(item["random_state"]))
                saved_status = SimulationStatus(item.get("status", "PAUSED"))
                restored_status = (
                    SimulationStatus.PREPARATION
                    if saved_status == SimulationStatus.PREPARATION
                    else SimulationStatus.PAUSED
                )
                temporary = type("ImportedSession", (), {})()
                temporary.simulation_id = simulation_id
                temporary.configuration = config
                temporary.status = restored_status
                temporary.state = state
                temporary.topology = topology
                temporary.history = type(
                    "ImportedHistory", (), {"can_undo": False, "can_redo": False}
                )()
                snapshot = SnapshotFactory.create(temporary)
                session = SimulationSession.create(
                    simulation_id,
                    config,
                    snapshot,
                    random_source.get_state(),
                    state=state,
                    topology=topology,
                    random_source=random_source,
                )
                session.public_revision = int(item.get("revision", state.revision))
                session.has_started = bool(
                    item.get("has_started", saved_status != SimulationStatus.PREPARATION)
                )
                history_payload = item["history"]
                decoded = {
                    "cursor": history_payload["cursor"],
                    "limit": history_payload.get(
                        "limit", SimulationHistory.DEFAULT_ACTION_LIMIT
                    ),
                    "history_truncated": history_payload.get(
                        "history_truncated", False
                    ),
                    "checkpoints": [
                        {
                            "state": self._decode_state(checkpoint["state"]),
                            "random_state": self._tuple_tree(checkpoint["random_state"]),
                            "source_revision": checkpoint.get("source_revision", 0),
                        }
                        for checkpoint in history_payload["checkpoints"]
                    ],
                }
                session.history = SimulationHistory.restore(decoded)
                for checkpoint in session.history.export()["checkpoints"]:
                    checkpoint["state"].validate(topology)
                session.trajectory_initial = session.history.initial()
                session.source_project_id = payload["project_id"]
                session.source_simulation_id = source_simulation_id
                session.status = restored_status
                session.last_valid_snapshot = SnapshotFactory.create(session)
                candidates.append(session)
        except ProjectDataError:
            raise
        except Exception as error:
            raise ProjectDataError("Project contains an invalid simulation") from error

        self.sessions.update({item.simulation_id: item for item in candidates})
        return [SnapshotFactory.create_summary(item) for item in candidates]

    async def close(self) -> None:
        running = []
        for session in self.sessions.values():
            session.status = SimulationStatus.STOPPED
            if session.run_task and not session.run_task.done():
                session.run_task.cancel()
                running.append(session.run_task)
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        await self.scheduler.close()

    async def _run_loop(self, session: SimulationSession) -> None:
        next_graph_update = 0.0
        try:
            while (
                session.status == SimulationStatus.RUNNING
                and not session.pause_requested
            ):
                visual_mode = session.run_mode == "visual"
                now = asyncio.get_running_loop().time()
                publish_graph_point = not visual_mode and now >= next_graph_update
                await self._execute_step(
                    session,
                    session.revision,
                    allow_running=True,
                    publish_updates=visual_mode,
                    publish_event_only=publish_graph_point,
                    enforce_timeout=visual_mode,
                )
                if publish_graph_point:
                    next_graph_update = asyncio.get_running_loop().time() + 0.1
                await asyncio.sleep(session.run_interval_seconds if visual_mode else 0)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        finally:
            if (
                session.status == SimulationStatus.RUNNING
                and session.pause_requested
            ):
                session.status = SimulationStatus.PAUSED

    async def _pause_for_history(self, session: SimulationSession) -> None:
        session.pause_requested = True
        run_task = session.run_task
        if run_task is not None and not run_task.done():
            await run_task
        elif session.status == SimulationStatus.RUNNING:
            session.status = SimulationStatus.PAUSED

    @staticmethod
    def _mark_recoverable_error(
        session: SimulationSession, command: str, error: Exception
    ) -> None:
        session.status = SimulationStatus.PAUSED_WITH_ERROR
        session.pending_retry = (command, {})
        session.error = ApplicationError(
            code="COMMAND_FAILED",
            message="Simulation command failed and can be retried",
            simulation_id=session.simulation_id,
            revision=session.revision,
            recoverable=True,
            details={"command": command, "error_type": type(error).__name__},
        )

    @staticmethod
    def _mark_terminal_error(
        session: SimulationSession, code: str, error: Exception
    ) -> None:
        session.status = SimulationStatus.FAILED
        session.pending_retry = None
        session.error = ApplicationError(
            code=code,
            message="Simulation state is not reliable",
            simulation_id=session.simulation_id,
            revision=session.revision,
            recoverable=False,
            details={"error_type": type(error).__name__},
        )

    async def _publish_error(self, session: SimulationSession) -> None:
        await self.event_hub.publish(
            session.simulation_id,
            {
                "type": "error",
                "revision": session.revision,
                "error": session.error.model_dump(mode="json"),
            },
        )
        await self._publish_snapshot(session)
        await self._publish_status(session)

    def _session(self, simulation_id: str) -> SimulationSession:
        try:
            return self.sessions[simulation_id]
        except KeyError as error:
            raise SimulationNotFoundError(
                f"Simulation {simulation_id} does not exist"
            ) from error

    async def _publish_status(self, session: SimulationSession) -> None:
        await self.event_hub.publish(
            session.simulation_id,
            {
                "type": "status",
                "summary": SnapshotFactory.create_summary(session).model_dump(mode="json"),
            },
        )

    async def _publish_snapshot(self, session: SimulationSession) -> None:
        await self.event_hub.publish(
            session.simulation_id,
            {
                "type": "snapshot",
                "snapshot": SnapshotFactory.create(session).model_dump(mode="json"),
            },
        )

    @staticmethod
    def _decode_state(payload: dict) -> SimulationState:
        return SimulationState(
            atoms={int(key): value for key, value in payload["atoms"].items()},
            occupied={key: int(value) for key, value in payload["occupied"].items()},
            act_number=payload.get("act_number", 0),
            revision=payload.get("revision", 0),
            events=deepcopy(payload.get("events", [])),
            metrics_points=deepcopy(payload.get("metrics_points", [])),
            configuration=deepcopy(payload.get("configuration", {})),
        )

    @staticmethod
    def _tuple_tree(value):
        if isinstance(value, list):
            return tuple(SimulationManager._tuple_tree(item) for item in value)
        return value

    @staticmethod
    def _ensure_command_allowed(session: SimulationSession, command: str) -> None:
        if not session.allows(command):
            raise InvalidSimulationCommandError(
                f"Cannot {command} simulation in status {session.status.value}"
            )

    @staticmethod
    def _ensure_revision(
        session: SimulationSession,
        expected_revision: int | None,
        *,
        allow_stale: bool = False,
    ) -> None:
        if expected_revision is not None and (
            expected_revision > session.revision
            or (not allow_stale and session.revision != expected_revision)
        ):
            raise RevisionConflictError(
                f"Expected revision {expected_revision}, actual revision {session.revision}"
            )

    @staticmethod
    def _event(session: SimulationSession, payload: dict) -> SimulationEvent:
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()
        return SimulationEvent(
            event_id=payload.get("event_id", str(uuid.uuid4())),
            simulation_id=session.simulation_id,
            revision=session.revision,
            act_number=payload["act_number"],
            source_atom_id=payload.get("source_atom_id"),
            source_site=payload.get("source_site"),
            source_coordinate=payload.get("source_coordinate"),
            destination_site=payload.get("destination_site"),
            destination_coordinate=payload.get("destination_coordinate"),
            operation=payload["operation"],
            shell=payload.get("shell"),
            q_n=payload.get("q_n"),
            q_thr=payload.get("q_thr"),
            result_reason=payload["result_reason"],
            operation_weight=payload.get("operation_weight", 0.0),
            shell_weight=payload.get("shell_weight", 0.0),
            position_weight=payload.get("position_weight", 0.0),
            total_weight=payload.get("total_weight", 0.0),
            probability=payload.get("probability", 1.0),
            affected_atom_ids=tuple(payload.get("affected_atom_ids", ())),
            affected_site_ids=tuple(payload.get("affected_site_ids", ())),
            metrics_before=payload["metrics_before"],
            metrics_after=payload["metrics_after"],
            origin=payload.get("origin", "physical_act"),
        )

    @staticmethod
    def _session_event_payload(session: SimulationSession, event) -> dict:
        payload = event.to_dict() if hasattr(event, "to_dict") else deepcopy(event)
        payload["simulation_id"] = session.simulation_id
        payload["event_id"] = f"{session.simulation_id}:{payload['event_id']}"
        payload["revision"] = session.revision
        return payload

    @staticmethod
    def _reattach_journals(previous: SimulationState, current: SimulationState) -> None:
        new_events = current.events
        new_metrics = current.metrics_points
        current.events = previous.events
        current.metrics_points = previous.metrics_points
        current.events.extend(new_events)
        current.metrics_points.extend(new_metrics)
