from __future__ import annotations

import asyncio
from collections import defaultdict

from backend.simulation_management.errors import SimulationTimeoutError


class SimulationScheduler:
    def __init__(
        self,
        max_parallel_simulations: int = 2,
        command_timeout_seconds: float = 30.0,
    ) -> None:
        if max_parallel_simulations < 1:
            raise ValueError("max_parallel_simulations must be positive")
        self.command_timeout_seconds = command_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_parallel_simulations)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._pending: dict[str, set[asyncio.Task]] = defaultdict(set)
        self._active: set[asyncio.Task] = set()
        self._closed = False

    async def submit(
        self,
        simulation_id: str,
        command,
        *,
        enforce_timeout: bool = True,
    ):
        if self._closed:
            raise RuntimeError("Scheduler is closed")
        task = asyncio.current_task()
        if task is not None:
            self._pending[simulation_id].add(task)
        try:
            async with self._locks[simulation_id]:
                async with self._semaphore:
                    if task is not None:
                        self._pending[simulation_id].discard(task)
                        self._active.add(task)
                    if not enforce_timeout:
                        return await command()
                    try:
                        return await asyncio.wait_for(
                            command(), timeout=self.command_timeout_seconds
                        )
                    except TimeoutError as error:
                        raise SimulationTimeoutError(
                            f"Simulation {simulation_id} command timed out"
                        ) from error
                    finally:
                        if task is not None:
                            self._active.discard(task)
        finally:
            if task is not None:
                self._pending[simulation_id].discard(task)

    async def cancel_pending(self, simulation_id: str) -> None:
        for task in tuple(self._pending.get(simulation_id, ())):
            if task not in self._active:
                task.cancel()
        await asyncio.sleep(0)

    async def close(self) -> None:
        self._closed = True
        for tasks in tuple(self._pending.values()):
            for task in tuple(tasks):
                if task not in self._active:
                    task.cancel()
        await asyncio.sleep(0)
