export type SimulationMetrics = {
  n_correct: number;
  n_v: number;
  n_i: number;
  n_as: number;
  d: number;
  s: number;
};

export type AtomSnapshot = {
  id: number;
  site_key: string;
  coordinate: number[];
  site_kind: "lattice" | "interstitial";
  metal_relation: "interior" | "boundary" | "outside";
  visual_state: string;
};

export type SimulationStatus =
  | "PREPARATION"
  | "PAUSED"
  | "RUNNING"
  | "PAUSED_WITH_ERROR"
  | "STOPPED"
  | "FAILED";

export type SimulationSnapshot = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  status: SimulationStatus;
  phase: "PREPARATION" | "SIMULATION";
  config_locked: boolean;
  configuration: {
    dimensions: number[];
    field_dimensions: number[];
    contour: [number, number][] | null;
    profile: "fe_co60_physical";
    method?: "monte_carlo" | "cellular_automata";
    initialization_mode:
      | "ordered"
      | "random_defective"
      | "explicit_defective"
      | "symmetric_defective";
    n_v: number;
    n_i: number;
    n_as: number;
    random_parameters: Record<string, { mu: number; sigma: number }>;
    seed_init: number;
    seed_sim: number;
    q_max_ev: number;
    q_thr_ev: number;
    weights: Record<string, number>;
  };
  dimensions: number[];
  atoms: AtomSnapshot[];
  vacancies: number[][];
  counts: {
    n0: number;
    n_atoms: number;
    n_v: number;
    n_i: number;
    n_as: number;
  };
  metrics: SimulationMetrics;
  history_capabilities: {
    can_undo: boolean;
    can_redo: boolean;
    retained_action_count: number;
    history_limit: number;
    history_truncated: boolean;
  };
  error: ApplicationError | null;
};

export type SimulationEvent = {
  schema_version: 1;
  event_id: string;
  simulation_id: string;
  revision: number;
  act_number: number;
  source_atom_id: number | null;
  source_site: string | null;
  source_coordinate: number[] | null;
  destination_site: string | null;
  destination_coordinate: number[] | null;
  operation:
    | "no_change"
    | "manual_edit"
    | "lattice_vacancy"
    | "lattice_interstitial"
    | "interstitial_vacancy"
    | "interstitial_interstitial"
    | "boundary_external"
    | "external_external"
    | "external_interstitial"
    | "interstitial_external";
  shell: number | null;
  q_n: number | null;
  q_thr: number | null;
  result_reason: string;
  operation_weight: number;
  shell_weight: number;
  position_weight: number;
  total_weight: number;
  probability: number;
  affected_atom_ids: number[];
  affected_site_ids: string[];
  metrics_before: SimulationMetrics;
  metrics_after: SimulationMetrics;
  origin: "physical_act" | "manual_edit";
};

export type ApplicationError = {
  schema_version: 1;
  code: string;
  message: string;
  simulation_id?: string | null;
  command_id?: string | null;
  revision?: number | null;
  recoverable: boolean;
  details: Record<string, unknown>;
};

export type ProbabilityOutcome = {
  source_site: string;
  source_coordinate: number[];
  source_kind: "lattice" | "interstitial";
  destination_site: string;
  destination_coordinate: number[];
  destination_kind: "lattice" | "interstitial";
  destination_relation: "interior" | "boundary" | "outside";
  operation:
    | "lattice_vacancy"
    | "lattice_interstitial"
    | "interstitial_vacancy"
    | "interstitial_interstitial"
    | "boundary_external"
    | "external_external"
    | "external_interstitial"
    | "interstitial_external"
    | "external_metal"
    | null;
  shell: 1 | 2;
  operation_weight: number;
  shell_weight: number;
  position_weight: number;
  total_weight: number;
  probability: number;
  selectable: boolean;
  block_code: string | null;
  q_test: number;
  q_thr: number;
};

export type ProbabilityOverlay = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  atom_id: number;
  q_test: number;
  q_thr: number;
  outcomes: ProbabilityOutcome[];
};

export type MetricsPoint = SimulationMetrics & {
  revision: number;
  act_number: number;
  origin: "initialization" | "physical_act" | "manual_edit";
};

export type MetricsSeries = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  points: MetricsPoint[];
};

export type SliceSite = {
  site_key: string;
  coordinate: number[];
  site_kind: "lattice" | "interstitial";
  metal_relation: "interior" | "boundary" | "outside";
  atom_id: number | null;
  visual_state: string;
};

export type SliceAtlas = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  axis: "z";
  slices: { coordinate: number; sites: SliceSite[] }[];
};

export type ProjectStatus = {
  schema_version: 1;
  project_id: string;
  status: "AVAILABLE" | "SAVED" | "LOADED" | "DELETED";
  simulation_count: number;
  created_at: string;
  updated_at: string;
  history_truncated: boolean;
};

