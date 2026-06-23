import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buckshot_roulette.llm.models import (
    AIPlayerPreset,
    FallbackPolicy,
    ModelPreset,
    ProviderConfig,
    ProviderProtocol,
    ProviderType,
)
from buckshot_roulette.llm.repositories import (
    FileBackedLLMConfigStore,
    LLMConfigFileError,
    default_llm_config_path,
)


class LLMFileRepositoryTests(unittest.TestCase):
    def test_new_store_writes_default_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"

            store = FileBackedLLMConfigStore(path)

            self.assertTrue(path.exists())
            self.assertIn("fake_local", store.providers)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("fake_default", payload["model_presets"])
            self.assertEqual(
                payload["ai_player_presets"]["fake_cautious"]["fallback_policy"],
                "conservative_shot",
            )
            self.assertEqual(
                payload["ai_player_presets"]["fake_cautious"]["rules_prompt_id"],
                "builtin:ai_game_rules_v1",
            )
            self.assertEqual(
                payload["ai_player_presets"]["fake_cautious"]["decision_prompt_id"],
                "builtin:ai_decision_hints_v1",
            )
            self.assertFalse(
                payload["ai_player_presets"]["fake_cautious"]["chat_enabled"]
            )
            self.assertEqual(
                payload["ai_player_presets"]["fake_cautious"]["chat_trigger_mode"],
                "mention",
            )

    def test_upsert_provider_persists_private_config_and_reloads(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"
            store = FileBackedLLMConfigStore(path)

            store.upsert_provider(
                ProviderConfig(
                    id="openrouter",
                    display_name="OpenRouter",
                    type=ProviderType.THIRD_PARTY,
                    protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
                    base_url="https://openrouter.ai/api/v1",
                    api_key="secret-value",
                    kwargs={"default_headers": {"X-App": "buckshot"}},
                )
            )

            reloaded = FileBackedLLMConfigStore(path)
            provider = reloaded.get_provider("openrouter")
            self.assertEqual(provider.protocol, ProviderProtocol.OPENAI_CHAT_COMPLETIONS)
            self.assertEqual(provider.api_key, "secret-value")
            self.assertEqual(provider.kwargs["default_headers"]["X-App"], "buckshot")

    def test_preset_versions_survive_reload_and_continue_incrementing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"
            store = FileBackedLLMConfigStore(path)
            store.upsert_model_preset(
                ModelPreset(
                    id="fake_default",
                    display_name="Fake Updated",
                    provider_id="fake_local",
                    model_name="fake-v2",
                )
            )
            store.upsert_ai_player_preset(
                AIPlayerPreset(
                    id="fake_cautious",
                    display_name="Fake AI Updated",
                    enabled=True,
                    model_preset_id="fake_default",
                    fallback_policy=FallbackPolicy.ATTACK_LOWEST_HP,
                )
            )

            reloaded = FileBackedLLMConfigStore(path)

            self.assertEqual(reloaded.get_model_preset("fake_default").version, 2)
            self.assertEqual(reloaded.get_ai_player_preset("fake_cautious").version, 2)
            reloaded.upsert_model_preset(
                ModelPreset(
                    id="fake_default",
                    display_name="Fake Updated Again",
                    provider_id="fake_local",
                    model_name="fake-v3",
                )
            )
            self.assertEqual(reloaded.get_model_preset("fake_default").version, 3)

    def test_missing_defaults_are_added_to_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "providers": {},
                        "model_presets": {},
                        "ai_player_presets": {},
                    }
                ),
                encoding="utf-8",
            )

            store = FileBackedLLMConfigStore(path)

            self.assertIn("fake_local", store.providers)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("fake_cautious", payload["ai_player_presets"])

    def test_old_ai_player_preset_config_loads_prompt_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "providers": {
                            "fake_local": {
                                "id": "fake_local",
                                "display_name": "Fake Local",
                                "type": "official",
                                "protocol": "fake",
                                "base_url": None,
                                "api_key_env": None,
                                "api_key": None,
                                "class_path": None,
                                "kwargs": {},
                            }
                        },
                        "model_presets": {
                            "fake_default": {
                                "id": "fake_default",
                                "display_name": "Fake Default",
                                "provider_id": "fake_local",
                                "model_name": "fake-buckshot-player",
                                "version": 1,
                                "temperature": 0.0,
                                "max_tokens": 200,
                                "reasoning_effort": None,
                                "timeout_seconds": 30,
                                "max_retries": 2,
                                "extra": {},
                            }
                        },
                        "ai_player_presets": {
                            "fake_cautious": {
                                "id": "fake_cautious",
                                "display_name": "Fake Cautious",
                                "enabled": True,
                                "model_preset_id": "fake_default",
                                "version": 1,
                                "persona_prompt": "old persona",
                                "strategy_prompt": "old strategy",
                                "max_item_actions_per_turn": 8,
                                "max_parse_failures_per_turn": 2,
                                "max_illegal_actions_per_turn": 2,
                                "fallback_policy": "conservative_shot",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            store = FileBackedLLMConfigStore(path)
            preset = store.get_ai_player_preset("fake_cautious")

            self.assertEqual(preset.rules_prompt_id, "builtin:ai_game_rules_v1")
            self.assertEqual(
                preset.decision_prompt_id,
                "builtin:ai_decision_hints_v1",
            )
            self.assertFalse(preset.chat_enabled)
            self.assertEqual(preset.chat_trigger_mode.value, "mention")

    def test_invalid_json_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"
            path.write_text("{bad json", encoding="utf-8")

            with self.assertRaises(LLMConfigFileError):
                FileBackedLLMConfigStore(path)

    def test_default_path_uses_environment_overrides(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit_file = Path(tmp_dir) / "custom.json"
            with patch.dict(
                os.environ,
                {
                    "BUCKSHOT_LLM_CONFIG_FILE": str(explicit_file),
                    "BUCKSHOT_DATA_DIR": str(Path(tmp_dir) / "ignored"),
                },
                clear=False,
            ):
                self.assertEqual(default_llm_config_path(), explicit_file)

            data_dir = Path(tmp_dir) / "data"
            with patch.dict(
                os.environ,
                {
                    "BUCKSHOT_LLM_CONFIG_FILE": "",
                    "BUCKSHOT_DATA_DIR": str(data_dir),
                },
                clear=False,
            ):
                self.assertEqual(default_llm_config_path(), data_dir / "llm_config.json")

    def test_successful_save_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "llm_config.json"
            store = FileBackedLLMConfigStore(path)

            store.upsert_provider(
                ProviderConfig(
                    id="fake_2",
                    display_name="Fake 2",
                    type=ProviderType.OFFICIAL,
                    protocol=ProviderProtocol.FAKE,
                )
            )

            temp_files = list(Path(tmp_dir).glob(".llm_config.json.*.tmp"))
            self.assertEqual(temp_files, [])


if __name__ == "__main__":
    unittest.main()
