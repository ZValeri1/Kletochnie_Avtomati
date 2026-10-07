from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, status

from backend.api.models import ExperimentRequest
from backend.contracts.experiments import ExperimentResults, ExperimentStatus
from backend.simulation_management.errors import InvalidSimulationCommandError


def create_experiments_router(service) -> APIRouter:
    router = APIRouter(prefix="/api/experiments", tags=["experiments"])

    def public_status(record) -> ExperimentStatus:
        state = record.status
        if record.task is not None and record.task.done() and record.task.exception():
            state = "FAILED"
        return ExperimentStatus(
            experiment_id=record.experiment_id,
            status=state,
            completed_steps=record.completed_steps,
            total_steps=record.total_steps,
            successful_runs=len(record.successful_runs),
            failed_runs=len(record.failed_runs),
        )

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=ExperimentStatus,
    )
    async def create_experiment(request: ExperimentRequest):
        record = await service.start(
            configurations=[
                item.model_dump(exclude={"schema_version"}, exclude_none=True)
                for item in request.configurations
            ],
            repetitions=request.repetitions,
            steps=request.steps,
            master_seed=request.master_seed,
        )
        return public_status(record).model_dump(mode="json")

    @router.get("/{experiment_id}", response_model=ExperimentStatus)
    async def get_experiment_status(experiment_id: str):
        try:
            record = service.get_status(experiment_id)
        except ValueError as error:
            raise InvalidSimulationCommandError("Experiment does not exist") from error
        return public_status(record).model_dump(mode="json")

    @router.post("/{experiment_id}/cancel", response_model=ExperimentStatus)
    async def cancel_experiment(experiment_id: str):
        try:
            record = await service.cancel(experiment_id)
        except ValueError as error:
            raise InvalidSimulationCommandError("Experiment does not exist") from error
        return public_status(record).model_dump(mode="json")

    @router.get("/{experiment_id}/results", response_model=ExperimentResults)
    async def experiment_results(experiment_id: str):
        try:
            result = service.get_result(experiment_id)
        except ValueError as error:
            if "still running" in str(error):
                raise InvalidSimulationCommandError("Experiment is still running") from error
            raise InvalidSimulationCommandError("Experiment does not exist") from error
        return ExperimentResults(
            experiment_id=experiment_id,
            status=result.status,
            successful_runs=result.successful_runs,
            failed_runs=result.failed_runs,
            aggregate=asdict(result.aggregate) if result.aggregate else None,
            completed_steps=result.completed_steps,
            total_steps=service.get_status(experiment_id).total_steps,
            master_seed=result.master_seed,
            bootstrap_seed=result.bootstrap_seed,
        ).model_dump(mode="json")

    return router
