import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const fixture = (name: string) =>
  JSON.parse(
    readFileSync(
      resolve(import.meta.dirname, "../../contract/fixtures", name),
      "utf8",
    ),
  );

test("the configuration form starts from the selected server configuration", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const { decodeSimulationSnapshot } = await import(contractsPath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { ConfigurationEditor } = await vite.ssrLoadModule(
    "/src/configuration/ConfigurationEditor.tsx",
  );
  const source = fixture("simulation_snapshot.json");
  const snapshot = decodeSimulationSnapshot({
    ...source,
    status: "PREPARATION",
    phase: "PREPARATION",
    config_locked: false,
    configuration: {
      ...source.configuration,
      initialization_mode: "explicit_defective",
      n_v: 2,
      n_i: 1,
      seed_init: 101,
      seed_sim: 202,
      q_thr_ev: 37,
    },
  });

  const markup = renderToStaticMarkup(
    createElement(ConfigurationEditor, {
      currentSnapshot: snapshot,
      onCreate: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toMatch(/data-testid="seed-init"[^>]*value="101"/);
  expect(markup).toMatch(/data-testid="seed-sim"[^>]*value="202"/);
  expect(markup).toMatch(/data-testid="q-threshold"[^>]*value="37"/);
  expect(markup).toMatch(/data-testid="initial-vacancies"[^>]*value="2"/);
});

test("a locked configuration exposes every server parameter as read-only data", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const { decodeSimulationSnapshot } = await import(contractsPath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { ConfigurationEditor } = await vite.ssrLoadModule(
    "/src/configuration/ConfigurationEditor.tsx",
  );
  const source = fixture("simulation_snapshot.json");
  const snapshot = decodeSimulationSnapshot({
    ...source,
    configuration: {
      ...source.configuration,
      initialization_mode: "random_defective",
      n_v: 3,
      n_i: 2,
      n_as: 1,
      random_parameters: {
        vacancies: { mu: 1.25, sigma: 0.4 },
        interstitials: { mu: 0.75, sigma: 0.3 },
        adatoms: { mu: 0.5, sigma: 0.2 },
      },
    },
  });

  const markup = renderToStaticMarkup(
    createElement(ConfigurationEditor, {
      currentSnapshot: snapshot,
      onCreate: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toMatch(/data-testid="locked-count-n-v"[^>]*>3</);
  expect(markup).toMatch(/data-testid="locked-count-n-i"[^>]*>2</);
  expect(markup).toMatch(/data-testid="locked-count-n-as"[^>]*>1</);
  expect(markup).toMatch(
    /data-testid="locked-random-vacancies"[^>]*>[^<]*1[,.]25[^<]*0[,.]4/,
  );
  expect(markup).toMatch(/Вероятности переходов/);
  expect(markup).toMatch(
    /data-testid="locked-weight-from-lattice-vacancy"[^>]*>0[,.]8</,
  );
  expect(markup).toMatch(
    /data-testid="locked-weight-from-lattice-shell-r2"[^>]*>0[,.]25</,
  );
  expect(markup).toMatch(
    /data-testid="locked-weight-from-interstitial-vacancy"[^>]*>0[,.]8</,
  );
  expect(markup).toMatch(
    /data-testid="locked-weight-from-interstitial-shell-r2"[^>]*>0[,.]25</,
  );
  expect(markup).toContain('data-testid="locked-field-dimensions"');
  expect(markup).toContain('data-testid="locked-profile"');
});

test("the probability editor exposes separate defaults for lattice and interstitial sources", async () => {
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { ConfigurationEditor } = await vite.ssrLoadModule(
    "/src/configuration/ConfigurationEditor.tsx",
  );

  const markup = renderToStaticMarkup(
    createElement(ConfigurationEditor, {
      onCreate: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toContain("Начальная позиция: узел");
  expect(markup).toContain("Начальная позиция: межузел");
  for (const source of ["lattice", "interstitial"]) {
    expect(markup).toMatch(
      new RegExp(
        `data-testid="weight-from-${source}-vacancy"[^>]*value="0[.,]8"`,
      ),
    );
    expect(markup).toMatch(
      new RegExp(
        `data-testid="weight-from-${source}-interstitial"[^>]*value="0[.,]2"`,
      ),
    );
    expect(markup).toMatch(
      new RegExp(
        `data-testid="weight-from-${source}-shell-r1"[^>]*value="0[.,]75"`,
      ),
    );
    expect(markup).toMatch(
      new RegExp(
        `data-testid="weight-from-${source}-shell-r2"[^>]*value="0[.,]25"`,
      ),
    );
    expect(markup).toMatch(
      new RegExp(
        `data-testid="weight-from-${source}-inside"[^>]*value="0[.,]95"`,
      ),
    );
    expect(markup).toMatch(
      new RegExp(
        `data-testid="weight-from-${source}-outside"[^>]*value="0[.,]05"`,
      ),
    );
  }
});

test("the 3D structure editor keeps atom actions visible and explains the boundary limitation", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const capabilitiesPath = "../../../src/simulations/capabilities.ts";
  const { decodeSimulationSnapshot } = await import(contractsPath);
  const { commandAvailability } = await import(capabilitiesPath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { StructureEditor } = await vite.ssrLoadModule(
    "/src/structure/StructureEditor.tsx",
  );
  const source = fixture("simulation_snapshot.json");
  const snapshot = decodeSimulationSnapshot({
    ...source,
    status: "PREPARATION",
    phase: "PREPARATION",
    config_locked: false,
    dimensions: [12, 12, 12],
    configuration: {
      ...source.configuration,
      dimensions: [4, 4, 4],
      field_dimensions: [12, 12, 12],
    },
    atoms: source.atoms.map((atom: { coordinate: number[] }) => ({
      ...atom,
      coordinate: [...atom.coordinate, 0],
    })),
  });

  const markup = renderToStaticMarkup(
    createElement(StructureEditor, {
      snapshot,
      availability: commandAvailability(
        "PREPARATION",
        snapshot.history_capabilities,
      ),
      selectedAtomId: 0,
      destinations: [
        {
          key: "lattice:2,3,4",
          kind: "lattice",
          coordinate: [2, 3, 4],
          selectable: true,
          block_code: null,
        },
      ],
      pending: false,
      error: "",
      onSelectAtom: () => undefined,
      onEdit: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toContain('data-testid="add-atom"');
  expect(markup).toContain('data-testid="remove-atom"');
  expect(markup).toContain('data-testid="move-atom"');
  expect(markup).toMatch(/data-testid="boundary-contour"[^>]*disabled/);
  expect(markup).toContain('data-testid="boundary-blocked-3d"');
});

test("a pending manual edit keeps the server snapshot visible and shows the last confirmed before/after metrics", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const capabilitiesPath = "../../../src/simulations/capabilities.ts";
  const { decodeSimulationEvent, decodeSimulationSnapshot } = await import(
    contractsPath
  );
  const { commandAvailability } = await import(capabilitiesPath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { StructureEditor } = await vite.ssrLoadModule(
    "/src/structure/StructureEditor.tsx",
  );
  const snapshot = decodeSimulationSnapshot(
    fixture("simulation_snapshot.json"),
  );
  const sourceEvent = fixture("simulation_event.json");
  const lastEdit = decodeSimulationEvent({
    ...sourceEvent,
    event_id: "manual-3",
    operation: "manual_edit",
    origin: "manual_edit",
    q_n: null,
    q_thr: null,
    metrics_before: { n_correct: 14, n_v: 2, n_i: 1, n_as: 0, d: 3, s: 0.5 },
    metrics_after: { n_correct: 14, n_v: 2, n_i: 0, n_as: 1, d: 3, s: 0.6 },
  });

  const markup = renderToStaticMarkup(
    createElement(StructureEditor, {
      snapshot,
      availability: commandAvailability(
        "PAUSED",
        snapshot.history_capabilities,
      ),
      selectedAtomId: 0,
      destinations: [
        {
          key: "lattice:2,3",
          kind: "lattice",
          coordinate: [2, 3],
          selectable: true,
          block_code: null,
        },
      ],
      lastEdit,
      pending: true,
      error: "",
      onSelectAtom: () => undefined,
      onEdit: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toMatch(/data-testid="structure-editor"[^>]*aria-busy="true"/);
  expect(markup).toContain("#0 · lattice:0,0");
  expect(markup).toMatch(/data-testid="move-atom"[^>]*disabled/);
  expect(markup).toContain('data-testid="manual-edit-comparison"');
  expect(markup).toMatch(/data-testid="manual-before-n-atoms"[^>]*>15</);
  expect(markup).toMatch(/data-testid="manual-before-n-i"[^>]*>1</);
  expect(markup).toMatch(/data-testid="manual-after-n-i"[^>]*>0</);
  expect(markup).toMatch(/data-testid="manual-after-n-as"[^>]*>1</);
});

test("the structure editor presents the server preview before a manual move", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const capabilitiesPath = "../../../src/simulations/capabilities.ts";
  const { decodeSimulationSnapshot } = await import(contractsPath);
  const { commandAvailability } = await import(capabilitiesPath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { StructureEditor } = await vite.ssrLoadModule(
    "/src/structure/StructureEditor.tsx",
  );
  const snapshot = decodeSimulationSnapshot(
    fixture("simulation_snapshot.json"),
  );
  const preview = {
    schema_version: 1,
    simulation_id: "sim-a",
    revision: 3,
    action: "move",
    metrics_before: snapshot.metrics,
    metrics_after: { ...snapshot.metrics, n_v: 1, n_i: 1, d: 2, s: 0.4 },
    counts_before: snapshot.counts,
    counts_after: { ...snapshot.counts, n_v: 1, n_i: 1 },
  };

  const markup = renderToStaticMarkup(
    createElement(StructureEditor, {
      snapshot,
      availability: commandAvailability(
        "PAUSED",
        snapshot.history_capabilities,
      ),
      selectedAtomId: 0,
      destinations: [
        {
          key: "interstitial:2,3",
          kind: "interstitial",
          coordinate: [2.5, 3.5],
          selectable: true,
          block_code: null,
        },
      ],
      preview,
      previewPending: false,
      previewError: "",
      pending: false,
      error: "",
      onSelectAtom: () => undefined,
      onPreview: () => undefined,
      onEdit: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toContain('data-testid="preview-move"');
  expect(markup).toContain('data-testid="manual-edit-preview"');
  expect(markup).toMatch(/data-testid="preview-before-n-atoms"[^>]*>16</);
  expect(markup).toMatch(/data-testid="preview-after-n-v"[^>]*>1</);
  expect(markup).toMatch(/data-testid="preview-after-n-i"[^>]*>1</);
  expect(markup).toMatch(/data-testid="preview-after-d"[^>]*>2</);
});

test("the structure editor separates allowed destinations from server block reasons", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const capabilitiesPath = "../../../src/simulations/capabilities.ts";
  const { decodeSimulationSnapshot } = await import(contractsPath);
  const { commandAvailability } = await import(capabilitiesPath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { StructureEditor } = await vite.ssrLoadModule(
    "/src/structure/StructureEditor.tsx",
  );
  const snapshot = decodeSimulationSnapshot(
    fixture("simulation_snapshot.json"),
  );

  const markup = renderToStaticMarkup(
    createElement(StructureEditor, {
      snapshot,
      availability: commandAvailability(
        "PAUSED",
        snapshot.history_capabilities,
      ),
      selectedAtomId: 0,
      destinations: [
        {
          key: "interstitial:2,3",
          kind: "interstitial",
          coordinate: [2.5, 3.5],
          selectable: true,
          block_code: null,
        },
        {
          key: "lattice:4,4",
          kind: "lattice",
          coordinate: [4, 4],
          selectable: false,
          block_code: "SITE_OCCUPIED",
        },
        {
          key: "interstitial:10,10",
          kind: "interstitial",
          coordinate: [10.5, 10.5],
          selectable: false,
          block_code: "DISCONNECTED_ATOM",
        },
      ],
      pending: false,
      error: "",
      onSelectAtom: () => undefined,
      onEdit: () => undefined,
    }),
  );
  await vite.close();

  expect(markup).toContain("Допустимых назначений по серверу: 1");
  expect(markup).toContain('data-testid="blocked-destinations"');
  expect(markup).toContain("lattice:4,4 — Позиция уже занята (SITE_OCCUPIED)");
  expect(markup).toContain(
    "interstitial:10,10 — Атом потеряет связь с металлом (DISCONNECTED_ATOM)",
  );
  const datalist = markup.match(/<datalist[^>]*>(.*?)<\/datalist>/)?.[1] ?? "";
  expect(datalist).toContain("interstitial:2,3");
  expect(datalist).not.toContain("lattice:4,4");
});

test("the control panel exposes only commands allowed by the public status", async () => {
  const modulePath = "../../../src/simulations/capabilities.ts";
  const { commandAvailability } = await import(modulePath);

  expect(
    commandAvailability("PREPARATION", { can_undo: false, can_redo: false }),
  ).toMatchObject({
    start: true,
    step: true,
    run: true,
    configure: true,
    add: true,
    remove: true,
    move: true,
    diagnostics: false,
    reset: false,
  });
  expect(
    commandAvailability("PAUSED", { can_undo: true, can_redo: true }),
  ).toMatchObject({
    step: true,
    run: true,
    pause: false,
    move: true,
    diagnostics: true,
    undo: true,
    redo: true,
    reset: true,
  });
  expect(
    commandAvailability("RUNNING", { can_undo: true, can_redo: false }),
  ).toMatchObject({
    step: false,
    run: false,
    pause: true,
    diagnostics: false,
    undo: true,
  });
  expect(
    commandAvailability("PAUSED_WITH_ERROR", {
      can_undo: true,
      can_redo: false,
    }),
  ).toMatchObject({
    retry: true,
    acknowledge: true,
    diagnostics: false,
    undo: true,
    run: false,
  });
  expect(
    commandAvailability("STOPPED", { can_undo: false, can_redo: false }),
  ).toMatchObject({
    reset: true,
    step: false,
  });
  expect(
    commandAvailability("FAILED", { can_undo: false, can_redo: false }),
  ).toMatchObject({
    reset: true,
    retry: false,
    step: false,
  });
});

test("the control panel explains the current status and retained history in Russian", async () => {
  const contractsPath = "../../../src/contracts/index.ts";
  const storePath = "../../../src/store/simulationStore.ts";
  const { decodeSimulationSnapshot } = await import(contractsPath);
  const { createSimulationStore } = await import(storePath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { SimulationControls } = await vite.ssrLoadModule(
    "/src/simulations/SimulationControls.tsx",
  );
  const source = fixture("simulation_snapshot.json");
  const snapshot = decodeSimulationSnapshot({
    ...source,
    status: "PAUSED_WITH_ERROR",
    history_capabilities: {
      ...source.history_capabilities,
      retained_action_count: 100,
      history_truncated: true,
    },
  });
  const store = createSimulationStore();
  store.applySnapshot(snapshot);

  try {
    const markup = renderToStaticMarkup(
      createElement(SimulationControls, {
        record: store.getSimulation(snapshot.simulation_id),
        onCommand: () => undefined,
        onRemove: () => undefined,
        playbackMs: 800,
        onPlaybackMs: () => undefined,
        runMode: "visual",
        onRunMode: () => undefined,
      }),
    );

    expect(markup).toContain("Пауза с ошибкой");
    expect(markup).toContain(
      "Можно повторить команду, отменить ошибку или вернуться по истории.",
    );
    expect(markup).toContain("Сохранено действий: 100 из 100");
    expect(markup).toContain("ранние действия усечены");
    expect(markup).toContain("Обычный");
    expect(markup).toContain("с отображением");
    expect(markup).toContain("Быстрый");
    expect(markup).toContain("без отображения");
    expect(markup).toContain("Что делают кнопки");
    expect(markup).toContain(
      "Запускает непрерывный расчёт в выбранном ниже режиме.",
    );
    expect(markup).toMatch(
      /data-testid="playback-speed"[\s\S]*option value="0">Максимальная/,
    );
    expect(markup).not.toContain("PAUSED_WITH_ERROR");
  } finally {
    await vite.close();
  }
});

test("structural metric cards prefer the newest streamed graph point", async () => {
  const modulePath = "../../../src/metrics/MetricsPanel.tsx";
  const { latestSimulationMetrics } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");

  expect(
    latestSimulationMetrics(snapshot.metrics, snapshot.revision, {
      schema_version: 1,
      simulation_id: snapshot.simulation_id,
      revision: snapshot.revision + 1,
      points: [
        {
          revision: snapshot.revision + 1,
          act_number: 7,
          origin: "simulation",
          n_correct: 10,
          n_v: 2,
          n_i: 3,
          n_as: 4,
          d: 9,
          s: 1.25,
        },
      ],
    }),
  ).toEqual({
    n_correct: 10,
    n_v: 2,
    n_i: 3,
    n_as: 4,
    d: 9,
    s: 1.25,
  });
});

test("the chart block reports simulation throughput in acts per second", async () => {
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { MetricsPanel, simulationRate } = await vite.ssrLoadModule(
    "/src/metrics/MetricsPanel.tsx",
  );
  const snapshot = fixture("simulation_snapshot.json");
  try {
    expect(
      simulationRate(
        { actNumber: 20, observedAtMs: 1_000 },
        { actNumber: 35, observedAtMs: 1_600 },
      ),
    ).toBe(25);

    const markup = renderToStaticMarkup(
      createElement(MetricsPanel, {
        current: snapshot.metrics,
        currentRevision: snapshot.revision,
        series: {
          schema_version: 1,
          simulation_id: snapshot.simulation_id,
          revision: snapshot.revision,
          points: [],
        },
      }),
    );

    expect(markup).toContain('data-testid="simulation-speed"');
    expect(markup).toContain("Скорость симуляции");
    expect(markup).toContain("акт/с");
  } finally {
    await vite.close();
  }
});

test("stream messages are deduplicated and an explicit resync may replace an equal revision", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");

  expect(
    store.applyStreamMessage(
      {
        schema_version: 1,
        message_id: 1,
        simulation_id: "sim-a",
        revision: 3,
        type: "snapshot",
        snapshot,
      },
      true,
    ),
  ).toBe(true);
  expect(
    store.applyStreamMessage({
      schema_version: 1,
      message_id: 1,
      simulation_id: "sim-a",
      revision: 3,
      type: "snapshot",
      snapshot: { ...snapshot, status: "RUNNING" },
    }),
  ).toBe(false);
  expect(
    store.applyStreamMessage({
      schema_version: 1,
      message_id: 2,
      simulation_id: "sim-a",
      revision: 2,
      type: "snapshot",
      snapshot: { ...snapshot, revision: 2 },
    }),
  ).toBe(false);

  const resynced = {
    ...snapshot,
    status: "PAUSED",
    atoms: snapshot.atoms.slice(0, 1),
  };
  expect(
    store.applyStreamMessage(
      {
        schema_version: 1,
        message_id: 3,
        simulation_id: "sim-a",
        revision: 3,
        type: "snapshot",
        snapshot: resynced,
      },
      true,
    ),
  ).toBe(true);
  expect(store.getSimulation("sim-a").current_snapshot.atoms).toHaveLength(1);
});

test("a reconnect snapshot remains authoritative when the server message sequence restarts", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");

  expect(
    store.applyStreamMessage(
      {
        schema_version: 1,
        message_id: 50,
        simulation_id: "sim-a",
        revision: 3,
        type: "snapshot",
        snapshot,
      },
      true,
    ),
  ).toBe(true);

  const resynced = { ...snapshot, atoms: snapshot.atoms.slice(0, 1) };
  expect(
    store.applyStreamMessage(
      {
        schema_version: 1,
        message_id: 1,
        simulation_id: "sim-a",
        revision: 3,
        type: "snapshot",
        snapshot: resynced,
      },
      true,
    ),
  ).toBe(true);
  expect(store.getSimulation("sim-a").current_snapshot.atoms).toHaveLength(1);
  expect(store.getSimulation("sim-a").last_message_id).toBe(1);
});

test("reconnect ignores stream deltas until the authoritative snapshot arrives", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");
  const overlay = fixture("probability_overlay.json");

  store.applyStreamMessage(
    {
      schema_version: 1,
      message_id: 50,
      simulation_id: "sim-a",
      revision: 3,
      type: "snapshot",
      snapshot,
    },
    true,
  );
  store.setOverlay(overlay);

  expect(
    store.applyStreamMessage(
      {
        schema_version: 1,
        message_id: 1,
        simulation_id: "sim-a",
        revision: 3,
        type: "event",
        event,
      },
      true,
    ),
  ).toBe(false);
  expect(store.getSimulation("sim-a").last_message_id).toBe(50);
  expect(store.getSimulation("sim-a").events).toHaveLength(0);

  expect(
    store.applyStreamMessage(
      {
        schema_version: 1,
        message_id: 2,
        simulation_id: "sim-a",
        revision: 3,
        type: "snapshot",
        snapshot: { ...snapshot, atoms: snapshot.atoms.slice(0, 1) },
      },
      true,
    ),
  ).toBe(true);
  expect(store.getSimulation("sim-a").last_message_id).toBe(2);
  expect(store.getSimulation("sim-a").current_snapshot.atoms).toHaveLength(1);
  expect(store.getSimulation("sim-a").overlay).toBeNull();
});

test("diagnostic overlays are cleared only for the simulation that starts running", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  const overlay = fixture("probability_overlay.json");

  store.applySnapshot(snapshot);
  store.applySnapshot({ ...snapshot, simulation_id: "sim-b" });
  store.setOverlay(overlay);
  store.setOverlay({ ...overlay, simulation_id: "sim-b" });
  store.clearOverlay("sim-a");

  expect(store.getSimulation("sim-a").overlay).toBeNull();
  expect(store.getSimulation("sim-b").overlay).not.toBeNull();
});

test("a diagnostic overlay is valid only for the current paused revision", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  const overlay = fixture("probability_overlay.json");

  store.applySnapshot(snapshot);
  expect(store.setOverlay(overlay)).toBe(true);

  store.applySnapshot({ ...snapshot, revision: 4 });
  expect(store.getSimulation("sim-a").overlay).toBeNull();
  expect(store.setOverlay(overlay)).toBe(false);
  expect(store.getSimulation("sim-a").overlay).toBeNull();
});

test("the diagnostic panel explains weighted outcomes and blocked targets", async () => {
  const storePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(storePath);
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { DiagnosticsPanel } = await vite.ssrLoadModule(
    "/src/diagnostics/DiagnosticsPanel.tsx",
  );
  const store = createSimulationStore();
  store.applySnapshot(fixture("simulation_snapshot.json"));
  store.setOverlay(fixture("probability_overlay.json"));

  try {
    const markup = renderToStaticMarkup(
      createElement(DiagnosticsPanel, {
        record: store.getSimulation("sim-a"),
        selectedAtomId: 1,
        onSelectAtom: () => undefined,
        onDiagnose: () => undefined,
      }),
    );

    expect(markup).toContain("Сумма выбираемых вероятностей");
    expect(markup).toContain("1.000000");
    expect(markup).toContain("(7, 5)");
    expect(markup).toContain("Кратчайший путь занят");
    expect(markup).toContain("PATH_BLOCKED");
  } finally {
    await vite.close();
  }
});

test("stale journal and metrics responses cannot replace newer websocket data", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");
  const metrics = fixture("metrics_series.json");

  store.applySnapshot({ ...snapshot, revision: 4 });
  store.addEvent("sim-a", { ...event, revision: 4, event_id: "event-4" });
  store.setMetrics({
    ...metrics,
    revision: 4,
    points: [{ ...metrics.points[0], revision: 4 }],
  });

  expect(
    store.setEvents({
      schema_version: 1,
      simulation_id: "sim-a",
      revision: 3,
      offset: 0,
      limit: 100,
      total: 1,
      events: [event],
    }),
  ).toBe(false);
  expect(store.setMetrics(metrics)).toBe(false);
  expect(store.getSimulation("sim-a").events).toEqual([
    expect.objectContaining({ event_id: "event-4" }),
  ]);
  expect(store.getSimulation("sim-a").metrics.revision).toBe(4);
});

test("slice data is isolated and a late socket close cannot recreate a removed session", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  const slices = fixture("slice_atlas.json");

  store.applySnapshot(snapshot);
  store.setSlices({ ...slices, simulation_id: "sim-a" });
  expect(store.getSimulation("sim-a").slices).toMatchObject({ axis: "z" });

  store.remove("sim-a");
  expect(store.setConnected("sim-a", false)).toBe(false);
  expect(store.list()).toHaveLength(0);
});

test("an HTTP step and its websocket replay produce one event and one metrics point", async () => {
  const modulePath = "../../../src/store/simulationStore.ts";
  const { createSimulationStore } = await import(modulePath);
  const store = createSimulationStore();
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");

  store.applyStepResponse({
    schema_version: 1,
    simulation_id: "sim-a",
    revision: 3,
    snapshot,
    event,
  });
  store.applyStreamMessage({
    schema_version: 1,
    message_id: 1,
    simulation_id: "sim-a",
    revision: 3,
    type: "event",
    event,
  });

  const state = store.getSimulation("sim-a");
  expect(state.events).toHaveLength(1);
  expect(state.events[0].event_id).toBe("event-3");
  expect(state.metrics.points).toHaveLength(1);
  expect(state.metrics.points[0]).toMatchObject({ revision: 3 });
});

test("the render frame copies server classifications and configuration geometry", async () => {
  const modulePath = "../../../src/rendering/common/snapshotMapper.ts";
  const { mapSnapshotToRenderFrame } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");
  const overlay = fixture("probability_overlay.json");
  const classified = {
    ...snapshot,
    atoms: [
      {
        ...snapshot.atoms[0],
        site_kind: "interstitial",
        metal_relation: "interior",
        visual_state: "external",
      },
    ],
  };

  const frame = mapSnapshotToRenderFrame(classified, event, overlay);

  expect(frame.field_dimensions).toEqual([12, 12]);
  expect(frame.metal_dimensions).toEqual([4, 4]);
  expect(frame.atoms[0]).toMatchObject({
    site_key: snapshot.atoms[0].site_key,
    site_kind: "interstitial",
    metal_relation: "interior",
    visual_state: "external",
  });
  expect(frame.diagnostic_targets).toEqual([
    expect.objectContaining({ site_key: "lattice:6,5", selectable: true }),
    expect.objectContaining({
      site_key: "lattice:7,5",
      selectable: false,
      block_code: "PATH_BLOCKED",
    }),
  ]);
  expect(frame.last_event).toMatchObject({
    operation: event.operation,
    q_n: event.q_n,
  });
});

test("the render frame places the local metal contour inside the centered movement field", async () => {
  const modulePath = "../../../src/rendering/common/snapshotMapper.ts";
  const { mapSnapshotToRenderFrame } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const localContour = [
    [0, 0],
    [3, 0],
    [3, 3],
    [0, 3],
    [0, 0],
  ];

  const frame = mapSnapshotToRenderFrame({
    ...snapshot,
    configuration: { ...snapshot.configuration, contour: localContour },
  });

  expect(frame.metal_origin).toEqual([4, 4]);
  expect(frame.metal_contour).toEqual([
    [4, 4],
    [7, 4],
    [7, 7],
    [4, 7],
    [4, 4],
  ]);
});

test("the render frame exposes a stable animation identity for one event revision", async () => {
  const modulePath = "../../../src/rendering/common/snapshotMapper.ts";
  const { mapSnapshotToRenderFrame } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");

  const first = mapSnapshotToRenderFrame(snapshot, event);
  const repeated = mapSnapshotToRenderFrame(structuredClone(snapshot), event);
  const stale = mapSnapshotToRenderFrame(snapshot, { ...event, revision: 2 });

  expect(first.event_highlight_revision).toBe(3);
  expect(repeated.event_highlight_revision).toBe(
    first.event_highlight_revision,
  );
  expect(stale.event_highlight_revision).toBeNull();
});

test("journal filters and metric plot models use public event and act data", async () => {
  const journalPath = "../../../src/journal/JournalPanel.tsx";
  const metricsPath = "../../../src/metrics/MetricsPanel.tsx";
  const { filterJournalEvents } = await import(journalPath);
  const { metricPlotPoints } = await import(metricsPath);
  const event = fixture("simulation_event.json");
  const manual = {
    ...event,
    event_id: "manual-4",
    revision: 4,
    act_number: 3,
    operation: "manual_edit",
    origin: "manual_edit",
    q_n: null,
    q_thr: null,
  };

  expect(
    filterJournalEvents([event, manual], {
      origin: "manual_edit",
      operation: "all",
      actFrom: 3,
      actTo: 3,
    }),
  ).toEqual([manual]);

  expect(
    metricPlotPoints(
      [
        {
          ...event.metrics_before,
          revision: 1,
          act_number: 1,
          origin: "initialization",
        },
        {
          ...event.metrics_after,
          revision: 3,
          act_number: 3,
          origin: "physical_act",
        },
        {
          ...event.metrics_after,
          revision: 4,
          act_number: 3,
          origin: "manual_edit",
        },
      ],
      "d",
    ),
  ).toEqual([
    expect.objectContaining({ revision: 1, x: 0, manual: false }),
    expect.objectContaining({ revision: 3, x: 100, manual: false }),
    expect.objectContaining({ revision: 4, x: 100, manual: true }),
  ]);
});

test("the journal and charts expose one linked revision and a manual-edit legend", async () => {
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { JournalPanel } = await vite.ssrLoadModule(
    "/src/journal/JournalPanel.tsx",
  );
  const { MetricsPanel } = await vite.ssrLoadModule(
    "/src/metrics/MetricsPanel.tsx",
  );
  const event = fixture("simulation_event.json");
  const manual = {
    ...event,
    event_id: "manual-4",
    revision: 4,
    operation: "manual_edit",
    origin: "manual_edit",
    q_n: null,
    q_thr: null,
  };
  const series = fixture("metrics_series.json");
  const manualPoint = {
    ...event.metrics_after,
    revision: 4,
    act_number: 3,
    origin: "manual_edit",
  };

  try {
    const markup = renderToStaticMarkup(
      createElement(
        "div",
        null,
        createElement(JournalPanel, {
          events: [event, manual],
          selectedRevision: 4,
        }),
        createElement(MetricsPanel, {
          current: manual.metrics_after,
          series: {
            ...series,
            revision: 4,
            points: [...series.points, manualPoint],
          },
          selectedRevision: 4,
        }),
      ),
    );

    expect(markup).toContain('aria-current="true"');
    expect(markup).toContain("Физический акт");
    expect(markup).toContain("Ручная правка");
    expect(markup).toContain("Общий X: номер акта");
  } finally {
    await vite.close();
  }
});

test("project persistence and journal export are presented as separate tools", async () => {
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { ProjectPanel } = await vite.ssrLoadModule(
    "/src/projects/ProjectPanel.tsx",
  );
  const { ExportPanel } = await vite.ssrLoadModule(
    "/src/export/ExportPanel.tsx",
  );

  try {
    const projectsMarkup = renderToStaticMarkup(
      createElement(ProjectPanel, {
        name: "project-a",
        onName: () => undefined,
        onSave: () => undefined,
        onLoad: () => undefined,
        onDelete: () => undefined,
        projects: [fixture("project_status.json")],
        simulations: [{ id: "sim-a", label: "Симуляция 1" }],
      }),
    );
    const exportMarkup = renderToStaticMarkup(
      createElement(ExportPanel, {
        onExport: () => undefined,
        disabled: false,
      }),
    );

    expect(projectsMarkup).not.toContain("журнал JSON");
    expect(projectsMarkup).toContain("Продолжимый проект");
    expect(exportMarkup).toContain("Экспорт результатов");
    expect(exportMarkup).toContain("не содержит RNG и истории");
  } finally {
    await vite.close();
  }
});

test("a cancelled experiment keeps completed aggregates and individual failures visible", async () => {
  const vite = await createServer({
    server: { middlewareMode: true },
    appType: "custom",
    optimizeDeps: { noDiscovery: true },
  });
  const { ExperimentPanel } = await vite.ssrLoadModule(
    "/src/experiments/ExperimentPanel.tsx",
  );
  const aggregate = {
    count: 2,
    mean: 1,
    minimum: 0,
    maximum: 2,
    p50: 1,
    p95: 1.9,
    confidence_interval: [0.5, 1.5],
    ci_informative: true,
  };

  try {
    const markup = renderToStaticMarkup(
      createElement(ExperimentPanel, {
        status: {
          schema_version: 1,
          experiment_id: "experiment-a",
          status: "CANCELLED",
          completed_steps: 6,
          total_steps: 10,
          successful_runs: 2,
          failed_runs: 1,
        },
        results: {
          schema_version: 1,
          experiment_id: "experiment-a",
          status: "CANCELLED",
          completed_steps: 6,
          total_steps: 10,
          successful_runs: [],
          failed_runs_details: [
            {
              run: 3,
              configuration_index: 0,
              derived_seeds: { seed_init: 31, seed_sim: 32 },
              code: "RUN_FAILED",
              message: "Ошибка отдельного запуска",
            },
          ],
          aggregate: {
            schema_version: 1,
            bootstrap_seed: 99,
            final: { d: aggregate },
            by_act: { "3": { d: aggregate } },
          },
          master_seed: 42,
          bootstrap_seed: 99,
        },
        disabled: false,
        onCreate: () => undefined,
        onCancel: () => undefined,
      }),
    );

    expect(markup).toContain("Отменена");
    expect(markup).toContain("Агрегаты по актам");
    expect(markup).toContain("Акт 3");
    expect(markup).toContain("Ошибка отдельного запуска");
  } finally {
    await vite.close();
  }
});
