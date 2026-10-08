from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from backend.contracts.simulation import (
    DestinationsResponse,
    EventPage,
    JournalExport,
    MetricsSeries,
    PreparationEditPreview,
    ProbabilityOverlay,
    SimulationCreatedResponse,
    SimulationSnapshot,
    SimulationSummary,
    SliceAtlas,
    StepResponse,
)

from backend.api.models import (
    ConfigurationPatchRequest,
    PreparationEditRequest,
    ProbabilityRequest,
    RevisionRequest,
    RunRequest,
    SimulationCreateRequest,
    StepRequest,
)


def create_simulations_router(manager) -> APIRouter:
    router = APIRouter(prefix="/api/simulations", tags=["simulations"])

    @router.post("", status_code=201, response_model=SimulationCreatedResponse)
    async def create_simulation(request: SimulationCreateRequest):
        summary = await manager.create(
            request.model_dump(exclude={"schema_version"}, exclude_none=True)
        )
        snapshot = await manager.get_snapshot(summary.simulation_id)
        return {
            **summary.model_dump(mode="json"),
            "snapshot": snapshot.model_dump(mode="json"),
        }

    @router.get("", response_model=list[SimulationSummary])
    async def list_simulations():
        return [item.model_dump(mode="json") for item in await manager.list()]

    @router.get("/{simulation_id}/snapshot", response_model=SimulationSnapshot)
    async def get_snapshot(simulation_id: str):
        return (await manager.get_snapshot(simulation_id)).model_dump(mode="json")

    @router.post("/{simulation_id}/step", response_model=StepResponse)
    async def step_simulation(simulation_id: str, request: StepRequest):
        result = await manager.step(
            simulation_id,
            expected_revision=request.expected_revision,
        )
        return result.model_dump(mode="json")

    @router.patch("/{simulation_id}/configuration", response_model=StepResponse)
    async def patch_configuration(
        simulation_id: str, request: ConfigurationPatchRequest
    ):
        patch = request.model_dump(
            exclude={"schema_version", "expected_revision"},
            exclude_none=True,
        )
        result = await manager.configure_initialization(
            simulation_id, request.expected_revision, patch
        )
        return result.model_dump(mode="json")

    @router.post("/{simulation_id}/edit", response_model=StepResponse)
    async def edit_preparation(simulation_id: str, request: PreparationEditRequest):
        if request.action == "add":
            result = await manager.add_atom(
                simulation_id, request.expected_revision, request.destination_key
            )
        elif request.action == "remove":
            result = await manager.remove_atom(
                simulation_id, request.expected_revision, request.atom_id
            )
        elif request.action == "move":
            result = await manager.move(
                simulation_id,
                request.expected_revision,
                request.atom_id,
                request.destination_key,
            )
        else:
            result = await manager.edit_metal_boundary(
                simulation_id,
                request.expected_revision,
                contour=request.contour,
                dimensions=request.dimensions,
            )
        return result.model_dump(mode="json")

    @router.post(
        "/{simulation_id}/edit/preview",
        response_model=PreparationEditPreview,
    )
    async def preview_preparation_edit(
        simulation_id: str, request: PreparationEditRequest
    ):
        return (
            await manager.preview_edit(
                simulation_id,
                request.expected_revision,
                request.action,
                atom_id=request.atom_id,
                destination_key=request.destination_key,
                contour=request.contour,
                dimensions=request.dimensions,
            )
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/start", response_model=SimulationSummary)
    async def start_simulation(simulation_id: str, request: RevisionRequest):
        return (
            await manager.start(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post(
        "/{simulation_id}/diagnostics/probabilities",
        response_model=ProbabilityOverlay,
    )
    async def diagnosis(simulation_id: str, request: ProbabilityRequest):
        return (
            await manager.probability_overlay(
                simulation_id, request.atom_id, request.q_test
            )
        ).model_dump(mode="json")

    @router.get("/{simulation_id}/events", response_model=EventPage)
    async def events(
        simulation_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        origin: Literal["physical_act", "manual_edit"] | None = None,
        operation: Literal[
            "no_change",
            "manual_edit",
            "lattice_vacancy",
            "lattice_interstitial",
            "interstitial_vacancy",
            "interstitial_interstitial",
            "boundary_external",
            "external_external",
            "external_interstitial",
            "interstitial_external",
        ] | None = None,
        act_from: int | None = Query(default=None, ge=0),
        act_to: int | None = Query(default=None, ge=0),
    ):
        if act_from is not None and act_to is not None and act_from > act_to:
            raise ValueError("act_from must not exceed act_to")
        return (
            await manager.event_page(
                simulation_id,
                offset,
                limit,
                origin=origin,
                operation=operation,
                act_from=act_from,
                act_to=act_to,
            )
        ).model_dump(mode="json")

    @router.get("/{simulation_id}/metrics", response_model=MetricsSeries)
    async def metrics(
        simulation_id: str,
        act_from: int | None = Query(default=None, ge=0),
        act_to: int | None = Query(default=None, ge=0),
    ):
        if act_from is not None and act_to is not None and act_from > act_to:
            raise ValueError("act_from must not exceed act_to")
        return (
            await manager.metrics_series(
                simulation_id,
                act_from=act_from,
                act_to=act_to,
            )
        ).model_dump(mode="json")

    @router.get("/{simulation_id}/slices", response_model=SliceAtlas)
    async def slices(
        simulation_id: str,
        axis: Literal["z"] = Query(default="z"),
    ):
        return (
            await manager.slice_atlas(simulation_id)
        ).model_dump(mode="json")

    @router.get("/{simulation_id}/journal.json", response_model=JournalExport)
    async def download_journal(simulation_id: str):
        journal = await manager.journal_export(simulation_id)
        return JSONResponse(
            content=journal.model_dump(mode="json"),
            headers={"Content-Disposition": 'attachment; filename="journal.json"'},
        )

    @router.get(
        "/{simulation_id}/atoms/{atom_id}/destinations",
        response_model=DestinationsResponse,
    )
    async def destinations(simulation_id: str, atom_id: int):
        return {
            "schema_version": 1,
            "simulation_id": simulation_id,
            "atom_id": atom_id,
            "destinations": await manager.destinations(simulation_id, atom_id),
        }

    @router.post("/{simulation_id}/undo", response_model=SimulationSnapshot)
    async def undo(simulation_id: str, request: RevisionRequest):
        return (
            await manager.undo(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/redo", response_model=SimulationSnapshot)
    async def redo(simulation_id: str, request: RevisionRequest):
        return (
            await manager.redo(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/run", response_model=SimulationSummary)
    async def run(simulation_id: str, request: RunRequest):
        return (
            await manager.run(
                simulation_id,
                request.expected_revision,
                mode=request.mode,
                interval_ms=request.interval_ms,
            )
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/pause", response_model=SimulationSummary)
    async def pause(simulation_id: str, request: RevisionRequest):
        return (
            await manager.pause(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/stop", response_model=SimulationSummary)
    async def stop(simulation_id: str, request: RevisionRequest):
        return (
            await manager.stop(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/error/retry", response_model=StepResponse)
    async def retry(simulation_id: str, request: RevisionRequest):
        return (
            await manager.retry(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post(
        "/{simulation_id}/error/acknowledge",
        response_model=SimulationSummary,
    )
    async def acknowledge(simulation_id: str, request: RevisionRequest):
        return (
            await manager.acknowledge(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.post("/{simulation_id}/reset", response_model=SimulationSnapshot)
    async def reset(simulation_id: str, request: RevisionRequest):
        return (
            await manager.reset(simulation_id, request.expected_revision)
        ).model_dump(mode="json")

    @router.delete("/{simulation_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove(
        simulation_id: str,
        expected_revision: int = Query(ge=0),
    ):
        await manager.remove(simulation_id, expected_revision)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
    SimulationCreatedResponse,