export type ExperimentStatus = {
  schema_version: 1;
  experiment_id: string;
  status:
    | "PENDING"
    | "RUNNING"
    | "COMPLETED"
    | "COMPLETED_WITH_ERRORS"
    | "CANCELLED"
    | "FAILED";
  completed_steps: number;
  total_steps: number;
  successful_runs: number;
  failed_runs: number;
};

export type ExperimentResults = {
  schema_version: 1;
  experiment_id: string;
  status: "COMPLETED" | "COMPLETED_WITH_ERRORS" | "CANCELLED" | "FAILED";
  completed_steps: number;
  total_steps: number;
  successful_runs: ExperimentRun[];
  failed_runs_details: ExperimentFailure[];
  aggregate: ResearchAggregate | null;
  master_seed: number;
  bootstrap_seed: number;
};

export type ExperimentRun = {
  run: number;
  configuration_index: number;
  simulation_id: string;
  derived_seeds: { seed_init: number; seed_sim: number };
  snapshot: SimulationSnapshot;
  metrics: MetricsPoint[];
};

export type ExperimentFailure = {
  run: number;
  configuration_index: number;
  derived_seeds: { seed_init: number; seed_sim: number };
  code: string;
  message: string;
};

export type MetricAggregate = {
  count: number;
  mean: number;
  minimum: number;
  maximum: number;
  p50: number;
  p95: number;
  confidence_interval: [number, number];
  ci_informative: boolean;
};

export type ResearchAggregate = {
  schema_version: 1;
  final: Record<string, MetricAggregate>;
  by_act: Record<string, Record<string, MetricAggregate>>;
  bootstrap_seed: number;
};

export type SimulationSummary = {
  schema_version: 1;
  simulation_id: string;
  status: SimulationStatus;
  revision: number;
  seed_init?: number | null;
  seed_sim?: number | null;
  source_project_id?: string | null;
  source_simulation_id?: string | null;
  run_mode?: "visual" | "fast" | null;
  error?: ApplicationError | null;
};

export type StepResponse = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  event: SimulationEvent;
  snapshot: SimulationSnapshot;
};

export type SimulationCreatedResponse = SimulationSummary & {
  snapshot: SimulationSnapshot;
};

export type EventPage = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  offset: number;
  limit: number;
  total: number;
  events: SimulationEvent[];
};

export type DestinationOption = {
  key: string;
  kind: "lattice" | "interstitial";
  coordinate: number[];
  selectable: boolean;
  block_code: string | null;
};

export type DestinationsResponse = {
  schema_version: 1;
  simulation_id: string;
  atom_id: number;
  destinations: DestinationOption[];
};

export type PreparationEditPreview = {
  schema_version: 1;
  simulation_id: string;
  revision: number;
  action: "add" | "remove" | "move" | "boundary";
  metrics_before: SimulationMetrics;
  metrics_after: SimulationMetrics;
  counts_before: SimulationSnapshot["counts"];
  counts_after: SimulationSnapshot["counts"];
};

export type ProjectLoadResponse = {
  schema_version: 1;
  project_id: string;
  simulations: SimulationSummary[];
};

type StreamEnvelope = {
  schema_version: 1;
  message_id: number;
  simulation_id: string;
  revision: number;
};

export type StreamMessage =
  | (StreamEnvelope & { type: "snapshot"; snapshot: SimulationSnapshot })
  | (StreamEnvelope & { type: "event"; event: SimulationEvent })
  | (StreamEnvelope & { type: "status"; summary: SimulationSummary })
  | (StreamEnvelope & { type: "error"; error: ApplicationError });

const object = (value: unknown, name: string): Record<string, unknown> => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
};

const version = (payload: Record<string, unknown>) => {
  if (payload.schema_version !== 1) {
    throw new Error("Unsupported schema_version");
  }
};

const finiteNumber = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value);

const numericCoordinate = (value: unknown, dimension: number) =>
  Array.isArray(value) &&
  value.length === dimension &&
  value.every(finiteNumber);

