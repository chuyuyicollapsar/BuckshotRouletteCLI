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
        action_events = [
            event for event in visible_events if event.event_type != "chat_message"
        ]
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
                for event in action_events[-max_events:]
            ],
            "current_visible_state": visible_state.model_dump(mode="json"),
        }

    def build_chat_context(
        self,
        room: Room,
        room_player: RoomPlayer,
        session: GameSession,
        trigger_event: GameEvent,
        *,
        max_chat_events: int = 20,
        max_game_events: int = 50,
    ) -> dict:
        snapshot = room_player.ai_preset_snapshot
        chat_events = [
            event for event in session.event_log if event.event_type == "chat_message"
        ]
        public_game_events = [
            event
            for event in session.event_log
            if event.event_type != "chat_message" and event.visible_to == "ALL"
        ]
        match = session.state.current_match_state
        return {
            "ai_profile": {
                "display_name": (
                    snapshot.display_name if snapshot is not None else room_player.name
                ),
                "rules_prompt": snapshot.rules_prompt if snapshot is not None else "",
                "persona_prompt": (
                    snapshot.persona_prompt if snapshot is not None else ""
                ),
                "chat_prompt": snapshot.chat_prompt if snapshot is not None else "",
                "chat_max_chars": snapshot.chat_max_chars if snapshot is not None else 0,
            },
            "trigger": self._chat_event_to_context(trigger_event),
            "chat_event_list": [
                self._chat_event_to_context(event)
                for event in chat_events[-max_chat_events:]
            ],
            "public_game_context": {
                "current_player_id": (
                    match.current_player_idx if match is not None else None
                ),
                "public_shell_counts": self._public_shell_counts(match),
                "players": (
                    [
                        {
                            "player_id": player.id,
                            "name": player.name,
                            "hp": player.hp,
                            "max_hp": player.max_hp,
                            "alive": player.alive,
                        }
                        for player in match.players
                    ]
                    if match is not None
                    else [
                        {
                            "player_id": player.seat_index,
                            "name": player.name,
                            "status": player.status.value,
                            "type": player.type.value.lower(),
                        }
                        for player in room.players
                        if player.seat_index is not None
                    ]
                ),
                "recent_game_events": [
                    serialize_event(event).model_dump(mode="json")
                    for event in public_game_events[-max_game_events:]
                ],
            },
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

    def _chat_event_to_context(self, event: GameEvent) -> dict:
        payload = event.payload or {}
        player_id = payload.get("player_seat_index", event.actor_player_id)
        name = payload.get("name", "")
        message = payload.get("message", event.message)
        return {
            "event_id": event.event_id,
            "player_id": player_id,
            "from_player_id": player_id,
            "name": name,
            "from_name": name,
            "message": message,
            "source": payload.get("source", "human"),
        }

    def _public_shell_counts(self, match) -> dict[str, int]:
        if match is None or not match.chambers:
            return {"remaining": 0}
        return {"remaining": len(match.chambers[match.chamber_index :])}
