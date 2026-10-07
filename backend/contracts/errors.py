from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApplicationError(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    code: str
    message: str
    simulation_id: str | None = None
    command_id: str | None = None
    revision: int | None = Field(default=None, ge=0)
    recoverable: bool
    details: dict[str, Any] = Field(default_factory=dict)