export function decodeSimulationSnapshot(value: unknown): SimulationSnapshot {
  const payload = object(value, "SimulationSnapshot");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    typeof payload.revision !== "number" ||
    ![
      "PREPARATION",
      "PAUSED",
      "RUNNING",
      "PAUSED_WITH_ERROR",
      "STOPPED",
      "FAILED",
    ].includes(String(payload.status)) ||
    !["PREPARATION", "SIMULATION"].includes(String(payload.phase)) ||
    typeof payload.config_locked !== "boolean" ||
    !Array.isArray(payload.dimensions) ||
    ![2, 3].includes(payload.dimensions.length) ||
    !payload.dimensions.every(
      (size) => Number.isInteger(size) && Number(size) >= 2,
    ) ||
    !Array.isArray(payload.atoms) ||
    !Array.isArray(payload.vacancies) ||
    payload.counts === undefined ||
    payload.metrics === undefined ||
    payload.history_capabilities === undefined ||
    !(payload.error === null || typeof payload.error === "object")
  ) {
    throw new Error("Invalid SimulationSnapshot");
  }
  if (payload.configuration === undefined) {
    throw new Error("Invalid snapshot configuration");
  }
  const dimension = payload.dimensions.length;
  const metrics = object(payload.metrics, "metrics");
  for (const key of ["n_correct", "n_v", "n_i", "n_as", "d"]) {
    if (!Number.isInteger(metrics[key]) || Number(metrics[key]) < 0) {
      throw new Error("Invalid snapshot metrics");
    }
  }
  if (!finiteNumber(metrics.s) || Number(metrics.s) < 0) {
    throw new Error("Invalid snapshot metrics");
  }
  const history = object(payload.history_capabilities, "history_capabilities");
  if (
    typeof history.can_undo !== "boolean" ||
    typeof history.can_redo !== "boolean" ||
    !Number.isInteger(history.retained_action_count) ||
    !Number.isInteger(history.history_limit) ||
    typeof history.history_truncated !== "boolean"
  ) {
    throw new Error("Invalid history capabilities");
  }
  const counts = object(payload.counts, "counts");
  if (
    !["n0", "n_atoms", "n_v", "n_i", "n_as"].every(
      (key) => Number.isInteger(counts[key]) && Number(counts[key]) >= 0,
    )
  ) {
    throw new Error("Invalid snapshot counts");
  }
  const configuration = object(payload.configuration, "configuration");
  const configDimensions = configuration.dimensions;
  const fieldDimensions = configuration.field_dimensions;
  const weights = object(configuration.weights, "configuration.weights");
  const randomParameters = object(
    configuration.random_parameters,
    "configuration.random_parameters",
  );
  const requiredWeights = [
    "lattice_vacancy",
    "lattice_interstitial",
    "interstitial_vacancy_r1",
    "interstitial_vacancy_r2",
    "interstitial_interstitial",
    "boundary_external",
    "external_external",
    "external_interstitial",
    "interstitial_external",
    "external_metal",
    "shell_r1",
    "shell_r2",
    "vacancy",
    "interstitial",
    "external",
    "from_lattice_vacancy",
    "from_lattice_interstitial",
    "from_lattice_shell_r1",
    "from_lattice_shell_r2",
    "from_lattice_inside",
    "from_lattice_outside",
    "from_interstitial_vacancy",
    "from_interstitial_interstitial",
    "from_interstitial_shell_r1",
    "from_interstitial_shell_r2",
    "from_interstitial_inside",
    "from_interstitial_outside",
  ];
  if (
    !Array.isArray(configDimensions) ||
    !Array.isArray(fieldDimensions) ||
    configDimensions.length !== dimension ||
    fieldDimensions.length !== dimension ||
    !configDimensions.every(
      (item) => Number.isInteger(item) && Number(item) >= 2,
    ) ||
    !fieldDimensions.every(
      (item) => Number.isInteger(item) && Number(item) >= 2,
    ) ||
    configuration.profile !== "fe_co60_physical" ||
    (configuration.method !== undefined &&
      configuration.method !== "monte_carlo" &&
      configuration.method !== "cellular_automata") ||
    ![
      "ordered",
      "random_defective",
      "explicit_defective",
      "symmetric_defective",
    ].includes(String(configuration.initialization_mode)) ||
    !["n_v", "n_i", "n_as", "seed_init", "seed_sim"].every((key) =>
      Number.isInteger(configuration[key]),
    ) ||
    !["n_v", "n_i", "n_as"].every(
      (key) => Number(configuration[key]) >= 0,
    ) ||
    !finiteNumber(configuration.q_max_ev) ||
    Number(configuration.q_max_ev) < 0 ||
    !finiteNumber(configuration.q_thr_ev) ||
    Number(configuration.q_thr_ev) < 0 ||
    configuration.random_parameters === undefined ||
    requiredWeights.some(
      (key) =>
        !finiteNumber(weights[key]) ||
        Number(weights[key]) < 0 ||
        Number(weights[key]) > 1,
    )
  ) {
    throw new Error("Invalid snapshot configuration");
  }
  if (
    !(
      configuration.contour === null ||
      (dimension === 2 &&
        Array.isArray(configuration.contour) &&
        configuration.contour.every(
          (point) => Array.isArray(point) && numericCoordinate(point, 2),
        ))
    )
  ) {
    throw new Error("Invalid snapshot configuration contour");
  }
  for (const parameters of Object.values(randomParameters)) {
    const distribution = object(
      parameters,
      "configuration.random_parameters distribution",
    );
    if (
      !finiteNumber(distribution.mu) ||
      !finiteNumber(distribution.sigma) ||
      Number(distribution.sigma) < 0
    ) {
      throw new Error("Invalid snapshot configuration random_parameters");
    }
  }
  if (payload.error !== null) decodeApplicationError(payload.error);
  for (const item of payload.atoms) {
    const atom = object(item, "atom");
    if (
      typeof atom.id !== "number" ||
      typeof atom.site_key !== "string" ||
      !["lattice", "interstitial"].includes(String(atom.site_kind)) ||
      !["interior", "boundary", "outside"].includes(
        String(atom.metal_relation),
      ) ||
      typeof atom.visual_state !== "string" ||
      !numericCoordinate(atom.coordinate, dimension)
    ) {
      throw new Error("Invalid atom coordinate");
    }
  }
  if (!payload.vacancies.every((item) => numericCoordinate(item, dimension))) {
    throw new Error("Invalid vacancy coordinate");
  }
  return structuredClone(payload) as SimulationSnapshot;
}

