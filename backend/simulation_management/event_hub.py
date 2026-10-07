from __future__ import annotations

import asyncio
from collections import defaultdict

from backend.contracts.simulation import STREAM_MESSAGE_ADAPTER


class EventSubscription:
    def __init__(self, hub, simulation_id: str) -> None:
        self.hub = hub
        self.simulation_id = simulation_id
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def receive(self):
        return await self.queue.get()

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.hub._remove(self)


class EventHub:
    def __init__(self) -> None:
        self._subscriptions: dict[str, set[EventSubscription]] = defaultdict(set)
        self._message_ids: dict[str, int] = defaultdict(int)

    async def subscribe(self, simulation_id: str) -> EventSubscription:
        subscription = EventSubscription(self, simulation_id)
        self._subscriptions[simulation_id].add(subscription)
        return subscription

    async def publish(self, simulation_id: str, message):
        published = self.envelope(simulation_id, message)
        for subscription in tuple(self._subscriptions.get(simulation_id, ())):
            if not subscription.closed:
                await subscription.queue.put(deepcopy_message(published))
        return STREAM_MESSAGE_ADAPTER.validate_python(published).model_dump(mode="json")

    def envelope(self, simulation_id: str, message):
        published = deepcopy_message(message)
        self._message_ids[simulation_id] += 1
        published["message_id"] = self._message_ids[simulation_id]
        published.setdefault("schema_version", 1)
        published.setdefault("simulation_id", simulation_id)
        if "revision" not in published:
            for field in ("snapshot", "summary", "error", "event"):
                nested = published.get(field)
                if isinstance(nested, dict) and "revision" in nested:
                    published["revision"] = nested["revision"]
                    break
        return published

    def _remove(self, subscription: EventSubscription) -> None:
        subscriptions = self._subscriptions.get(subscription.simulation_id)
        if subscriptions is not None:
            subscriptions.discard(subscription)
            if not subscriptions:
                self._subscriptions.pop(subscription.simulation_id, None)


def deepcopy_message(message):
    from copy import deepcopy

    return deepcopy(message)
