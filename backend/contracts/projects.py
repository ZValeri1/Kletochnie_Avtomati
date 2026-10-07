from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.contracts.simulation import SimulationSummary


class ProjectMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    project_id: str
    created_at: str
    updated_at: str
    simulation_count: int = Field(ge=0)
    history_truncated: bool


class ProjectStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    project_id: str
    status: Literal["AVAILABLE", "SAVED", "LOADED", "DELETED"]
    simulation_count: int = Field(ge=0)
    created_at: str
    updated_at: str
    history_truncated: bool


class ProjectLoadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    project_id: str
    simulations: tuple[SimulationSummary, ...]


class ProjectExport(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    project_id: str
    simulations: list[dict[str, Any]] = Field(default_factory=list)
    aggregate: dict[str, Any] | None = None
