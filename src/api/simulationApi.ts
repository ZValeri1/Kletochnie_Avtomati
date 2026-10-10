import {
  decodeApplicationError,
  decodeDestinationsResponse,
  decodeEventPage,
  decodeExperimentResults,
  decodeExperimentStatus,
  decodeMetricsSeries,
  decodeProbabilityOverlay,
  decodePreparationEditPreview,
  decodeProjectLoadResponse,
  decodeProjectStatus,
  decodeProjectStatusList,
  decodeSimulationCreatedResponse,
  decodeSimulationSnapshot,
  decodeSimulationSummary,
  decodeStepResponse,
  type ApplicationError,
  type DestinationsResponse,
  type EventPage,
  type ExperimentResults,
  type ExperimentStatus,
  type MetricsSeries,
  type ProbabilityOverlay,
  type PreparationEditPreview,
  type ProjectLoadResponse,
  type ProjectStatus,
  type SimulationCreatedResponse,
  type SimulationSnapshot,
  type SimulationSummary,
  type StepResponse,
} from "../contracts";

export class ApplicationRequestError extends Error {
  constructor(
    public readonly applicationError: ApplicationError,
    public readonly status = 500,
  ) {
    super(requestErrorMessage(applicationError));
    this.name = "ApplicationRequestError";
  }
}

const requestErrorMessage = (error: ApplicationError) => {
  const validationErrors = Array.isArray(error.details?.errors)
    ? (error.details.errors as Array<Record<string, unknown>>)
    : [];
  if (error.code !== "VALIDATION_ERROR" || validationErrors.length === 0) {
    return error.message;
  }
  const formatted = validationErrors.slice(0, 3).map((item) => {
    const location = Array.isArray(item.loc)
      ? item.loc.filter((part) => part !== "body").join(".")
      : "параметр";
    return `${location}: ${String(item.msg ?? "некорректное значение")}`;
  });
  const versionMismatch = validationErrors.some(
    (item) => item.type === "extra_forbidden",
  );
  return `${error.message}: ${formatted.join("; ")}.${
    versionMismatch
      ? " Сервер не поддерживает поля интерфейса — перезапустите сервер приложения."
      : ""
  }`;
};

type RequestOptions<T> = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  decode: (payload: unknown) => T;
};

const requestJson = async <T>(
  path: string,
  { method = "GET", body, decode }: RequestOptions<T>,
): Promise<T> => {
  const response = await fetch(path, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    try {
      throw new ApplicationRequestError(
        decodeApplicationError(payload),
        response.status,
      );
    } catch (error) {
      if (error instanceof ApplicationRequestError) throw error;
      const record = payload as { message?: unknown; detail?: unknown } | null;
      throw new Error(
        String(record?.message ?? record?.detail ?? "Request failed"),
      );
    }
  }
  return decode(payload);
};

const revisionBody = (expectedRevision: number) => ({
  schema_version: 1 as const,
  expected_revision: expectedRevision,
});

export type SimulationSubscription = { close: () => void };

export type InitializationMode =
  "ordered" | "random_defective" | "explicit_defective" | "symmetric_defective";

export type OperationWeightsInput = Partial<{
  lattice_vacancy: number;
  lattice_interstitial: number;
  interstitial_vacancy_r1: number;
  interstitial_vacancy_r2: number;
  interstitial_interstitial: number;
  boundary_external: number;
  external_external: number;
  external_interstitial: number;
  interstitial_external: number;
  external_metal: number;
  shell_r1: number;
  shell_r2: number;
  vacancy: number;
  interstitial: number;
  external: number;
  from_lattice_vacancy: number;
  from_lattice_interstitial: number;
  from_lattice_shell_r1: number;
  from_lattice_shell_r2: number;
  from_lattice_inside: number;
  from_lattice_outside: number;
  from_interstitial_vacancy: number;
  from_interstitial_interstitial: number;
  from_interstitial_shell_r1: number;
  from_interstitial_shell_r2: number;
  from_interstitial_inside: number;
  from_interstitial_outside: number;
}>;

