from __future__ import annotations

from buckshot_roulette.llm.models import ModelPresetSnapshot, ProviderConfig, ProviderProtocol


class ModelFactoryError(RuntimeError):
    pass


class FakeChatModel:
    def invoke(self, context: dict) -> dict:
        legal_actions = context["current_visible_state"].get("legal_actions", [])
        for action in legal_actions:
            if action.get("type") == "shoot_player":
                return {
                    "thought_summary": "Use the first legal attack action.",
                    "action": action,
                }
        if legal_actions:
            return {
                "thought_summary": "Use the first legal action.",
                "action": legal_actions[0],
            }
        return {
            "thought_summary": "No legal action is available.",
            "action": {"type": "shoot_self"},
        }


class LangChainModelFactory:
    def create_chat_model(
        self,
        provider: ProviderConfig,
        model_preset: ModelPresetSnapshot,
    ):
        if provider.protocol == ProviderProtocol.FAKE:
            return FakeChatModel()
        raise ModelFactoryError(
            "真实 LangChain provider 尚未启用；请先使用 model-preset test 验证配置。"
        )