export function decodeSimulationEvent(value: unknown): SimulationEvent {
  const payload = object(value, "SimulationEvent");
  version(payload);
  if (
    typeof payload.event_id !== "string" ||
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    Number(payload.revision) < 0 ||
    !Number.isInteger(payload.act_number) ||
    Number(payload.act_number) < 0 ||
    !(
      payload.source_atom_id === null || Number.isInteger(payload.source_atom_id)
    ) ||
    !(
      payload.source_site === null || typeof payload.source_site === "string"
    ) ||
    !(
      payload.destination_site === null ||
      typeof payload.destination_site === "string"
    ) ||
    ![
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
    ].includes(String(payload.operation)) ||
    typeof payload.result_reason !== "string" ||
    !Array.isArray(payload.affected_atom_ids) ||
    !Array.isArray(payload.affected_site_ids) ||
    payload.metrics_before === undefined ||
    payload.metrics_after === undefined ||
    !(
      payload.q_n === null ||
      (finiteNumber(payload.q_n) && Number(payload.q_n) >= 0)
    ) ||
    !(
      payload.q_thr === null ||
      (finiteNumber(payload.q_thr) && Number(payload.q_thr) >= 0)
    ) ||
    !(payload.shell === null || [1, 2].includes(Number(payload.shell))) ||
    ![
      "operation_weight",
      "shell_weight",
      "position_weight",
      "total_weight",
      "probability",
    ].every(
      (key) => finiteNumber(payload[key]) && Number(payload[key]) >= 0,
    ) ||
    Number(payload.probability) > 1 ||
    !["physical_act", "manual_edit"].includes(String(payload.origin))
  ) {
    throw new Error("Invalid SimulationEvent");
  }
  const coordinates = [payload.source_coordinate, payload.destination_coordinate];
  if (
    coordinates.some(
      (coordinate) =>
        coordinate !== null &&
        (!Array.isArray(coordinate) ||
          ![2, 3].includes(coordinate.length) ||
          !coordinate.every(finiteNumber)),
    ) ||
    (Array.isArray(payload.source_coordinate) &&
      Array.isArray(payload.destination_coordinate) &&
      payload.source_coordinate.length !== payload.destination_coordinate.length)
  ) {
    throw new Error("Invalid event coordinate");
  }
  if (!payload.affected_atom_ids.every((item) => Number.isInteger(item))) {
    throw new Error("Invalid affected_atom_ids");
  }
  if (!payload.affected_site_ids.every((item) => typeof item === "string")) {
    throw new Error("Invalid affected_site_ids");
  }
  for (const field of ["metrics_before", "metrics_after"]) {
    const metrics = object(payload[field], field);
    if (
      !["n_correct", "n_v", "n_i", "n_as", "d"].every(
        (key) => Number.isInteger(metrics[key]) && Number(metrics[key]) >= 0,
      ) ||
      !finiteNumber(metrics.s) ||
      Number(metrics.s) < 0
    ) {
      throw new Error("Invalid event metrics");
    }
  }
  return structuredClone(payload) as SimulationEvent;
}

export function decodeApplicationError(value: unknown): ApplicationError {
  const payload = object(value, "ApplicationError");
  version(payload);
  if (
    typeof payload.code !== "string" ||
    typeof payload.message !== "string" ||
    typeof payload.recoverable !== "boolean" ||
    !(
      payload.simulation_id === undefined ||
      payload.simulation_id === null ||
      typeof payload.simulation_id === "string"
    ) ||
    !(
      payload.command_id === undefined ||
      payload.command_id === null ||
      typeof payload.command_id === "string"
    ) ||
    !(
      payload.revision === undefined ||
      payload.revision === null ||
      Number.isInteger(payload.revision)
    )
  ) {
    throw new Error("Invalid ApplicationError");
  }
  object(payload.details, "ApplicationError.details");
  return structuredClone(payload) as ApplicationError;
}

