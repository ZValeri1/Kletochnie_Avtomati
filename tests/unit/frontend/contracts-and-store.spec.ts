import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const fixture = (name: string) =>
  JSON.parse(
    readFileSync(
      resolve(import.meta.dirname, "../../contract/fixtures", name),
      "utf8",
    ),
  );

test("shared DTO fixtures are decoded by the frontend contracts", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const contracts = await import(modulePath);

  expect(
    contracts.decodeSimulationSnapshot(fixture("simulation_snapshot.json")),
  ).toMatchObject({ simulation_id: "sim-a", revision: 3 });
  expect(
    contracts.decodeSimulationEvent(fixture("simulation_event.json")),
  ).toMatchObject({ event_id: "event-3" });
  expect(
    contracts.decodeApplicationError(fixture("application_error.json")),
  ).toMatchObject({ code: "REVISION_CONFLICT" });
  expect(
    contracts.decodeProbabilityOverlay(fixture("probability_overlay.json")),
  ).toMatchObject({
    atom_id: 1,
    outcomes: [{ selectable: true }, { selectable: false }],
  });
  expect(
    contracts.decodeMetricsSeries(fixture("metrics_series.json")),
  ).toMatchObject({
    revision: 3,
    points: [{ origin: "initialization" }, { revision: 3 }],
  });
  expect(
    contracts.decodePreparationEditPreview(
      fixture("preparation_edit_preview.json"),
    ),
  ).toMatchObject({
    action: "move",
    revision: 3,
    counts_after: { n_v: 1, n_i: 1 },
  });
  expect(contracts.decodeSliceAtlas(fixture("slice_atlas.json"))).toMatchObject(
    { axis: "z", slices: [{ sites: [{ atom_id: 0 }] }] },
  );
  expect(contracts.decodeProjectStatus(fixture("project_status.json"))).toEqual(
    {
      schema_version: 1,
      project_id: "project-a",
      status: "AVAILABLE",
      simulation_count: 2,
      created_at: "2026-09-27T12:00:00+00:00",
      updated_at: "2026-09-27T12:30:00+00:00",
      history_truncated: false,
    },
  );
  expect(
    contracts.decodeExperimentStatus(fixture("experiment_status.json")),
  ).toMatchObject({
    experiment_id: "experiment-a",
    status: "RUNNING",
    completed_steps: 4,
  });
});

test("websocket envelopes reuse the shared snapshot and event decoders", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeStreamMessage } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");

  expect(
    decodeStreamMessage({
      schema_version: 1,
      message_id: 10,
      simulation_id: snapshot.simulation_id,
      revision: snapshot.revision,
      type: "snapshot",
      snapshot,
    }),
  ).toMatchObject({ type: "snapshot", snapshot: { revision: 3 } });
  expect(
    decodeStreamMessage({
      schema_version: 1,
      message_id: 11,
      simulation_id: event.simulation_id,
      revision: event.revision,
      type: "event",
      event,
    }),
  ).toMatchObject({ type: "event", event: { event_id: "event-3" } });
});

test("frontend contracts reject an unknown schema version", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationSnapshot } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");

  expect(() =>
    decodeSimulationSnapshot({ ...snapshot, schema_version: 999 }),
  ).toThrow(/schema_version/i);
});

test("destination contracts keep server selectability and block reasons", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeDestinationsResponse } = await import(modulePath);
  const response = {
    schema_version: 1,
    simulation_id: "sim-a",
    atom_id: 1,
    destinations: [
      { key: "lattice:1,1", kind: "lattice", coordinate: [1, 1], selectable: true, block_code: null },
      { key: "lattice:2,2", kind: "lattice", coordinate: [2, 2], selectable: false, block_code: "SITE_OCCUPIED" },
    ],
  };

  expect(decodeDestinationsResponse(response).destinations).toEqual(response.destinations);
  expect(() => decodeDestinationsResponse({
    ...response,
    destinations: [{ ...response.destinations[1], block_code: null }],
  })).toThrow(/DestinationOption/);
});

