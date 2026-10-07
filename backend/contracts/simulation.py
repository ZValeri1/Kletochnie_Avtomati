from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    TypeAdapter,
    model_validator,
)

from backend.contracts.errors import ApplicationError


SimulationStatusValue = Literal[
    "PREPARATION",
    "PAUSED",
    "RUNNING",
    "PAUSED_WITH_ERROR",
    "STOPPED",
    "FAILED",
]


class SimulationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n_correct: int = Field(ge=0)
    n_v: int = Field(ge=0)
    n_i: int = Field(ge=0)
    n_as: int = Field(ge=0)
    d: int = Field(ge=0)
    s: FiniteFloat = Field(ge=0)


class MetricsPoint(SimulationMetrics):
    revision: int = Field(ge=0)
    act_number: int = Field(ge=0)
    origin: Literal["initialization", "physical_act", "manual_edit"]


class MetricsSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    points: tuple[MetricsPoint, ...]


class AtomSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: int
    site_key: str
    coordinate: tuple[FiniteFloat, ...]
    site_kind: Literal["lattice", "interstitial"]
    metal_relation: Literal["interior", "boundary", "outside"]
    visual_state: str


class ProbabilityOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_site: str
    source_coordinate: tuple[FiniteFloat, ...]
    source_kind: Literal["lattice", "interstitial"]
    destination_site: str
    destination_coordinate: tuple[FiniteFloat, ...]
    destination_kind: Literal["lattice", "interstitial"]
    destination_relation: Literal["interior", "boundary", "outside"]
    operation: Literal[
        "lattice_vacancy",
        "lattice_interstitial",
        "interstitial_vacancy",
        "interstitial_interstitial",
        "boundary_external",
        "external_external",
        "external_interstitial",
        "interstitial_external",
        "external_metal",
    ] | None
    shell: Literal[1, 2]
    operation_weight: FiniteFloat = Field(ge=0)
    shell_weight: FiniteFloat = Field(ge=0)
    position_weight: FiniteFloat = Field(ge=0)
    total_weight: FiniteFloat = Field(ge=0)
    probability: FiniteFloat = Field(ge=0, le=1)
    selectable: bool
    block_code: str | None
    q_test: FiniteFloat = Field(ge=0)
    q_thr: FiniteFloat = Field(ge=0)


class ProbabilityOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    atom_id: int = Field(ge=0)
    q_test: FiniteFloat = Field(ge=0)
    q_thr: FiniteFloat = Field(ge=0)
    outcomes: tuple[ProbabilityOutcome, ...]


class SliceSite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    site_key: str
    coordinate: tuple[FiniteFloat, ...]
    site_kind: Literal["lattice", "interstitial"]
    metal_relation: Literal["interior", "boundary", "outside"]
    atom_id: int | None = Field(default=None, ge=0)
    visual_state: str


class SliceLayer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    coordinate: FiniteFloat
    sites: tuple[SliceSite, ...]


