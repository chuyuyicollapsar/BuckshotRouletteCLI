from __future__ import annotations

from dataclasses import asdict
from typing import Any

from buckshot_roulette.llm.models import (
    AIPlayerPreset,
    AIPlayerPresetSnapshot,
    ModelPreset,
    ModelPresetSnapshot,
    ProviderConfig,
)


def mask_secret(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def provider_to_public_dict(provider: ProviderConfig) -> dict[str, Any]:
    data = asdict(provider)
    data["type"] = provider.type.value
    data["protocol"] = provider.protocol.value
    data["api_key"] = mask_secret(provider.api_key)
    return data


def provider_to_private_dict(provider: ProviderConfig) -> dict[str, Any]:
    data = asdict(provider)
    data["type"] = provider.type.value
    data["protocol"] = provider.protocol.value
    return data


def model_preset_to_dict(preset: ModelPreset) -> dict[str, Any]:
    return asdict(preset)


def ai_player_preset_to_dict(preset: AIPlayerPreset) -> dict[str, Any]:
    data = asdict(preset)
    data["fallback_policy"] = preset.fallback_policy.value
    data["chat_trigger_mode"] = preset.chat_trigger_mode.value
    return data


def model_snapshot_to_dict(snapshot: ModelPresetSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def ai_snapshot_to_dict(snapshot: AIPlayerPresetSnapshot) -> dict[str, Any]:
    data = asdict(snapshot)
    data["model_preset_snapshot"] = model_snapshot_to_dict(
        snapshot.model_preset_snapshot
    )
    data["chat_model_preset_snapshot"] = (
        model_snapshot_to_dict(snapshot.chat_model_preset_snapshot)
        if snapshot.chat_model_preset_snapshot is not None
        else None
    )
    return data
