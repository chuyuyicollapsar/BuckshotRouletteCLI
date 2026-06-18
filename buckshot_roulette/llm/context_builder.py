from __future__ import annotations

from buckshot_roulette.backend.models import GameEvent, GameSession, Room, RoomPlayer
from buckshot_roulette.backend.serializers import serialize_event
from buckshot_roulette.backend.services import TurnCoordinator


class LLMContextBuilder:
    def __init__(self, turn_coordinator: TurnCoordinator) -> None:
        self.turn_coordinator = turn_coordinator

    def build_context(
        self,
        room: Room,
        room_player: RoomPlayer,
        session: GameSession,
        *,
        max_events: int = 50,
    ) -> dict:
        state = self.turn_coordinator.build_visible_state(room, room_player)
        visible_events = self._visible_events(session.event_log, room_player.seat_index)
        return {
            "initial_info_memory": {
                "game_id": session.id,
                "players": [
                    {
                        "player_id": player.seat_index,
                        "name": player.name,
                        "type": player.type.value.lower(),
                    }
                    for player in room.players
                    if player.seat_index is not None
                ],
            },
            "action_event_list": [
                serialize_event(event).model_dump(mode="json")
                for event in visible_events[-max_events:]
            ],
            "current_visible_state": state.model_dump(mode="json"),
        }

    def _visible_events(
        self, events: list[GameEvent], seat_index: int | None
    ) -> list[GameEvent]:
        visible: list[GameEvent] = []
        for event in events:
            if event.visible_to == "ALL":
                visible.append(event)
            elif seat_index is not None and seat_index in event.visible_to:
                visible.append(event)
        return visible
