from __future__ import annotations

import importlib
import json
import os
from typing import Any

from buckshot_roulette.llm.models import ModelPresetSnapshot, ProviderConfig, ProviderProtocol


class ModelFactoryError(RuntimeError):
    pass


class MissingProviderDependencyError(ModelFactoryError):
    def __init__(self, package_name: str, import_name: str) -> None:
        super().__init__(
            f"缺少 provider 依赖：请安装 {package_name} 后再测试或使用该模型。"
        )
        self.package_name = package_name
        self.import_name = import_name


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


class LangChainChatModelAdapter:
    def __init__(self, model: Any) -> None:
        self.model = model

    def invoke(self, context: dict) -> str:
        ai_profile = context.get("ai_profile") or {}
        profile_prompt = "\n".join(
            self._prompt_section(label, ai_profile.get(key))
            for label, key in [
                ("Game rules", "rules_prompt"),
                ("Decision hints", "decision_prompt"),
                ("Persona", "persona_prompt"),
                ("Strategy", "strategy_prompt"),
            ]
            if str(ai_profile.get(key) or "").strip()
        )
        system_prompt = (
            "You are an AI player for a Buckshot Roulette game. "
            "Return exactly one JSON object with keys thought_summary and action. "
            "Do not use markdown fences, prose, XML tags, or comments. "
            "Keep thought_summary under 120 characters and do not include chain-of-thought. "
            "Use only one action from current_visible_state.legal_actions. "
            "Do not reveal or assume hidden shell order. "
            "Track remaining LIVE/BLANK counts yourself from round_started events "
            "and public shot/item events. If the public history proves the next "
            "shell is LIVE, prefer shooting an opponent over shooting yourself. "
            'Example response: {"thought_summary":"Known LIVE; attack.",'
            '"action":{"type":"shoot_player","target_player_id":0}}'
        )
        if profile_prompt:
            system_prompt = f"{system_prompt}\n\nAI profile:\n{profile_prompt}"
        messages = [
            ("system", system_prompt),
            ("human", json.dumps(context, ensure_ascii=False)),
        ]
        response = self.model.invoke(messages)
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            return json.dumps(tool_calls, ensure_ascii=False)
        content = getattr(response, "content", response)
        self._raise_if_only_reasoning_content(response, content)
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        if isinstance(content, list):
            return self._content_blocks_to_text(content)
        return str(content)

    def _prompt_section(self, label: str, value: Any) -> str:
        return f"{label}:\n{str(value).strip()}"

    def _raise_if_only_reasoning_content(self, response: Any, content: Any) -> None:
        if content:
            return
        additional = getattr(response, "additional_kwargs", {}) or {}
        reasoning_content = additional.get("reasoning_content")
        if not reasoning_content:
            return
        metadata = getattr(response, "response_metadata", {}) or {}
        token_usage = metadata.get("token_usage") or {}
        completion_details = token_usage.get("completion_tokens_details") or {}
        reason = metadata.get("finish_reason")
        completion_tokens = token_usage.get("completion_tokens")
        reasoning_tokens = completion_details.get("reasoning_tokens")
        raise ModelFactoryError(
            "模型只返回 reasoning_content，没有返回正文 content。"
            f" finish_reason={reason}"
            f" completion_tokens={completion_tokens}"
            f" reasoning_tokens={reasoning_tokens}"
            "；请关闭 thinking 或提高 max_tokens。"
        )

    def _content_blocks_to_text(self, blocks: list[Any]) -> str:
        texts: list[str] = []
        for block in blocks:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                if block.get("type") in {"text", "output_text"}:
                    texts.append(str(block.get("text", "")))
                elif "json" in block:
                    texts.append(json.dumps(block["json"], ensure_ascii=False))
                elif "args" in block:
                    texts.append(json.dumps(block["args"], ensure_ascii=False))
        return "\n".join(texts)


