import type { SimulationRecord } from "../store/simulationStore";
import { simulationStatusPresentation } from "./statusPresentation";

export function SimulationList({
  records,
  selectedId,
  onSelect,
  onCommand,
}: {
  records: SimulationRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCommand: (id: string, command: "run" | "pause" | "stop") => void;
}) {
  const sparkline = (record: SimulationRecord) => {
    const source = record.metrics.points;
    const points = source[0]?.act_number > 0
      ? [{ act_number: 0, d: 0 }, ...source]
      : source;
    if (!points.length) return "4,24 104,24";
    const max = Math.max(1, ...points.map((point) => point.d));
    const maxAct = Math.max(1, ...points.map((point) => point.act_number));
    const width = 100;
    return points
      .map((point) => {
        const x = 4 + (point.act_number * width) / maxAct;
        const y = 27 - (point.d * 21) / max;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  };

  const lastAct = (record: SimulationRecord) =>
    Math.max(0, ...record.metrics.points.map((point) => point.act_number));

  return (
    <section className="panel simulation-list">
      <div className="panel-title-row">
        <div>
          <span className="section-kicker">Очередь расчётов</span>
          <h2>Симуляции и их статус</h2>
        </div>
        <span className="list-count">{records.length}</span>
      </div>
      {records.length === 0 && (
        <p className="muted simulation-list-empty">Созданные запуски появятся здесь.</p>
      )}
      {records.map((record, index) => (
        <article
          key={record.summary.simulation_id}
          data-testid="simulation-row"
          data-revision={record.summary.revision}
          data-status={record.summary.status}
          className={
            record.summary.simulation_id === selectedId ? "selected" : ""
          }
          onClick={() => onSelect(record.summary.simulation_id)}
        >
          <div className="simulation-row-copy">
            <strong>Симуляция {index + 1}</strong>
            <span className={`status-text status-${record.summary.status.toLowerCase()}`}>
              {simulationStatusPresentation[record.summary.status].label}
            </span>
            <small>Ревизия {record.summary.revision} · {record.connection_status === "connected" ? "онлайн" : "переподключение"}</small>
          </div>
          <svg className="simulation-sparkline" viewBox="0 0 108 32" role="img" aria-label={`График симуляции ${index + 1}`}>
            <path d="M4 27H104" />
            <polyline points={sparkline(record)} />
            <text x="4" y="31">0</text>
            <text x="104" y="31" textAnchor="end">{lastAct(record)}</text>
          </svg>
          <div className="row-actions">
            <button
              data-testid="run-simulation"
              disabled={
                !["PREPARATION", "PAUSED"].includes(record.summary.status)
              }
              onClick={(event) => {
                event.stopPropagation();
                onCommand(record.summary.simulation_id, "run");
              }}
            >
              Быстрый запуск
            </button>
            <button
              data-testid="pause-simulation"
              disabled={record.summary.status !== "RUNNING"}
              onClick={(event) => {
                event.stopPropagation();
                onCommand(record.summary.simulation_id, "pause");
              }}
            >
              Пауза
            </button>
            <button
              disabled={!["PAUSED", "RUNNING"].includes(record.summary.status)}
              onClick={(event) => {
                event.stopPropagation();
                onCommand(record.summary.simulation_id, "stop");
              }}
            >
              Стоп
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}
