from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from backend.atomic_model.events import RandomSource
from backend.contracts.errors import ApplicationError
from backend.simulation_management.history import HistoryCheckpoint, SimulationHistory


class SimulationStatus(StrEnum):
    PREPARATION = "PREPARATION"
    PAUSED = "PAUSED"
    RUNNING = "RUNNING"
    PAUSED_WITH_ERROR = "PAUSED_WITH_ERROR"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass
class SimulationSession:
    COMMAND_MATRIX = {
        SimulationStatus.PREPARATION: frozenset(
            {
                "configure", "boundary", "add", "remove", "move", "start",
                "step", "run", "undo", "redo", "destinations",
            }
        ),
        SimulationStatus.PAUSED: frozenset(
            {
                "step", "run", "move", "diagnostics", "destinations", "undo",
                "redo", "reset", "stop",
            }
        ),
        SimulationStatus.RUNNING: frozenset(
            {"run", "pause", "stop", "undo", "redo"}
        ),
        SimulationStatus.PAUSED_WITH_ERROR: frozenset(
            {"retry", "undo", "reset", "acknowledge", "diagnostics", "destinations"}
        ),
        SimulationStatus.STOPPED: frozenset({"reset"}),
        SimulationStatus.FAILED: frozenset({"reset"}),
    }

    simulation_id: str
    configuration: dict
    status: SimulationStatus
    state: object | None
    topology: object | None
    random_source: RandomSource | None
    history: SimulationHistory
    last_valid_snapshot: object
    error: ApplicationError | None = None
    public_revision: int = 0
    has_started: bool = False
    pending_retry: tuple[str, dict] | None = None
    trajectory_initial: HistoryCheckpoint | None = None
    source_project_id: str | None = None
    source_simulation_id: str | None = None
    run_mode: str | None = None
    run_interval_seconds: float = 0.8

    def __post_init__(self) -> None:
        self.lock = asyncio.Lock()
        self.run_task: asyncio.Task | None = None
        self.pause_requested = False

    @classmethod
    def create(
        cls,
        simulation_id: str,
        configuration: dict,
        initial_snapshot,
        random_state,
        *,
        state=None,
        topology=None,
        random_source: RandomSource | None = None,
    ):
        history_state = state if state is not None else deepcopy(initial_snapshot)
        session = cls(
            simulation_id=simulation_id,
            configuration=deepcopy(configuration),
            status=SimulationStatus.PREPARATION,
            state=deepcopy(state),
            topology=topology,
            random_source=random_source,
            history=SimulationHistory(history_state, random_state),
            last_valid_snapshot=deepcopy(initial_snapshot),
        )
        session.trajectory_initial = session.history.current()
        return session

    @property
    def revision(self) -> int:
        return self.public_revision

    @classmethod
    def allowed_commands(cls, status: SimulationStatus) -> set[str]:
        return set(cls.COMMAND_MATRIX[status])

    def allows(self, command: str) -> bool:
        return command in self.COMMAND_MATRIX[self.status]

    def record_failure(self, code: str, message: str) -> None:
        self.status = SimulationStatus.FAILED
        self.error = ApplicationError(
            code=code,
            message=message,
            simulation_id=self.simulation_id,
            revision=self.revision,
            recoverable=False,
        )
