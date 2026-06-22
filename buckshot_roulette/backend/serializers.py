from __future__ import annotations

from typing import Any

from buckshot_roulette.backend.models import GameEvent, Room, RoomPlayer
from buckshot_roulette.backend.schemas import (
    GameEventResponse,
    RoomListItem,
    RoomPlayerResponse,
    RoomResponse,
)
from buckshot_roulette.models import ItemType, MatchState, Player


def serialize_room_player(player: RoomPlayer, room: Room) -> RoomPlayerResponse:
    return RoomPlayerResponse(
        id=player.id,
        name=player.name,
        type=player.type.value,
        status=player.status.value,
        seat_index=player.seat_index,
        is_owner=player.id == room.owner_player_id,
        ai_preset_id=(
            player.ai_preset_snapshot.preset_id
            if player.ai_preset_snapshot is not None
            else None
        ),
    )


def serialize_room(room: Room) -> RoomResponse:
    return RoomResponse(
        room_code=room.room_code,
        name=room.name,
        visibility=room.visibility.value,
        status=room.status.value,
        owner_player_id=room.owner_player_id,
        max_players=room.max_players,
        players=[serialize_room_player(player, room) for player in room.players],
        game_session_id=room.game_session_id,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


def serialize_room_list_item(room: Room) -> RoomListItem:
    active_players = [
        player for player in room.players if player.status.value != "LEFT"
    ]
    return RoomListItem(
        room_code=room.room_code,
        name=room.name,
        status=room.status.value,
        player_count=len(active_players),
        max_players=room.max_players,
        created_at=room.created_at,
    )


def serialize_event(event: GameEvent) -> GameEventResponse:
    return GameEventResponse(
        event_id=event.event_id,
        room_id=event.room_id,
        game_id=event.game_id,
        revision=event.revision,
        event_type=event.event_type,
        message=event.message,
        payload=event.payload,
        match_index=event.match_index,
        reload_round=event.reload_round,
        actor_player_id=event.actor_player_id,
        visible_to=event.visible_to,
        created_at=event.created_at,
    )


def serialize_domain_player(player: Player) -> dict[str, Any]:
    return {
        "player_id": player.id,
        "name": player.name,
        "hp": player.hp,
        "max_hp": player.max_hp,
        "alive": player.alive,
        "items": [item.value for item in player.items],
        "hand_saw_active": player.hand_saw_active,
    }


def public_shell_counts(match: MatchState | None) -> dict[str, int]:
    if match is None or not match.chambers:
        return {"remaining": 0}
    remaining = match.chambers[match.chamber_index :]
    return {"remaining": len(remaining)}


def item_action(item: ItemType, item_index: int) -> dict[str, Any]:
    action: dict[str, Any] = {
        "type": "use_item",
        "item": item.value,
        "item_index": item_index,
    }
    if item in {ItemType.JAMMER, ItemType.ADRENALINE}:
        action["requires_target_player_id"] = True
    if item == ItemType.ADRENALINE:
        action["requires_target_item_index"] = True
    return action
