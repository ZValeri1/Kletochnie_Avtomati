import { useMemo, useState } from "react";
import type { SimulationEvent } from "../contracts";

export type JournalFilters = {
  origin: "all" | "physical_act" | "manual_edit";
  operation: "all" | SimulationEvent["operation"];
  actFrom: number | null;
  actTo: number | null;
};

export function filterJournalEvents(
  events: SimulationEvent[],
  filters: JournalFilters,
) {
  return [...events]
    .reverse()
    .filter(
      (event) =>
        (filters.origin === "all" || event.origin === filters.origin) &&
        (filters.operation === "all" ||
          event.operation === filters.operation) &&
        (filters.actFrom === null || event.act_number >= filters.actFrom) &&
        (filters.actTo === null || event.act_number <= filters.actTo),
    );
}

export function JournalPanel({
  events,
  selectedRevision,
  onSelectRevision,
}: {
  events: SimulationEvent[];
  selectedRevision?: number | null;
  onSelectRevision?: (revision: number | null) => void;
}) {
  const [origin, setOrigin] = useState<"all" | "physical_act" | "manual_edit">(
    "all",
  );
  const [operation, setOperation] = useState<
    "all" | SimulationEvent["operation"]
  >("all");
  const [actFrom, setActFrom] = useState("");
  const [actTo, setActTo] = useState("");
  const visible = useMemo(
    () =>
      filterJournalEvents(events, {
        origin,
        operation,
        actFrom: actFrom === "" ? null : Number(actFrom),
        actTo: actTo === "" ? null : Number(actTo),
      }),
    [actFrom, actTo, events, operation, origin],
  );
  const operations = [
    ...new Set(events.map((event) => event.operation)),
  ].sort();
  return (
    <section className="panel journal-panel" data-testid="journal-panel">
      <div className="panel-heading journal-heading">
        <div>
          <h2>Журнал событий</h2>
          <span>{visible.length} из {events.length} записей</span>
        </div>
        <div className="journal-filters">
          <label>
            Тип
            <select
              value={origin}
              onChange={(event) =>
                setOrigin(event.target.value as typeof origin)
              }
            >
              <option value="all">Все</option>
              <option value="physical_act">Физические акты</option>
              <option value="manual_edit">Ручные правки</option>
            </select>
          </label>
          <label>
            Операция
            <select
              value={operation}
              onChange={(event) =>
                setOperation(event.target.value as typeof operation)
              }
            >
              <option value="all">Все</option>
              {operations.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label>
            Акт от
            <input
              type="number"
              min={0}
              value={actFrom}
              onChange={(event) => setActFrom(event.target.value)}
            />
          </label>
          <label>
            до
            <input
              type="number"
              min={0}
              value={actTo}
              onChange={(event) => setActTo(event.target.value)}
            />
          </label>
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Акт</th>
              <th>Источник</th>
              <th>Операция</th>
              <th>Qₙ</th>
              <th>Вероятность</th>
              <th>ΔD</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((event) => (
              <tr
                data-testid="journal-row"
                data-selected={event.revision === selectedRevision}
                aria-current={
                  event.revision === selectedRevision ? "true" : undefined
                }
                key={event.event_id}
                onMouseEnter={() => onSelectRevision?.(event.revision)}
                onMouseLeave={() => onSelectRevision?.(null)}
              >
                <td>{event.act_number}</td>
                <td>
                  {event.origin === "manual_edit" ? "◆ ручная правка" : "акт"}
                </td>
                <td>
                  <details>
                    <summary>{event.operation}</summary>
                    <dl className="event-details">
                      <div>
                        <dt>Источник</dt>
                        <dd>
                          {event.source_site ?? "—"}{" "}
                          {event.source_coordinate
                            ? `(${event.source_coordinate.join(", ")})`
                            : ""}
                        </dd>
                      </div>
                      <div>
                        <dt>Цель</dt>
                        <dd>
                          {event.destination_site ?? "—"}{" "}
                          {event.destination_coordinate
                            ? `(${event.destination_coordinate.join(", ")})`
                            : ""}
                        </dd>
                      </div>
                      <div>
                        <dt>Множители вероятности</dt>
                        <dd>
                          {event.operation_weight} × {event.shell_weight} ×{" "}
                          {event.position_weight} = {event.total_weight}
                        </dd>
                      </div>
                      <div>
                        <dt>Метрики</dt>
                        <dd>
                          D {event.metrics_before.d} → {event.metrics_after.d};
                          S {event.metrics_before.s.toFixed(4)} →{" "}
                          {event.metrics_after.s.toFixed(4)}
                        </dd>
                      </div>
                      <div>
                        <dt>Причина</dt>
                        <dd>{event.result_reason}</dd>
                      </div>
                    </dl>
                  </details>
                </td>
                <td>{event.q_n ?? "—"}</td>
                <td>{event.probability.toFixed(4)}</td>
                <td>{event.metrics_after.d - event.metrics_before.d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!visible.length && <p className="muted">Записей пока нет.</p>}
    </section>
  );
}
