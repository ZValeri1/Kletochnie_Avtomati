from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VersionedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1


class DistributionParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mu: float
    sigma: float = Field(ge=0)


class RandomInitializationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vacancies: DistributionParameters | None = None
    interstitials: DistributionParameters | None = None
    adatoms: DistributionParameters | None = None


class OperationWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lattice_vacancy: float | None = Field(default=None, ge=0, le=1)
    lattice_interstitial: float | None = Field(default=None, ge=0, le=1)
    interstitial_vacancy_r1: float | None = Field(default=None, ge=0, le=1)
    interstitial_vacancy_r2: float | None = Field(default=None, ge=0, le=1)
    interstitial_interstitial: float | None = Field(default=None, ge=0, le=1)
    boundary_external: float | None = Field(default=None, ge=0, le=1)
    external_external: float | None = Field(default=None, ge=0, le=1)
    external_interstitial: float | None = Field(default=None, ge=0, le=1)
    interstitial_external: float | None = Field(default=None, ge=0, le=1)
    external_metal: float | None = Field(default=None, ge=0, le=1)
    shell_r1: float | None = Field(default=None, ge=0, le=1)
    shell_r2: float | None = Field(default=None, ge=0, le=1)
    vacancy: float | None = Field(default=None, ge=0, le=1)
    interstitial: float | None = Field(default=None, ge=0, le=1)
    external: float | None = Field(default=None, ge=0, le=1)


class SimulationCreateRequest(VersionedRequest):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[int] = Field(default=[30, 30], min_length=2, max_length=3)
    initialization_mode: Literal[
        "ordered", "random_defective", "explicit_defective", "symmetric_defective"
    ] = "ordered"
    n_v: int = Field(default=0, ge=0)
    n_i: int = Field(default=0, ge=0)
    n_as: int = Field(default=0, ge=0)
    random_parameters: RandomInitializationParameters | None = None
    contour: list[tuple[int, int]] | None = None
    seed_init: int | None = None
    seed_sim: int | None = None
    profile: Literal["fe_co60_physical"] = "fe_co60_physical"
    q_max_ev: float | None = Field(default=None, ge=0)
    q_thr_ev: float = Field(default=20, ge=0)
    weights: OperationWeights | None = None


class ConfigurationPatchRequest(VersionedRequest):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    dimensions: list[int] | None = Field(default=None, min_length=2, max_length=3)
    contour: list[tuple[int, int]] | None = None
    initialization_mode: Literal[
        "ordered", "random_defective", "explicit_defective", "symmetric_defective"
    ] | None = None
    n_v: int | None = Field(default=None, ge=0)
    n_i: int | None = Field(default=None, ge=0)
    n_as: int | None = Field(default=None, ge=0)
    random_parameters: RandomInitializationParameters | None = None
    seed_init: int | None = None
    seed_sim: int | None = None
    profile: Literal["fe_co60_physical"] | None = None
    q_max_ev: float | None = Field(default=None, ge=0)
    q_thr_ev: float | None = Field(default=None, ge=0)
    weights: OperationWeights | None = None

    @model_validator(mode="after")
    def contains_a_patch(self):
        if self.model_fields_set == {"expected_revision"}:
            raise ValueError("configuration patch is empty")
        return self


class PreparationEditRequest(VersionedRequest):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    action: Literal["add", "remove", "move", "boundary"]
    atom_id: int | None = Field(default=None, ge=0)
    destination_key: str | None = None
    contour: list[tuple[int, int]] | None = None
    dimensions: list[int] | None = None

    @model_validator(mode="after")
    def action_has_required_arguments(self):
        if self.action == "add" and self.destination_key is None:
            raise ValueError("add requires destination_key")
        if self.action == "remove" and self.atom_id is None:
            raise ValueError("remove requires atom_id")
        if self.action == "move" and (
            self.atom_id is None or self.destination_key is None
        ):
            raise ValueError("move requires atom_id and destination_key")
        if self.action == "boundary" and self.contour is None and self.dimensions is None:
            raise ValueError("boundary requires contour or dimensions")
        return self


class StepRequest(VersionedRequest):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class RevisionRequest(VersionedRequest):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class ProbabilityRequest(VersionedRequest):
    atom_id: int = Field(ge=0)
    q_test: float = Field(ge=0)


class ProjectSaveRequest(VersionedRequest):
    simulation_ids: list[str]
    overwrite: bool = False


class ExperimentRequest(VersionedRequest):
    configurations: list[SimulationCreateRequest]
    repetitions: int = Field(default=1, ge=1, le=10_000)
    steps: int = Field(ge=0, le=10_000)
    master_seed: int
