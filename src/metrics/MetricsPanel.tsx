import type {
  MetricsPoint,
  MetricsSeries,
  SimulationMetrics,
} from "../contracts";

const metricLabels: Record<string, string> = {
  n_correct: "Атомы в узлах",
  n_v: "Вакансии",
  n_i: "Межузельные атомы",
  n_as: "Атомы за контуром",
  d: "Количество дефектов",
  s: "Энтропия",
};

export function metricPlotPoints(points: MetricsPoint[], key: "d" | "s") {
  if (!points.length) return [];
  const minAct = Math.min(...points.map((point) => point.act_number));
  const maxAct = Math.max(...points.map((point) => point.act_number));
  const maxValue = Math.max(1, ...points.map((point) => point[key]));
  const actSpan = Math.max(1, maxAct - minAct);
  return points.map((point) => ({
    revision: point.revision,
    x: ((point.act_number - minAct) * 100) / actSpan,
    y: 38 - (point[key] * 34) / maxValue,
    value: point[key],
    manual: point.origin === "manual_edit",
  }));
}

export function MetricsPanel({
  current,
  series,
  selectedRevision,
  onSelectRevision,
}: {
  current: SimulationMetrics;
  series: MetricsSeries;
  selectedRevision?: number | null;
  onSelectRevision?: (revision: number | null) => void;
}) {
  const chart = (
    key: "d" | "s",
    title: string,
    description: string,
    yAxisTitle: string,
  ) => {
    const width = 280;
    const height = 110;
    const margin = { top: 8, right: 10, bottom: 30, left: 52 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maxAct = Math.max(1, ...series.points.map((point) => point.act_number));
    const maxValue = Math.max(key === "s" ? 0.1 : 1, ...series.points.map((point) => point[key]));
    const points = series.points.map((point) => ({
      revision: point.revision,
      x: margin.left + (point.act_number / maxAct) * plotWidth,
      y: margin.top + plotHeight - (point[key] / maxValue) * plotHeight,
      value: point[key],
      manual: point.origin === "manual_edit",
    }));
    const xTicks = [...new Set([0, Math.round(maxAct / 2), maxAct])];
    const yTicks = [0, maxValue / 2, maxValue];
    const formatY = (value: number) =>
      key === "s" ? value.toFixed(2) : Number(value.toFixed(1)).toString();
    return (
      <figure>
        <figcaption>
          <strong>{title}</strong>
          <span>{description}</span>
        </figcaption>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title}: ${yAxisTitle} по номеру итерации`}>
          {yTicks.map((value) => {
            const y = margin.top + plotHeight - (value / maxValue) * plotHeight;
            return (
              <g key={`y-${value}`}>
                <line className="chart-grid-line" x1={margin.left} x2={width - margin.right} y1={y} y2={y} />
                <text className="chart-tick-label" x={margin.left - 5} y={y + 2.5} textAnchor="end">{formatY(value)}</text>
              </g>
            );
          })}
          {xTicks.map((value) => {
            const x = margin.left + (value / maxAct) * plotWidth;
            return (
              <g key={`x-${value}`}>
                <line className="chart-tick-mark" x1={x} x2={x} y1={margin.top + plotHeight} y2={margin.top + plotHeight + 3} />
                <text className="chart-tick-label" x={x} y={margin.top + plotHeight + 11} textAnchor="middle">{value}</text>
              </g>
            );
          })}
          <line className="chart-axis-line" x1={margin.left} x2={margin.left} y1={margin.top} y2={margin.top + plotHeight} />
          <line className="chart-axis-line" x1={margin.left} x2={width - margin.right} y1={margin.top + plotHeight} y2={margin.top + plotHeight} />
          <text className="chart-axis-title" x={margin.left + plotWidth / 2} y={height - 2} textAnchor="middle">Номер итерации</text>
          <text className="chart-axis-title" transform={`translate(9 ${margin.top + plotHeight / 2}) rotate(-90)`} textAnchor="middle">{yAxisTitle}</text>
          <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} />
          {points.map((point) => (
            <circle
              key={`${key}-${point.revision}`}
              cx={point.x}
              cy={point.y}
              r={point.manual ? 2.2 : 1.4}
              className={`${point.manual ? "manual-point" : "physical-point"}${point.revision === selectedRevision ? " selected-point" : ""}`}
              aria-current={point.revision === selectedRevision ? "true" : undefined}
              aria-label={`revision ${point.revision}: ${title} — ${point.value}${point.manual ? ", ручная правка" : ", физический акт"}`}
              onMouseEnter={() => onSelectRevision?.(point.revision)}
              onMouseLeave={() => onSelectRevision?.(null)}
            >
              <title>{`Итерация: ${point.revision}; ${title}: ${point.value}${point.manual ? "; ручная правка" : "; физический акт"}`}</title>
            </circle>
          ))}
        </svg>
      </figure>
    );
  };
  return (
    <section className="panel" data-testid="metrics-panel">
      <h2>Структурные метрики</h2>
      <div className="metric-cards" data-testid="simulation-metrics">
        {Object.entries(current).map(([key, value]) => (
          <div key={key} data-testid={`metric-${key.replaceAll("_", "-")}`}>
            <span>{metricLabels[key] ?? key}</span>
            <strong>{Number(value).toFixed(key === "s" ? 4 : 0)}</strong>
          </div>
        ))}
      </div>
      <div className="metric-legend" aria-label="Легенда графиков">
        <span>
          <i className="physical-point" />
          Физический акт
        </span>
        <span>
          <i className="manual-point" />
          Ручная правка
        </span>
        <span>Общий X: номер акта</span>
      </div>
      <div className="charts">
        {chart(
          "d",
          "Количество дефектов",
          "Вакансии + межузельные атомы + атомы за контуром",
          "Дефекты, шт.",
        )}
        {chart(
          "s",
          "Энтропия",
          "Структурная энтропия распределения атомов",
          "Энтропия S",
        )}
      </div>
    </section>
  );
}
