"""WebSocket hub for live dashboard updates."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

router = APIRouter()


class WebSocketHub:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, recording_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.connections[recording_id].add(websocket)

    async def disconnect(self, recording_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self.connections.get(recording_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self.connections.pop(recording_id, None)

    async def broadcast(self, recording_id: str, event_type: str, payload: dict[str, Any]) -> None:
        message = jsonable_encoder(
            {
                "type": event_type,
                "recording_id": recording_id,
                "payload": payload,
            }
        )
        async with self._lock:
            targets = list(self.connections.get(recording_id, set()))
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(recording_id, websocket)


ws_hub = WebSocketHub()


@router.websocket("/ws/{recording_id}")
async def recording_ws(websocket: WebSocket, recording_id: str) -> None:
    await ws_hub.connect(recording_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_hub.disconnect(recording_id, websocket)
