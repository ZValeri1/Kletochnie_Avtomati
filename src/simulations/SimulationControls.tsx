import type { SimulationRecord } from "../store/simulationStore";
import { commandAvailability } from "./capabilities";
import { simulationStatusPresentation } from "./statusPresentation";

export type RunMode = "visual" | "fast";

const commandDescriptions = {
  start: "Фиксирует начальную структуру и переводит симуляцию в паузу.",
  step: "Выполняет один атомарный акт и сразу обновляет модель и графики.",
  run: "Запускает непрерывный расчёт в выбранном ниже режиме.",
  pause: "Безопасно завершает текущий акт и ставит расчёт на паузу.",
  stop: "Завершает траекторию; продолжить её можно только после сброса.",
  reset: "Возвращает траекторию к исходной структуре.",
  undo: "Возвращает предыдущее сохранённое состояние.",
  redo: "Повторно применяет отменённое состояние.",
  retry: "Повторяет команду, завершившуюся восстанавливаемой ошибкой.",
  acknowledge: "Закрывает сообщение об ошибке без повторения команды.",
} as const;

export function SimulationControls({
  record,
  onCommand,
  onRemove,
  playbackMs,
  onPlaybackMs,
  runMode,
  onRunMode,
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
  runMode: RunMode;
  onRunMode: (mode: RunMode) => void;
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
  const statusExplanation =
    record.summary.status === "RUNNING"
      ? record.summary.run_mode === "fast"
        ? "Быстрый расчёт без отображения структуры; графики обновляются в реальном времени."
        : "Обычный расчёт: структура и графики обновляются после каждого акта."
      : status.explanation;
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
      title={commandDescriptions[command]}
    >
      {label}
    </button>
  );
  return (
    <section className="panel controls">
      <h2>Управление</h2>
      <div className="control-status" role="status">
        <strong>{status.label}</strong>
        <span>{statusExplanation}</span>
      </div>
      <fieldset
        className="run-mode-picker"
        disabled={record.summary.status === "RUNNING"}
      >
        <legend>Режим запуска</legend>
        <label className={runMode === "visual" ? "selected" : ""}>
          <input
            data-testid="run-mode-visual"
            type="radio"
            name="run-mode"
            value="visual"
            checked={runMode === "visual"}
            onChange={() => onRunMode("visual")}
          />
          <span>
            <strong>Обычный</strong>
            <small>с отображением</small>
          </span>
        </label>
        <label className={runMode === "fast" ? "selected" : ""}>
          <input
            data-testid="run-mode-fast"
            type="radio"
            name="run-mode"
            value="fast"
            checked={runMode === "fast"}
            onChange={() => onRunMode("fast")}
          />
          <span>
            <strong>Быстрый</strong>
            <small>без отображения</small>
          </span>
        </label>
      </fieldset>
      <p className="run-mode-note">
        {runMode === "visual"
          ? "Структура и графики обновляются после каждого акта."
          : "Структура скрыта, графики обновляются во время расчёта."}
      </p>
      <div className="control-group">
        <h3>Ход симуляции</h3>
        <div className="control-buttons">
          {button("start", "Начать", available.start, "start-simulation")}
          {button("step", "Один акт", available.step, "step-simulation")}
          {button(
            "run",
            runMode === "visual"
              ? "Запустить с отображением"
              : "Запустить быстро",
            available.run,
            "run-selected-simulation",
          )}
          {button(
            "pause",
            "Пауза",
            available.pause,
            "pause-selected-simulation",
          )}
          {button("stop", "Завершить", available.stop)}
        </div>
      </div>
      <div className="control-group">
        <h3>История и восстановление</h3>
        <div className="control-buttons">
          {button("undo", "Назад", available.undo, "undo-simulation")}
          {button("redo", "Вперёд", available.redo, "redo-simulation")}
          {button("reset", "Сбросить", available.reset)}
          {button("retry", "Повторить", available.retry)}
          {button("acknowledge", "Закрыть ошибку", available.acknowledge)}
        </div>
      </div>
      <div className="history-summary">
        Сохранено действий: {history.retained_action_count} из{" "}
        {history.history_limit}
        {history.history_truncated && (
          <strong> · ранние действия усечены</strong>
        )}
      </div>
      <label className="playback-speed">
        Интервал кадров обычного режима
        <select
          data-testid="playback-speed"
          value={playbackMs}
          onChange={(event) => onPlaybackMs(Number(event.target.value))}
        >
          <option value={0}>Максимальная — без задержки</option>
          <option value={250}>0,25 с — быстро</option>
          <option value={800}>0,8 с — обычно</option>
          <option value={1600}>1,6 с — медленно</option>
        </select>
      </label>
      <details className="control-help">
        <summary>Что делают кнопки</summary>
        <dl>
          {(
            Object.entries(commandDescriptions) as [
              keyof typeof commandDescriptions,
              string,
            ][]
          ).map(([command, description]) => (
            <div key={command}>
              <dt>
                {command === "start"
                  ? "Начать"
                  : command === "step"
                    ? "Один акт"
                    : command === "run"
                      ? "Запустить"
                      : command === "pause"
                        ? "Пауза"
                        : command === "stop"
                          ? "Завершить"
                          : command === "reset"
                            ? "Сбросить"
                            : command === "undo"
                              ? "Назад"
                              : command === "redo"
                                ? "Вперёд"
                                : command === "retry"
                                  ? "Повторить"
                                  : "Закрыть ошибку"}
              </dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
      </details>
      <button
        className="remove-session"
        data-testid="remove-simulation"
        onClick={onRemove}
      >
        Удалить сессию
      </button>
    </section>
  );
}
