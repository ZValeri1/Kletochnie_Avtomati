import type { SimulationStatus } from "../contracts";

export const simulationStatusPresentation: Record<
  SimulationStatus,
  { label: string; explanation: string }
> = {
  PREPARATION: {
    label: "Подготовка",
    explanation: "Настройте конфигурацию или начните траекторию.",
  },
  PAUSED: {
    label: "Пауза",
    explanation:
      "Можно выполнить один акт, запустить серию актов или открыть диагностику.",
  },
  RUNNING: {
    label: "Выполняется",
    explanation:
      "Симуляция выполняет атомарные акты; доступна безопасная пауза.",
  },
  PAUSED_WITH_ERROR: {
    label: "Пауза с ошибкой",
    explanation:
      "Можно повторить команду, отменить ошибку или вернуться по истории.",
  },
  STOPPED: {
    label: "Завершена",
    explanation: "Траектория завершена; для нового запуска выполните сброс.",
  },
  FAILED: {
    label: "Недостоверное состояние",
    explanation: "Продолжение невозможно; доступны просмотр, экспорт и сброс.",
  },
};
