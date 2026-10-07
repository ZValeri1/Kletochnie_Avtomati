import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  ApplicationRequestError,
  simulationApi,
  type ConfigurationPatchInput,
  type PreparationEditInput,
  type SimulationCreateInput,
  type SimulationSubscription,
} from "../api/simulationApi";
import { ConfigurationEditor } from "../configuration/ConfigurationEditor";
import type {
  DestinationOption,
  ExperimentResults,
  ExperimentStatus,
  PreparationEditPreview,
  ProjectStatus,
} from "../contracts";
import { DiagnosticsPanel } from "../diagnostics/DiagnosticsPanel";
import { ExperimentPanel } from "../experiments/ExperimentPanel";
import { ExportPanel } from "../export/ExportPanel";
import { JournalPanel } from "../journal/JournalPanel";
import { MetricsPanel } from "../metrics/MetricsPanel";
import { ProjectPanel } from "../projects/ProjectPanel";
import { Lattice2DRenderer } from "../rendering/canvas2d/Lattice2DRenderer";
import { mapSnapshotToRenderFrame } from "../rendering/common/snapshotMapper";
import { Lattice3DRenderer } from "../rendering/three3d/Lattice3DRenderer";
import { SimulationControls } from "../simulations/SimulationControls";
import { SimulationList } from "../simulations/SimulationList";
import { commandAvailability } from "../simulations/capabilities";
import { simulationStatusPresentation } from "../simulations/statusPresentation";
import { createSimulationStore } from "../store/simulationStore";
import { StructureEditor } from "../structure/StructureEditor";
import { WorkspaceTabs } from "./WorkspaceTabs";
import "./app.css";