test("event decoder rejects missing physical weights", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationEvent } = await import(modulePath);
  const event = fixture("simulation_event.json");

  expect(() =>
    decodeSimulationEvent({ ...event, operation_weight: undefined }),
  ).toThrow(/event/i);
  expect(() => decodeSimulationEvent({ ...event, q_thr: undefined })).toThrow(
    /event/i,
  );
});

test("probability decoder rejects removed operation names", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeProbabilityOverlay } = await import(modulePath);
  const overlay = fixture("probability_overlay.json");

  expect(() =>
    decodeProbabilityOverlay({
      ...overlay,
      outcomes: [{ ...overlay.outcomes[0], operation: "swap" }],
    }),
  ).toThrow(/outcome/i);
});

test("application error decoder requires recovery metadata", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeApplicationError } = await import(modulePath);
  const applicationError = fixture("application_error.json");

  expect(() =>
    decodeApplicationError({ ...applicationError, recoverable: undefined }),
  ).toThrow(/applicationerror/i);
});

test("simulation summary decoder validates nested recovery metadata", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationSummary } = await import(modulePath);

  expect(() => decodeSimulationSummary({
    schema_version: 1,
    simulation_id: "sim-a",
    status: "PAUSED_WITH_ERROR",
    revision: 3,
    seed_init: 11,
    seed_sim: 12,
    source_project_id: null,
    source_simulation_id: null,
    error: {
      schema_version: 1,
      code: "TEMPORARY_FAILURE",
      message: "retry",
      details: {},
    },
  })).toThrow(/ApplicationError/i);
});

test("created simulation decoder rejects a snapshot from another revision", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationCreatedResponse } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");

  expect(() => decodeSimulationCreatedResponse({
    schema_version: 1,
    simulation_id: snapshot.simulation_id,
    status: snapshot.status,
    revision: snapshot.revision + 1,
    snapshot,
  })).toThrow(/revision/i);
});

test("created simulation decoder rejects a snapshot with another status", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationCreatedResponse } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");

  expect(() => decodeSimulationCreatedResponse({
    schema_version: 1,
    simulation_id: snapshot.simulation_id,
    status: "RUNNING",
    revision: snapshot.revision,
    snapshot,
  })).toThrow(/status/i);
});

test("snapshot decoder rejects missing mandatory physical fields", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationSnapshot } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const atomWithoutKind = { ...snapshot.atoms[0] };
  delete atomWithoutKind.site_kind;

  expect(() =>
    decodeSimulationSnapshot({
      ...snapshot,
      atoms: [atomWithoutKind, ...snapshot.atoms.slice(1)],
    }),
  ).toThrow(/atom/i);
  expect(() =>
    decodeSimulationSnapshot({ ...snapshot, phase: undefined }),
  ).toThrow();
  expect(() =>
    decodeSimulationSnapshot({ ...snapshot, status: "BROKEN" }),
  ).toThrow(/snapshot/i);
  expect(() =>
    decodeSimulationSnapshot({ ...snapshot, configuration: undefined }),
  ).toThrow(/configuration/i);
  expect(() =>
    decodeSimulationSnapshot({
      ...snapshot,
      history_capabilities: { can_undo: true, can_redo: false },
    }),
  ).toThrow(/history/i);
});

test("snapshot decoder validates nested configuration geometry and errors", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationSnapshot } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");

  expect(() => decodeSimulationSnapshot({
    ...snapshot,
    configuration: { ...snapshot.configuration, contour: [[0, 0], [1]] },
  })).toThrow(/configuration/i);
  expect(() => decodeSimulationSnapshot({
    ...snapshot,
    configuration: {
      ...snapshot.configuration,
      random_parameters: { vacancies: { mu: 1 } },
    },
  })).toThrow(/configuration/i);
  expect(() => decodeSimulationSnapshot({
    ...snapshot,
    error: {
      schema_version: 1,
      code: "TEMPORARY_FAILURE",
      message: "retry",
      details: {},
    },
  })).toThrow(/ApplicationError/i);
});

