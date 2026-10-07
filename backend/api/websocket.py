from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


def create_websocket_router(manager) -> APIRouter:
    router = APIRouter(tags=["events"])

    @router.websocket("/ws/simulations/{simulation_id}")
    async def simulation_stream(websocket: WebSocket, simulation_id: str):
        await websocket.accept()
        subscription = await manager.event_hub.subscribe(simulation_id)
        disconnect_task: asyncio.Task | None = None
        event_task: asyncio.Task | None = None

        async def wait_for_disconnect() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return

        try:
            snapshot = await manager.get_snapshot(simulation_id)
            await websocket.send_json(
                manager.event_hub.envelope(
                    simulation_id,
                    {
                        "type": "snapshot",
                        "snapshot": snapshot.model_dump(mode="json"),
                    },
                )
            )
            disconnect_task = asyncio.create_task(wait_for_disconnect())
            while True:
                event_task = asyncio.create_task(subscription.receive())
                done, _pending = await asyncio.wait(
                    {disconnect_task, event_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_task in done:
                    break
                await websocket.send_json(event_task.result())
                event_task = None
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            tasks = [task for task in (disconnect_task, event_task) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await subscription.close()

    return router
