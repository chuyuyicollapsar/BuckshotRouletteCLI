from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from buckshot_roulette.llm.models import (
    AIPlayerPreset,
    FallbackPolicy,
    ModelPreset,
    ProviderConfig,
    ProviderProtocol,
    ProviderType,
)
from buckshot_roulette.llm.prompt_library import (
    DEFAULT_DECISION_PROMPT_ID,
    DEFAULT_RULES_PROMPT_ID,
)
from buckshot_roulette.llm.serializers import (
    ai_player_preset_to_dict,
    model_preset_to_dict,
    provider_to_private_dict,
)


LLM_CONFIG_FILE_NAME = "llm_config.json"
LLM_CONFIG_SCHEMA_VERSION = 1


class LLMConfigFileError(ValueError):
    pass


def default_llm_config_dir() -> Path:
    data_dir = os.getenv("BUCKSHOT_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser()

    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata).expanduser() / "BuckshotRoulette"
        return Path.home() / "AppData" / "Roaming" / "BuckshotRoulette"

    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "buckshot-roulette"
    return Path.home() / ".config" / "buckshot-roulette"


def default_llm_config_path() -> Path:
    config_file = os.getenv("BUCKSHOT_LLM_CONFIG_FILE")
    if config_file:
        return Path(config_file).expanduser()
    return default_llm_config_dir() / LLM_CONFIG_FILE_NAME


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


