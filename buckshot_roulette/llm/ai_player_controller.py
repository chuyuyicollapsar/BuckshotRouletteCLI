from __future__ import annotations

from buckshot_roulette.backend.models import GameSession, Room, RoomPlayer
from buckshot_roulette.backend.schemas import PlayerVisibleStateResponse
from buckshot_roulette.llm.context_builder import LLMContextBuilder
from buckshot_roulette.llm.services import LLMDecisionService


class AIPlayerController:
    def __init__(
        self,
        decision_service: LLMDecisionService,
        context_builder: LLMContextBuilder | None = None,
    ) -> None:
        self.decision_service = decision_service
        self.context_builder = context_builder or LLMContextBuilder()

    def decide_one_action(
        self,
        room: Room,
        room_player: RoomPlayer,
        session: GameSession,
        visible_state: PlayerVisibleStateResponse,
    ) -> dict:
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
        return decision.action