class SliceAtlas(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    axis: Literal["z"]
    slices: tuple[SliceLayer, ...]


class HistoryCapabilities(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    can_undo: bool
    can_redo: bool
    retained_action_count: int = Field(ge=0)
    history_limit: int = Field(ge=1)
    history_truncated: bool


class DefectCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    n0: int
    n_atoms: int
    n_v: int
    n_i: int
    n_as: int


class EffectiveWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lattice_vacancy: FiniteFloat = Field(ge=0, le=1)
    lattice_interstitial: FiniteFloat = Field(ge=0, le=1)
    interstitial_vacancy_r1: FiniteFloat = Field(ge=0, le=1)
    interstitial_vacancy_r2: FiniteFloat = Field(ge=0, le=1)
    interstitial_interstitial: FiniteFloat = Field(ge=0, le=1)
    boundary_external: FiniteFloat = Field(ge=0, le=1)
    external_external: FiniteFloat = Field(ge=0, le=1)
    external_interstitial: FiniteFloat = Field(ge=0, le=1)
    interstitial_external: FiniteFloat = Field(ge=0, le=1)
    external_metal: FiniteFloat = Field(ge=0, le=1)
    shell_r1: FiniteFloat = Field(ge=0, le=1)
    shell_r2: FiniteFloat = Field(ge=0, le=1)
    vacancy: FiniteFloat = Field(ge=0, le=1)
    interstitial: FiniteFloat = Field(ge=0, le=1)
    external: FiniteFloat = Field(ge=0, le=1)


class SimulationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimensions: tuple[int, ...]
    field_dimensions: tuple[int, ...]
    contour: tuple[tuple[int, int], ...] | None
    profile: Literal["fe_co60_physical"]
    initialization_mode: Literal[
        "ordered", "random_defective", "explicit_defective", "symmetric_defective"
    ]
    n_v: int = Field(ge=0)
    n_i: int = Field(ge=0)
    n_as: int = Field(ge=0)
    random_parameters: dict[str, dict[str, float]]
    seed_init: int
    seed_sim: int
    q_max_ev: FiniteFloat = Field(ge=0)
    q_thr_ev: FiniteFloat = Field(ge=0)
    weights: EffectiveWeights

    @model_validator(mode="after")
    def dimensions_match(self):
        if len(self.dimensions) not in (2, 3):
            raise ValueError("metal dimensions must be 2D or 3D")
        if len(self.field_dimensions) != len(self.dimensions):
            raise ValueError("field and metal dimensions must match")
        return self


class SimulationSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    status: SimulationStatusValue
    phase: Literal["PREPARATION", "SIMULATION"]
    config_locked: bool
    configuration: SimulationConfiguration
    dimensions: tuple[int, ...]
    atoms: tuple[AtomSnapshot, ...]
    vacancies: tuple[tuple[FiniteFloat, ...], ...]
    metrics: SimulationMetrics
    counts: DefectCounts
    history_capabilities: HistoryCapabilities
    error: ApplicationError | None = None

    @model_validator(mode="after")
    def coordinates_match_dimensions(self):
        dimension = len(self.dimensions)
        if dimension not in (2, 3):
            raise ValueError("dimensions must describe a 2D or 3D model")
        if any(len(atom.coordinate) != dimension for atom in self.atoms):
            raise ValueError("atom coordinate dimension does not match snapshot")
        if any(len(coordinate) != dimension for coordinate in self.vacancies):
            raise ValueError("vacancy coordinate dimension does not match snapshot")
        return self


class SimulationEvent(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    schema_version: Literal[1] = 1
    event_id: str
    simulation_id: str
    revision: int = Field(ge=0)
    act_number: int = Field(ge=0)
    source_atom_id: int | None
    source_site: str | None
    source_coordinate: tuple[FiniteFloat, ...] | None
    destination_site: str | None
    destination_coordinate: tuple[FiniteFloat, ...] | None
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
        "external_metal",
    ]
    shell: int | None
    q_n: FiniteFloat | None = Field(ge=0)
    q_thr: FiniteFloat | None = Field(ge=0)
    result_reason: str
    operation_weight: FiniteFloat = Field(ge=0)
    shell_weight: FiniteFloat = Field(ge=0)
    position_weight: FiniteFloat = Field(ge=0)
    total_weight: FiniteFloat = Field(ge=0)
    probability: FiniteFloat = Field(ge=0, le=1)
    affected_atom_ids: tuple[int, ...]
    affected_site_ids: tuple[str, ...]
    metrics_before: SimulationMetrics
    metrics_after: SimulationMetrics
    origin: Literal["physical_act", "manual_edit"]


class EventPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    events: tuple[SimulationEvent, ...]


class JournalExport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    configuration: SimulationConfiguration
    events: tuple[SimulationEvent, ...]
    metrics: tuple[MetricsPoint, ...]
    formulas: dict[str, str]
    units: dict[str, str]
    final_snapshot: SimulationSnapshot


class DestinationOption(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    key: str
    kind: Literal["lattice", "interstitial"]
    coordinate: tuple[FiniteFloat, ...]
    selectable: bool
    block_code: str | None

    @model_validator(mode="after")
    def reason_matches_selectability(self):
        if self.selectable != (self.block_code is None):
            raise ValueError("block_code must be null exactly for selectable destinations")
        return self


class DestinationsResponse(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    atom_id: int = Field(ge=0)
    destinations: tuple[DestinationOption, ...]


class SimulationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    simulation_id: str
    status: SimulationStatusValue
    revision: int = 0
    seed_init: int | None = None
    seed_sim: int | None = None
    source_project_id: str | None = None
    source_simulation_id: str | None = None
    last_valid_snapshot: SimulationSnapshot | dict[str, Any] | None = None
    error: ApplicationError | None = None


class StepResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int
    event: SimulationEvent
    snapshot: SimulationSnapshot


class PreparationEditPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    simulation_id: str
    revision: int = Field(ge=0)
    action: Literal["add", "remove", "move", "boundary"]
    metrics_before: SimulationMetrics
    metrics_after: SimulationMetrics
    counts_before: DefectCounts
    counts_after: DefectCounts


class SimulationCreatedResponse(SimulationSummary):
    snapshot: SimulationSnapshot


class StreamMessageBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    message_id: int = Field(ge=1)
    simulation_id: str
    revision: int = Field(ge=0)


class SnapshotStreamMessage(StreamMessageBase):
    type: Literal["snapshot"]
    snapshot: SimulationSnapshot


class EventStreamMessage(StreamMessageBase):
    type: Literal["event"]
    event: SimulationEvent


class StatusStreamMessage(StreamMessageBase):
    type: Literal["status"]
    summary: SimulationSummary


class ErrorStreamMessage(StreamMessageBase):
    type: Literal["error"]
    error: ApplicationError


StreamMessage = Annotated[
    SnapshotStreamMessage
    | EventStreamMessage
    | StatusStreamMessage
    | ErrorStreamMessage,
    Field(discriminator="type"),
]

STREAM_MESSAGE_ADAPTER = TypeAdapter(StreamMessage)