export function decodeProbabilityOverlay(value: unknown): ProbabilityOverlay {
  const payload = object(value, "ProbabilityOverlay");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    Number(payload.revision) < 0 ||
    !Number.isInteger(payload.atom_id) ||
    Number(payload.atom_id) < 0 ||
    !finiteNumber(payload.q_test) ||
    Number(payload.q_test) < 0 ||
    !finiteNumber(payload.q_thr) ||
    Number(payload.q_thr) < 0 ||
    !Array.isArray(payload.outcomes)
  ) {
    throw new Error("Invalid ProbabilityOverlay");
  }
  const operations = [
    "lattice_vacancy",
    "lattice_interstitial",
    "interstitial_vacancy",
    "interstitial_interstitial",
    "boundary_external",
    "external_external",
    "external_interstitial",
    "interstitial_external",
    "external_metal",
  ];
  for (const item of payload.outcomes) {
    const outcome = object(item, "ProbabilityOutcome");
    if (
      typeof outcome.source_site !== "string" ||
      !Array.isArray(outcome.source_coordinate) ||
      !outcome.source_coordinate.every(finiteNumber) ||
      !["lattice", "interstitial"].includes(String(outcome.source_kind)) ||
      typeof outcome.destination_site !== "string" ||
      !Array.isArray(outcome.destination_coordinate) ||
      !outcome.destination_coordinate.every(finiteNumber) ||
      !["lattice", "interstitial"].includes(String(outcome.destination_kind)) ||
      !["interior", "boundary", "outside"].includes(
        String(outcome.destination_relation),
      ) ||
      !(
        outcome.operation === null ||
        operations.includes(String(outcome.operation))
      ) ||
      ![1, 2].includes(Number(outcome.shell)) ||
      typeof outcome.selectable !== "boolean" ||
      !(
        outcome.block_code === null || typeof outcome.block_code === "string"
      ) ||
      ![
        "operation_weight",
        "shell_weight",
        "position_weight",
        "total_weight",
        "probability",
        "q_test",
        "q_thr",
      ].every(
        (key) => finiteNumber(outcome[key]) && Number(outcome[key]) >= 0,
      ) ||
      Number(outcome.probability) > 1
    ) {
      throw new Error("Invalid ProbabilityOutcome");
    }
  }
  return structuredClone(payload) as ProbabilityOverlay;
}

export function decodeMetricsSeries(value: unknown): MetricsSeries {
  const payload = object(value, "MetricsSeries");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    Number(payload.revision) < 0 ||
    !Array.isArray(payload.points)
  ) {
    throw new Error("Invalid MetricsSeries");
  }
  for (const item of payload.points) {
    const point = object(item, "MetricsPoint");
    if (
      !Number.isInteger(point.revision) ||
      Number(point.revision) < 0 ||
      !Number.isInteger(point.act_number) ||
      Number(point.act_number) < 0 ||
      !["initialization", "physical_act", "manual_edit"].includes(
        String(point.origin),
      ) ||
      !["n_correct", "n_v", "n_i", "n_as", "d"].every(
        (key) => Number.isInteger(point[key]) && Number(point[key]) >= 0,
      ) ||
      !finiteNumber(point.s) ||
      Number(point.s) < 0
    ) {
      throw new Error("Invalid MetricsPoint");
    }
  }
  return structuredClone(payload) as MetricsSeries;
}

export function decodeSliceAtlas(value: unknown): SliceAtlas {
  const payload = object(value, "SliceAtlas");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    payload.axis !== "z" ||
    !Array.isArray(payload.slices)
  ) {
    throw new Error("Invalid SliceAtlas");
  }
  for (const item of payload.slices) {
    const layer = object(item, "SliceLayer");
    if (!finiteNumber(layer.coordinate) || !Array.isArray(layer.sites)) {
      throw new Error("Invalid SliceLayer");
    }
    for (const value of layer.sites) {
      const site = object(value, "SliceSite");
      if (
        typeof site.site_key !== "string" ||
        !Array.isArray(site.coordinate) ||
        !site.coordinate.every(finiteNumber) ||
        !["lattice", "interstitial"].includes(String(site.site_kind)) ||
        !["interior", "boundary", "outside"].includes(
          String(site.metal_relation),
        ) ||
        !(site.atom_id === null || Number.isInteger(site.atom_id)) ||
        typeof site.visual_state !== "string"
      ) {
        throw new Error("Invalid SliceSite");
      }
    }
  }
  return structuredClone(payload) as SliceAtlas;
}

