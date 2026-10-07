from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.experiments import create_experiments_router
from backend.api.projects import create_projects_router
from backend.api.simulations import create_simulations_router
from backend.api.websocket import create_websocket_router
from backend.atomic_model.errors import InitializationError, StateInvariantError, TopologyError
from backend.contracts.errors import ApplicationError
from backend.data_research.errors import (
    DataResearchError,
    ProjectConfirmationError,
    ProjectConflictError,
    ProjectNotFoundError,
)
from backend.data_research.experiments import ExperimentService
from backend.data_research.project_store import ProjectStore
from backend.simulation_management.errors import (
    InvalidSimulationCommandError,
    RevisionConflictError,
    SimulationManagementError,
    SimulationNotFoundError,
)
from backend.simulation_management.manager import SimulationManager


def create_app(
    projects_root: str | Path = "projects",
    max_parallel_simulations: int = 2,
    frontend_root: str | Path | None = None,
) -> FastAPI:
    manager = SimulationManager(max_parallel_simulations=max_parallel_simulations)
    store = ProjectStore(projects_root)
    experiments = ExperimentService(manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await experiments.close()
        await manager.close()

    app = FastAPI(
        title="Gamma Irradiation Modular Monolith",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.state.project_store = store
    app.state.experiments = experiments

    def error_response(
        status_code: int,
        code: str,
        message: str,
        details=None,
        simulation_id: str | None = None,
        revision: int | None = None,
    ):
        payload = ApplicationError(
            code=code,
            message=message,
            details=details or {},
            simulation_id=simulation_id,
            revision=revision,
            recoverable=False,
        )
        return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        return error_response(422, "VALIDATION_ERROR", "Request validation failed", {"errors": error.errors()})

    @app.exception_handler(RevisionConflictError)
    async def revision_error(_request: Request, error: RevisionConflictError):
        simulation_id = _request.path_params.get("simulation_id")
        summary = await manager.get_summary(simulation_id)
        return error_response(
            409,
            error.code,
            str(error),
            details={"actual_revision": summary.revision},
            simulation_id=simulation_id,
            revision=summary.revision,
        )

    @app.exception_handler(InvalidSimulationCommandError)
    async def command_error(_request: Request, error: InvalidSimulationCommandError):
        return error_response(
            400,
            error.code,
            str(error),
            simulation_id=_request.path_params.get("simulation_id"),
        )

    @app.exception_handler(SimulationNotFoundError)
    async def simulation_not_found(_request: Request, error: SimulationNotFoundError):
        return error_response(
            404,
            error.code,
            "Simulation does not exist",
            simulation_id=_request.path_params.get("simulation_id"),
        )

    @app.exception_handler(SimulationManagementError)
    async def simulation_error(_request: Request, error: SimulationManagementError):
        return error_response(422, error.code, str(error))

    @app.exception_handler(DataResearchError)
    async def data_error(_request: Request, error: DataResearchError):
        if isinstance(error, ProjectNotFoundError):
            return error_response(404, "PROJECT_NOT_FOUND", "Project does not exist")
        if isinstance(error, ProjectConfirmationError):
            return error_response(400, "CONFIRMATION_REQUIRED", str(error))
        if isinstance(error, ProjectConflictError):
            return error_response(409, error.code, str(error))
        status_code = 503 if error.code == "STORAGE_UNAVAILABLE" else 422
        return error_response(status_code, error.code, str(error))

    @app.exception_handler(InitializationError)
    async def initialization_error(_request: Request, error: InitializationError):
        return error_response(422, error.code, str(error))

    @app.exception_handler(TopologyError)
    async def topology_error(_request: Request, error: TopologyError):
        return error_response(422, error.code, str(error))

    @app.exception_handler(StateInvariantError)
    async def state_error(_request: Request, error: StateInvariantError):
        return error_response(422, error.code, str(error))

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, error: ValueError):
        return error_response(422, "VALIDATION_ERROR", str(error))

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception):
        return error_response(
            500,
            "INTERNAL_ERROR",
            "Unexpected server error",
            simulation_id=_request.path_params.get("simulation_id"),
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(create_simulations_router(manager))
    app.include_router(create_projects_router(manager, store))
    app.include_router(create_experiments_router(experiments))
    app.include_router(create_websocket_router(manager))

    if frontend_root is not None:
        frontend = Path(frontend_root)
        assets = frontend / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/")
        async def index():
            return FileResponse(frontend / "index.html")

    return app
