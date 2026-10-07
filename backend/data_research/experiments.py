from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass, field

from backend.data_research.statistics import ResearchAggregate, StatisticsCalculator


@dataclass
class ExperimentResult:
    status: str
    successful_runs: list[dict]
    failed_runs: list[dict]
    aggregate: ResearchAggregate | None
    completed_steps: int
    project_export: dict
    master_seed: int
    bootstrap_seed: int
    schema_version: int = 1


@dataclass
class ExperimentRecord:
    experiment_id: str
    master_seed: int
    bootstrap_seed: int
    total_steps: int
    status: str = "PENDING"
    completed_steps: int = 0
    successful_runs: list[dict] = field(default_factory=list)
    failed_runs: list[dict] = field(default_factory=list)
    aggregate: ResearchAggregate | None = None
    project_export: dict | None = None
    cancel_requested: bool = False
    task: asyncio.Task | None = None


class ExperimentService:
    def __init__(self, manager) -> None:
        self.manager = manager
        self.statistics = StatisticsCalculator()
        self.records: dict[str, ExperimentRecord] = {}

    async def run(
        self,
        configurations: list[dict],
        steps: int,
        master_seed: int,
        repetitions: int = 1,
    ) -> ExperimentResult:
        record = self._create_record(configurations, repetitions, steps, master_seed)
        await self._execute(record, configurations, repetitions, steps)
        return self._result(record)

    async def start(
        self,
        *,
        configurations: list[dict],
        steps: int,
        master_seed: int,
        repetitions: int = 1,
    ) -> ExperimentRecord:
        record = self._create_record(configurations, repetitions, steps, master_seed)
        self.records[record.experiment_id] = record
        record.task = asyncio.create_task(
            self._execute(record, configurations, repetitions, steps)
        )
        return record

    def get_status(self, experiment_id: str) -> ExperimentRecord:
        try:
            return self.records[experiment_id]
        except KeyError as error:
            raise ValueError("Experiment does not exist") from error

    async def cancel(self, experiment_id: str) -> ExperimentRecord:
        record = self.get_status(experiment_id)
        record.cancel_requested = True
        if record.task is not None:
            await asyncio.gather(record.task, return_exceptions=True)
        return record

    def get_result(self, experiment_id: str) -> ExperimentResult:
        record = self.get_status(experiment_id)
        if record.task is not None and not record.task.done():
            raise ValueError("Experiment is still running")
        return self._result(record)

    async def close(self) -> None:
        pending = []
        for record in self.records.values():
            if record.task is not None and not record.task.done():
                record.cancel_requested = True
                pending.append(record.task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    @staticmethod
    def _create_record(configurations, repetitions, steps, master_seed):
        if not configurations:
            raise ValueError("At least one experiment configuration is required")
        if repetitions < 1:
            raise ValueError("repetitions must be positive")
        if steps < 0:
            raise ValueError("steps must be non-negative")
        seed_source = random.Random(master_seed)
        return ExperimentRecord(
            experiment_id=str(uuid.uuid4()),
            master_seed=master_seed,
            bootstrap_seed=seed_source.randrange(2**63),
            total_steps=len(configurations) * repetitions * steps,
        )

    async def _execute(self, record, configurations, repetitions, steps) -> None:
        record.status = "RUNNING"
        seed_source = random.Random(record.master_seed)
        seed_source.randrange(2**63)
        specs = []
        run_index = 0
        for configuration_index, configuration in enumerate(configurations):
            for _ in range(repetitions):
                specs.append(
                    (
                        run_index,
                        configuration_index,
                        configuration,
                        seed_source.randrange(2**63),
                        seed_source.randrange(2**63),
                    )
                )
                run_index += 1
        await asyncio.gather(*[self._run_one(record, spec, steps) for spec in specs])
        record.successful_runs.sort(key=lambda item: item["run"])
        record.failed_runs.sort(key=lambda item: item["run"])
        trajectories = [item["metrics"] for item in record.successful_runs]
        record.aggregate = (
            self.statistics.aggregate_trajectories(
                trajectories, bootstrap_seed=record.bootstrap_seed
            )
            if trajectories
            else None
        )
        successful_ids = [item["simulation_id"] for item in record.successful_runs]
        record.project_export = (
            await self.manager.export_project(
                f"experiment-{record.experiment_id}", successful_ids
            )
            if successful_ids
            else {
                "schema_version": 1,
                "application_version": "1.0.0",
                "project_id": f"experiment-{record.experiment_id}",
                "simulations": [],
            }
        )
        if record.cancel_requested:
            record.status = "CANCELLED"
        elif record.failed_runs:
            record.status = "COMPLETED_WITH_ERRORS"
        else:
            record.status = "COMPLETED"

    async def _run_one(self, record, spec, steps) -> None:
        run_index, configuration_index, configuration, seed_init, seed_sim = spec
        seeds = {"seed_init": seed_init, "seed_sim": seed_sim}
        if record.cancel_requested:
            return
        try:
            config = dict(configuration)
            config.update(seeds)
            summary = await self.manager.create(config)
            simulation_id = summary.simulation_id
            revision = summary.revision
            for _ in range(steps):
                if record.cancel_requested:
                    return
                response = await self.manager.step(simulation_id, revision)
                revision = response.revision
                record.completed_steps += 1
            metrics = await self.manager.metrics_series(simulation_id)
            snapshot = await self.manager.get_snapshot(simulation_id)
            record.successful_runs.append(
                {
                    "run": run_index,
                    "configuration_index": configuration_index,
                    "simulation_id": simulation_id,
                    "derived_seeds": seeds,
                    "snapshot": snapshot.model_dump(mode="json"),
                    "metrics": [item.model_dump(mode="json") for item in metrics.points],
                }
            )
        except Exception as error:
            record.failed_runs.append(
                {
                    "run": run_index,
                    "configuration_index": configuration_index,
                    "derived_seeds": seeds,
                    "code": type(error).__name__,
                    "message": str(error),
                }
            )

    @staticmethod
    def _result(record: ExperimentRecord) -> ExperimentResult:
        return ExperimentResult(
            status=record.status,
            successful_runs=list(record.successful_runs),
            failed_runs=list(record.failed_runs),
            aggregate=record.aggregate,
            completed_steps=record.completed_steps,
            project_export=record.project_export
            or {
                "schema_version": 1,
                "application_version": "1.0.0",
                "project_id": f"experiment-{record.experiment_id}",
                "simulations": [],
            },
            master_seed=record.master_seed,
            bootstrap_seed=record.bootstrap_seed,
        )
