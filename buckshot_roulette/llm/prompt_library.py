from __future__ import annotations

from importlib import resources
from types import MappingProxyType


DEFAULT_RULES_PROMPT_ID = "builtin:ai_game_rules_v1"
DEFAULT_DECISION_PROMPT_ID = "builtin:ai_decision_hints_v1"

BUILTIN_PROMPTS = MappingProxyType(
    {
        DEFAULT_RULES_PROMPT_ID: "ai_game_rules.md",
        DEFAULT_DECISION_PROMPT_ID: "ai_decision_hints.md",
    }
)


class PromptLibraryError(ValueError):
    pass


class PromptLibrary:
    def resolve(self, prompt_id: str, *, custom_text: str | None = None) -> str:
        custom = custom_text.strip() if custom_text is not None else ""
        if custom:
            return custom

        normalized_id = str(prompt_id or "").strip()
        if not normalized_id:
            raise PromptLibraryError("prompt_id must not be empty")

        filename = BUILTIN_PROMPTS.get(normalized_id)
        if filename is None:
            raise PromptLibraryError(f"unknown prompt_id: {normalized_id}")

        try:
            text = (
                resources.files("buckshot_roulette.llm.prompts")
                .joinpath(filename)
                .read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise PromptLibraryError(
                f"builtin prompt resource is missing: {normalized_id}"
            ) from exc

        resolved = text.strip()
        if not resolved:
            raise PromptLibraryError(f"builtin prompt resource is empty: {normalized_id}")
        return resolved