export function decodeProjectStatus(value: unknown): ProjectStatus {
  const payload = object(value, "ProjectStatus");
  version(payload);
  if (
    typeof payload.project_id !== "string" ||
    !["AVAILABLE", "SAVED", "LOADED", "DELETED"].includes(
      String(payload.status),
    ) ||
    !Number.isInteger(payload.simulation_count) ||
    Number(payload.simulation_count) < 0 ||
    typeof payload.created_at !== "string" ||
    typeof payload.updated_at !== "string" ||
    typeof payload.history_truncated !== "boolean"
  ) {
    throw new Error("Invalid ProjectStatus");
  }
  return structuredClone(payload) as ProjectStatus;
}

export function decodeExperimentStatus(value: unknown): ExperimentStatus {
  const payload = object(value, "ExperimentStatus");
  version(payload);
  if (
    typeof payload.experiment_id !== "string" ||
    ![
      "PENDING",
      "RUNNING",
      "COMPLETED",
      "COMPLETED_WITH_ERRORS",
      "CANCELLED",
      "FAILED",
    ].includes(String(payload.status)) ||
    !["completed_steps", "total_steps", "successful_runs", "failed_runs"].every(
      (key) => Number.isInteger(payload[key]) && Number(payload[key]) >= 0,
    )
  ) {
    throw new Error("Invalid ExperimentStatus");
  }
  return structuredClone(payload) as ExperimentStatus;
}

export function decodeSimulationSummary(value: unknown): SimulationSummary {
  const payload = object(value, "SimulationSummary");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    Number(payload.revision) < 0 ||
    ![
      "PREPARATION",
      "PAUSED",
      "RUNNING",
      "PAUSED_WITH_ERROR",
      "STOPPED",
      "FAILED",
    ].includes(String(payload.status)) ||
    !(
      payload.seed_init === undefined ||
      payload.seed_init === null ||
      Number.isInteger(payload.seed_init)
    ) ||
    !(
      payload.seed_sim === undefined ||
      payload.seed_sim === null ||
      Number.isInteger(payload.seed_sim)
    ) ||
    !(
      payload.source_project_id === undefined ||
      payload.source_project_id === null ||
      typeof payload.source_project_id === "string"
    ) ||
    !(
      payload.source_simulation_id === undefined ||
      payload.source_simulation_id === null ||
      typeof payload.source_simulation_id === "string"
    ) ||
    !(
      payload.run_mode === undefined ||
      payload.run_mode === null ||
      payload.run_mode === "visual" ||
      payload.run_mode === "fast"
    ) ||
    !(
      payload.error === undefined ||
      payload.error === null ||
      typeof payload.error === "object"
    )
  ) {
    throw new Error("Invalid SimulationSummary");
  }
  if (payload.error !== undefined && payload.error !== null) {
    decodeApplicationError(payload.error);
  }
  return structuredClone(payload) as SimulationSummary;
}

export function decodeStepResponse(value: unknown): StepResponse {
  const payload = object(value, "StepResponse");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision)
  ) {
    throw new Error("Invalid StepResponse");
  }
  const event = decodeSimulationEvent(payload.event);
  const snapshot = decodeSimulationSnapshot(payload.snapshot);
  if (
    event.simulation_id !== payload.simulation_id ||
    snapshot.simulation_id !== payload.simulation_id ||
    event.revision !== payload.revision ||
    snapshot.revision !== payload.revision
  ) {
    throw new Error("StepResponse envelope mismatch");
  }
  return structuredClone(payload) as StepResponse;
}

export function decodeSimulationCreatedResponse(
  value: unknown,
): SimulationCreatedResponse {
  const payload = object(value, "SimulationCreatedResponse");
  const summary = decodeSimulationSummary(payload);
  const snapshot = decodeSimulationSnapshot(payload.snapshot);
  if (snapshot.simulation_id !== summary.simulation_id) {
    throw new Error("SimulationCreatedResponse simulation_id mismatch");
  }
  if (snapshot.revision !== summary.revision) {
    throw new Error("SimulationCreatedResponse revision mismatch");
  }
  if (snapshot.status !== summary.status) {
    throw new Error("SimulationCreatedResponse status mismatch");
  }
  return structuredClone(payload) as SimulationCreatedResponse;
}

export function decodeEventPage(value: unknown): EventPage {
  const payload = object(value, "EventPage");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    !Number.isInteger(payload.offset) ||
    !Number.isInteger(payload.limit) ||
    !Number.isInteger(payload.total) ||
    !Array.isArray(payload.events)
  ) {
    throw new Error("Invalid EventPage");
  }
  const events = payload.events.map(decodeSimulationEvent);
  if (events.some((event) => event.simulation_id !== payload.simulation_id)) {
    throw new Error("EventPage simulation_id mismatch");
  }
  return structuredClone(payload) as EventPage;
}

