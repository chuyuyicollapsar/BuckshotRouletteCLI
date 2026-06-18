from __future__ import annotations

from buckshot_roulette.llm.models import (
    AIPlayerPreset,
    FallbackPolicy,
    ModelPreset,
    ProviderConfig,
    ProviderProtocol,
    ProviderType,
)


class LLMConfigStore:
    def __init__(self) -> None:
        self.providers: dict[str, ProviderConfig] = {}
        self.model_presets: dict[str, ModelPreset] = {}
        self.ai_player_presets: dict[str, AIPlayerPreset] = {}
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        self.providers["fake_local"] = ProviderConfig(
            id="fake_local",
            display_name="Fake Local",
            type=ProviderType.OFFICIAL,
            protocol=ProviderProtocol.FAKE,
        )
        self.model_presets["fake_default"] = ModelPreset(
            id="fake_default",
            display_name="Fake Default",
            provider_id="fake_local",
            model_name="fake-buckshot-player",
            temperature=0.0,
            max_tokens=200,
        )
        self.ai_player_presets["fake_cautious"] = AIPlayerPreset(
            id="fake_cautious",
            display_name="Fake Cautious",
            enabled=True,
            model_preset_id="fake_default",
            persona_prompt="A deterministic fake player for local tests.",
            strategy_prompt="Prefer legal shooting actions.",
            fallback_policy=FallbackPolicy.CONSERVATIVE_SHOT,
        )

    def list_providers(self) -> list[ProviderConfig]:
        return list(self.providers.values())

    def list_model_presets(self) -> list[ModelPreset]:
        return list(self.model_presets.values())

    def list_ai_player_presets(self) -> list[AIPlayerPreset]:
        return list(self.ai_player_presets.values())

    def enabled_ai_player_presets(self) -> list[AIPlayerPreset]:
        return [preset for preset in self.ai_player_presets.values() if preset.enabled]

    def get_provider(self, provider_id: str) -> ProviderConfig:
        try:
            return self.providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"Provider 不存在：{provider_id}") from exc

    def get_model_preset(self, preset_id: str) -> ModelPreset:
        try:
            return self.model_presets[preset_id]
        except KeyError as exc:
            raise KeyError(f"模型预设不存在：{preset_id}") from exc

    def get_ai_player_preset(self, preset_id: str) -> AIPlayerPreset:
        try:
            return self.ai_player_presets[preset_id]
        except KeyError as exc:
            raise KeyError(f"AI 玩家预设不存在：{preset_id}") from exc

    def upsert_provider(self, provider: ProviderConfig) -> ProviderConfig:
        self.providers[provider.id] = provider
        return provider

    def upsert_model_preset(self, preset: ModelPreset) -> ModelPreset:
        existing = self.model_presets.get(preset.id)
        if existing is not None:
            preset.version = existing.version + 1
        self.model_presets[preset.id] = preset
        return preset

    def upsert_ai_player_preset(self, preset: AIPlayerPreset) -> AIPlayerPreset:
        existing = self.ai_player_presets.get(preset.id)
        if existing is not None:
            preset.version = existing.version + 1
        self.ai_player_presets[preset.id] = preset
        return preset