class FileBackedLLMConfigStore(LLMConfigStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        super().__init__()
        if self.path.exists():
            self._load()
            if self._ensure_default_entries():
                self.save()
        else:
            self.save()

    @classmethod
    def from_default_path(cls) -> FileBackedLLMConfigStore:
        return cls(default_llm_config_path())

    def upsert_provider(self, provider: ProviderConfig) -> ProviderConfig:
        provider = super().upsert_provider(provider)
        self.save()
        return provider

    def upsert_model_preset(self, preset: ModelPreset) -> ModelPreset:
        preset = super().upsert_model_preset(preset)
        self.save()
        return preset

    def upsert_ai_player_preset(self, preset: AIPlayerPreset) -> AIPlayerPreset:
        preset = super().upsert_ai_player_preset(preset)
        self.save()
        return preset

    def save(self) -> None:
        tmp_path = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(
                    self._to_payload(),
                    file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, self.path)
        except OSError as exc:
            raise LLMConfigFileError(
                f"无法写入 LLM 配置文件：{self.path}"
            ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except json.JSONDecodeError as exc:
            raise LLMConfigFileError(
                f"LLM 配置文件不是有效 JSON：{self.path}"
            ) from exc
        except OSError as exc:
            raise LLMConfigFileError(
                f"无法读取 LLM 配置文件：{self.path}"
            ) from exc

        try:
            self._load_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMConfigFileError(
                f"LLM 配置文件格式无效：{self.path}"
            ) from exc

    def _to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": LLM_CONFIG_SCHEMA_VERSION,
            "providers": {
                provider_id: provider_to_private_dict(provider)
                for provider_id, provider in self.providers.items()
            },
            "model_presets": {
                preset_id: model_preset_to_dict(preset)
                for preset_id, preset in self.model_presets.items()
            },
            "ai_player_presets": {
                preset_id: ai_player_preset_to_dict(preset)
                for preset_id, preset in self.ai_player_presets.items()
            },
        }

    def _load_payload(self, payload: Any) -> None:
        payload = _expect_mapping(payload, "root")
        if payload.get("schema_version") != LLM_CONFIG_SCHEMA_VERSION:
            raise TypeError("unsupported schema_version")

        providers = _expect_mapping(payload.get("providers", {}), "providers")
        model_presets = _expect_mapping(
            payload.get("model_presets", {}), "model_presets"
        )
        ai_player_presets = _expect_mapping(
            payload.get("ai_player_presets", {}), "ai_player_presets"
        )

        self.providers = {
            provider_id: _provider_from_dict(provider_id, raw)
            for provider_id, raw in providers.items()
        }
        self.model_presets = {
            preset_id: _model_preset_from_dict(preset_id, raw)
            for preset_id, raw in model_presets.items()
        }
        self.ai_player_presets = {
            preset_id: _ai_player_preset_from_dict(preset_id, raw)
            for preset_id, raw in ai_player_presets.items()
        }

    def _ensure_default_entries(self) -> bool:
        defaults = LLMConfigStore()
        changed = False
        for provider_id, provider in defaults.providers.items():
            if provider_id not in self.providers:
                self.providers[provider_id] = provider
                changed = True
        for preset_id, preset in defaults.model_presets.items():
            if preset_id not in self.model_presets:
                self.model_presets[preset_id] = preset
                changed = True
        for preset_id, preset in defaults.ai_player_presets.items():
            if preset_id not in self.ai_player_presets:
                self.ai_player_presets[preset_id] = preset
                changed = True
        return changed


def _expect_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _require_id(section_id: str, raw: dict[str, Any]) -> str:
    value = str(raw["id"])
    if value != section_id:
        raise ValueError(f"id mismatch: {section_id} != {value}")
    return value


def _provider_from_dict(provider_id: str, raw: Any) -> ProviderConfig:
    raw = _expect_mapping(raw, f"providers.{provider_id}")
    return ProviderConfig(
        id=_require_id(provider_id, raw),
        display_name=str(raw.get("display_name") or raw["id"]),
        type=ProviderType(raw["type"]),
        protocol=ProviderProtocol(raw["protocol"]),
        base_url=raw.get("base_url"),
        api_key_env=raw.get("api_key_env"),
        api_key=raw.get("api_key"),
        class_path=raw.get("class_path"),
        kwargs=dict(raw.get("kwargs") or {}),
    )


def _model_preset_from_dict(preset_id: str, raw: Any) -> ModelPreset:
    raw = _expect_mapping(raw, f"model_presets.{preset_id}")
    return ModelPreset(
        id=_require_id(preset_id, raw),
        display_name=str(raw.get("display_name") or raw["id"]),
        provider_id=str(raw["provider_id"]),
        model_name=str(raw["model_name"]),
        version=int(raw.get("version", 1)),
        temperature=raw.get("temperature"),
        max_tokens=raw.get("max_tokens"),
        reasoning_effort=raw.get("reasoning_effort"),
        timeout_seconds=int(raw.get("timeout_seconds", 30)),
        max_retries=int(raw.get("max_retries", 2)),
        extra=dict(raw.get("extra") or {}),
    )


def _ai_player_preset_from_dict(preset_id: str, raw: Any) -> AIPlayerPreset:
    raw = _expect_mapping(raw, f"ai_player_presets.{preset_id}")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be a boolean")
    return AIPlayerPreset(
        id=_require_id(preset_id, raw),
        display_name=str(raw.get("display_name") or raw["id"]),
        enabled=enabled,
        model_preset_id=str(raw["model_preset_id"]),
        version=int(raw.get("version", 1)),
        rules_prompt_id=str(raw.get("rules_prompt_id") or DEFAULT_RULES_PROMPT_ID),
        decision_prompt_id=str(
            raw.get("decision_prompt_id") or DEFAULT_DECISION_PROMPT_ID
        ),
        custom_rules_prompt=_optional_string(raw.get("custom_rules_prompt")),
        custom_decision_prompt=_optional_string(raw.get("custom_decision_prompt")),
        persona_prompt=str(raw.get("persona_prompt", "")),
        strategy_prompt=str(raw.get("strategy_prompt", "")),
        max_item_actions_per_turn=int(raw.get("max_item_actions_per_turn", 8)),
        max_parse_failures_per_turn=int(raw.get("max_parse_failures_per_turn", 2)),
        max_illegal_actions_per_turn=int(raw.get("max_illegal_actions_per_turn", 2)),
        fallback_policy=FallbackPolicy(
            raw.get("fallback_policy", FallbackPolicy.CONSERVATIVE_SHOT.value)
        ),
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
