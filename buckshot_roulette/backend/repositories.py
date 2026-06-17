from __future__ import annotations

from buckshot_roulette.backend.models import GameSession, Room


class InMemoryStore:
    def __init__(self) -> None:
        self.rooms_by_code: dict[str, Room] = {}
        self.sessions_by_id: dict[str, GameSession] = {}

    def add_room(self, room: Room) -> None:
        self.rooms_by_code[room.room_code] = room

    def get_room(self, room_code: str) -> Room | None:
        return self.rooms_by_code.get(room_code.upper())

    def list_rooms(self) -> list[Room]:
        return list(self.rooms_by_code.values())

    def add_session(self, session: GameSession) -> None:
        self.sessions_by_id[session.id] = session

    def get_session(self, session_id: str | None) -> GameSession | None:
        if session_id is None:
            return None
        return self.sessions_by_id.get(session_id)
