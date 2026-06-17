from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from typing import Any, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketState


@dataclass(eq=False, slots=True)
class RoomConnection:
    websocket: WebSocket
    player_id: str


class EventPublisher:
    def __init__(self) -> None:
        self._connections: dict[str, list[RoomConnection]] = defaultdict(list)

    async def connect(
        self, room_code: str, websocket: WebSocket, player_id: str
    ) -> None:
        await websocket.accept()
        self._connections[room_code].append(
            RoomConnection(websocket=websocket, player_id=player_id)
        )

    def disconnect(self, room_code: str, websocket: WebSocket) -> None:
        connections = self._connections.get(room_code)
        if connections is None:
            return
        self._connections[room_code] = [
            connection
            for connection in connections
            if connection.websocket is not websocket
        ]
        if not self._connections[room_code]:
            self._connections.pop(room_code, None)

    async def publish(self, room_code: str, payload: dict[str, Any]) -> None:
        await self.publish_personalized(room_code, lambda _: payload)

    async def publish_personalized(
        self,
        room_code: str,
        payload_factory: Callable[[str], dict[str, Any]],
    ) -> None:
        connections = list(self._connections.get(room_code, []))
        if not connections:
            return
        stale: list[RoomConnection] = []
        for connection in connections:
            websocket = connection.websocket
            if websocket.application_state != WebSocketState.CONNECTED:
                stale.append(connection)
                continue
            try:
                payload = payload_factory(connection.player_id)
                encoded = json.dumps(payload, ensure_ascii=False, default=str)
                await websocket.send_text(encoded)
            except RuntimeError:
                stale.append(connection)
        for connection in stale:
            self.disconnect(room_code, connection.websocket)