export type SimulationCreateInput = {
  dimensions: number[];
  initialization_mode: InitializationMode;
  n_v: number;
  n_i: number;
  n_as: number;
  random_parameters?: Record<string, { mu: number; sigma: number }>;
  contour?: [number, number][] | null;
  seed_init: number;
  seed_sim: number;
  profile?: "fe_co60_physical";
  method?: "monte_carlo" | "cellular_automata";
  q_max_ev: number;
  q_thr_ev: number;
  weights: OperationWeightsInput;
};

export type ConfigurationPatchInput = Partial<SimulationCreateInput>;

export type PreparationEditInput =
  | { action: "add"; destination_key: string }
  | { action: "remove"; atom_id: number }
  | { action: "move"; atom_id: number; destination_key: string }
  | { action: "boundary"; contour: [number, number][] };

export const simulationApi = {
  create(
    configuration: SimulationCreateInput,
  ): Promise<SimulationCreatedResponse> {
    return requestJson("/api/simulations", {
      method: "POST",
      body: { schema_version: 1, ...configuration },
      decode: decodeSimulationCreatedResponse,
    });
  },
  snapshot(simulationId: string): Promise<SimulationSnapshot> {
    return requestJson(`/api/simulations/${simulationId}/snapshot`, {
      decode: decodeSimulationSnapshot,
    });
  },
  step(simulationId: string, revision: number): Promise<StepResponse> {
    return requestJson(`/api/simulations/${simulationId}/step`, {
      method: "POST",
      body: revisionBody(revision),
      decode: decodeStepResponse,
    });
  },
  configure(
    simulationId: string,
    revision: number,
    patch: ConfigurationPatchInput,
  ) {
    return requestJson(`/api/simulations/${simulationId}/configuration`, {
      method: "PATCH",
      body: { schema_version: 1, expected_revision: revision, ...patch },
      decode: decodeStepResponse,
    });
  },
  edit(simulationId: string, revision: number, edit: PreparationEditInput) {
    return requestJson(`/api/simulations/${simulationId}/edit`, {
      method: "POST",
      body: { schema_version: 1, expected_revision: revision, ...edit },
      decode: decodeStepResponse,
    });
  },
  previewEdit(
    simulationId: string,
    revision: number,
    edit: PreparationEditInput,
  ): Promise<PreparationEditPreview> {
    return requestJson(`/api/simulations/${simulationId}/edit/preview`, {
      method: "POST",
      body: { schema_version: 1, expected_revision: revision, ...edit },
      decode: decodePreparationEditPreview,
    });
  },
  summaryCommand(
    simulationId: string,
    command: "start" | "pause" | "stop" | "error/acknowledge",
    revision: number,
  ): Promise<SimulationSummary> {
    return requestJson(`/api/simulations/${simulationId}/${command}`, {
      method: "POST",
      body: revisionBody(revision),
      decode: decodeSimulationSummary,
    });
  },
  run(
    simulationId: string,
    revision: number,
    mode: "visual" | "fast",
    intervalMs: number,
  ): Promise<SimulationSummary> {
    return requestJson(`/api/simulations/${simulationId}/run`, {
      method: "POST",
      body: {
        schema_version: 1,
        expected_revision: revision,
        mode,
        interval_ms: intervalMs,
      },
      decode: decodeSimulationSummary,
    });
  },
  snapshotCommand(
    simulationId: string,
    command: "undo" | "redo" | "reset",
    revision: number,
  ): Promise<SimulationSnapshot> {
    return requestJson(`/api/simulations/${simulationId}/${command}`, {
      method: "POST",
      body: revisionBody(revision),
      decode: decodeSimulationSnapshot,
    });
  },
  retry(simulationId: string, revision: number): Promise<StepResponse> {
    return requestJson(`/api/simulations/${simulationId}/error/retry`, {
      method: "POST",
      body: revisionBody(revision),
      decode: decodeStepResponse,
    });
  },
  diagnose(simulationId: string, atomId: number, qTest: number) {
    return requestJson(
      `/api/simulations/${simulationId}/diagnostics/probabilities`,
      {
        method: "POST",
        body: { schema_version: 1, atom_id: atomId, q_test: qTest },
        decode: decodeProbabilityOverlay,
      },
    );
  },
  destinations(
    simulationId: string,
    atomId: number,
  ): Promise<DestinationsResponse> {
    return requestJson(
      `/api/simulations/${simulationId}/atoms/${atomId}/destinations`,
      {
        decode: decodeDestinationsResponse,
      },
    );
  },
  events(simulationId: string): Promise<EventPage> {
    return requestJson(`/api/simulations/${simulationId}/events?limit=500`, {
      decode: decodeEventPage,
    });
  },
  metrics(simulationId: string): Promise<MetricsSeries> {
    return requestJson(`/api/simulations/${simulationId}/metrics`, {
      decode: decodeMetricsSeries,
    });
  },
  listProjects(): Promise<ProjectStatus[]> {
    return requestJson("/api/projects", { decode: decodeProjectStatusList });
  },
  saveProject(projectId: string, simulationIds: string[], overwrite = false) {
    return requestJson(`/api/projects/${encodeURIComponent(projectId)}/save`, {
      method: "POST",
      body: { schema_version: 1, simulation_ids: simulationIds, overwrite },
      decode: decodeProjectStatus,
    });
  },
  loadProject(projectId: string): Promise<ProjectLoadResponse> {
    return requestJson(`/api/projects/${encodeURIComponent(projectId)}/load`, {
      method: "POST",
      body: { schema_version: 1 },
      decode: decodeProjectLoadResponse,
    });
  },
  deleteProject(projectId: string) {
    return requestJson(
      `/api/projects/${encodeURIComponent(projectId)}?confirm=true`,
      {
        method: "DELETE",
        decode: decodeProjectStatus,
      },
    );
  },
  createExperiment(
    configuration: Record<string, unknown>,
  ): Promise<ExperimentStatus> {
    return requestJson("/api/experiments", {
      method: "POST",
      body: { schema_version: 1, ...configuration },
      decode: decodeExperimentStatus,
    });
  },
  experimentStatus(experimentId: string): Promise<ExperimentStatus> {
    return requestJson(`/api/experiments/${experimentId}`, {
      decode: decodeExperimentStatus,
    });
  },
  cancelExperiment(experimentId: string): Promise<ExperimentStatus> {
    return requestJson(`/api/experiments/${experimentId}/cancel`, {
      method: "POST",
      body: { schema_version: 1 },
      decode: decodeExperimentStatus,
    });
  },
  experimentResults(experimentId: string): Promise<ExperimentResults> {
    return requestJson(`/api/experiments/${experimentId}/results`, {
      decode: decodeExperimentResults,
    });
  },
  async journal(simulationId: string): Promise<Blob> {
    const response = await fetch(
      `/api/simulations/${simulationId}/journal.json`,
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new ApplicationRequestError(
        decodeApplicationError(payload),
        response.status,
      );
    }
    return response.blob();
  },
  async remove(simulationId: string, revision: number): Promise<void> {
    const response = await fetch(
      `/api/simulations/${simulationId}?expected_revision=${revision}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new ApplicationRequestError(
        decodeApplicationError(payload),
        response.status,
      );
    }
  },
  subscribe(
    simulationId: string,
    onMessage: (message: Record<string, unknown>, resync: boolean) => void,
    onConnectionChange: (connected: boolean) => void = () => undefined,
  ): SimulationSubscription {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${location.host}/ws/simulations/${simulationId}`;
    let stopped = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let socket: WebSocket | undefined;
    let attempt = 0;

    const connect = () => {
      if (stopped) return;
      let awaitingSnapshot = true;
      socket = new WebSocket(url);
      socket.onopen = () => {
        attempt = 0;
        onConnectionChange(true);
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as Record<string, unknown>;
        const resync = awaitingSnapshot && message.type === "snapshot";
        onMessage(message, resync);
        if (resync) awaitingSnapshot = false;
      };
      socket.onclose = () => {
        onConnectionChange(false);
        if (!stopped) {
          const delay = Math.min(8_000, 500 * 2 ** attempt);
          attempt += 1;
          reconnectTimer = setTimeout(connect, delay);
        }
      };
    };
    connect();
    return {
      close() {
        stopped = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        socket?.close();
      },
    };
  },
};