test("snapshot decoder rejects values outside backend numeric bounds", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationSnapshot } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");

  expect(() => decodeSimulationSnapshot({
    ...snapshot,
    metrics: { ...snapshot.metrics, n_v: -1 },
  })).toThrow(/metrics/i);
  expect(() => decodeSimulationSnapshot({
    ...snapshot,
    configuration: { ...snapshot.configuration, q_thr_ev: -1 },
  })).toThrow(/configuration/i);
  expect(() => decodeSimulationSnapshot({
    ...snapshot,
    configuration: {
      ...snapshot.configuration,
      weights: { ...snapshot.configuration.weights, external_metal: 1.01 },
    },
  })).toThrow(/configuration/i);
});

test("event decoder validates coordinates and metric categories", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationEvent } = await import(modulePath);
  const event = fixture("simulation_event.json");

  expect(() => decodeSimulationEvent({
    ...event,
    source_coordinate: [1],
  })).toThrow(/coordinate/i);
  expect(() => decodeSimulationEvent({
    ...event,
    metrics_after: { ...event.metrics_after, n_v: -1 },
  })).toThrow(/metrics/i);
});

test("event decoder rejects impossible probabilities and energies", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeSimulationEvent } = await import(modulePath);
  const event = fixture("simulation_event.json");

  expect(() => decodeSimulationEvent({
    ...event,
    probability: 1.01,
  })).toThrow(/event/i);
  expect(() => decodeSimulationEvent({
    ...event,
    q_n: -0.01,
  })).toThrow(/event/i);
});

test("probability overlay decoder rejects weights outside the public contract", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeProbabilityOverlay } = await import(modulePath);
  const overlay = fixture("probability_overlay.json");

  expect(() => decodeProbabilityOverlay({
    ...overlay,
    outcomes: [{ ...overlay.outcomes[0], total_weight: -0.01 }],
  })).toThrow(/outcome/i);
  expect(() => decodeProbabilityOverlay({
    ...overlay,
    outcomes: [{ ...overlay.outcomes[0], probability: 1.01 }],
  })).toThrow(/outcome/i);
});

test("metrics series decoder rejects negative structural categories", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeMetricsSeries } = await import(modulePath);
  const metrics = fixture("metrics_series.json");

  expect(() => decodeMetricsSeries({
    ...metrics,
    points: [{ ...metrics.points[0], n_as: -1 }],
  })).toThrow(/MetricsPoint/i);
});

test("experiment result decoder validates runs and statistical aggregates", async () => {
  const modulePath = "../../../src/contracts/index.ts";
  const { decodeExperimentResults } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const metrics = fixture("metrics_series.json");
  const metricAggregate = {
    count: 2,
    mean: 1,
    minimum: 0,
    maximum: 2,
    p50: 1,
    p95: 1.9,
    confidence_interval: [0.5, 1.5],
    ci_informative: true,
  };
  const payload = {
    schema_version: 1,
    experiment_id: "experiment-a",
    status: "COMPLETED",
    completed_steps: 3,
    total_steps: 3,
    successful_runs: [{
      run: 0,
      configuration_index: 0,
      simulation_id: "sim-a",
      derived_seeds: { seed_init: 11, seed_sim: 12 },
      snapshot,
      metrics: metrics.points,
    }],
    failed_runs: [],
    aggregate: {
      schema_version: 1,
      bootstrap_seed: 99,
      final: { d: metricAggregate },
      by_act: { "3": { d: metricAggregate } },
    },
    master_seed: 42,
    bootstrap_seed: 99,
  };

  expect(decodeExperimentResults(payload)).toMatchObject({
    successful_runs: [{ simulation_id: "sim-a" }],
    aggregate: { final: { d: { count: 2 } } },
  });
  expect(() => decodeExperimentResults({
    ...payload,
    aggregate: {
      ...payload.aggregate,
      final: { d: { ...metricAggregate, confidence_interval: [0.5] } },
    },
  })).toThrow(/aggregate/i);
});

