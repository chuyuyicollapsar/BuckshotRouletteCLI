from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from buckshot_roulette.llm.prompt_library import (
    DEFAULT_DECISION_PROMPT_ID,
    DEFAULT_RULES_PROMPT_ID,
)


class ProviderType(str, Enum):
    OFFICIAL = "official"
    THIRD_PARTY = "third_party"


class ProviderProtocol(str, Enum):
    OPENAI_RESPONSES = "openai_responses"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    ANTHROPIC = "anthropic"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    CUSTOM_LANGCHAIN = "custom_langchain"
    FAKE = "fake"


class FallbackPolicy(str, Enum):
    CONSERVATIVE_SHOT = "conservative_shot"
    ATTACK_LOWEST_HP = "attack_lowest_hp"


@dataclass(slots=True)
class ProviderConfig:
    id: str
    display_name: str
    type: ProviderType
    protocol: ProviderProtocol
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    class_path: str | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelPreset:
    id: str
    display_name: str
    provider_id: str
    model_name: str
    version: int = 1
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 2
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelPresetSnapshot:
    preset_id: str
    preset_version: int
    provider_id: str
    protocol: str
    model_name: str
    temperature: float | None
    max_tokens: int | None
    reasoning_effort: str | None
    timeout_seconds: int
    max_retries: int
    extra: dict[str, Any]


@dataclass(slots=True)
class AIPlayerPreset:
    id: str
    display_name: str
    enabled: bool
    model_preset_id: str
    version: int = 1
    rules_prompt_id: str = DEFAULT_RULES_PROMPT_ID
    decision_prompt_id: str = DEFAULT_DECISION_PROMPT_ID
    custom_rules_prompt: str | None = None
    custom_decision_prompt: str | None = None
    persona_prompt: str = ""
    strategy_prompt: str = ""
    max_item_actions_per_turn: int = 8
    max_parse_failures_per_turn: int = 2
    max_illegal_actions_per_turn: int = 2
    fallback_policy: FallbackPolicy = FallbackPolicy.CONSERVATIVE_SHOT


@dataclass(slots=True)
class AIPlayerPresetSnapshot:
    preset_id: str
    preset_version: int
    display_name: str
    model_preset_snapshot: ModelPresetSnapshot
    rules_prompt: str
    decision_prompt: str
    persona_prompt: str
    strategy_prompt: str
    max_item_actions_per_turn: int
    max_parse_failures_per_turn: int
    max_illegal_actions_per_turn: int
    fallback_policy: str


@dataclass(slots=True)
class SingleActionDecision:
    thought_summary: str
    action: dict[str, Any]
    fallback_reason: str | None = None


@dataclass(slots=True)
class PresetTestResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
