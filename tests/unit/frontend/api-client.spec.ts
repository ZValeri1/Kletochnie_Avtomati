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

test("step sends only optimistic-concurrency data and rejects a malformed success payload", async () => {
  const modulePath = "../../../src/api/simulationApi.ts";
  const { simulationApi } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");
  let requestBody: Record<string, unknown> | undefined;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body));
    return new Response(
      JSON.stringify({
        schema_version: 1,
        simulation_id: "sim-a",
        revision: 3,
        event,
        snapshot: { ...snapshot, metrics: undefined },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await expect(simulationApi.step("sim-a", 2)).rejects.toThrow(/snapshot/i);
    expect(requestBody).toEqual({ schema_version: 1, expected_revision: 2 });
    expect(requestBody).not.toHaveProperty("forced_energy");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("configuration patch is versioned and keeps optimistic concurrency data", async () => {
  const modulePath = "../../../src/api/simulationApi.ts";
  const { simulationApi } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");
  let requestBody: Record<string, unknown> | undefined;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body));
    return new Response(
      JSON.stringify({
        schema_version: 1,
        simulation_id: "sim-a",
        revision: 4,
        event: { ...event, revision: 4, event_id: "event-4" },
        snapshot: { ...snapshot, revision: 4 },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await simulationApi.configure("sim-a", 3, {
      q_thr_ev: 25,
      weights: { boundary_external: 0.03 },
    });
    expect(requestBody).toEqual({
      schema_version: 1,
      expected_revision: 3,
      q_thr_ev: 25,
      weights: { boundary_external: 0.03 },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("continuous run accepts zero delay for maximum visual speed", async () => {
  const modulePath = "../../../src/api/simulationApi.ts";
  const { simulationApi } = await import(modulePath);
  let requestBody: Record<string, unknown> | undefined;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body));
    return new Response(
      JSON.stringify({
        schema_version: 1,
        simulation_id: "sim-a",
        revision: 4,
        status: "RUNNING",
        run_mode: "visual",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await simulationApi.run("sim-a", 3, "visual", 0);
    expect(requestBody).toEqual({
      schema_version: 1,
      expected_revision: 3,
      mode: "visual",
      interval_ms: 0,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("validation errors identify an outdated running server", async () => {
  const modulePath = "../../../src/api/simulationApi.ts";
  const { simulationApi } = await import(modulePath);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        schema_version: 1,
        code: "VALIDATION_ERROR",
        message: "Request validation failed",
        simulation_id: null,
        command_id: null,
        revision: null,
        recoverable: false,
        details: {
          errors: [
            {
              type: "extra_forbidden",
              loc: ["body", "weights", "from_lattice_inside"],
              msg: "Extra inputs are not permitted",
            },
          ],
        },
      }),
      { status: 422, headers: { "Content-Type": "application/json" } },
    );

  try {
    await expect(
      simulationApi.create({} as Parameters<typeof simulationApi.create>[0]),
    ).rejects.toThrow(/from_lattice_inside.*перезапустите сервер/i);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("manual edit preview uses the versioned read-only API contract", async () => {
  const modulePath = "../../../src/api/simulationApi.ts";
  const { simulationApi } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  let requestUrl = "";
  let requestBody: Record<string, unknown> | undefined;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestBody = JSON.parse(String(init?.body));
    return new Response(
      JSON.stringify({
        schema_version: 1,
        simulation_id: "sim-a",
        revision: 3,
        action: "move",
        metrics_before: snapshot.metrics,
        metrics_after: { ...snapshot.metrics, n_v: 1, n_i: 1, d: 2 },
        counts_before: snapshot.counts,
        counts_after: { ...snapshot.counts, n_v: 1, n_i: 1 },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const preview = await simulationApi.previewEdit("sim-a", 3, {
      action: "move",
      atom_id: 0,
      destination_key: "interstitial:1,1",
    });
    expect(requestUrl).toBe("/api/simulations/sim-a/edit/preview");
    expect(requestBody).toEqual({
      schema_version: 1,
      expected_revision: 3,
      action: "move",
      atom_id: 0,
      destination_key: "interstitial:1,1",
    });
    expect(preview.metrics_after).toMatchObject({ n_v: 1, n_i: 1, d: 2 });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("websocket reconnect treats the first full snapshot as the resync boundary", async () => {
  const modulePath = "../../../src/api/simulationApi.ts";
  const { simulationApi } = await import(modulePath);
  const snapshot = fixture("simulation_snapshot.json");
  const event = fixture("simulation_event.json");
  const originalWebSocket = Object.getOwnPropertyDescriptor(
    globalThis,
    "WebSocket",
  );
  const originalLocation = Object.getOwnPropertyDescriptor(
    globalThis,
    "location",
  );
  let socket: FakeWebSocket | undefined;

  class FakeWebSocket {
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;

    constructor(readonly url: string) {
      socket = this;
    }

    close() {}
  }

  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    value: FakeWebSocket,
  });
  Object.defineProperty(globalThis, "location", {
    configurable: true,
    value: { protocol: "http:", host: "example.test" },
  });

  const resyncFlags: boolean[] = [];
  try {
    const subscription = simulationApi.subscribe("sim-a", (_message, resync) =>
      resyncFlags.push(resync),
    );
    expect(socket?.url).toBe("ws://example.test/ws/simulations/sim-a");

    socket?.onmessage?.({
      data: JSON.stringify({
        schema_version: 1,
        message_id: 1,
        simulation_id: "sim-a",
        revision: 3,
        type: "event",
        event,
      }),
    });
    socket?.onmessage?.({
      data: JSON.stringify({
        schema_version: 1,
        message_id: 2,
        simulation_id: "sim-a",
        revision: 3,
        type: "snapshot",
        snapshot,
      }),
    });
    socket?.onmessage?.({
      data: JSON.stringify({
        schema_version: 1,
        message_id: 3,
        simulation_id: "sim-a",
        revision: 3,
        type: "event",
        event,
      }),
    });

    expect(resyncFlags).toEqual([false, true, false]);
    subscription.close();
  } finally {
    if (originalWebSocket) {
      Object.defineProperty(globalThis, "WebSocket", originalWebSocket);
    } else {
      Reflect.deleteProperty(globalThis, "WebSocket");
    }
    if (originalLocation) {
      Object.defineProperty(globalThis, "location", originalLocation);
    } else {
      Reflect.deleteProperty(globalThis, "location");
    }
  }
});
