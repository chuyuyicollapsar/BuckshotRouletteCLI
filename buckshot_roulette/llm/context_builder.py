from __future__ import annotations

from buckshot_roulette.backend.models import GameEvent, GameSession, Room, RoomPlayer
from buckshot_roulette.backend.schemas import PlayerVisibleStateResponse
from buckshot_roulette.backend.serializers import serialize_event


class LLMContextBuilder:
    def build_context(
        self,
        room: Room,
        room_player: RoomPlayer,
        session: GameSession,
        visible_state: PlayerVisibleStateResponse,
        *,
        max_events: int = 50,
    ) -> dict:
        visible_events = self._visible_events(session.event_log, room_player.seat_index)
        snapshot = room_player.ai_preset_snapshot
        return {
            "ai_profile": {
                "display_name": (
                    snapshot.display_name if snapshot is not None else room_player.name
                ),
                "rules_prompt": snapshot.rules_prompt if snapshot is not None else "",
                "decision_prompt": (
                    snapshot.decision_prompt if snapshot is not None else ""
                ),
                "persona_prompt": (
                    snapshot.persona_prompt if snapshot is not None else ""
                ),
                "strategy_prompt": (
                    snapshot.strategy_prompt if snapshot is not None else ""
                ),
            },
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
            "current_visible_state": visible_state.model_dump(mode="json"),
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