class LangChainModelFactory:
    EXTRA_PACKAGES = {
        ProviderProtocol.OPENAI_RESPONSES: ("langchain-openai", "langchain_openai"),
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS: (
            "langchain-openai",
            "langchain_openai",
        ),
        ProviderProtocol.ANTHROPIC: ("langchain-anthropic", "langchain_anthropic"),
        ProviderProtocol.ANTHROPIC_MESSAGES: (
            "langchain-anthropic",
            "langchain_anthropic",
        ),
        ProviderProtocol.GEMINI: ("langchain-google-genai", "langchain_google_genai"),
        ProviderProtocol.DEEPSEEK: ("langchain-deepseek", "langchain_deepseek"),
    }

    def create_chat_model(
        self,
        provider: ProviderConfig,
        model_preset: ModelPresetSnapshot,
    ):
        if provider.protocol == ProviderProtocol.FAKE:
            return FakeChatModel()
        if provider.protocol in {
            ProviderProtocol.OPENAI_RESPONSES,
            ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        }:
            model_class = self._import_provider_class(
                provider.protocol, "ChatOpenAI"
            )
            kwargs = self._openai_kwargs(provider, model_preset)
            return LangChainChatModelAdapter(model_class(**kwargs))
        if provider.protocol in {
            ProviderProtocol.ANTHROPIC,
            ProviderProtocol.ANTHROPIC_MESSAGES,
        }:
            model_class = self._import_provider_class(
                provider.protocol, "ChatAnthropic"
            )
            kwargs = self._standard_kwargs(provider, model_preset)
            return LangChainChatModelAdapter(model_class(**kwargs))
        if provider.protocol == ProviderProtocol.GEMINI:
            model_class = self._import_provider_class(
                provider.protocol, "ChatGoogleGenerativeAI"
            )
            kwargs = self._standard_kwargs(provider, model_preset)
            return LangChainChatModelAdapter(model_class(**kwargs))
        if provider.protocol == ProviderProtocol.DEEPSEEK:
            model_class = self._import_provider_class(
                provider.protocol, "ChatDeepSeek"
            )
            kwargs = self._standard_kwargs(provider, model_preset)
            return LangChainChatModelAdapter(model_class(**kwargs))
        if provider.protocol == ProviderProtocol.CUSTOM_LANGCHAIN:
            model_class = self._import_custom_class(provider)
            kwargs = {
                **provider.kwargs,
                **self._standard_kwargs(provider, model_preset),
            }
            return LangChainChatModelAdapter(model_class(**kwargs))
        raise ModelFactoryError(f"不支持的 provider 协议：{provider.protocol.value}")

    def check_dependencies(self, provider: ProviderConfig) -> None:
        if provider.protocol in {ProviderProtocol.FAKE, ProviderProtocol.CUSTOM_LANGCHAIN}:
            return
        package_name, import_name = self.EXTRA_PACKAGES[provider.protocol]
        try:
            importlib.import_module(import_name)
        except ImportError as exc:
            raise MissingProviderDependencyError(package_name, import_name) from exc

    def _import_provider_class(
        self, protocol: ProviderProtocol, class_name: str
    ):
        package_name, import_name = self.EXTRA_PACKAGES[protocol]
        try:
            module = importlib.import_module(import_name)
        except ImportError as exc:
            raise MissingProviderDependencyError(package_name, import_name) from exc
        try:
            return getattr(module, class_name)
        except AttributeError as exc:
            raise ModelFactoryError(
                f"{import_name} 中找不到 {class_name}，请升级 {package_name}。"
            ) from exc

    def _import_custom_class(self, provider: ProviderConfig):
        if not provider.class_path:
            raise ModelFactoryError("custom_langchain provider 缺少 class_path。")
        if not provider.class_path.startswith("buckshot_roulette."):
            raise ModelFactoryError("custom_langchain class_path 不在允许模块内。")
        module_name, _, class_name = provider.class_path.rpartition(".")
        if not module_name or not class_name:
            raise ModelFactoryError("custom_langchain class_path 格式无效。")
        module = importlib.import_module(module_name)
        return getattr(module, class_name)

    def _openai_kwargs(
        self, provider: ProviderConfig, model_preset: ModelPresetSnapshot
    ) -> dict[str, Any]:
        kwargs = self._standard_kwargs(provider, model_preset)
        if provider.protocol == ProviderProtocol.OPENAI_RESPONSES:
            kwargs["use_responses_api"] = True
        if model_preset.reasoning_effort:
            kwargs["reasoning_effort"] = model_preset.reasoning_effort
        return kwargs

    def _standard_kwargs(
        self, provider: ProviderConfig, model_preset: ModelPresetSnapshot
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model_preset.model_name,
            "timeout": model_preset.timeout_seconds,
            "max_retries": model_preset.max_retries,
            **model_preset.extra,
        }
        if model_preset.temperature is not None:
            kwargs["temperature"] = model_preset.temperature
        if model_preset.max_tokens is not None:
            kwargs["max_tokens"] = model_preset.max_tokens
        secret = self._resolve_secret(provider)
        if secret:
            kwargs["api_key"] = secret
        if provider.base_url:
            kwargs["base_url"] = provider.base_url
        return kwargs

    def _resolve_secret(self, provider: ProviderConfig) -> str | None:
        if provider.api_key_env:
            value = os.getenv(provider.api_key_env)
            if value:
                return value
        return provider.api_key