export function decodeDestinationsResponse(value: unknown): DestinationsResponse {
  const payload = object(value, "DestinationsResponse");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.atom_id) ||
    !Array.isArray(payload.destinations)
  ) {
    throw new Error("Invalid DestinationsResponse");
  }
  for (const item of payload.destinations) {
    const destination = object(item, "DestinationOption");
    if (
      typeof destination.key !== "string" ||
      !["lattice", "interstitial"].includes(String(destination.kind)) ||
      !Array.isArray(destination.coordinate) ||
      !destination.coordinate.every(finiteNumber) ||
      typeof destination.selectable !== "boolean" ||
      !(
        destination.block_code === null ||
        typeof destination.block_code === "string"
      ) ||
      (destination.selectable && destination.block_code !== null) ||
      (!destination.selectable && typeof destination.block_code !== "string")
    ) {
      throw new Error("Invalid DestinationOption");
    }
  }
  return structuredClone(payload) as DestinationsResponse;
}

export function decodePreparationEditPreview(value: unknown): PreparationEditPreview {
  const payload = object(value, "PreparationEditPreview");
  version(payload);
  if (
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision) ||
    Number(payload.revision) < 0 ||
    !["add", "remove", "move", "boundary"].includes(String(payload.action))
  ) {
    throw new Error("Invalid PreparationEditPreview");
  }
  for (const field of ["metrics_before", "metrics_after"] as const) {
    const metrics = object(payload[field], field);
    if (
      !["n_correct", "n_v", "n_i", "n_as", "d"].every(
        (key) => Number.isInteger(metrics[key]) && Number(metrics[key]) >= 0,
      ) ||
      !finiteNumber(metrics.s) ||
      Number(metrics.s) < 0
    ) {
      throw new Error(`Invalid PreparationEditPreview ${field}`);
    }
  }
  for (const field of ["counts_before", "counts_after"] as const) {
    const counts = object(payload[field], field);
    if (
      !["n0", "n_atoms", "n_v", "n_i", "n_as"].every(
        (key) => Number.isInteger(counts[key]) && Number(counts[key]) >= 0,
      )
    ) {
      throw new Error(`Invalid PreparationEditPreview ${field}`);
    }
  }
  return structuredClone(payload) as PreparationEditPreview;
}

export function decodeProjectLoadResponse(value: unknown): ProjectLoadResponse {
  const payload = object(value, "ProjectLoadResponse");
  version(payload);
  if (typeof payload.project_id !== "string" || !Array.isArray(payload.simulations)) {
    throw new Error("Invalid ProjectLoadResponse");
  }
  payload.simulations.map(decodeSimulationSummary);
  return structuredClone(payload) as ProjectLoadResponse;
}

export function decodeProjectStatusList(value: unknown): ProjectStatus[] {
  if (!Array.isArray(value)) throw new Error("ProjectStatus list must be an array");
  return value.map(decodeProjectStatus);
}

