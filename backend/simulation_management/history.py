from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryCheckpoint:
    state: object
    random_state: object
    source_revision: int = 0


@dataclass(frozen=True)
class AtomChange:
    atom_id: int
    source_site: str | None
    destination_site: str | None


@dataclass(frozen=True)
class HistoryDelta:
    atom_changes: tuple[AtomChange, ...]
    act_number_before: int
    act_number_after: int
    revision_before: int
    revision_after: int
    random_state_before: object
    random_state_after: object
    source_revision: int
    event_count_before: int
    event_count_after: int
    metric_count_before: int
    metric_count_after: int
    event_replacement_before: tuple | None = None
    event_replacement_after: tuple | None = None
    metric_replacement_before: tuple | None = None
    metric_replacement_after: tuple | None = None
    state_before: object | None = None
    state_after: object | None = None
    checkpoint_after: object | None = None


class SimulationHistory:
    DEFAULT_ACTION_LIMIT = 100
    DEFAULT_CHECKPOINT_INTERVAL = 50

    def __init__(
        self,
        initial_state,
        random_state,
        limit: int = DEFAULT_ACTION_LIMIT,
        *,
        source_revision: int = 0,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
    ) -> None:
        if limit < 1:
            raise ValueError("history limit must be positive")
        if checkpoint_interval < 1:
            raise ValueError("checkpoint interval must be positive")
        self.limit = limit
        self.checkpoint_interval = checkpoint_interval
        self.history_truncated = False
        initial_copy = deepcopy(initial_state)
        self._initial = HistoryCheckpoint(
            initial_copy, deepcopy(random_state), source_revision
        )
        self._current_state = self._clone_state(initial_copy, deep_journal=False)
        self._current_random_state = deepcopy(random_state)
        self._event_log = deepcopy(getattr(initial_copy, "events", []))
        self._metric_log = deepcopy(getattr(initial_copy, "metrics_points", []))
        self._entries: list[HistoryDelta] = []
        self._cursor = 0

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return self._cursor < len(self._entries)

    def current(self) -> HistoryCheckpoint:
        return self._checkpoint(
            self._current_state,
            self._current_random_state,
            self._source_revision_at(self._cursor),
        )

    def initial(self) -> HistoryCheckpoint:
        return self._checkpoint(
            self._initial.state,
            self._initial.random_state,
            self._initial.source_revision,
        )

    @property
    def retained_action_count(self) -> int:
        return len(self._entries)

    @property
    def history_limit(self) -> int:
        return self.limit

    @property
    def checkpoint_count(self) -> int:
        return 1 + sum(
            entry.checkpoint_after is not None or entry.state_after is not None
            for entry in self._entries
        )

    def commit(
        self,
        state,
        random_state,
        source_revision: int = 0,
        *,
        force_checkpoint: bool = False,
    ) -> HistoryCheckpoint:
        if self.can_redo:
            del self._entries[self._cursor :]
            self._truncate_logs_to_current()

        periodic_checkpoint = (
            (len(self._entries) + 1) % self.checkpoint_interval == 0
        )
        delta = self._make_delta(
            self._current_state,
            state,
            self._current_random_state,
            random_state,
            source_revision,
            force_checkpoint=force_checkpoint,
            periodic_checkpoint=periodic_checkpoint,
        )
        self._append_logs(delta, state)
        self._entries.append(delta)
        self._cursor += 1
        self._apply(delta, forward=True)

        if self.retained_action_count > self.limit:
            self._collapse_oldest_entries()
            self._cursor -= 1
            self.history_truncated = True

        return self._checkpoint(
            self._current_state,
            self._current_random_state,
            source_revision,
            deep_journal=False,
        )

    def undo(self) -> HistoryCheckpoint:
        if not self.can_undo:
            raise ValueError("No earlier simulation state")
        self._apply(self._entries[self._cursor - 1], forward=False)
        self._cursor -= 1
        return self.current()

    def redo(self) -> HistoryCheckpoint:
        if not self.can_redo:
            raise ValueError("No later simulation state")
        self._apply(self._entries[self._cursor], forward=True)
        self._cursor += 1
        return self.current()

    def peek_redo(self) -> HistoryCheckpoint:
        if not self.can_redo:
            raise ValueError("No later simulation state")
        return self._state_at(self._cursor + 1)

    def replace_current(self, checkpoint: HistoryCheckpoint) -> None:
        if self._cursor == 0:
            self._initial = self._checkpoint(
                checkpoint.state,
                checkpoint.random_state,
                checkpoint.source_revision,
            )
            self._current_state = self._clone_state(
                checkpoint.state, deep_journal=False
            )
            self._current_random_state = deepcopy(checkpoint.random_state)
            return
        previous = self._state_at(self._cursor - 1)
        replacement = self._make_delta(
            previous.state,
            checkpoint.state,
            previous.random_state,
            checkpoint.random_state,
            checkpoint.source_revision,
            force_checkpoint=True,
            periodic_checkpoint=False,
            preserve_logs=True,
        )
        self._entries[self._cursor - 1] = replacement
        self._current_state = self._clone_state(
            checkpoint.state, deep_journal=False
        )
        self._current_random_state = deepcopy(checkpoint.random_state)

    def export(self) -> dict:
        return {
            "cursor": self._cursor,
            "limit": self.limit,
            "history_truncated": self.history_truncated,
            "checkpoints": [
                {
                    "state": checkpoint.state,
                    "random_state": checkpoint.random_state,
                    "source_revision": checkpoint.source_revision,
                }
                for checkpoint in (
                    self._state_at(index)
                    for index in range(len(self._entries) + 1)
                )
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

        first = checkpoints[0]
        target = cls(
            first["state"],
            first["random_state"],
            limit=limit,
            source_revision=first.get("source_revision", 0),
        )
        for item in checkpoints[1:]:
            target.commit(
                item["state"],
                item["random_state"],
                source_revision=item.get("source_revision", 0),
            )
        while target._cursor > cursor:
            target._apply(target._entries[target._cursor - 1], forward=False)
            target._cursor -= 1
        target.history_truncated = bool(payload.get("history_truncated", False))
        return target

    def _make_delta(
        self,
        before,
        after,
        random_before,
        random_after,
        source_revision: int,
        *,
        force_checkpoint: bool,
        periodic_checkpoint: bool,
        preserve_logs: bool = False,
    ) -> HistoryDelta:
        if not self._is_simulation_state(before, after):
            return HistoryDelta(
                atom_changes=(),
                act_number_before=0,
                act_number_after=0,
                revision_before=0,
                revision_after=0,
                random_state_before=deepcopy(random_before),
                random_state_after=deepcopy(random_after),
                source_revision=source_revision,
                event_count_before=0,
                event_count_after=0,
                metric_count_before=0,
                metric_count_after=0,
                state_before=deepcopy(before),
                state_after=deepcopy(after),
            )

        configuration_changed = before.configuration != after.configuration
        full_checkpoint = force_checkpoint or configuration_changed
        atom_changes = () if full_checkpoint else self._atom_changes(before, after)
        event_replacements = self._journal_replacements(
            before.events, after.events, preserve_logs=preserve_logs
        )
        metric_replacements = self._journal_replacements(
            before.metrics_points,
            after.metrics_points,
            preserve_logs=preserve_logs,
        )
        return HistoryDelta(
            atom_changes=atom_changes,
            act_number_before=before.act_number,
            act_number_after=after.act_number,
            revision_before=before.revision,
            revision_after=after.revision,
            random_state_before=deepcopy(random_before),
            random_state_after=deepcopy(random_after),
            source_revision=source_revision,
            event_count_before=len(before.events),
            event_count_after=len(after.events),
            metric_count_before=len(before.metrics_points),
            metric_count_after=len(after.metrics_points),
            event_replacement_before=event_replacements[0],
            event_replacement_after=event_replacements[1],
            metric_replacement_before=metric_replacements[0],
            metric_replacement_after=metric_replacements[1],
            state_before=self._physical_copy(before) if full_checkpoint else None,
            state_after=self._physical_copy(after) if full_checkpoint else None,
            checkpoint_after=(
                self._physical_copy(after)
                if periodic_checkpoint and not full_checkpoint
                else None
            ),
        )

    @staticmethod
    def _is_simulation_state(before, after) -> bool:
        required = {
            "atoms", "occupied", "act_number", "revision", "events",
            "metrics_points", "configuration",
        }
        return all(hasattr(before, name) and hasattr(after, name) for name in required)

    @staticmethod
    def _atom_changes(before, after) -> tuple[AtomChange, ...]:
        appended = after.events[-1] if len(after.events) == len(before.events) + 1 else None
        if isinstance(appended, dict):
            atom_id = appended.get("source_atom_id")
            if isinstance(atom_id, int) and before.atoms.get(atom_id) != after.atoms.get(atom_id):
                return (
                    AtomChange(
                        atom_id,
                        before.atoms.get(atom_id),
                        after.atoms.get(atom_id),
                    ),
                )
        return tuple(
            AtomChange(atom_id, before.atoms.get(atom_id), after.atoms.get(atom_id))
            for atom_id in before.atoms.keys() | after.atoms.keys()
            if before.atoms.get(atom_id) != after.atoms.get(atom_id)
        )

    @staticmethod
    def _journal_replacements(before: list, after: list, *, preserve_logs: bool):
        if not preserve_logs and len(after) == len(before) + 1:
            return None, None
        if preserve_logs and len(after) >= len(before):
            return None, None
        return tuple(deepcopy(before)), tuple(deepcopy(after))

    def _append_logs(self, delta: HistoryDelta, state) -> None:
        if not self._is_simulation_state(self._current_state, state):
            return
        if delta.event_replacement_after is None:
            del self._event_log[delta.event_count_before :]
            self._event_log.extend(deepcopy(state.events[delta.event_count_before :]))
        else:
            self._event_log[:] = deepcopy(delta.event_replacement_after)
        if delta.metric_replacement_after is None:
            del self._metric_log[delta.metric_count_before :]
            self._metric_log.extend(
                deepcopy(state.metrics_points[delta.metric_count_before :])
            )
        else:
            self._metric_log[:] = deepcopy(delta.metric_replacement_after)

    def _apply(self, delta: HistoryDelta, *, forward: bool) -> None:
        full_state = delta.state_after if forward else delta.state_before
        if full_state is not None and self._is_simulation_state(full_state, full_state):
            events = self._current_state.events
            metrics = self._current_state.metrics_points
            self._current_state = self._clone_state(full_state, deep_journal=False)
            self._current_state.events = events
            self._current_state.metrics_points = metrics
        elif full_state is not None:
            self._current_state = deepcopy(full_state)

        if self._is_simulation_state(self._current_state, self._current_state):
            for change in delta.atom_changes:
                destination = change.destination_site if forward else change.source_site
                current = self._current_state.atoms.get(change.atom_id)
                if current is not None:
                    self._current_state.occupied.pop(current, None)
                if destination is None:
                    self._current_state.atoms.pop(change.atom_id, None)
                else:
                    self._current_state.atoms[change.atom_id] = destination
                    self._current_state.occupied[destination] = change.atom_id
            self._current_state.act_number = (
                delta.act_number_after if forward else delta.act_number_before
            )
            self._current_state.revision = (
                delta.revision_after if forward else delta.revision_before
            )
            self._restore_journal(delta, forward=forward, events=True)
            self._restore_journal(delta, forward=forward, events=False)
        elif full_state is not None:
            self._current_state = deepcopy(full_state)
        self._current_random_state = deepcopy(
            delta.random_state_after if forward else delta.random_state_before
        )

    def _restore_journal(
        self, delta: HistoryDelta, *, forward: bool, events: bool
    ) -> None:
        before_replacement = (
            delta.event_replacement_before if events else delta.metric_replacement_before
        )
        after_replacement = (
            delta.event_replacement_after if events else delta.metric_replacement_after
        )
        replacement = after_replacement if forward else before_replacement
        count = (
            (delta.event_count_after if forward else delta.event_count_before)
            if events
            else (delta.metric_count_after if forward else delta.metric_count_before)
        )
        target = self._current_state.events if events else self._current_state.metrics_points
        log = self._event_log if events else self._metric_log
        if replacement is not None:
            target[:] = deepcopy(replacement)
        elif count == len(target) + 1:
            target.append(deepcopy(log[count - 1]))
        elif count == len(target) - 1:
            target.pop()
        else:
            target[:] = deepcopy(log[:count])

    def _state_at(self, index: int) -> HistoryCheckpoint:
        if not 0 <= index <= len(self._entries):
            raise ValueError("History cursor is outside retained checkpoints")
        saved_state = self._current_state
        saved_random = self._current_random_state
        start_index = 0
        state = self._clone_state(self._initial.state, deep_journal=True)
        random_state = deepcopy(self._initial.random_state)
        source_revision = self._initial.source_revision
        for candidate_index in range(index, 0, -1):
            entry = self._entries[candidate_index - 1]
            checkpoint = entry.state_after or entry.checkpoint_after
            if checkpoint is None:
                continue
            if self._is_simulation_state(checkpoint, checkpoint):
                state = self._physical_copy(checkpoint)
                state.events = deepcopy(self._event_log[: entry.event_count_after])
                state.metrics_points = deepcopy(
                    self._metric_log[: entry.metric_count_after]
                )
            else:
                state = deepcopy(checkpoint)
            random_state = deepcopy(entry.random_state_after)
            source_revision = entry.source_revision
            start_index = candidate_index
            break
        self._current_state = state
        self._current_random_state = random_state
        try:
            for entry in self._entries[start_index:index]:
                self._apply(entry, forward=True)
                source_revision = entry.source_revision
            return self._checkpoint(
                self._current_state, self._current_random_state, source_revision
            )
        finally:
            self._current_state = saved_state
            self._current_random_state = saved_random

    def _truncate_logs_to_current(self) -> None:
        if not self._is_simulation_state(self._current_state, self._current_state):
            return
        self._event_log[:] = deepcopy(self._current_state.events)
        self._metric_log[:] = deepcopy(self._current_state.metrics_points)

    def _collapse_oldest_entries(self) -> None:
        first, second = self._entries[:2]
        retained_state = self._physical_copy(self._initial.state)
        retained_state = self._apply_physical(retained_state, first, forward=True)
        retained_state = self._apply_physical(retained_state, second, forward=True)
        jump = HistoryDelta(
            atom_changes=(),
            act_number_before=getattr(self._initial.state, "act_number", 0),
            act_number_after=second.act_number_after,
            revision_before=getattr(self._initial.state, "revision", 0),
            revision_after=second.revision_after,
            random_state_before=deepcopy(self._initial.random_state),
            random_state_after=deepcopy(second.random_state_after),
            source_revision=second.source_revision,
            event_count_before=len(getattr(self._initial.state, "events", [])),
            event_count_after=second.event_count_after,
            metric_count_before=len(
                getattr(self._initial.state, "metrics_points", [])
            ),
            metric_count_after=second.metric_count_after,
            state_before=self._physical_copy(self._initial.state),
            state_after=retained_state,
        )
        self._entries[:2] = [jump]

    def _apply_physical(self, state, delta: HistoryDelta, *, forward: bool):
        full_state = delta.state_after if forward else delta.state_before
        if full_state is not None:
            state = self._physical_copy(full_state)
        if not self._is_simulation_state(state, state):
            return deepcopy(full_state)
        for change in delta.atom_changes:
            destination = change.destination_site if forward else change.source_site
            current = state.atoms.get(change.atom_id)
            if current is not None:
                state.occupied.pop(current, None)
            if destination is None:
                state.atoms.pop(change.atom_id, None)
            else:
                state.atoms[change.atom_id] = destination
                state.occupied[destination] = change.atom_id
        state.act_number = delta.act_number_after if forward else delta.act_number_before
        state.revision = delta.revision_after if forward else delta.revision_before
        return state

    def _source_revision_at(self, index: int) -> int:
        return (
            self._initial.source_revision
            if index == 0
            else self._entries[index - 1].source_revision
        )

    @staticmethod
    def _physical_copy(state):
        if hasattr(state, "transition_copy"):
            return state.transition_copy(include_history=False)
        return deepcopy(state)

    @classmethod
    def _clone_state(cls, state, *, deep_journal: bool):
        if not hasattr(state, "transition_copy"):
            return deepcopy(state)
        cloned = state.transition_copy(include_history=False)
        cloned.events = deepcopy(state.events) if deep_journal else list(state.events)
        cloned.metrics_points = (
            deepcopy(state.metrics_points)
            if deep_journal
            else list(state.metrics_points)
        )
        return cloned

    @classmethod
    def _checkpoint(
        cls,
        state,
        random_state,
        source_revision: int,
        *,
        deep_journal: bool = True,
    ) -> HistoryCheckpoint:
        return HistoryCheckpoint(
            cls._clone_state(state, deep_journal=deep_journal),
            deepcopy(random_state),
            source_revision,
        )
