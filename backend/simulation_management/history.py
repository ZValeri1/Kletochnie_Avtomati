from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryCheckpoint:
    state: object
    random_state: object
    source_revision: int = 0


class SimulationHistory:
    DEFAULT_ACTION_LIMIT = 100

    def __init__(
        self,
        initial_state,
        random_state,
        limit: int = DEFAULT_ACTION_LIMIT,
        *,
        source_revision: int = 0,
    ) -> None:
        if limit < 1:
            raise ValueError("history limit must be positive")
        self.limit = limit
        self.history_truncated = False
        self._checkpoints = [
            HistoryCheckpoint(
                deepcopy(initial_state), deepcopy(random_state), source_revision
            )
        ]
        self._cursor = 0

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._checkpoints) - 1

    def current(self) -> HistoryCheckpoint:
        return deepcopy(self._checkpoints[self._cursor])

    def initial(self) -> HistoryCheckpoint:
        return deepcopy(self._checkpoints[0])

    @property
    def retained_action_count(self) -> int:
        return len(self._checkpoints) - 1

    @property
    def history_limit(self) -> int:
        return self.limit

    def commit(
        self, state, random_state, source_revision: int = 0
    ) -> HistoryCheckpoint:
        del self._checkpoints[self._cursor + 1 :]
        checkpoint = HistoryCheckpoint(
            deepcopy(state), deepcopy(random_state), source_revision
        )
        self._checkpoints.append(checkpoint)
        if self.retained_action_count > self.limit:
            self._checkpoints.pop(1)
            self.history_truncated = True
        self._cursor = len(self._checkpoints) - 1
        return deepcopy(checkpoint)

    def undo(self) -> HistoryCheckpoint:
        if not self.can_undo:
            raise ValueError("No earlier simulation state")
        self._cursor -= 1
        return deepcopy(self._checkpoints[self._cursor])

    def redo(self) -> HistoryCheckpoint:
        if not self.can_redo:
            raise ValueError("No later simulation state")
        self._cursor += 1
        return deepcopy(self._checkpoints[self._cursor])

    def peek_redo(self) -> HistoryCheckpoint:
        if not self.can_redo:
            raise ValueError("No later simulation state")
        return deepcopy(self._checkpoints[self._cursor + 1])

    def replace_current(self, checkpoint: HistoryCheckpoint) -> None:
        self._checkpoints[self._cursor] = deepcopy(checkpoint)

    def export(self) -> dict:
        return {
            "cursor": self._cursor,
            "limit": self.limit,
            "history_truncated": self.history_truncated,
            "checkpoints": [
                {
                    "state": deepcopy(item.state),
                    "random_state": deepcopy(item.random_state),
                    "source_revision": item.source_revision,
                }
                for item in self._checkpoints
            ],
        }

    @classmethod
    def restore(cls, payload: dict):
        checkpoints = payload["checkpoints"]
        if not isinstance(checkpoints, list) or not checkpoints:
            raise ValueError("History must contain the protected initial checkpoint")
        cursor = payload["cursor"]
        if not isinstance(cursor, int) or not 0 <= cursor < len(checkpoints):
            raise ValueError("History cursor is outside retained checkpoints")
        limit = payload.get("limit", cls.DEFAULT_ACTION_LIMIT)
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("History limit must be positive")
        if len(checkpoints) > limit + 1:
            raise ValueError("History exceeds the configured action limit")
        target = cls(
            checkpoints[0]["state"],
            checkpoints[0]["random_state"],
            limit=limit,
            source_revision=checkpoints[0].get("source_revision", 0),
        )
        target._checkpoints = [
            HistoryCheckpoint(
                deepcopy(item["state"]),
                deepcopy(item["random_state"]),
                item.get("source_revision", 0),
            )
            for item in checkpoints
        ]
        target._cursor = cursor
        target.history_truncated = bool(payload.get("history_truncated", False))
        return target