test("snapshot mapper creates dimension-specific renderer frames", async () => {
  const modulePath = "../../../src/rendering/common/snapshotMapper.ts";
  const { mapSnapshotToRenderFrame } = await import(modulePath);
  const twoDimensional = fixture("simulation_snapshot.json");
  const threeDimensional = {
    ...twoDimensional,
    simulation_id: "sim-3d",
    dimensions: [9, 9, 9],
    configuration: {
      ...twoDimensional.configuration,
      dimensions: [3, 3, 3],
      field_dimensions: [9, 9, 9],
    },
    atoms: [
      {
        id: 0,
        site_key: "lattice:0,0,0",
        coordinate: [0, 0, 0],
        site_kind: "lattice",
        metal_relation: "boundary",
        visual_state: "boundary",
      },
    ],
  };

  const frame2d = mapSnapshotToRenderFrame(twoDimensional);
  const frame3d = mapSnapshotToRenderFrame(threeDimensional);

  expect(frame2d.mode).toBe("2d");
  expect(frame2d.atoms[0].coordinate).toHaveLength(2);
  expect(frame3d.mode).toBe("3d");
  expect(frame3d.atoms[0].coordinate).toHaveLength(3);
});

test("invalid or stale snapshot does not replace the last valid snapshot", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const valid = fixture("simulation_snapshot.json");

  store.applySnapshot(valid);
  store.applySnapshot({ ...valid, revision: 2 });
  store.applySnapshot({ ...valid, revision: 4, metrics: undefined });

  const state = store.getSimulation("sim-a");
  expect(state.current_snapshot.revision).toBe(3);
  expect(state.last_valid_snapshot.revision).toBe(3);
  expect(state.error).toBeTruthy();
});

test("a snapshot updates only its own simulation state", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const left = fixture("simulation_snapshot.json");
  const right = { ...left, simulation_id: "sim-b", revision: 1 };
  store.applySnapshot(left);
  store.applySnapshot(right);

  store.applySnapshot({ ...left, revision: 4 });

  expect(store.getSimulation("sim-a").current_snapshot.revision).toBe(4);
  expect(store.getSimulation("sim-b").current_snapshot.revision).toBe(1);
});

test("a fast-mode event advances the visible act without waiting for a snapshot", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const paused = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");

  store.applySnapshot(paused);
  store.applySummary({
    schema_version: 1,
    simulation_id: paused.simulation_id,
    status: "RUNNING",
    revision: paused.revision + 1,
    run_mode: "fast",
  });
  store.applySnapshot(
    {
      ...paused,
      status: "RUNNING",
      revision: paused.revision + 1,
    },
    { allowEqual: true },
  );

  const fastEvent = {
    ...event,
    event_id: "fast-event-12",
    revision: paused.revision + 8,
    act_number: event.act_number + 8,
    metrics_after: {
      n_correct: 12,
      n_v: 2,
      n_i: 1,
      n_as: 1,
      d: 4,
      s: 0.75,
    },
  };
  expect(
    store.applyStreamMessage({
      schema_version: 1,
      message_id: 12,
      simulation_id: paused.simulation_id,
      revision: fastEvent.revision,
      type: "event",
      event: fastEvent,
    }),
  ).toBe(true);

  const state = store.getSimulation(paused.simulation_id);
  expect(state.current_snapshot).toMatchObject({
    status: "RUNNING",
    revision: fastEvent.revision,
    metrics: fastEvent.metrics_after,
  });
  expect(state.summary).toMatchObject({
    status: "RUNNING",
    revision: fastEvent.revision,
    run_mode: "fast",
  });
  expect(state.metrics.points.at(-1)).toMatchObject({
    revision: fastEvent.revision,
    act_number: fastEvent.act_number,
    ...fastEvent.metrics_after,
  });
});

test("renderer failure preserves controls and the last valid snapshot", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  store.applySnapshot(snapshot);

  store.recordRendererFailure("sim-a", new Error("WebGL unavailable"));

  const state = store.getSimulation("sim-a");
  expect(state.last_valid_snapshot).toEqual(snapshot);
  expect(state.summary.status).toBe("PAUSED");
  expect(state.controls_enabled).toBe(true);
  expect(state.renderer_error.message).toContain("WebGL unavailable");
});
