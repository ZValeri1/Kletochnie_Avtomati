import { useState } from "react";
import type { ExperimentResults, ExperimentStatus } from "../contracts";

const statusLabels: Record<ExperimentStatus["status"], string> = {
  PENDING: "Ожидает запуска",
  RUNNING: "Выполняется",
  COMPLETED: "Завершена",
  COMPLETED_WITH_ERRORS: "Завершена с ошибками",
  CANCELLED: "Отменена",
  FAILED: "Завершилась ошибкой",
};

export function ExperimentPanel({
  status,
  results,
  disabled,
  onCreate,
  onCancel,
}: {
  status: ExperimentStatus | null;
  results: ExperimentResults | null;
  disabled: boolean;
  onCreate: (repetitions: number, steps: number, masterSeed: number) => void;
  onCancel: () => void;
}) {
  const [repetitions, setRepetitions] = useState(5);
  const [steps, setSteps] = useState(100);
  const [masterSeed, setMasterSeed] = useState(12345);
  return (
    <section className="panel experiments" data-testid="experiment-panel">
      <h2>Исследовательская серия</h2>
      <div className="form-grid">
        <label>
          Повторы
          <input
            type="number"
            min={1}
            value={repetitions}
            onChange={(event) => setRepetitions(Number(event.target.value))}
          />
        </label>
        <label>
          Акты
          <input
            type="number"
            min={0}
            value={steps}
            onChange={(event) => setSteps(Number(event.target.value))}
          />
        </label>
        <label>
          Master seed
          <input
            type="number"
            value={masterSeed}
            onChange={(event) => setMasterSeed(Number(event.target.value))}
          />
        </label>
      </div>
      <div className="row-actions">
        <button
          disabled={
            disabled ||
            status?.status === "RUNNING" ||
            status?.status === "PENDING"
          }
          onClick={() => onCreate(repetitions, steps, masterSeed)}
        >
          Запустить серию
        </button>
        <button
          disabled={!status || !["PENDING", "RUNNING"].includes(status.status)}
          onClick={onCancel}
        >
          Отменить
        </button>
      </div>
      {status && (
        <div className="experiment-progress">
          <progress
            max={Math.max(1, status.total_steps)}
            value={status.completed_steps}
          />
          <span>
            {statusLabels[status.status]}: {status.completed_steps}/
            {status.total_steps}, успешно {status.successful_runs}, ошибок{" "}
            {status.failed_runs}
          </span>
        </div>
      )}
      {results && (
        <div className="experiment-results">
          <h3>Запуски</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>№</th>
                  <th>Симуляция</th>
                  <th>seed_init</th>
                  <th>seed_sim</th>
                  <th>D фин.</th>
                  <th>S фин.</th>
                </tr>
              </thead>
              <tbody>
                {results.successful_runs.map((run) => {
                  const final = run.metrics.at(-1);
                  return (
                    <tr key={run.run}>
                      <td>{run.run}</td>
                      <td>{run.simulation_id.slice(0, 8)}</td>
                      <td>{run.derived_seeds.seed_init}</td>
                      <td>{run.derived_seeds.seed_sim}</td>
                      <td>{final?.d ?? "—"}</td>
                      <td>{final?.s.toFixed(4) ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {results.aggregate && (
            <>
              <h3>Финальные агрегаты</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Метрика</th>
                      <th>N</th>
                      <th>Среднее</th>
                      <th>min…max</th>
                      <th>p50 / p95</th>
                      <th>95% CI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(results.aggregate.final).map(
                      ([name, aggregate]) => (
                        <tr key={name}>
                          <td>{name}</td>
                          <td>{aggregate.count}</td>
                          <td>{aggregate.mean.toFixed(4)}</td>
                          <td>
                            {aggregate.minimum.toFixed(4)}…
                            {aggregate.maximum.toFixed(4)}
                          </td>
                          <td>
                            {aggregate.p50.toFixed(4)} /{" "}
                            {aggregate.p95.toFixed(4)}
                          </td>
                          <td>
                            {aggregate.confidence_interval
                              .map((value) => value.toFixed(4))
                              .join("…")}
                            {!aggregate.ci_informative && " (неинформативен)"}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
              <div className="aggregate-ranges">
                {Object.entries(results.aggregate.final).map(
                  ([name, aggregate]) => {
                    const span = Math.max(
                      1e-12,
                      aggregate.maximum - aggregate.minimum,
                    );
                    const mean =
                      ((aggregate.mean - aggregate.minimum) / span) * 100;
                    return (
                      <figure key={name}>
                        <figcaption>{name}: диапазон и среднее</figcaption>
                        <div className="range-track">
                          <span
                            className="range-mean"
                            style={{ left: `${mean}%` }}
                          />
                        </div>
                      </figure>
                    );
                  },
                )}
              </div>
              <h3>Агрегаты по актам</h3>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Акт</th>
                      <th>Метрика</th>
                      <th>N</th>
                      <th>Среднее</th>
                      <th>95% CI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(results.aggregate.by_act).flatMap(
                      ([act, metrics]) =>
                        Object.entries(metrics).map(([name, aggregate]) => (
                          <tr key={`${act}-${name}`}>
                            <td>Акт {act}</td>
                            <td>{name}</td>
                            <td>{aggregate.count}</td>
                            <td>{aggregate.mean.toFixed(4)}</td>
                            <td>
                              {aggregate.confidence_interval
                                .map((value) => value.toFixed(4))
                                .join("…")}
                            </td>
                          </tr>
                        )),
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {results.failed_runs_details.length > 0 && (
            <>
              <h3>Ошибки отдельных запусков</h3>
              <ul>
                {results.failed_runs_details.map((failure) => (
                  <li key={failure.run}>
                    Запуск {failure.run}: <strong>{failure.code}</strong> —{" "}
                    {failure.message}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