export function decodeExperimentResults(value: unknown): ExperimentResults {
  const payload = object(value, "ExperimentResults");
  version(payload);
  if (
    typeof payload.experiment_id !== "string" ||
    !["COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "FAILED"].includes(
      String(payload.status),
    ) ||
    !Array.isArray(payload.successful_runs) ||
    !Array.isArray(payload.failed_runs) ||
    !(payload.aggregate === null || typeof payload.aggregate === "object") ||
    !Number.isInteger(payload.completed_steps) ||
    !Number.isInteger(payload.total_steps) ||
    !Number.isInteger(payload.master_seed) ||
    !Number.isInteger(payload.bootstrap_seed)
  ) {
    throw new Error("Invalid ExperimentResults");
  }
  const decodeSeeds = (value: unknown, name: string) => {
    const seeds = object(value, name);
    if (!Number.isInteger(seeds.seed_init) || !Number.isInteger(seeds.seed_sim)) {
      throw new Error(`Invalid ${name}`);
    }
    return { seed_init: Number(seeds.seed_init), seed_sim: Number(seeds.seed_sim) };
  };
  const decodeMetricPoint = (value: unknown): MetricsPoint => {
    const point = object(value, "Experiment MetricsPoint");
    if (
      !Number.isInteger(point.revision) ||
      !Number.isInteger(point.act_number) ||
      !["initialization", "physical_act", "manual_edit"].includes(String(point.origin)) ||
      !["n_correct", "n_v", "n_i", "n_as", "d"].every(
        (key) => Number.isInteger(point[key]) && Number(point[key]) >= 0,
      ) ||
      !finiteNumber(point.s) || Number(point.s) < 0
    ) {
      throw new Error("Invalid Experiment MetricsPoint");
    }
    return structuredClone(point) as MetricsPoint;
  };
  const successfulRuns = payload.successful_runs.map((value) => {
    const run = object(value, "ExperimentRun");
    if (
      !Number.isInteger(run.run) ||
      !Number.isInteger(run.configuration_index) ||
      typeof run.simulation_id !== "string" ||
      !Array.isArray(run.metrics)
    ) {
      throw new Error("Invalid ExperimentRun");
    }
    const snapshot = decodeSimulationSnapshot(run.snapshot);
    if (snapshot.simulation_id !== run.simulation_id) {
      throw new Error("Invalid ExperimentRun snapshot");
    }
    return {
      run: Number(run.run),
      configuration_index: Number(run.configuration_index),
      simulation_id: run.simulation_id,
      derived_seeds: decodeSeeds(run.derived_seeds, "ExperimentRun derived_seeds"),
      snapshot,
      metrics: run.metrics.map(decodeMetricPoint),
    };
  });
  const failedRuns = payload.failed_runs.map((value) => {
    const run = object(value, "ExperimentFailure");
    if (
      !Number.isInteger(run.run) ||
      !Number.isInteger(run.configuration_index) ||
      typeof run.code !== "string" ||
      typeof run.message !== "string"
    ) {
      throw new Error("Invalid ExperimentFailure");
    }
    return {
      run: Number(run.run),
      configuration_index: Number(run.configuration_index),
      derived_seeds: decodeSeeds(run.derived_seeds, "ExperimentFailure derived_seeds"),
      code: run.code,
      message: run.message,
    };
  });
  const decodeMetricAggregate = (value: unknown): MetricAggregate => {
    const aggregate = object(value, "Experiment aggregate metric");
    if (
      !Number.isInteger(aggregate.count) || Number(aggregate.count) < 1 ||
      !["mean", "minimum", "maximum", "p50", "p95"].every((key) => finiteNumber(aggregate[key])) ||
      !Array.isArray(aggregate.confidence_interval) ||
      aggregate.confidence_interval.length !== 2 ||
      !aggregate.confidence_interval.every(finiteNumber) ||
      typeof aggregate.ci_informative !== "boolean"
    ) {
      throw new Error("Invalid Experiment aggregate metric");
    }
    return structuredClone(aggregate) as MetricAggregate;
  };
  let decodedAggregate: ResearchAggregate | null = null;
  if (payload.aggregate !== null) {
    const aggregate = object(payload.aggregate, "Experiment aggregate");
    version(aggregate);
    const final = object(aggregate.final, "Experiment aggregate final");
    const byAct = object(aggregate.by_act, "Experiment aggregate by_act");
    if (!Number.isInteger(aggregate.bootstrap_seed)) {
      throw new Error("Invalid Experiment aggregate bootstrap_seed");
    }
    decodedAggregate = {
      schema_version: 1,
      bootstrap_seed: Number(aggregate.bootstrap_seed),
      final: Object.fromEntries(Object.entries(final).map(([key, item]) => [key, decodeMetricAggregate(item)])),
      by_act: Object.fromEntries(Object.entries(byAct).map(([act, metrics]) => {
        const group = object(metrics, "Experiment aggregate act");
        return [act, Object.fromEntries(Object.entries(group).map(([key, item]) => [key, decodeMetricAggregate(item)]))];
      })),
    };
  }
  return {
    schema_version: 1,
    experiment_id: payload.experiment_id,
    status: payload.status as ExperimentResults["status"],
    completed_steps: Number(payload.completed_steps),
    total_steps: Number(payload.total_steps),
    successful_runs: successfulRuns,
    failed_runs_details: failedRuns,
    aggregate: decodedAggregate,
    master_seed: Number(payload.master_seed),
    bootstrap_seed: Number(payload.bootstrap_seed),
  };
}

export function decodeStreamMessage(value: unknown): StreamMessage {
  const payload = object(value, "StreamMessage");
  version(payload);
  if (
    !Number.isInteger(payload.message_id) ||
    Number(payload.message_id) < 1 ||
    typeof payload.simulation_id !== "string" ||
    !Number.isInteger(payload.revision)
  ) {
    throw new Error("Invalid StreamMessage envelope");
  }

  let nested:
    SimulationSnapshot | SimulationEvent | SimulationSummary | ApplicationError;
  if (payload.type === "snapshot") {
    nested = decodeSimulationSnapshot(payload.snapshot);
  } else if (payload.type === "event") {
    nested = decodeSimulationEvent(payload.event);
  } else if (payload.type === "status") {
    nested = decodeSimulationSummary(payload.summary);
  } else if (payload.type === "error") {
    nested = decodeApplicationError(payload.error);
  } else {
    throw new Error("Invalid StreamMessage type");
  }

  if (
    "simulation_id" in nested &&
    nested.simulation_id !== null &&
    nested.simulation_id !== undefined &&
    nested.simulation_id !== payload.simulation_id
  ) {
    throw new Error("StreamMessage simulation_id mismatch");
  }
  if (
    "revision" in nested &&
    nested.revision !== null &&
    nested.revision !== undefined &&
    nested.revision !== payload.revision
  ) {
    throw new Error("StreamMessage revision mismatch");
  }
  return structuredClone(payload) as StreamMessage;
}
