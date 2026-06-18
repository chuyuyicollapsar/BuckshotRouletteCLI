from __future__ import annotations

import json

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from buckshot_roulette.backend.events import EventPublisher
from buckshot_roulette.backend.models import RoomVisibility
from buckshot_roulette.backend.repositories import InMemoryStore
from buckshot_roulette.backend.schemas import (
    ActionRequest,
    AddAIPlayerRequest,
    AIPlayerPresetRequest,
    ChatRequest,
    CreateRoomRequest,
    CreateRoomResponse,
    EventEnvelope,
    JoinRoomRequest,
    JoinRoomResponse,
    LeaveRoomRequest,
    ModelPresetRequest,
    ProviderConfigRequest,
    ReadyRequest,
    RoomListItem,
    RoomResponse,
    StartGameRequest,
)
from buckshot_roulette.backend.serializers import (
    serialize_event,
    serialize_room,
    serialize_room_list_item,
)
from buckshot_roulette.backend.services import (
    AuthError,
    GameSessionService,
    RoomService,
    ServiceError,
    TurnCoordinator,
)
from buckshot_roulette.engine import GameEngine
from buckshot_roulette.llm.repositories import LLMConfigStore
from buckshot_roulette.llm.serializers import (
    ai_player_preset_to_dict,
    model_preset_to_dict,
    provider_to_public_dict,
)
from buckshot_roulette.llm.services import (
    LLMAdminService,
    LLMConfigError,
    LLMDecisionService,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Buckshot Roulette Backend")
    store = InMemoryStore()
    engine = GameEngine()
    room_service = RoomService(store)
    session_service = GameSessionService(store, engine)
    turn_coordinator = TurnCoordinator(room_service, session_service, engine)
    publisher = EventPublisher()
    llm_store = LLMConfigStore()
    llm_admin_service = LLMAdminService(llm_store)
    llm_decision_service = LLMDecisionService(llm_store)

    app.state.store = store
    app.state.room_service = room_service
    app.state.session_service = session_service
    app.state.turn_coordinator = turn_coordinator
    app.state.publisher = publisher
    app.state.llm_store = llm_store
    app.state.llm_admin_service = llm_admin_service
    app.state.llm_decision_service = llm_decision_service

    def _events_visible_to_player(events, seat_index):
        visible = []
        for event in events:
            if event.visible_to == "ALL":
                visible.append(event)
            elif seat_index is not None and seat_index in event.visible_to:
                visible.append(event)
        return visible

    async def publish_room_update(room, event_type, events=None, message=None):
        events = events or []

        def payload_for(player_id):
            player = next(
                room_player
                for room_player in room.players
                if room_player.id == player_id
            )
            visible_events = _events_visible_to_player(events, player.seat_index)
            return EventEnvelope(
                type=event_type,
                room=serialize_room(room),
                visible_state=turn_coordinator.build_visible_state(room, player),
                events=[serialize_event(event) for event in visible_events],
                message=message,
            ).model_dump(mode="json")

        await publisher.publish_personalized(room.room_code, payload_for)

    @app.exception_handler(ServiceError)
    async def service_error_handler(_, exc: ServiceError) -> JSONResponse:
        status_code = 401 if isinstance(exc, AuthError) else 400
        return JSONResponse({"detail": str(exc)}, status_code=status_code)

    @app.exception_handler(LLMConfigError)
    async def llm_error_handler(_, exc: LLMConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def key_error_handler(_, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/rooms", response_model=CreateRoomResponse)
    async def create_room(request: CreateRoomRequest) -> CreateRoomResponse:
        room, token = room_service.create_room(
            owner_name=request.player_name,
            room_name=request.room_name,
            visibility=RoomVisibility(request.visibility),
            max_players=request.max_players,
        )
        return CreateRoomResponse(
            room=serialize_room(room),
            player_id=token.player_id,
            player_token=token.token,
        )

    @app.get("/rooms", response_model=list[RoomListItem])
    async def list_rooms() -> list[RoomListItem]:
        return [serialize_room_list_item(room) for room in room_service.list_public_rooms()]

    @app.get("/rooms/{room_code}", response_model=RoomResponse)
    async def get_room(room_code: str) -> RoomResponse:
        return serialize_room(room_service.get_room(room_code))

    @app.post("/rooms/{room_code}/join", response_model=JoinRoomResponse)
    async def join_room(room_code: str, request: JoinRoomRequest) -> JoinRoomResponse:
        room, token = room_service.join_room(room_code, request.player_name)
        await publish_room_update(room, "room_updated")
        return JoinRoomResponse(
            room=serialize_room(room),
            player_id=token.player_id,
            player_token=token.token,
        )

    @app.post("/rooms/{room_code}/ai-players", response_model=RoomResponse)
    async def add_ai_player(
        room_code: str, request: AddAIPlayerRequest
    ) -> RoomResponse:
        snapshot = llm_admin_service.create_ai_snapshot(request.ai_player_preset_id)
        room = room_service.add_ai_player(room_code, request.player_token, snapshot)
        await publish_room_update(room, "room_updated")
        return serialize_room(room)

    @app.post("/rooms/{room_code}/ready", response_model=RoomResponse)
    async def set_ready(room_code: str, request: ReadyRequest) -> RoomResponse:
        room = room_service.set_ready(room_code, request.player_token, request.ready)
        await publish_room_update(room, "room_updated")
        return serialize_room(room)

    @app.post("/rooms/{room_code}/leave", response_model=RoomResponse)
    async def leave_room(room_code: str, request: LeaveRoomRequest) -> RoomResponse:
        room = room_service.leave_room(room_code, request.player_token)
        await publish_room_update(room, "room_updated")
        return serialize_room(room)

    @app.post("/rooms/{room_code}/start", response_model=EventEnvelope)
    async def start_game(room_code: str, request: StartGameRequest) -> EventEnvelope:
        session, events = turn_coordinator.start_game(room_code, request.player_token)
        room = room_service.get_room(room_code)
        envelope = EventEnvelope(
            type="game_started",
            room=serialize_room(room),
            events=[serialize_event(event) for event in events],
        )
        await publish_room_update(room, "game_started", events)
        return envelope

    @app.post("/rooms/{room_code}/actions", response_model=EventEnvelope)
    async def submit_action(room_code: str, request: ActionRequest) -> EventEnvelope:
        session, events = turn_coordinator.submit_action(
            room_code,
            request.player_token,
            request.revision,
            request.action,
        )
        room = room_service.get_room(room_code)
        player = room_service.require_player(room, request.player_token)
        visible_state = turn_coordinator.build_visible_state(room, player)
        envelope = EventEnvelope(
            type="action_result",
            events=[
                serialize_event(event)
                for event in _events_visible_to_player(events, player.seat_index)
            ],
            visible_state=visible_state,
        )
        await publish_room_update(room, "action_result", events)
        return envelope

    @app.post("/rooms/{room_code}/chat", response_model=EventEnvelope)
    async def chat(room_code: str, request: ChatRequest) -> EventEnvelope:
        _, event = turn_coordinator.append_chat(
            room_code,
            request.player_token,
            request.message,
        )
        room = room_service.get_room(room_code)
        envelope = EventEnvelope(type="chat_message", event=serialize_event(event))
        await publish_room_update(room, "chat_message", [event])
        return envelope

    @app.get("/rooms/{room_code}/visible-state")
    async def visible_state(
        room_code: str,
        player_token: str = Query(min_length=1),
    ):
        return turn_coordinator.build_visible_state_by_token(room_code, player_token)

    @app.websocket("/rooms/{room_code}/events")
    async def room_events(websocket: WebSocket, room_code: str, player_token: str) -> None:
        room = room_service.get_room(room_code)
        player = room_service.require_player(room, player_token)
        await publisher.connect(room.room_code, websocket, player.id)
        try:
            visible_state = turn_coordinator.build_visible_state(room, player)
            await websocket.send_json(
                EventEnvelope(
                    type="visible_state",
                    room=serialize_room(room),
                    visible_state=visible_state,
                ).model_dump(mode="json")
            )
            while True:
                raw_message = await websocket.receive_text()
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "chat_message":
                    message = str(data.get("message", "")).strip()
                    if message:
                        _, event = turn_coordinator.append_chat(
                            room.room_code,
                            player_token,
                            message,
                        )
                        await publish_room_update(room, "chat_message", [event])
        except WebSocketDisconnect:
            publisher.disconnect(room.room_code, websocket)

    @app.get("/ai-player-presets")
    async def list_enabled_ai_player_presets():
        return [
            ai_player_preset_to_dict(preset)
            for preset in llm_store.enabled_ai_player_presets()
        ]

    @app.get("/admin/llm/providers")
    async def admin_list_providers():
        return [
            provider_to_public_dict(provider)
            for provider in llm_store.list_providers()
        ]

    @app.post("/admin/llm/providers")
    async def admin_upsert_provider(request: ProviderConfigRequest):
        provider = llm_admin_service.create_provider(request.model_dump())
        return provider_to_public_dict(provider)

    @app.post("/admin/llm/providers/{provider_id}/test")
    async def admin_test_provider(provider_id: str):
        return llm_admin_service.test_provider(provider_id)

    @app.get("/admin/llm/model-presets")
    async def admin_list_model_presets():
        return [
            model_preset_to_dict(preset)
            for preset in llm_store.list_model_presets()
        ]

    @app.post("/admin/llm/model-presets")
    async def admin_upsert_model_preset(request: ModelPresetRequest):
        preset = llm_admin_service.create_model_preset(request.model_dump())
        return model_preset_to_dict(preset)

    @app.post("/admin/llm/model-presets/{preset_id}/test")
    async def admin_test_model_preset(preset_id: str):
        preset = llm_store.get_model_preset(preset_id)
        provider_result = llm_admin_service.test_provider(preset.provider_id)
        return {
            "ok": provider_result.ok,
            "message": provider_result.message,
            "details": {
                **provider_result.details,
                "model_preset_id": preset.id,
                "model_name": preset.model_name,
                "structured_output": (
                    "fake" if preset.provider_id == "fake_local" else "not_tested"
                ),
            },
        }

    @app.get("/admin/ai-player-presets")
    async def admin_list_ai_player_presets():
        return [
            ai_player_preset_to_dict(preset)
            for preset in llm_store.list_ai_player_presets()
        ]

    @app.post("/admin/ai-player-presets")
    async def admin_upsert_ai_player_preset(request: AIPlayerPresetRequest):
        preset = llm_admin_service.create_ai_player_preset(request.model_dump())
        return ai_player_preset_to_dict(preset)

    @app.post("/admin/ai-player-presets/{preset_id}/test-action")
    async def admin_test_ai_player_action(preset_id: str):
        return llm_decision_service.test_ai_action(preset_id)

    return app


app = create_app()
