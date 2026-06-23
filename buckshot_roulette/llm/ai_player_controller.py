from __future__ import annotations

from buckshot_roulette.backend.models import GameSession, Room, RoomPlayer
from buckshot_roulette.backend.schemas import PlayerVisibleStateResponse
from buckshot_roulette.llm.context_builder import LLMContextBuilder
from buckshot_roulette.llm.models import SingleActionDecision
from buckshot_roulette.llm.services import LLMChatService, LLMDecisionService


class AIPlayerController:
    def __init__(
        self,
        decision_service: LLMDecisionService,
        chat_service: LLMChatService | None = None,
        context_builder: LLMContextBuilder | None = None,
    ) -> None:
        self.decision_service = decision_service
        self.chat_service = chat_service
        self.context_builder = context_builder or LLMContextBuilder()

    def decide_one_action(
        self,
        room: Room,
        room_player: RoomPlayer,
        session: GameSession,
        visible_state: PlayerVisibleStateResponse,
    ) -> SingleActionDecision:
        if room_player.ai_preset_snapshot is None:
            raise ValueError("AI 玩家缺少预设快照。")
        context = self.context_builder.build_context(
            room,
            room_player,
            session,
            visible_state,
        )
        decision = self.decision_service.decide_one_action(
            room_player.ai_preset_snapshot,
            context,
        )
        return decision

    def generate_chat_reply(
        self,
        room: Room,
        room_player: RoomPlayer,
        session: GameSession,
        trigger_event,
    ) -> str | None:
        if self.chat_service is None:
            return None
        if room_player.ai_preset_snapshot is None:
            return None
        context = self.context_builder.build_chat_context(
            room,
            room_player,
            session,
            trigger_event,
        )
        return self.chat_service.generate_reply(
            room_player.ai_preset_snapshot,
            context,
        )
