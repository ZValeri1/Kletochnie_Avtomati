import {
  decodeStreamMessage,
  decodeSimulationSnapshot,
  decodeStepResponse,
  type ApplicationError,
  type EventPage,
  type MetricsSeries,
  type ProbabilityOverlay,
  type SliceAtlas,
  type SimulationEvent,
  type SimulationSnapshot,
  type SimulationSummary,
  type StreamMessage,
} from "../contracts";

export type SimulationRecord = {
  summary: SimulationSummary;
  current_snapshot: SimulationSnapshot | null;
  last_valid_snapshot: SimulationSnapshot | null;
  events: SimulationEvent[];
  metrics: MetricsSeries;
  overlay: ProbabilityOverlay | null;
  slices: SliceAtlas | null;
  connection_status: "connected" | "disconnected";
  error: Error | ApplicationError | null;
  renderer_error: Error | null;
  controls_enabled: boolean;
  last_message_id: number;
};

export function createSimulationStore() {
  const simulations = new Map<string, SimulationRecord>();

  const ensure = (simulationId: string): SimulationRecord => {
    const current = simulations.get(simulationId);
    if (current) return current;
    const created: SimulationRecord = {
      summary: {
        schema_version: 1,
        simulation_id: simulationId,
        status: "PAUSED",
        revision: 0,
      },
      current_snapshot: null,
      last_valid_snapshot: null,
      events: [],
      metrics: {
        schema_version: 1,
        simulation_id: simulationId,
        revision: 0,
        points: [],
      },
      overlay: null,
      slices: null,
      connection_status: "disconnected",
      error: null,
      renderer_error: null,
      controls_enabled: true,
      last_message_id: 0,
    };
    simulations.set(simulationId, created);
    return created;
  };

  return {
    applySummary(summary: SimulationSummary) {
      const state = ensure(summary.simulation_id);
      if (summary.revision < state.summary.revision) return false;
      state.summary = structuredClone(summary);
      state.controls_enabled = summary.status !== "STOPPED";
      if (summary.status === "RUNNING") state.overlay = null;
      return true;
    },
    applySnapshot(
      payload: unknown,
      options: { allowEqual?: boolean; clearOverlay?: boolean } = {},
    ) {
      let simulationId: string | undefined;
      try {
        const raw = payload as Record<string, unknown>;
        simulationId = typeof raw?.simulation_id === "string" ? raw.simulation_id : undefined;
        const snapshot = decodeSimulationSnapshot(payload);
        const state = ensure(snapshot.simulation_id);
        if (
          state.current_snapshot &&
          (snapshot.revision < state.current_snapshot.revision ||
            (snapshot.revision === state.current_snapshot.revision &&
              !options.allowEqual))
        ) {
          return false;
        }
        state.current_snapshot = structuredClone(snapshot);
        state.last_valid_snapshot = structuredClone(snapshot);
        state.summary = {
          ...state.summary,
          status: snapshot.status,
          revision: snapshot.revision,
        };
        if (options.clearOverlay) {
          state.overlay = null;
        } else if (
          state.overlay &&
          (state.overlay.revision !== snapshot.revision ||
            snapshot.status !== "PAUSED")
        ) {
          state.overlay = null;
        }
        state.error = snapshot.error ? structuredClone(snapshot.error) : null;
        return true;
      } catch (error) {
        if (simulationId) ensure(simulationId).error = error as Error;
        return false;
      }
    },
    applyStreamMessage(payload: unknown, resync = false) {
      let message: StreamMessage;
      try {
        message = decodeStreamMessage(payload);
      } catch (error) {
        const simulationId = (payload as { simulation_id?: unknown })?.simulation_id;
        if (typeof simulationId === "string") ensure(simulationId).error = error as Error;
        return false;
      }
      if (resync && message.type !== "snapshot") return false;
      const state = ensure(message.simulation_id);
      if (!resync && message.message_id <= state.last_message_id) return false;
      state.last_message_id = message.message_id;
      if (
        state.current_snapshot &&
        message.revision < state.current_snapshot.revision
      ) {
        return false;
      }
      if (message.type === "snapshot") {
        return this.applySnapshot(message.snapshot, {
          allowEqual: resync,
          clearOverlay: resync,
        });
      }
      if (message.type === "event") {
        if (!state.events.some((event) => event.event_id === message.event.event_id)) {
          state.events.push(structuredClone(message.event));
          if (!state.metrics.points.some((point) => point.revision === message.event.revision)) {
            state.metrics.points.push({
              ...structuredClone(message.event.metrics_after),
              revision: message.event.revision,
              act_number: message.event.act_number,
              origin: message.event.origin,
            });
            state.metrics.revision = Math.max(
              state.metrics.revision,
              message.event.revision,
            );
          }
        }
        if (
          state.summary.status === "RUNNING" &&
          state.summary.run_mode === "fast" &&
          state.current_snapshot
        ) {
          state.current_snapshot = {
            ...state.current_snapshot,
            revision: message.event.revision,
            metrics: structuredClone(message.event.metrics_after),
          };
          state.summary = {
            ...state.summary,
            revision: message.event.revision,
          };
        }
        return true;
      }
      if (message.type === "status") {
        this.applySummary(message.summary);
        return true;
      }
      state.error = structuredClone(message.error);
      return true;
    },
    applyStepResponse(payload: unknown) {
      const response = decodeStepResponse(payload);
      const applied = this.applySnapshot(response.snapshot, { allowEqual: true });
      const state = ensure(response.simulation_id);
      if (!state.events.some((event) => event.event_id === response.event.event_id)) {
        state.events.push(structuredClone(response.event));
      }
      if (!state.metrics.points.some((point) => point.revision === response.event.revision)) {
        state.metrics.points.push({
          ...structuredClone(response.event.metrics_after),
          revision: response.event.revision,
          act_number: response.event.act_number,
          origin: response.event.origin,
        });
        state.metrics.revision = Math.max(
          state.metrics.revision,
          response.event.revision,
        );
      }
      return applied;
    },
    setEvents(page: EventPage) {
      const state = ensure(page.simulation_id);
      if (
        state.current_snapshot &&
        page.revision < state.current_snapshot.revision
      ) {
        return false;
      }
      state.events = page.events.map((event) => structuredClone(event));
      return true;
    },
    setMetrics(series: MetricsSeries) {
      const state = ensure(series.simulation_id);
      if (
        series.revision < state.metrics.revision ||
        (state.current_snapshot &&
          series.revision < state.current_snapshot.revision)
      ) {
        return false;
      }
      state.metrics = structuredClone(series);
      return true;
    },
    setOverlay(overlay: ProbabilityOverlay) {
      const state = simulations.get(overlay.simulation_id);
      if (
        !state?.current_snapshot ||
        state.current_snapshot.status !== "PAUSED" ||
        state.current_snapshot.revision !== overlay.revision
      ) {
        return false;
      }
      state.overlay = structuredClone(overlay);
      return true;
    },
    clearOverlay(simulationId: string) {
      const state = simulations.get(simulationId);
      if (state) state.overlay = null;
    },
    setSlices(slices: SliceAtlas) {
      const state = ensure(slices.simulation_id);
      if (
        state.current_snapshot &&
        slices.revision < state.current_snapshot.revision
      ) {
        return false;
      }
      state.slices = structuredClone(slices);
      return true;
    },
    addEvent(simulationId: string, event: SimulationEvent) {
      const state = ensure(simulationId);
      if (!state.events.some((current) => current.event_id === event.event_id)) {
        state.events.push(structuredClone(event));
      }
    },
    setConnected(simulationId: string, connected: boolean) {
      const state = simulations.get(simulationId);
      if (!state) return false;
      state.connection_status = connected ? "connected" : "disconnected";
      return true;
    },
    recordRendererFailure(simulationId: string, error: Error) {
      const state = ensure(simulationId);
      state.renderer_error = error;
      state.controls_enabled = true;
    },
    getSimulation(simulationId: string) {
      return ensure(simulationId);
    },
    list() {
      return [...simulations.values()];
    },
    remove(simulationId: string) {
      simulations.delete(simulationId);
    },
  };
}

export type SimulationStore = ReturnType<typeof createSimulationStore>;