export function App() {
  const store = useRef(createSimulationStore()).current;
  const sockets = useRef(new Map<string, SimulationSubscription>());
  const editPreviewRequest = useRef(0);
  const [, refresh] = useReducer((value) => value + 1, 0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("project-a");
  const [projects, setProjects] = useState<ProjectStatus[]>([]);
  const [selectedAtomId, setSelectedAtomId] = useState<number | null>(null);
  const [destinations, setDestinations] = useState<DestinationOption[]>([]);
  const [pendingEdit, setPendingEdit] = useState(false);
  const [editorError, setEditorError] = useState("");
  const [editPreview, setEditPreview] = useState<PreparationEditPreview | null>(
    null,
  );
  const [pendingEditPreview, setPendingEditPreview] = useState(false);
  const [editPreviewError, setEditPreviewError] = useState("");
  const [pendingConfiguration, setPendingConfiguration] = useState(false);
  const [configurationError, setConfigurationError] = useState("");
  const [focusedRevision, setFocusedRevision] = useState<number | null>(null);
  const [playbackMs, setPlaybackMs] = useState(800);
  const [experimentStatus, setExperimentStatus] =
    useState<ExperimentStatus | null>(null);
  const [experimentResults, setExperimentResults] =
    useState<ExperimentResults | null>(null);
  const [message, setMessage] = useState("");

  const loadSideData = useCallback(
    async (simulationId: string) => {
      const [events, metrics] = await Promise.all([
        simulationApi.events(simulationId),
        simulationApi.metrics(simulationId),
      ]);
      store.setEvents(events);
      store.setMetrics(metrics);
      refresh();
    },
    [store],
  );

  const connect = useCallback(
    (simulationId: string) => {
      if (sockets.current.has(simulationId)) return;
      const socket = simulationApi.subscribe(
        simulationId,
        (payload, resync) => {
          store.applyStreamMessage(payload, resync);
          if (resync) void loadSideData(simulationId).catch(() => undefined);
          refresh();
        },
        (connected) => {
          store.setConnected(simulationId, connected);
          refresh();
        },
      );
      sockets.current.set(simulationId, socket);
    },
    [loadSideData, store],
  );

  useEffect(
    () => () => {
      for (const socket of sockets.current.values()) socket.close();
    },
    [],
  );

  const run = async (action: () => Promise<void>) => {
    try {
      setMessage("");
      await action();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const create = (configuration: SimulationCreateInput) =>
    run(async () => {
      const result = await simulationApi.create(configuration);
      store.applySummary(result);
      store.applySnapshot(result.snapshot);
      setSelectedId(result.simulation_id);
      connect(result.simulation_id);
      await loadSideData(result.simulation_id);
      refresh();
    });

  const configure = (configuration: ConfigurationPatchInput) => {
    if (!selectedId) return;
    const record = store.getSimulation(selectedId);
    setPendingConfiguration(true);
    setConfigurationError("");
    void simulationApi
      .configure(selectedId, record.summary.revision, configuration)
      .then(async (response) => {
        store.applyStepResponse(response);
        await loadSideData(selectedId);
        refresh();
      })
      .catch((error) =>
        setConfigurationError(
          error instanceof Error ? error.message : String(error),
        ),
      )
      .finally(() => setPendingConfiguration(false));
  };

  const command = (simulationId: string, type: "run" | "pause" | "stop") =>
    run(async () => {
      const summary = await simulationApi.summaryCommand(
        simulationId,
        type,
        store.getSimulation(simulationId).summary.revision,
      );
      store.applySummary(summary);
      if (type === "run") store.clearOverlay(simulationId);
      refresh();
    });

  const selected = selectedId ? store.getSimulation(selectedId) : null;
  const records = store.list();
  const frame = selected?.current_snapshot
    ? mapSnapshotToRenderFrame(
        selected.current_snapshot,
        selected.events.at(-1),
        selected.overlay,
      )
    : null;
  const availability = selected?.current_snapshot
    ? commandAvailability(
        selected.summary.status,
        selected.current_snapshot.history_capabilities,
      )
    : null;
  const lastManualEdit =
    selected?.events.filter((event) => event.origin === "manual_edit").at(-1) ??
    null;

  useEffect(() => {
    editPreviewRequest.current += 1;
    setSelectedAtomId(null);
    setDestinations([]);
    setEditorError("");
    setEditPreview(null);
    setEditPreviewError("");
    setPendingEditPreview(false);
  }, [selectedId]);

  useEffect(() => {
    editPreviewRequest.current += 1;
    setEditPreview(null);
    setEditPreviewError("");
    setPendingEditPreview(false);
  }, [selected?.summary.revision]);

  useEffect(() => {
    let active = true;
    if (!selectedId || selectedAtomId === null) {
      setDestinations([]);
      return () => {
        active = false;
      };
    }
    void simulationApi
      .destinations(selectedId, selectedAtomId)
      .then((response) => {
        if (active) setDestinations(response.destinations);
      })
      .catch((error) => {
        if (active) {
          setDestinations([]);
          setEditorError(
            error instanceof Error ? error.message : String(error),
          );
        }
      });
    return () => {
      active = false;
    };
  }, [selectedId, selectedAtomId, selected?.summary.revision]);

  const step = () =>
    selectedId && selected
      ? run(async () => {
          const result = await simulationApi.step(
            selectedId,
            selected.summary.revision,
          );
          store.applyStepResponse(result);
          await loadSideData(selectedId);
          refresh();
        })
      : undefined;

  const control = (
    type:
      | "start"
      | "step"
      | "run"
      | "pause"
      | "stop"
      | "reset"
      | "undo"
      | "redo"
      | "retry"
      | "acknowledge",
  ) => {
    if (!selectedId || !selected) return;
    if (
      type === "reset" &&
      !window.confirm("Сбросить траекторию к исходной конфигурации?")
    )
      return;
    if (type === "step") {
      void step?.();
      return;
    }
    void run(async () => {
      const revision = selected.summary.revision;
      if (
        (type === "undo" || type === "redo") &&
        selected.summary.status === "RUNNING"
      ) {
        setMessage(
          "Завершается текущий атомарный акт и выполняется безопасная пауза…",
        );
      }
      if (type === "undo" || type === "redo" || type === "reset") {
        store.applySnapshot(
          await simulationApi.snapshotCommand(selectedId, type, revision),
          { allowEqual: true },
        );
      } else if (type === "retry") {
        store.applyStepResponse(
          await simulationApi.retry(selectedId, revision),
        );
      } else {
        const route = type === "acknowledge" ? "error/acknowledge" : type;
        store.applySummary(
          await simulationApi.summaryCommand(selectedId, route, revision),
        );
        store.applySnapshot(await simulationApi.snapshot(selectedId), {
          allowEqual: true,
        });
        if (type === "run") store.clearOverlay(selectedId);
      }
      await loadSideData(selectedId);
      setMessage("");
      refresh();
    });
  };

  const edit = (payload: PreparationEditInput) => {
    if (!selectedId || !selected) return;
    setPendingEdit(true);
    setEditorError("");
    void simulationApi
      .edit(selectedId, selected.summary.revision, payload)
      .then(async (response) => {
        store.applyStepResponse(response);
        editPreviewRequest.current += 1;
        setEditPreview(null);
        setPendingEditPreview(false);
        await loadSideData(selectedId);
        refresh();
      })
      .catch((error) =>
        setEditorError(error instanceof Error ? error.message : String(error)),
      )
      .finally(() => setPendingEdit(false));
  };

  const previewEdit = (payload: PreparationEditInput) => {
    if (!selectedId || !selected) return;
    const revision = selected.summary.revision;
    const requestId = ++editPreviewRequest.current;
    setPendingEditPreview(true);
    setEditPreviewError("");
    void simulationApi
      .previewEdit(selectedId, revision, payload)
      .then((response) => {
        if (requestId !== editPreviewRequest.current) return;
        const current = store.getSimulation(selectedId);
        if (response.revision === current.summary.revision)
          setEditPreview(response);
      })
      .catch((error) => {
        if (requestId !== editPreviewRequest.current) return;
        setEditPreview(null);
        setEditPreviewError(
          error instanceof Error ? error.message : String(error),
        );
      })
      .finally(() => {
        if (requestId === editPreviewRequest.current)
          setPendingEditPreview(false);
      });
  };

  const save = (ids: string[]) =>
    run(async () => {
      try {
        await simulationApi.saveProject(projectName, ids, false);
      } catch (error) {
        if (
          !(error instanceof ApplicationRequestError) ||
          error.status !== 409 ||
          !window.confirm("Проект существует. Перезаписать?")
        )
          throw error;
        await simulationApi.saveProject(projectName, ids, true);
      }
      setProjects(await simulationApi.listProjects());
    });
  const load = () =>
    run(async () => {
      const result = await simulationApi.loadProject(projectName);
      for (const summary of result.simulations) {
        store.applySummary(summary);
        store.applySnapshot(
          await simulationApi.snapshot(summary.simulation_id),
        );
        connect(summary.simulation_id);
        await loadSideData(summary.simulation_id);
      }
      if (result.simulations[0])
        setSelectedId(result.simulations[0].simulation_id);
      refresh();
    });
  const deleteProject = () =>
    run(async () => {
      if (!window.confirm(`Удалить проект ${projectName}?`)) return;
      await simulationApi.deleteProject(projectName);
      setProjects(await simulationApi.listProjects());
    });
  const exportJournal = () =>
    selectedId &&
    run(async () => {
      const blob = await simulationApi.journal(selectedId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${selectedId}-journal.json`;
      link.click();
      URL.revokeObjectURL(url);
    });

  const removeSelected = () =>
    selectedId &&
    selected &&
    run(async () => {
      if (!window.confirm("Удалить выбранную сессию?")) return;
      await simulationApi.remove(selectedId, selected.summary.revision);
      store.remove(selectedId);
      sockets.current.get(selectedId)?.close();
      sockets.current.delete(selectedId);
      setSelectedId(store.list()[0]?.summary.simulation_id ?? null);
      refresh();
    });

  const startExperiment = (
    repetitions: number,
    steps: number,
    masterSeed: number,
  ) => {
    const snapshot = selected?.current_snapshot;
    if (!snapshot) return;
    void run(async () => {
      const { field_dimensions: _field, ...createConfiguration } =
        snapshot.configuration;
      setExperimentResults(null);
      setExperimentStatus(
        await simulationApi.createExperiment({
          configurations: [createConfiguration],
          repetitions,
          steps,
          master_seed: masterSeed,
        }),
      );
    });
  };
  const cancelExperiment = () =>
    experimentStatus &&
    run(async () => {
      const status = await simulationApi.cancelExperiment(
        experimentStatus.experiment_id,
      );
      setExperimentStatus(status);
      if (!["PENDING", "RUNNING"].includes(status.status)) {
        setExperimentResults(
          await simulationApi.experimentResults(status.experiment_id),
        );
      }
    });

  useEffect(() => {
    void simulationApi
      .listProjects()
      .then(setProjects)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (
      !experimentStatus ||
      !["PENDING", "RUNNING"].includes(experimentStatus.status)
    )
      return;
    const timer = window.setTimeout(() => {
      void simulationApi
        .experimentStatus(experimentStatus.experiment_id)
        .then(async (status) => {
          setExperimentStatus(status);
          if (!["PENDING", "RUNNING"].includes(status.status)) {
            setExperimentResults(
              await simulationApi.experimentResults(status.experiment_id),
            );
          }
        })
        .catch((error) =>
          setMessage(error instanceof Error ? error.message : String(error)),
        );
    }, 500);
    return () => window.clearTimeout(timer);
  }, [experimentStatus]);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <span className="brand-mark" aria-hidden="true">γ</span>
          <div>
            <span className="eyebrow">Gamma Irradiation</span>
            <h1>Моделирование облучения</h1>
          </div>
        </div>
        <span className="simulation-counter">
          <strong>{records.length}</strong>
          {records.length === 1 ? " симуляция" : " симуляций"}
        </span>
      </header>
      <nav className="method-switcher" aria-label="Методы моделирования">
        <span>Методы моделирования</span>
        <div>
          <button type="button" aria-current="page">Монте-Карло</button>
          <button
            type="button"
            className="method-coming-soon"
            disabled
            title="Метод клеточных автоматов пока недоступен"
          >
            Клеточные автоматы
          </button>
        </div>
      </nav>
      {message && <div className="error-banner">{message}</div>}
      {selected?.renderer_error && (
        <div className="warning-banner">
          Ошибка визуализации: {selected.renderer_error.message}. Управление и
          данные остаются доступны.
        </div>
      )}
      {selected?.current_snapshot?.error && (
        <div className="error-banner">
          <strong>{selected.current_snapshot.error.code}</strong>:{" "}
          {selected.current_snapshot.error.message}
          {selected.current_snapshot.error.recoverable && (
            <div className="row-actions">
              <button onClick={() => control("retry")}>Повторить</button>
              <button onClick={() => control("acknowledge")}>
                Отменить ошибку
              </button>
              <button
                disabled={
                  !selected.current_snapshot.history_capabilities.can_undo
                }
                onClick={() => control("undo")}
              >
                Назад
              </button>
              <button onClick={exportJournal}>Скачать диагностику JSON</button>
            </div>
          )}
        </div>
      )}
      {selected?.summary.status === "FAILED" && (
        <div className="error-banner">
          Состояние симуляции недостоверно: продолжение невозможно. Доступны
          просмотр и диагностический экспорт.
        </div>
      )}
      <div className="dashboard-grid">
        <section className="visualization-area">
          {selected && selectedId ? (
          <div
            data-testid="selected-simulation"
            data-revision={selected.summary.revision}
            data-status={selected.summary.status}
            className="selected-summary simulation-titlebar"
          >
            <div>
              <span className="section-kicker">Активная сессия</span>
              <strong>Симуляция {Math.max(1, records.findIndex((record) => record.summary.simulation_id === selectedId) + 1)}</strong>
            </div>
            <span className={`status-pill status-${selected.summary.status.toLowerCase()}`}>
              {simulationStatusPresentation[selected.summary.status].label}
            </span>
            <span className="revision-label">Ревизия {selected.summary.revision}</span>
          </div>
          ) : (
            <div className="selected-summary simulation-titlebar empty-titlebar">
              <div>
                <span className="section-kicker">Рабочее поле</span>
                <strong>Новая симуляция</strong>
              </div>
              <span className="revision-label">Ожидает настройки</span>
            </div>
          )}
          <div className="simulation-stage">
            {frame && frame.mode === "2d" && (
              <Lattice2DRenderer
                frame={frame}
                highlightDurationMs={playbackMs}
                selectedAtomId={selectedAtomId}
                onSelectAtom={setSelectedAtomId}
                onMove={(atomId, destinationKey) =>
                  availability?.move &&
                  edit({
                    action: "move",
                    atom_id: atomId,
                    destination_key: destinationKey,
                  })
                }
              />
            )}
            {frame && frame.mode === "3d" && (
              <Lattice3DRenderer
                frame={frame}
                onError={(error) => {
                  if (selectedId) store.recordRendererFailure(selectedId, error);
                }}
              />
            )}
            {!selected && (
              <div className="empty-state stage-empty">
                <span className="empty-orbit" aria-hidden="true">γ</span>
                <strong>Подготовьте первую симуляцию</strong>
                <span>Задайте параметры ниже — модель появится здесь.</span>
              </div>
            )}
          </div>
        </section>

        <aside className="tools-column insights-area">
          <WorkspaceTabs
            tabs={[
              {
                id: "metrics",
                label: "Графики",
                content: selected?.current_snapshot ? (
                  <MetricsPanel
                    current={selected.current_snapshot.metrics}
                    series={selected.metrics}
                    selectedRevision={focusedRevision}
                    onSelectRevision={setFocusedRevision}
                  />
                ) : (
                  <div className="empty-state">Метрики пока недоступны.</div>
                ),
              },
              {
                id: "diagnostics",
                label: "Диагностика",
                content:
                  selected && selectedId ? (
                    <DiagnosticsPanel
                      record={selected}
                      selectedAtomId={selectedAtomId}
                      onSelectAtom={setSelectedAtomId}
                      onDiagnose={(atomId, qTest) =>
                        void run(async () => {
                          store.setOverlay(
                            await simulationApi.diagnose(
                              selectedId,
                              atomId,
                              qTest,
                            ),
                          );
                          refresh();
                        })
                      }
                    />
                  ) : (
                    <div className="empty-state">
                      Сначала создайте симуляцию.
                    </div>
                  ),
              },
              {
                id: "journal",
                label: "Журнал",
                content: selected ? (
                  <JournalPanel
                    events={selected.events}
                    selectedRevision={focusedRevision}
                    onSelectRevision={setFocusedRevision}
                  />
                ) : (
                  <div className="empty-state">Журнал пока пуст.</div>
                ),
              },
              {
                id: "projects",
                label: "Проекты",
                content: (
                  <div className="tool-stack">
                    <ProjectPanel
                      name={projectName}
                      onName={setProjectName}
                      onSave={save}
                      onLoad={load}
                      onDelete={deleteProject}
                      projects={projects}
                      simulations={records.map((record, index) => ({
                        id: record.summary.simulation_id,
                        label: `Симуляция ${index + 1} · ${simulationStatusPresentation[record.summary.status].label}`,
                      }))}
                    />
                    <ExportPanel
                      onExport={exportJournal}
                      disabled={!selectedId}
                    />
                  </div>
                ),
              },
              {
                id: "experiments",
                label: "Эксперименты",
                content: (
                  <ExperimentPanel
                    status={experimentStatus}
                    results={experimentResults}
                    disabled={!selected?.current_snapshot}
                    onCreate={startExperiment}
                    onCancel={cancelExperiment}
                  />
                ),
              },
            ]}
          />
        </aside>

        <section className="configuration-area">
          {selected && (
            <SimulationControls
              record={selected}
              onCommand={control}
              onRemove={removeSelected}
              playbackMs={playbackMs}
              onPlaybackMs={setPlaybackMs}
            />
          )}
          <ConfigurationEditor
            onCreate={create}
            onConfigure={configure}
            currentSnapshot={selected?.current_snapshot}
            pending={pendingConfiguration}
            serverError={configurationError}
          />
          {selected?.current_snapshot && availability && (
            <StructureEditor
              snapshot={selected.current_snapshot}
              availability={availability}
              selectedAtomId={selectedAtomId}
              destinations={destinations}
              preview={editPreview}
              previewPending={pendingEditPreview}
              previewError={editPreviewError}
              lastEdit={lastManualEdit}
              pending={pendingEdit}
              error={editorError}
              onSelectAtom={setSelectedAtomId}
              onPreview={previewEdit}
              onEdit={edit}
            />
          )}
        </section>

        <aside className="sessions-area">
          <SimulationList
            records={records}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onCommand={command}
          />
        </aside>
      </div>
    </main>
  );
}
