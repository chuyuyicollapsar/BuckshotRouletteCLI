from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from buckshot_roulette.llm.prompt_library import (
    DEFAULT_DECISION_PROMPT_ID,
    DEFAULT_RULES_PROMPT_ID,
)


class ErrorResponse(BaseModel):
    detail: str


class CreateRoomRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=32)
    room_name: str | None = Field(default=None, max_length=64)
    visibility: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"
    max_players: int = Field(default=4, ge=2, le=4)


class JoinRoomRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=32)


class AddAIPlayerRequest(BaseModel):
    player_token: str
    ai_player_preset_id: str = Field(min_length=1)


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
    ai_preset_id: str | None = None


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


class ProviderConfigRequest(BaseModel):
    id: str
    display_name: str | None = None
    type: str = "third_party"
    protocol: str
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    class_path: str | None = None
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ModelPresetRequest(BaseModel):
    id: str
    display_name: str | None = None
    provider_id: str
    model_name: str
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 2
    extra: dict[str, Any] = Field(default_factory=dict)


class AIPlayerPresetRequest(BaseModel):
    id: str
    display_name: str | None = None
    enabled: bool = True
    model_preset_id: str
    rules_prompt_id: str = DEFAULT_RULES_PROMPT_ID
    decision_prompt_id: str = DEFAULT_DECISION_PROMPT_ID
    custom_rules_prompt: str | None = None
    custom_decision_prompt: str | None = None
    persona_prompt: str = ""
    strategy_prompt: str = ""
    chat_enabled: bool = False
    chat_prompt: str = ""
    chat_trigger_mode: str = "mention"
    chat_model_preset_id: str | None = None
    chat_max_chars: int = 160
    chat_cooldown_seconds: int = 5
    max_item_actions_per_turn: int = 8
    max_parse_failures_per_turn: int = 2
    max_illegal_actions_per_turn: int = 2
    fallback_policy: str = "conservative_shot"


class AIActionTestRequest(BaseModel):
    context: dict[str, Any] | None = None
