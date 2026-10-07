import type { SimulationRecord } from "../store/simulationStore";
import { commandAvailability } from "./capabilities";
import { simulationStatusPresentation } from "./statusPresentation";

export function SimulationControls({
  record,
  onCommand,
  onRemove,
  playbackMs,
  onPlaybackMs,
}: {
  record: SimulationRecord;
  onCommand: (
    command:
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
  ) => void;
  onRemove: () => void;
  playbackMs: number;
  onPlaybackMs: (milliseconds: number) => void;
}) {
  const history = record.current_snapshot?.history_capabilities ?? {
    can_undo: false,
    can_redo: false,
    retained_action_count: 0,
    history_limit: 100,
    history_truncated: false,
  };
  const available = commandAvailability(record.summary.status, history);
  const status = simulationStatusPresentation[record.summary.status];
  const button = (
    command: Parameters<typeof onCommand>[0],
    label: string,
    enabled: boolean,
    testId?: string,
  ) => (
    <button
      data-testid={testId}
      disabled={!enabled}
      onClick={() => onCommand(command)}
    >
      {label}
    </button>
  );
  return (
    <section className="panel controls">
      <h2>Управление</h2>
      <div className="control-status" role="status">
        <strong>{status.label}</strong>
        <span>{status.explanation}</span>
      </div>
      <div className="control-buttons">
        {button("start", "Начать", available.start, "start-simulation")}
        {button("step", "Один акт", available.step, "step-simulation")}
        {button("run", "Запустить", available.run, "run-selected-simulation")}
        {button("pause", "Пауза", available.pause, "pause-selected-simulation")}
        {button("stop", "Завершить", available.stop)}
        {button("reset", "Сбросить", available.reset)}
        {button("undo", "Назад", available.undo, "undo-simulation")}
        {button("redo", "Вперёд", available.redo, "redo-simulation")}
        {button("retry", "Повторить", available.retry)}
        {button("acknowledge", "Отменить ошибку", available.acknowledge)}
        <button data-testid="remove-simulation" onClick={onRemove}>
          Удалить сессию
        </button>
      </div>
      <div className="history-summary">
        Сохранено действий: {history.retained_action_count} из{" "}
        {history.history_limit}
        {history.history_truncated && (
          <strong> · ранние действия усечены</strong>
        )}
      </div>
      <label className="playback-speed">
        Скорость визуального воспроизведения
        <select
          data-testid="playback-speed"
          value={playbackMs}
          onChange={(event) => onPlaybackMs(Number(event.target.value))}
        >
          <option value={250}>Быстро</option>
          <option value={800}>Обычно</option>
          <option value={1600}>Медленно</option>
        </select>
      </label>
    </section>
  );
}
