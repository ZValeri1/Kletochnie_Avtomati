import { useState } from "react";
import type { SimulationRecord } from "../store/simulationStore";

const blockMessages: Record<string, string> = {
  PATH_BLOCKED: "Кратчайший путь занят",
  BELOW_THRESHOLD: "Q_test ниже порога активации",
  ZERO_PROBABILITY: "Для этой группы задана нулевая вероятность",
  SITE_OCCUPIED: "Позиция уже занята",
  DISCONNECTED_ATOM: "Атом потеряет связь с металлом",
};

const blockMessage = (code: string | null) =>
  code ? (blockMessages[code] ?? "Цель заблокирована") : "Цель заблокирована";

export function DiagnosticsPanel({
  record,
  selectedAtomId,
  onSelectAtom,
  onDiagnose,
}: {
  record: SimulationRecord;
  selectedAtomId: number | null;
  onSelectAtom: (atomId: number | null) => void;
  onDiagnose: (atomId: number, qTest: number) => void;
}) {
  const [qTest, setQTest] = useState(30);
  const snapshot = record.current_snapshot;
  if (!snapshot) return null;
  const allowed = record.summary.status === "PAUSED";
  const selectableSum =
    record.overlay?.outcomes
      .filter((outcome) => outcome.selectable)
      .reduce((sum, outcome) => sum + outcome.probability, 0) ?? 0;
  return (
    <section className="panel diagnostics" data-testid="diagnostics-panel">
      <h2>Диагностика переходов</h2>
      <p className="muted">
        Q_test — только диагностическое значение: оно не создаёт акт, не меняет
        RNG и траекторию.
      </p>
      <div className="diagnostic-controls">
        <label>
          Атом
          <select
            value={selectedAtomId ?? ""}
            onChange={(event) =>
              onSelectAtom(
                event.target.value === "" ? null : Number(event.target.value),
              )
            }
          >
            <option value="">Выберите атом</option>
            {snapshot.atoms.map((atom) => (
              <option value={atom.id} key={atom.id}>
                #{atom.id} · {atom.site_key}
              </option>
            ))}
          </select>
        </label>
        <label>
          Q_test
          <input
            type="number"
            min={0}
            value={qTest}
            onChange={(event) => setQTest(Number(event.target.value))}
          />
        </label>
        <button
          disabled={!allowed || selectedAtomId === null}
          onClick={() =>
            selectedAtomId !== null && onDiagnose(selectedAtomId, qTest)
          }
        >
          Рассчитать
        </button>
      </div>
      {!allowed && (
        <p className="blocked-reason">
          Диагностика доступна только на паузе; во время запуска вероятностный
          слой очищен.
        </p>
      )}
      {record.overlay && (
        <>
          <p>
            Сумма выбираемых вероятностей:{" "}
            <strong>{selectableSum.toFixed(6)}</strong>
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Цель</th>
                  <th>Операция</th>
                  <th>r</th>
                  <th>P типа</th>
                  <th>P контура</th>
                  <th>P положения</th>
                  <th>Произведение</th>
                  <th>P</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {record.overlay.outcomes.map((outcome) => (
                  <tr key={`${outcome.destination_site}-${outcome.operation}`}>
                    <td>
                      {outcome.destination_site} (
                      {outcome.destination_coordinate.join(", ")})
                    </td>
                    <td>{outcome.operation ?? "—"}</td>
                    <td>{outcome.shell}</td>
                    <td>{outcome.operation_weight}</td>
                    <td>{outcome.shell_weight}</td>
                    <td>{outcome.position_weight}</td>
                    <td>{outcome.total_weight}</td>
                    <td>{outcome.probability.toFixed(6)}</td>
                    <td>
                      {outcome.selectable
                        ? "доступно"
                        : `${blockMessage(outcome.block_code)} (${outcome.block_code ?? "UNKNOWN"})`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
