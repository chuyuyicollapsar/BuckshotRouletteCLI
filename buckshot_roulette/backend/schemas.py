from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str


class CreateRoomRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=32)
    room_name: str | None = Field(default=None, max_length=64)
    visibility: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"
    max_players: int = Field(default=4, ge=2, le=4)


class JoinRoomRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=32)


class ReadyRequest(BaseModel):
    player_token: str
    ready: bool


class LeaveRoomRequest(BaseModel):
    player_token: str


class StartGameRequest(BaseModel):
    player_token: str


class ActionRequest(BaseModel):
    player_token: str
    revision: int
    action: dict[str, Any]


class ChatRequest(BaseModel):
    player_token: str
    message: str = Field(min_length=1, max_length=500)


class RoomPlayerResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    seat_index: int | None
    is_owner: bool = False


class RoomResponse(BaseModel):
    room_code: str
    name: str
    visibility: str
    status: str
    owner_player_id: str
    max_players: int
    players: list[RoomPlayerResponse]
    game_session_id: str | None
    created_at: datetime
    updated_at: datetime


class RoomListItem(BaseModel):
    room_code: str
    name: str
    status: str
    player_count: int
    max_players: int
    created_at: datetime


class CreateRoomResponse(BaseModel):
    room: RoomResponse
    player_id: str
    player_token: str


class JoinRoomResponse(BaseModel):
    room: RoomResponse
    player_id: str
    player_token: str


class GameEventResponse(BaseModel):
    event_id: int
    room_id: str
    game_id: str | None
    revision: int
    event_type: str
    message: str
    payload: dict[str, Any]
    match_index: int | None
    reload_round: int | None
    actor_player_id: int | None
    visible_to: str | list[int]
    created_at: datetime


class PlayerVisibleStateResponse(BaseModel):
    room_id: str
    room_code: str
    game_id: str | None
    player_id: str
    player_seat_index: int | None
    revision: int
    room_status: str
    visible_players: list[dict[str, Any]]
    public_shell_counts: dict[str, int]
    current_player_id: int | None
    legal_actions: list[dict[str, Any]]
    visible_events: list[GameEventResponse]
    match_results: list[int]


class EventEnvelope(BaseModel):
    type: str
    room: RoomResponse | None = None
    visible_state: PlayerVisibleStateResponse | None = None
    event: GameEventResponse | None = None
    events: list[GameEventResponse] = Field(default_factory=list)
    message: str | None = None
