from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from buckshot_roulette.models import GameState, MatchConfig
from buckshot_roulette.llm.models import AIPlayerPresetSnapshot


Visibility = Literal["ALL"] | list[int]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RoomVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class RoomStatus(str, Enum):
    LOBBY = "LOBBY"
    IN_GAME = "IN_GAME"
    FINISHED = "FINISHED"
    CLOSED = "CLOSED"


class RoomPlayerType(str, Enum):
    HUMAN = "HUMAN"
    AI = "AI"


class RoomPlayerStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    READY = "READY"
    LEFT = "LEFT"


@dataclass(slots=True)
class RoomPlayer:
    id: str
    name: str
    type: RoomPlayerType
    status: RoomPlayerStatus
    token_hash: str | None = None
    seat_index: int | None = None
    ai_preset_snapshot: AIPlayerPresetSnapshot | None = None
    joined_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Room:
    id: str
    room_code: str
    name: str
    visibility: RoomVisibility
    status: RoomStatus
    owner_player_id: str
    max_players: int
    config: MatchConfig
    players: list[RoomPlayer]
    game_session_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class GameEvent:
    event_id: int
    room_id: str
    game_id: str | None
    revision: int
    event_type: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    match_index: int | None = None
    reload_round: int | None = None
    actor_player_id: int | None = None
    visible_to: Visibility = "ALL"
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class GameSession:
    id: str
    room_id: str
    state: GameState
    revision: int = 0
    event_log: list[GameEvent] = field(default_factory=list)


@dataclass(slots=True)
class PlayerToken:
    player_id: str
    token: str
