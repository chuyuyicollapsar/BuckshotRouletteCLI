from __future__ import annotations

import hashlib
import secrets
import string
import uuid
from typing import Any

from buckshot_roulette.backend.models import (
    GameEvent,
    GameSession,
    PlayerToken,
    Room,
    RoomPlayer,
    RoomPlayerStatus,
    RoomPlayerType,
    RoomStatus,
    RoomVisibility,
    utc_now,
)
from buckshot_roulette.backend.repositories import InMemoryStore
from buckshot_roulette.backend.schemas import PlayerVisibleStateResponse
from buckshot_roulette.backend.serializers import (
    item_action,
    public_shell_counts,
    serialize_domain_player,
    serialize_event,
)
from buckshot_roulette.engine import GameEngine
from buckshot_roulette.llm.ai_player_controller import AIPlayerController
from buckshot_roulette.models import (
    ActionResult,
    ActionType,
    ItemType,
    MatchConfig,
    MatchState,
    item_label,
)


class ServiceError(ValueError):
    pass


class AuthError(ServiceError):
    pass


class RoomService:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def create_room(
        self,
        *,
        owner_name: str,
        room_name: str | None,
        visibility: RoomVisibility,
        max_players: int,
        config: MatchConfig | None = None,
    ) -> tuple[Room, PlayerToken]:
        if not owner_name.strip():
            raise ServiceError("玩家名不能为空。")
        if not 2 <= max_players <= 4:
            raise ServiceError("房间人数必须是 2 到 4。")
        player, token = self._new_human_player(owner_name)
        room = Room(
            id=str(uuid.uuid4()),
            room_code=self._new_room_code(),
            name=room_name or f"{owner_name} 的房间",
            visibility=visibility,
            status=RoomStatus.LOBBY,
            owner_player_id=player.id,
            max_players=max_players,
            config=config or MatchConfig(),
            players=[player],
        )
        self.store.add_room(room)
        return room, token

    def list_public_rooms(self) -> list[Room]:
        return [
            room
            for room in self.store.list_rooms()
            if room.visibility == RoomVisibility.PUBLIC
            and room.status == RoomStatus.LOBBY
            and len(self._active_players(room)) < room.max_players
        ]

    def get_room(self, room_code: str) -> Room:
        room = self.store.get_room(room_code)
        if room is None:
            raise ServiceError("房间不存在。")
        return room

    def join_room(self, room_code: str, player_name: str) -> tuple[Room, PlayerToken]:
        room = self.get_room(room_code)
        if room.status != RoomStatus.LOBBY:
            raise ServiceError("只能加入大厅中的房间。")
        if len(self._active_players(room)) >= room.max_players:
            raise ServiceError("房间已满。")
        player, token = self._new_human_player(player_name)
        room.players.append(player)
        room.updated_at = utc_now()
        return room, token

    def add_ai_player(
        self,
        room_code: str,
        owner_token: str,
        ai_snapshot,
    ) -> Room:
        room = self.get_room(room_code)
        self.require_owner(room, owner_token)
        if room.status != RoomStatus.LOBBY:
            raise ServiceError("只能在大厅中添加 AI 玩家。")
        if len(self._active_players(room)) >= room.max_players:
            raise ServiceError("房间已满。")
        player = RoomPlayer(
            id=str(uuid.uuid4()),
            name=ai_snapshot.display_name,
            type=RoomPlayerType.AI,
            status=RoomPlayerStatus.READY,
            ai_preset_snapshot=ai_snapshot,
        )
        room.players.append(player)
        room.updated_at = utc_now()
        return room

    def set_ready(self, room_code: str, token: str, ready: bool) -> Room:
        room = self.get_room(room_code)
        if room.status != RoomStatus.LOBBY:
            raise ServiceError("只有大厅中可以切换准备状态。")
        player = self.require_player(room, token)
        player.status = RoomPlayerStatus.READY if ready else RoomPlayerStatus.CONNECTED
        room.updated_at = utc_now()
        return room

    def leave_room(self, room_code: str, token: str) -> Room:
        room = self.get_room(room_code)
        player = self.require_player(room, token)
        if room.status == RoomStatus.IN_GAME:
            player.status = RoomPlayerStatus.DISCONNECTED
        else:
            player.status = RoomPlayerStatus.LEFT
            if player.id == room.owner_player_id:
                active_players = self._active_players(room)
                if active_players:
                    room.owner_player_id = active_players[0].id
                else:
                    room.status = RoomStatus.CLOSED
        room.updated_at = utc_now()
        return room

    def require_player(self, room: Room, token: str) -> RoomPlayer:
        token_hash = self._hash_token(token)
        for player in room.players:
            if (
                player.type == RoomPlayerType.HUMAN
                and player.token_hash == token_hash
                and player.status != RoomPlayerStatus.LEFT
            ):
                return player
        raise AuthError("玩家令牌无效。")

    def require_owner(self, room: Room, token: str) -> RoomPlayer:
        player = self.require_player(room, token)
        if player.id != room.owner_player_id:
            raise AuthError("只有房主可以执行该操作。")
        return player

    def assign_seats(self, room: Room) -> list[RoomPlayer]:
        players = self._active_players(room)
        if not 2 <= len(players) <= room.max_players:
            raise ServiceError("开始游戏需要 2 到 4 名玩家。")
        for player in players:
            if player.id == room.owner_player_id:
                continue
            if (
                player.type == RoomPlayerType.HUMAN
                and player.status != RoomPlayerStatus.READY
            ):
                raise ServiceError("还有玩家未准备。")
        for index, player in enumerate(players):
            player.seat_index = index
        room.updated_at = utc_now()
        return players

    def _active_players(self, room: Room) -> list[RoomPlayer]:
        return [player for player in room.players if player.status != RoomPlayerStatus.LEFT]

    def _new_human_player(self, player_name: str) -> tuple[RoomPlayer, PlayerToken]:
        name = player_name.strip()
        if not name:
            raise ServiceError("玩家名不能为空。")
        token = secrets.token_urlsafe(32)
        player = RoomPlayer(
            id=str(uuid.uuid4()),
            name=name[:32],
            type=RoomPlayerType.HUMAN,
            status=RoomPlayerStatus.CONNECTED,
            token_hash=self._hash_token(token),
        )
        return player, PlayerToken(player_id=player.id, token=token)

    def _new_room_code(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            if self.store.get_room(code) is None:
                return code

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class GameSessionService:
    def __init__(self, store: InMemoryStore, engine: GameEngine) -> None:
        self.store = store
        self.engine = engine

    def start_game(self, room: Room) -> GameSession:
        player_names = [player.name for player in room.players if player.seat_index is not None]
        game_state = self.engine.init_game(player_names, room.config)
        session = GameSession(
            id=str(uuid.uuid4()),
            room_id=room.id,
            state=game_state,
            revision=0,
        )
        room.status = RoomStatus.IN_GAME
        room.game_session_id = session.id
        room.updated_at = utc_now()
        self.store.add_session(session)
        return session

    def get_session_for_room(self, room: Room) -> GameSession:
        session = self.store.get_session(room.game_session_id)
        if session is None:
            raise ServiceError("房间尚未开始游戏。")
        return session

    def append_event(
        self,
        session: GameSession,
        *,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
        actor_player_id: int | None = None,
        visible_to: str | list[int] = "ALL",
    ) -> GameEvent:
        match = session.state.current_match_state
        event = GameEvent(
            event_id=len(session.event_log) + 1,
            room_id=session.room_id,
            game_id=session.id,
            revision=session.revision,
            event_type=event_type,
            message=message,
            payload=payload or {},
            match_index=match.match_index if match is not None else None,
            reload_round=match.round_number if match is not None else None,
            actor_player_id=actor_player_id,
            visible_to=visible_to,
        )
        session.event_log.append(event)
        return event


class TurnCoordinator:
    def __init__(
        self,
        room_service: RoomService,
        session_service: GameSessionService,
        engine: GameEngine,
        ai_player_controller: AIPlayerController | None = None,
    ) -> None:
        self.room_service = room_service
        self.session_service = session_service
        self.engine = engine
        self.ai_player_controller = ai_player_controller

    def start_game(self, room_code: str, owner_token: str) -> tuple[GameSession, list[GameEvent]]:
        room = self.room_service.get_room(room_code)
        self.room_service.require_owner(room, owner_token)
        players = self.room_service.assign_seats(room)
        session = self.session_service.start_game(room)
        events: list[GameEvent] = []

        match = self.engine.start_match(session.state)
        session.revision += 1
        events.append(
            self.session_service.append_event(
                session,
                event_type="game_started",
                message="游戏开始。",
                payload={"players": [player.name for player in players]},
            )
        )
        events.append(
            self.session_service.append_event(
                session,
                event_type="match_started",
                message=f"第 {match.match_index + 1} 场比赛开始。",
                payload={
                    "initial_hp": match.players[0].max_hp,
                    "players": [serialize_domain_player(player) for player in match.players],
                },
            )
        )
        events.extend(self._start_round(session, match))
        events.extend(self.run_ai_turns(room, session))
        return session, events

    def submit_action(
        self,
        room_code: str,
        token: str,
        revision: int,
        raw_action: dict[str, Any],
        *,
        run_ai_turns: bool = True,
    ) -> tuple[GameSession, list[GameEvent]]:
        room = self.room_service.get_room(room_code)
        room_player = self.room_service.require_player(room, token)
        if room.status != RoomStatus.IN_GAME:
            raise ServiceError("房间不在游戏中。")
        session = self.session_service.get_session_for_room(room)
        if revision != session.revision:
            raise ServiceError("状态版本已过期，请等待最新状态。")
        match = session.state.current_match_state
        if match is None:
            raise ServiceError("当前没有进行中的比赛。")
        if room_player.seat_index != match.current_player_idx:
            raise ServiceError("还没有轮到你行动。")

        action_type, kwargs = self._parse_action(match, raw_action)
        result = self.engine.execute_action(match, action_type, **kwargs)
        session.revision += 1
        events = self._events_from_action_result(session, result)

        if result.round_ended and not match.match_over:
            events.extend(self._start_round(session, match))
        if match.match_over:
            events.extend(self._finish_match_if_needed(room, session, match))
        if run_ai_turns:
            events.extend(self.run_ai_turns(room, session))
        return session, events

    def run_ai_turns(
        self,
        room: Room,
        session: GameSession,
        *,
        max_actions: int = 32,
    ) -> list[GameEvent]:
        if self.ai_player_controller is None:
            return []
        events: list[GameEvent] = []
        actions_taken = 0
        while (
            room.status == RoomStatus.IN_GAME
            and session.state.current_match_state is not None
            and not session.state.game_over
            and actions_taken < max_actions
        ):
            ai_events = self.run_one_ai_turn(room, session)
            if not ai_events:
                break
            events.extend(ai_events)
            actions_taken += 1
        if actions_taken >= max_actions:
            events.append(self.append_ai_safety_stop(session, max_actions))
        return events

    def run_one_ai_turn(
        self,
        room: Room,
        session: GameSession,
    ) -> list[GameEvent]:
        if self.ai_player_controller is None:
            return []
        if (
            room.status != RoomStatus.IN_GAME
            or session.state.current_match_state is None
            or session.state.game_over
        ):
            return []
        match = session.state.current_match_state
        room_player = self._room_player_by_seat(room, match.current_player_idx)
        if room_player is None or room_player.type != RoomPlayerType.AI:
            return []
        return self._execute_one_ai_action(room, session, room_player)

    def append_ai_safety_stop(
        self, session: GameSession, max_actions: int
    ) -> GameEvent:
        return self.session_service.append_event(
            session,
            event_type="ai_safety_stop",
            message="AI 连续行动达到安全上限，已暂停自动行动。",
            payload={"max_actions": max_actions},
        )

    def build_visible_state(
        self, room: Room, room_player: RoomPlayer
    ) -> PlayerVisibleStateResponse:
        session = self.store_session(room)
        seat_index = room_player.seat_index
        visible_events = self._visible_events(session, seat_index)
        match = session.state.current_match_state if session is not None else None
        visible_players = (
            [serialize_domain_player(player) for player in match.players]
            if match is not None
            else [
                {
                    "player_id": player.seat_index,
                    "name": player.name,
                    "status": player.status.value,
                    "type": player.type.value,
                }
                for player in room.players
                if player.status != RoomPlayerStatus.LEFT
            ]
        )
        return PlayerVisibleStateResponse(
            room_id=room.id,
            room_code=room.room_code,
            game_id=session.id if session is not None else None,
            player_id=room_player.id,
            player_seat_index=seat_index,
            revision=session.revision if session is not None else 0,
            room_status=room.status.value,
            visible_players=visible_players,
            public_shell_counts=public_shell_counts(match),
            current_player_id=match.current_player_idx if match is not None else None,
            legal_actions=self._legal_actions(match, seat_index),
            visible_events=[serialize_event(event) for event in visible_events[-50:]],
            match_results=session.state.match_results if session is not None else [],
        )

    def build_visible_state_by_token(
        self, room_code: str, token: str
    ) -> PlayerVisibleStateResponse:
        room = self.room_service.get_room(room_code)
        player = self.room_service.require_player(room, token)
        return self.build_visible_state(room, player)

    def append_chat(
        self, room_code: str, token: str, message: str
    ) -> tuple[GameSession | None, GameEvent]:
        room = self.room_service.get_room(room_code)
        player = self.room_service.require_player(room, token)
        session = self.store_session(room)
        revision = session.revision if session is not None else 0
        event = GameEvent(
            event_id=(len(session.event_log) + 1) if session is not None else 1,
            room_id=room.id,
            game_id=session.id if session is not None else None,
            revision=revision,
            event_type="chat_message",
            message=f"{player.name}: {message}",
            payload={"player_id": player.id, "name": player.name, "message": message},
            visible_to="ALL",
        )
        if session is not None:
            session.event_log.append(event)
        return session, event

    def store_session(self, room: Room) -> GameSession | None:
        return self.session_service.store.get_session(room.game_session_id)

    def _execute_one_ai_action(
        self,
        room: Room,
        session: GameSession,
        room_player: RoomPlayer,
    ) -> list[GameEvent]:
        match = session.state.current_match_state
        if match is None or room_player.seat_index != match.current_player_idx:
            return []
        visible_state = self.build_visible_state(room, room_player)
        try:
            decision = self.ai_player_controller.decide_one_action(
                room,
                room_player,
                session,
                visible_state,
            )
            raw_action = decision.action
        except Exception as exc:
            raw_action = self._fallback_ai_action(match)
            decision_event = {
                "event_type": "ai_fallback",
                "message": f"{room_player.name} 决策失败，使用保底行动。",
                "payload": {"error": str(exc), "action": raw_action},
                "visible_to": "ALL",
            }
        else:
            if decision.fallback_reason:
                decision_event = {
                    "event_type": "ai_fallback",
                    "message": f"{room_player.name} 决策失败，使用保底行动。",
                    "payload": {
                        "error": decision.fallback_reason,
                        "action": raw_action,
                    },
                    "visible_to": "ALL",
                }
            else:
                decision_event = {
                    "event_type": "ai_decision",
                    "message": f"{room_player.name} 选择了一个行动。",
                    "payload": {
                        "action": raw_action,
                        "thought_summary": decision.thought_summary,
                    },
                    "visible_to": [room_player.seat_index],
                }
        try:
            action_type, kwargs = self._parse_action(match, raw_action)
            result = self.engine.execute_action(match, action_type, **kwargs)
        except Exception as exc:
            fallback = self._fallback_ai_action(match)
            decision_event = {
                "event_type": "ai_fallback",
                "message": f"{room_player.name} 返回非法行动，改用保底行动。",
                "payload": {
                    "error": str(exc),
                    "invalid_action": raw_action,
                    "fallback_action": fallback,
                },
                "visible_to": "ALL",
            }
            action_type, kwargs = self._parse_action(match, fallback)
            result = self.engine.execute_action(match, action_type, **kwargs)
        session.revision += 1
        events = [
            self.session_service.append_event(
                session,
                event_type=decision_event["event_type"],
                message=decision_event["message"],
                payload=decision_event["payload"],
                actor_player_id=room_player.seat_index,
                visible_to=decision_event["visible_to"],
            )
        ]
        events.extend(self._events_from_action_result(session, result))
        if result.round_ended and not match.match_over:
            events.extend(self._start_round(session, match))
        if match.match_over:
            events.extend(self._finish_match_if_needed(room, session, match))
        return events

    def _room_player_by_seat(self, room: Room, seat_index: int) -> RoomPlayer | None:
        for player in room.players:
            if player.seat_index == seat_index and player.status != RoomPlayerStatus.LEFT:
                return player
        return None

    def _fallback_ai_action(self, match: MatchState) -> dict[str, Any]:
        actor_idx = match.current_player_idx
        for player in match.players:
            if player.alive and player.id != actor_idx:
                return {"type": "shoot_player", "target_player_id": player.id}
        return {"type": "shoot_self"}

    def _start_round(self, session: GameSession, match: MatchState) -> list[GameEvent]:
        round_result = self.engine.start_round(match)
        session.revision += 1
        events = [
            self.session_service.append_event(
                session,
                event_type="round_started",
                message=(
                    f"第 {round_result.round_number} 轮装弹："
                    f"LIVE {round_result.live_count} / BLANK {round_result.blank_count}。"
                ),
                payload={
                    "round_number": round_result.round_number,
                    "shell_count": round_result.shell_count,
                    "live_count": round_result.live_count,
                    "blank_count": round_result.blank_count,
                    "dealt_items": {
                        str(player_id): [item.value for item in items]
                        for player_id, items in round_result.dealt_items.items()
                    },
                },
            )
        ]
        return events

    def _finish_match_if_needed(
        self, room: Room, session: GameSession, match: MatchState
    ) -> list[GameEvent]:
        events: list[GameEvent] = []
        winner_idx = match.winner_idx
        if winner_idx is None:
            return events
        winner = match.players[winner_idx]
        events.append(
            self.session_service.append_event(
                session,
                event_type="match_ended",
                message=f"第 {match.match_index + 1} 场结束，胜者：{winner.name}。",
                payload={"winner_player_id": winner_idx},
            )
        )
        self.engine.finish_match(session.state)
        session.revision += 1
        if session.state.game_over:
            room.status = RoomStatus.FINISHED
            room.updated_at = utc_now()
            final_idx = session.state.final_winner_idx
            final_name = (
                session.state.player_names[final_idx]
                if final_idx is not None
                else "平局"
            )
            events.append(
                self.session_service.append_event(
                    session,
                    event_type="game_ended",
                    message=f"整局游戏结束，最终结果：{final_name}。",
                    payload={
                        "match_results": session.state.match_results,
                        "final_winner_player_id": final_idx,
                    },
                )
            )
        else:
            new_match = self.engine.start_match(session.state)
            session.revision += 1
            events.append(
                self.session_service.append_event(
                    session,
                    event_type="match_started",
                    message=f"第 {new_match.match_index + 1} 场比赛开始。",
                    payload={
                        "initial_hp": new_match.players[0].max_hp,
                        "players": [
                            serialize_domain_player(player)
                            for player in new_match.players
                        ],
                    },
                )
            )
            events.extend(self._start_round(session, new_match))
        return events

    def _events_from_action_result(
        self, session: GameSession, result: ActionResult
    ) -> list[GameEvent]:
        event_type = {
            ActionType.SHOOT_SELF: "shoot_self",
            ActionType.SHOOT_OPPONENT: "shoot_player",
            ActionType.USE_ITEM: "use_item",
        }[result.action_type]
        public_message = result.message
        public_payload: dict[str, Any] = {
            "item": result.item_used.value if result.item_used else None,
            "shell": result.shell.value if result.shell else None,
            "target_player_id": result.target_idx,
            "damage": result.damage,
            "turn_retained": result.turn_retained,
            "round_ended": result.round_ended,
        }
        sensitive = self._result_has_private_details(result)
        if sensitive and result.item_used is not None:
            match = session.state.current_match_state
            actor_name = (
                match.players[result.actor_idx].name
                if match is not None
                else f"玩家 {result.actor_idx}"
            )
            public_message = f"{actor_name} 使用了{item_label(result.item_used)}。"
        else:
            public_payload["details"] = result.details

        events = [
            self.session_service.append_event(
                session,
                event_type=event_type,
                message=public_message,
                payload=public_payload,
                actor_player_id=result.actor_idx,
            )
        ]
        if sensitive:
            events.append(
                self.session_service.append_event(
                    session,
                    event_type="item_result",
                    message=result.message,
                    payload={"details": result.details},
                    actor_player_id=result.actor_idx,
                    visible_to=[result.actor_idx],
                )
            )
        for message in result.events:
            visible_to: str | list[int] = "ALL"
            if sensitive:
                visible_to = [result.actor_idx]
            events.append(
                self.session_service.append_event(
                    session,
                    event_type="action_result",
                    message=message,
                    payload={},
                    actor_player_id=result.actor_idx,
                    visible_to=visible_to,
                )
            )
        return events

    def _result_has_private_details(self, result: ActionResult) -> bool:
        if result.item_used in {ItemType.MAGNIFYING_GLASS, ItemType.BURNER_PHONE}:
            return True
        details = result.details
        if "revealed_shell" in details or "offset" in details:
            return True
        stolen_result = details.get("stolen_result")
        return isinstance(stolen_result, dict) and (
            "revealed_shell" in stolen_result or "offset" in stolen_result
        )

    def _parse_action(
        self, match: MatchState, raw_action: dict[str, Any]
    ) -> tuple[ActionType, dict[str, Any]]:
        action_type = raw_action.get("type")
        if action_type == "shoot_self":
            return ActionType.SHOOT_SELF, {}
        if action_type == "shoot_player":
            return ActionType.SHOOT_OPPONENT, {
                "target_idx": self._required_int(raw_action, "target_player_id")
            }
        if action_type == "use_item":
            item = ItemType(raw_action["item"])
            kwargs: dict[str, Any] = {"item_type": item}
            if "item_index" in raw_action:
                kwargs["item_index"] = int(raw_action["item_index"])
            if "target_player_id" in raw_action:
                kwargs["target_idx"] = int(raw_action["target_player_id"])
            if "target_item_index" in raw_action:
                kwargs["target_item_idx"] = int(raw_action["target_item_index"])
            if "secondary_target_player_id" in raw_action:
                kwargs["secondary_target_player_idx"] = int(
                    raw_action["secondary_target_player_id"]
                )
            return ActionType.USE_ITEM, kwargs
        raise ServiceError("未知行动类型。")

    def _required_int(self, raw_action: dict[str, Any], key: str) -> int:
        if key not in raw_action:
            raise ServiceError(f"行动缺少字段：{key}")
        return int(raw_action[key])

    def _legal_actions(
        self, match: MatchState | None, seat_index: int | None
    ) -> list[dict[str, Any]]:
        if match is None or seat_index is None:
            return []
        if match.match_over or match.current_player_idx != seat_index:
            return []
        actor = match.players[seat_index]
        if not actor.alive:
            return []
        actions: list[dict[str, Any]] = [{"type": "shoot_self"}]
        actions.extend(
            {"type": "shoot_player", "target_player_id": player.id}
            for player in match.players
            if player.alive and player.id != seat_index
        )
        actions.extend(
            item_action(item, index)
            for index, item in enumerate(actor.items)
        )
        return actions

    def _visible_events(
        self, session: GameSession | None, seat_index: int | None
    ) -> list[GameEvent]:
        if session is None:
            return []
        visible: list[GameEvent] = []
        for event in session.event_log:
            if event.visible_to == "ALL":
                visible.append(event)
            elif seat_index is not None and seat_index in event.visible_to:
                visible.append(event)
        return visible
