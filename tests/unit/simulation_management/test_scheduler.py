import asyncio

import pytest

from tests.support import symbol


def scheduler(max_parallel: int = 2, timeout: float = 1.0):
    scheduler_class = symbol(
        "backend.simulation_management.scheduler", "SimulationScheduler"
    )
    return scheduler_class(
        max_parallel_simulations=max_parallel,
        command_timeout_seconds=timeout,
    )


def test_commands_for_one_simulation_execute_strictly_fifo():
    async def scenario():
        target = scheduler()
        order = []

        async def command(number):
            order.append(("start", number))
            await asyncio.sleep(0)
            order.append(("finish", number))
            return number

        results = await asyncio.gather(
            target.submit("sim-a", lambda: command(1)),
            target.submit("sim-a", lambda: command(2)),
            target.submit("sim-a", lambda: command(3)),
        )
        await target.close()
        return order, results

    order, results = asyncio.run(scenario())
    assert results == [1, 2, 3]
    assert order == [
        ("start", 1),
        ("finish", 1),
        ("start", 2),
        ("finish", 2),
        ("start", 3),
        ("finish", 3),
    ]


def test_different_simulations_overlap_but_respect_the_global_limit():
    async def scenario():
        target = scheduler(max_parallel=2)
        release = asyncio.Event()
        both_started = asyncio.Event()
        active = 0
        maximum = 0

        async def command():
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both_started.set()
            await release.wait()
            active -= 1

        tasks = [
            asyncio.create_task(target.submit(f"sim-{index}", command))
            for index in range(4)
        ]
        await asyncio.wait_for(both_started.wait(), timeout=0.5)
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(*tasks)
        await target.close()
        return maximum

    assert asyncio.run(scenario()) == 2


def test_timeout_does_not_block_the_next_simulation():
    timeout_error = symbol(
        "backend.simulation_management.errors", "SimulationTimeoutError"
    )

    async def scenario():
        target = scheduler(max_parallel=1, timeout=0.01)

        async def blocked():
            await asyncio.Event().wait()

        with pytest.raises(timeout_error):
            await target.submit("sim-a", blocked)
        result = await target.submit("sim-b", lambda: asyncio.sleep(0, result="ok"))
        await target.close()
        return result

    assert asyncio.run(scenario()) == "ok"


def test_command_can_explicitly_run_without_the_scheduler_timeout():
    async def scenario():
        target = scheduler(timeout=0.001)

        async def slower_than_the_default_timeout():
            await asyncio.sleep(0.01)
            return "completed"

        result = await target.submit(
            "sim-fast",
            slower_than_the_default_timeout,
            enforce_timeout=False,
        )
        await target.close()
        return result

    assert asyncio.run(scenario()) == "completed"


def test_failure_of_one_command_does_not_stop_the_scheduler():
    async def scenario():
        target = scheduler(max_parallel=2)

        async def broken():
            raise RuntimeError("step failed")

        with pytest.raises(RuntimeError, match="step failed"):
            await target.submit("sim-a", broken)
        result = await target.submit("sim-b", lambda: asyncio.sleep(0, result=42))
        await target.close()
        return result

    assert asyncio.run(scenario()) == 42


def test_pending_commands_can_be_cancelled_for_only_one_simulation():
    async def scenario():
        target = scheduler(max_parallel=1)
        release = asyncio.Event()
        started = asyncio.Event()

        async def occupied_worker():
            started.set()
            await release.wait()

        running = asyncio.create_task(target.submit("sim-a", occupied_worker))
        await started.wait()
        cancelled = asyncio.create_task(
            target.submit("sim-b", lambda: asyncio.sleep(0, result="cancelled"))
        )
        healthy = asyncio.create_task(
            target.submit("sim-c", lambda: asyncio.sleep(0, result="healthy"))
        )
        await asyncio.sleep(0)
        await target.cancel_pending("sim-b")
        release.set()
        await running
        result = await healthy
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        await target.close()
        return result

    assert asyncio.run(scenario()) == "healthy"


def test_parallel_and_sequential_runs_are_seed_equivalent():
    manager_class = symbol(
        "backend.simulation_management.manager", "SimulationManager"
    )

    async def run(parallelism):
        manager = manager_class(max_parallel_simulations=parallelism)
        summaries = await manager.create_batch(
            {"dimensions": [4, 4], "q_max_ev": 30}, count=3, master_seed=19
        )
        for revision in range(5):
            await asyncio.gather(
                *[
                    manager.step(summary.simulation_id, expected_revision=revision)
                    for summary in summaries
                ]
            )
        return [await manager.get_snapshot(item.simulation_id) for item in summaries]

    sequential = asyncio.run(run(1))
    parallel = asyncio.run(run(3))
    assert [item.atoms for item in parallel] == [item.atoms for item in sequential]
    assert [item.metrics for item in parallel] == [item.metrics for item in sequential]
