import type { SimulationStatus } from "../contracts";

export type CommandAvailability = {
  configure: boolean;
  boundary: boolean;
  add: boolean;
  remove: boolean;
  move: boolean;
  start: boolean;
  step: boolean;
  run: boolean;
  pause: boolean;
  stop: boolean;
  reset: boolean;
  undo: boolean;
  redo: boolean;
  diagnostics: boolean;
  retry: boolean;
  acknowledge: boolean;
};

export function commandAvailability(
  status: SimulationStatus,
  history: { can_undo: boolean; can_redo: boolean },
): CommandAvailability {
  const preparation = status === "PREPARATION";
  const paused = status === "PAUSED";
  const running = status === "RUNNING";
  const recoverable = status === "PAUSED_WITH_ERROR";
  const terminal = status === "STOPPED" || status === "FAILED";

  return {
    configure: preparation,
    boundary: preparation,
    add: preparation,
    remove: preparation,
    move: preparation || paused,
    start: preparation,
    step: preparation || paused,
    run: preparation || paused,
    pause: running,
    stop: paused || running,
    reset: paused || recoverable || terminal,
    undo:
      history.can_undo &&
      (preparation || paused || running || recoverable),
    redo: history.can_redo && (preparation || paused || running),
    diagnostics: paused,
    retry: recoverable,
    acknowledge: recoverable,
  };
}
