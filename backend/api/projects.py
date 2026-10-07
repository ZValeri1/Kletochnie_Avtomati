from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.models import ProjectSaveRequest
from backend.contracts.projects import ProjectLoadResponse, ProjectStatus
from backend.data_research.errors import ProjectConfirmationError


def create_projects_router(manager, store) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("", response_model=list[ProjectStatus])
    async def list_projects():
        return [
            ProjectStatus(
                project_id=item.project_id,
                status="AVAILABLE",
                simulation_count=item.simulation_count,
                created_at=item.created_at,
                updated_at=item.updated_at,
                history_truncated=item.history_truncated,
            ).model_dump(mode="json")
            for item in store.list()
        ]

    @router.post("/{project_id}/save", response_model=ProjectStatus)
    async def save_project(project_id: str, request: ProjectSaveRequest):
        payload = await manager.export_project(project_id, request.simulation_ids)
        metadata = store.save(payload, overwrite=request.overwrite)
        return ProjectStatus(
            project_id=project_id,
            status="SAVED",
            simulation_count=metadata.simulation_count,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            history_truncated=metadata.history_truncated,
        ).model_dump(mode="json")

    @router.post("/{project_id}/load", response_model=ProjectLoadResponse)
    async def load_project(project_id: str):
        payload = store.load(project_id)
        simulations = await manager.import_project(payload)
        return {
            "schema_version": 1,
            "project_id": project_id,
            "simulations": [item.model_dump(mode="json") for item in simulations],
        }

    @router.delete("/{project_id}", response_model=ProjectStatus)
    async def delete_project(
        project_id: str, confirm: bool = Query(default=False)
    ):
        if not confirm:
            raise ProjectConfirmationError("Project deletion requires confirm=true")
        metadata = next(
            (item for item in store.list() if item.project_id == project_id), None
        )
        if metadata is None:
            store.load(project_id)
        store.delete(project_id)
        return ProjectStatus(
            project_id=project_id,
            status="DELETED",
            simulation_count=metadata.simulation_count,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            history_truncated=metadata.history_truncated,
        ).model_dump(mode="json")

    return router
