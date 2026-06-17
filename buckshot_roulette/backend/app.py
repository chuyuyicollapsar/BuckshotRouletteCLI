from __future__ import annotations

import json

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from buckshot_roulette.backend.events import EventPublisher
from buckshot_roulette.backend.models import RoomVisibility
from buckshot_roulette.backend.repositories import InMemoryStore
from buckshot_roulette.backend.schemas import (
    ActionRequest,
    ChatRequest,
    CreateRoomRequest,
    CreateRoomResponse,
    EventEnvelope,
    JoinRoomRequest,
    JoinRoomResponse,
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


def create_app() -> FastAPI:
    app = FastAPI(title="Buckshot Roulette Backend")
    store = InMemoryStore()
    engine = GameEngine()
    room_service = RoomService(store)
    session_service = GameSessionService(store, engine)
    turn_coordinator = TurnCoordinator(room_service, session_service, engine)
    publisher = EventPublisher()

    app.state.store = store
    app.state.room_service = room_service
    app.state.session_service = session_service
    app.state.turn_coordinator = turn_coordinator
    app.state.publisher = publisher

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

    @app.post("/rooms/{room_code}/ready", response_model=RoomResponse)
    async def set_ready(room_code: str, request: ReadyRequest) -> RoomResponse:
        room = room_service.set_ready(room_code, request.player_token, request.ready)
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

    return app


app = create_app()
