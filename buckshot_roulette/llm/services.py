from __future__ import annotations

import logging
from urllib.parse import urlparse
import os

from buckshot_roulette.llm.model_factory import (
    LangChainModelFactory,
    MissingProviderDependencyError,
    ModelFactoryError,
)
from buckshot_roulette.llm.models import (
    AIPlayerPreset,
    AIPlayerPresetSnapshot,
    FallbackPolicy,
    ModelPreset,
    ModelPresetSnapshot,
    PresetTestResult,
    ProviderConfig,
    ProviderProtocol,
    ProviderType,
    SingleActionDecision,
)
from buckshot_roulette.llm.output_parser import OutputParser, OutputParserError
from buckshot_roulette.llm.repositories import LLMConfigStore


class LLMConfigError(ValueError):
    pass


logger = logging.getLogger(__name__)


class LLMAdminService:
    ALLOWED_EXTRA_KEYS = {"top_p", "frequency_penalty", "presence_penalty", "stop"}

    def __init__(
        self,
        store: LLMConfigStore,
        model_factory: LangChainModelFactory | None = None,
        output_parser: OutputParser | None = None,
    ) -> None:
        self.store = store
        self.model_factory = model_factory or LangChainModelFactory()
        self.output_parser = output_parser or OutputParser()

    def create_provider(self, data: dict) -> ProviderConfig:
        provider = ProviderConfig(
            id=self._required_id(data, "id"),
            display_name=str(data.get("display_name") or data["id"]),
            type=ProviderType(data.get("type", ProviderType.THIRD_PARTY.value)),
            protocol=ProviderProtocol(data["protocol"]),
            base_url=data.get("base_url"),
            api_key_env=data.get("api_key_env"),
            api_key=data.get("api_key"),
            class_path=data.get("class_path"),
            kwargs=dict(data.get("kwargs") or {}),
        )
        self._validate_provider(provider)
        return self.store.upsert_provider(provider)

    def create_model_preset(self, data: dict) -> ModelPreset:
        preset = ModelPreset(
            id=self._required_id(data, "id"),
            display_name=str(data.get("display_name") or data["id"]),
            provider_id=str(data["provider_id"]),
            model_name=str(data["model_name"]),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            reasoning_effort=data.get("reasoning_effort"),
            timeout_seconds=int(data.get("timeout_seconds", 30)),
            max_retries=int(data.get("max_retries", 2)),
            extra=dict(data.get("extra") or {}),
        )
        self._validate_model_preset(preset)
        self.store.get_provider(preset.provider_id)
        return self.store.upsert_model_preset(preset)

    def create_ai_player_preset(self, data: dict) -> AIPlayerPreset:
        preset = AIPlayerPreset(
            id=self._required_id(data, "id"),
            display_name=str(data.get("display_name") or data["id"]),
            enabled=bool(data.get("enabled", True)),
            model_preset_id=str(data["model_preset_id"]),
            persona_prompt=str(data.get("persona_prompt", "")),
            strategy_prompt=str(data.get("strategy_prompt", "")),
            max_item_actions_per_turn=int(data.get("max_item_actions_per_turn", 8)),
            max_parse_failures_per_turn=int(
                data.get("max_parse_failures_per_turn", 2)
            ),
            max_illegal_actions_per_turn=int(
                data.get("max_illegal_actions_per_turn", 2)
            ),
            fallback_policy=FallbackPolicy(
                data.get("fallback_policy", FallbackPolicy.CONSERVATIVE_SHOT.value)
            ),
        )
        self._validate_ai_player_preset(preset)
        self.store.get_model_preset(preset.model_preset_id)
        return self.store.upsert_ai_player_preset(preset)

    def create_ai_snapshot(self, preset_id: str) -> AIPlayerPresetSnapshot:
        ai_preset = self.store.get_ai_player_preset(preset_id)
        if not ai_preset.enabled:
            raise LLMConfigError("AI 玩家预设未启用。")
        model_preset = self.store.get_model_preset(ai_preset.model_preset_id)
        provider = self.store.get_provider(model_preset.provider_id)
        model_snapshot = ModelPresetSnapshot(
            preset_id=model_preset.id,
            preset_version=model_preset.version,
            provider_id=model_preset.provider_id,
            protocol=provider.protocol.value,
            model_name=model_preset.model_name,
            temperature=model_preset.temperature,
            max_tokens=model_preset.max_tokens,
            reasoning_effort=model_preset.reasoning_effort,
            timeout_seconds=model_preset.timeout_seconds,
            max_retries=model_preset.max_retries,
            extra=dict(model_preset.extra),
        )
        return AIPlayerPresetSnapshot(
            preset_id=ai_preset.id,
            preset_version=ai_preset.version,
            display_name=ai_preset.display_name,
            model_preset_snapshot=model_snapshot,
            persona_prompt=ai_preset.persona_prompt,
            strategy_prompt=ai_preset.strategy_prompt,
            max_item_actions_per_turn=ai_preset.max_item_actions_per_turn,
            max_parse_failures_per_turn=ai_preset.max_parse_failures_per_turn,
            max_illegal_actions_per_turn=ai_preset.max_illegal_actions_per_turn,
            fallback_policy=ai_preset.fallback_policy.value,
        )

    def test_provider(self, provider_id: str) -> PresetTestResult:
        provider = self.store.get_provider(provider_id)
        if provider.protocol == ProviderProtocol.FAKE:
            return PresetTestResult(ok=True, message="fake provider 可用。")
        secret = self._resolve_secret(provider)
        if not secret:
            return PresetTestResult(
                ok=False,
                message="API Key 缺失。",
                details={"api_key_env": provider.api_key_env},
            )
        try:
            self.model_factory.check_dependencies(provider)
        except MissingProviderDependencyError as exc:
            return PresetTestResult(
                ok=False,
                message=str(exc),
                details={"package": exc.package_name, "import": exc.import_name},
            )
        return PresetTestResult(
            ok=True,
            message="provider 配置和本地依赖有效。",
            details={"protocol": provider.protocol.value},
        )

    def test_model_preset(self, preset_id: str) -> PresetTestResult:
        preset = self.store.get_model_preset(preset_id)
        provider = self.store.get_provider(preset.provider_id)
        provider_result = self.test_provider(provider.id)
        if not provider_result.ok:
            return PresetTestResult(
                ok=False,
                message=provider_result.message,
                details={
                    **provider_result.details,
                    "model_preset_id": preset.id,
                    "model_name": preset.model_name,
                },
            )
        snapshot = ModelPresetSnapshot(
            preset_id=preset.id,
            preset_version=preset.version,
            provider_id=preset.provider_id,
            protocol=provider.protocol.value,
            model_name=preset.model_name,
            temperature=preset.temperature,
            max_tokens=preset.max_tokens,
            reasoning_effort=preset.reasoning_effort,
            timeout_seconds=preset.timeout_seconds,
            max_retries=preset.max_retries,
            extra=dict(preset.extra),
        )
        try:
            model = self.model_factory.create_chat_model(provider, snapshot)
            if provider.protocol == ProviderProtocol.FAKE:
                output = model.invoke(
                    {
                        "current_visible_state": {
                            "legal_actions": [{"type": "shoot_self"}]
                        }
                    }
                )
                self.output_parser.parse(output)
                structured_output = "ok"
                network_tested = False
            else:
                structured_output = "not_tested"
                network_tested = False
        except MissingProviderDependencyError as exc:
            return PresetTestResult(
                ok=False,
                message=str(exc),
                details={"package": exc.package_name, "import": exc.import_name},
            )
        except (ModelFactoryError, OutputParserError) as exc:
            return PresetTestResult(ok=False, message=str(exc))
        return PresetTestResult(
            ok=True,
            message="模型预设可创建。",
            details={
                "model_preset_id": preset.id,
                "model_name": preset.model_name,
                "provider_id": provider.id,
                "protocol": provider.protocol.value,
                "structured_output": structured_output,
                "network_tested": network_tested,
            },
        )

    def _required_id(self, data: dict, key: str) -> str:
        value = str(data.get(key, "")).strip()
        if not value:
            raise LLMConfigError(f"缺少字段：{key}")
        return value

    def _validate_provider(self, provider: ProviderConfig) -> None:
        if provider.protocol in {
            ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            ProviderProtocol.OPENAI_RESPONSES,
            ProviderProtocol.ANTHROPIC_MESSAGES,
        } and provider.type == ProviderType.THIRD_PARTY:
            if not provider.base_url:
                raise LLMConfigError("第三方兼容服务必须配置 base_url。")
            parsed = urlparse(provider.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise LLMConfigError("base_url 必须是 http(s) URL。")
        if provider.protocol == ProviderProtocol.CUSTOM_LANGCHAIN:
            if not provider.class_path:
                raise LLMConfigError("custom_langchain 必须配置 class_path。")

    def _validate_model_preset(self, preset: ModelPreset) -> None:
        if not preset.model_name:
            raise LLMConfigError("模型预设必须配置真实 model_name。")
        if preset.temperature is not None and not 0 <= float(preset.temperature) <= 2:
            raise LLMConfigError("temperature 必须在 0 到 2 之间。")
        if preset.max_tokens is not None and int(preset.max_tokens) <= 0:
            raise LLMConfigError("max_tokens 必须大于 0。")
        unknown_extra = set(preset.extra) - self.ALLOWED_EXTRA_KEYS
        if unknown_extra:
            raise LLMConfigError(
                "extra 包含不允许字段：" + ", ".join(sorted(unknown_extra))
            )

    def _validate_ai_player_preset(self, preset: AIPlayerPreset) -> None:
        if preset.max_item_actions_per_turn < 0:
            raise LLMConfigError("max_item_actions_per_turn 不能为负。")
        if preset.max_parse_failures_per_turn < 0:
            raise LLMConfigError("max_parse_failures_per_turn 不能为负。")
        if preset.max_illegal_actions_per_turn < 0:
            raise LLMConfigError("max_illegal_actions_per_turn 不能为负。")

    def _resolve_secret(self, provider: ProviderConfig) -> str | None:
        if provider.api_key_env:
            value = os.getenv(provider.api_key_env)
            if value:
                return value
        return provider.api_key


class LLMDecisionService:
    def __init__(
        self,
        store: LLMConfigStore,
        model_factory: LangChainModelFactory | None = None,
        output_parser: OutputParser | None = None,
    ) -> None:
        self.store = store
        self.model_factory = model_factory or LangChainModelFactory()
        self.output_parser = output_parser or OutputParser()

    def decide_one_action(
        self,
        snapshot: AIPlayerPresetSnapshot,
        context: dict,
    ) -> SingleActionDecision:
        provider = self.store.get_provider(snapshot.model_preset_snapshot.provider_id)
        try:
            model = self.model_factory.create_chat_model(
                provider,
                snapshot.model_preset_snapshot,
            )
            raw = model.invoke(context)
            decision = self.output_parser.parse(raw)
            return self._validate_against_legal_actions(decision, context)
        except Exception as exc:
            logger.warning(
                "LLM decision failed; using fallback action. preset_id=%s "
                "model_preset_id=%s error=%s",
                snapshot.preset_id,
                snapshot.model_preset_snapshot.preset_id,
                exc,
            )
            return self._fallback(snapshot, context, reason=str(exc))

    def test_ai_action(self, preset_id: str, context: dict | None = None) -> PresetTestResult:
        admin = LLMAdminService(self.store, self.model_factory, self.output_parser)
        snapshot = admin.create_ai_snapshot(preset_id)
        test_context = context or self._default_test_context()
        decision = self.decide_one_action(snapshot, test_context)
        return PresetTestResult(
            ok=True,
            message="AI 玩家预设可生成单步行动。",
            details={
                "thought_summary": decision.thought_summary,
                "action": decision.action,
                "fallback_reason": decision.fallback_reason,
            },
        )

    def _validate_against_legal_actions(
        self, decision: SingleActionDecision, context: dict
    ) -> SingleActionDecision:
        legal_actions = context["current_visible_state"].get("legal_actions", [])
        normalized_action = self._normalize_action(decision.action)
        if normalized_action not in legal_actions:
            raise LLMConfigError("模型返回非法行动。")
        decision.action = normalized_action
        return decision

    def _normalize_action(self, action: dict) -> dict:
        normalized = dict(action)
        for key in {
            "target_player_id",
            "item_index",
            "target_item_index",
            "secondary_target_player_id",
        }:
            if key in normalized:
                try:
                    normalized[key] = int(normalized[key])
                except (TypeError, ValueError) as exc:
                    raise LLMConfigError(f"行动字段 {key} 必须是整数。") from exc
        return normalized

    def _fallback(
        self,
        snapshot: AIPlayerPresetSnapshot,
        context: dict,
        *,
        reason: str | None = None,
    ) -> SingleActionDecision:
        legal_actions = context["current_visible_state"].get("legal_actions", [])
        if not legal_actions:
            return SingleActionDecision(
                thought_summary="Fallback: no legal action.",
                action={"type": "shoot_self"},
                fallback_reason=reason,
            )
        inferred_shell = self._infer_remaining_shell(context)
        if inferred_shell == "LIVE":
            for action in legal_actions:
                if action.get("type") == "shoot_player":
                    return SingleActionDecision(
                        thought_summary="Fallback: public history implies LIVE.",
                        action=action,
                        fallback_reason=reason,
                    )
        if inferred_shell == "BLANK":
            for action in legal_actions:
                if action.get("type") == "shoot_self":
                    return SingleActionDecision(
                        thought_summary="Fallback: public history implies BLANK.",
                        action=action,
                        fallback_reason=reason,
                    )
        if snapshot.fallback_policy == FallbackPolicy.ATTACK_LOWEST_HP.value:
            for action in legal_actions:
                if action.get("type") == "shoot_player":
                    return SingleActionDecision(
                        thought_summary="Fallback: attack a legal target.",
                        action=action,
                        fallback_reason=reason,
                    )
        for action in legal_actions:
            if action.get("type") == "shoot_self":
                return SingleActionDecision(
                    thought_summary="Fallback: conservative shot.",
                    action=action,
                    fallback_reason=reason,
                )
        return SingleActionDecision(
            thought_summary="Fallback: first legal action.",
            action=legal_actions[0],
            fallback_reason=reason,
        )

    def _infer_remaining_shell(self, context: dict) -> str | None:
        live_count: int | None = None
        blank_count: int | None = None
        for event in context.get("action_event_list", []):
            event_type = event.get("event_type")
            payload = event.get("payload") or {}
            if event_type == "round_started":
                if "live_count" in payload and "blank_count" in payload:
                    live_count = int(payload["live_count"])
                    blank_count = int(payload["blank_count"])
            shell = payload.get("shell") or payload.get("ejected_shell")
            if live_count is not None and shell == "LIVE":
                live_count = max(0, live_count - 1)
            elif blank_count is not None and shell == "BLANK":
                blank_count = max(0, blank_count - 1)
        remaining = (
            context.get("current_visible_state", {})
            .get("public_shell_counts", {})
            .get("remaining")
        )
        if remaining == 1:
            if live_count == 1 and blank_count == 0:
                return "LIVE"
            if live_count == 0 and blank_count == 1:
                return "BLANK"
        return None

    def _default_test_context(self) -> dict:
        return {
            "initial_info_memory": {
                "game_id": "test",
                "players": [
                    {"player_id": 0, "name": "Alice", "type": "human"},
                    {"player_id": 1, "name": "AI", "type": "ai"},
                ],
            },
            "action_event_list": [],
            "current_visible_state": {
                "revision": 1,
                "current_player_id": 1,
                "players": [
                    {"player_id": 0, "name": "Alice", "hp": 3, "alive": True},
                    {"player_id": 1, "name": "AI", "hp": 3, "alive": True},
                ],
                "legal_actions": [
                    {"type": "shoot_self"},
                    {"type": "shoot_player", "target_player_id": 0},
                ],
            },
        }
