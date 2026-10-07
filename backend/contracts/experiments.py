from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExperimentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experiment_id: str
    status: Literal[
        "PENDING", "RUNNING", "COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "FAILED"
    ]
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    successful_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)


class ExperimentResults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    experiment_id: str
    status: Literal["COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "FAILED"]
    successful_runs: list[dict[str, Any]]
    failed_runs: list[dict[str, Any]]
    aggregate: dict[str, Any] | None
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    master_seed: int
    bootstrap_seed: int
