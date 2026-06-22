import unittest
from unittest.mock import patch

from buckshot_roulette.llm.model_factory import (
    LangChainChatModelAdapter,
    LangChainModelFactory,
    MissingProviderDependencyError,
)
from buckshot_roulette.llm.models import SingleActionDecision
from buckshot_roulette.llm.output_parser import OutputParser, OutputParserError
from buckshot_roulette.llm.repositories import LLMConfigStore
from buckshot_roulette.llm.serializers import provider_to_public_dict
from buckshot_roulette.llm.services import LLMAdminService, LLMConfigError, LLMDecisionService


class LLMServiceTests(unittest.TestCase):
    def test_provider_api_key_is_masked(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)
        provider = admin.create_provider(
            {
                "id": "openrouter",
                "display_name": "OpenRouter",
                "type": "third_party",
                "protocol": "openai_chat_completions",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "abcd1234567890ef",
            }
        )

        public = provider_to_public_dict(provider)

        self.assertEqual(public["api_key"], "abcd***90ef")

    def test_model_preset_version_increments_and_snapshot_freezes(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)

        snapshot = admin.create_ai_snapshot("fake_cautious")
        admin.create_model_preset(
            {
                "id": "fake_default",
                "display_name": "Fake Default Updated",
                "provider_id": "fake_local",
                "model_name": "fake-updated",
            }
        )
        new_snapshot = admin.create_ai_snapshot("fake_cautious")

        self.assertEqual(snapshot.model_preset_snapshot.preset_version, 1)
        self.assertEqual(snapshot.model_preset_snapshot.model_name, "fake-buckshot-player")
        self.assertEqual(new_snapshot.model_preset_snapshot.preset_version, 2)
        self.assertEqual(new_snapshot.model_preset_snapshot.model_name, "fake-updated")

    def test_extra_field_allowlist_rejects_unknown_fields(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)

        with self.assertRaises(LLMConfigError):
            admin.create_model_preset(
                {
                    "id": "bad",
                    "provider_id": "fake_local",
                    "model_name": "fake",
                    "extra": {"danger": True},
                }
            )

    def test_output_parser_validates_schema(self):
        parser = OutputParser()

        decision = parser.parse(
            '{"thought_summary":"x","action":{"type":"shoot_self"}}'
        )

        self.assertEqual(decision.action, {"type": "shoot_self"})
        with self.assertRaises(OutputParserError):
            parser.parse('{"action":{"type":"shoot_player"}}')

    def test_output_parser_accepts_markdown_json_block(self):
        parser = OutputParser()

        decision = parser.parse(
            '```json\n'
            '{"thought_summary":"x","action":{"type":"shoot_player",'
            '"target_player_id":0}}\n'
            '```'
        )

        self.assertEqual(
            decision.action,
            {"type": "shoot_player", "target_player_id": 0},
        )

    def test_fake_decision_service_returns_legal_action(self):
        store = LLMConfigStore()
        decision_service = LLMDecisionService(store)

        result = decision_service.test_ai_action("fake_cautious")

        self.assertTrue(result.ok)
        self.assertIn(result.details["action"]["type"], {"shoot_player", "shoot_self"})

    def test_decision_service_normalizes_numeric_action_fields(self):
        store = LLMConfigStore()
        decision_service = LLMDecisionService(store)
        snapshot = LLMAdminService(store).create_ai_snapshot("fake_cautious")
        context = {
            "current_visible_state": {
                "legal_actions": [
                    {"type": "shoot_self"},
                    {"type": "shoot_player", "target_player_id": 0},
                ]
            }
        }

        with patch.object(
            decision_service.model_factory,
            "create_chat_model",
            return_value=type(
                "DummyModel",
                (),
                {
                    "invoke": lambda self, _: {
                        "thought_summary": "Last shell is live; attack.",
                        "action": {
                            "type": "shoot_player",
                            "target_player_id": "0",
                        },
                    }
                },
            )(),
        ):
            decision = decision_service.decide_one_action(snapshot, context)

        self.assertEqual(
            decision,
            SingleActionDecision(
                thought_summary="Last shell is live; attack.",
                action={"type": "shoot_player", "target_player_id": 0},
                fallback_reason=None,
            ),
        )

    def test_fallback_uses_public_history_when_last_shell_is_known_live(self):
        store = LLMConfigStore()
        decision_service = LLMDecisionService(store)
        snapshot = LLMAdminService(store).create_ai_snapshot("fake_cautious")
        context = {
            "action_event_list": [
                {
                    "event_type": "round_started",
                    "payload": {"live_count": 1, "blank_count": 2},
                },
                {"event_type": "shoot_self", "payload": {"shell": "BLANK"}},
                {"event_type": "shoot_self", "payload": {"shell": "BLANK"}},
            ],
            "current_visible_state": {
                "public_shell_counts": {"remaining": 1},
                "legal_actions": [
                    {"type": "shoot_self"},
                    {"type": "shoot_player", "target_player_id": 0},
                ],
            },
        }

        with patch.object(
            decision_service.model_factory,
            "create_chat_model",
            side_effect=RuntimeError("missing credentials"),
        ):
            decision = decision_service.decide_one_action(snapshot, context)

        self.assertEqual(
            decision.action,
            {"type": "shoot_player", "target_player_id": 0},
        )
        self.assertEqual(
            decision.thought_summary,
            "Fallback: public history implies LIVE.",
        )
        self.assertEqual(decision.fallback_reason, "missing credentials")

    def test_missing_provider_dependency_is_reported(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)
        admin.create_provider(
            {
                "id": "openai_official",
                "display_name": "OpenAI",
                "type": "official",
                "protocol": "openai_responses",
                "api_key": "sk-test",
            }
        )
        admin.create_model_preset(
            {
                "id": "openai_model",
                "provider_id": "openai_official",
                "model_name": "gpt-test",
            }
        )

        with patch.object(
            admin.model_factory,
            "check_dependencies",
            side_effect=MissingProviderDependencyError(
                "langchain-openai", "langchain_openai"
            ),
        ):
            result = admin.test_model_preset("openai_model")

        self.assertFalse(result.ok)
        self.assertEqual(result.details["package"], "langchain-openai")

    def test_openai_factory_maps_responses_kwargs(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)
        provider = admin.create_provider(
            {
                "id": "openai_official",
                "display_name": "OpenAI",
                "type": "official",
                "protocol": "openai_responses",
                "api_key": "sk-test",
            }
        )
        preset = admin.create_model_preset(
            {
                "id": "openai_model",
                "provider_id": "openai_official",
                "model_name": "gpt-test",
                "temperature": 0.2,
                "max_tokens": 100,
                "reasoning_effort": "medium",
                "extra": {"top_p": 0.9},
            }
        )
        snapshot = admin.create_ai_snapshot("fake_cautious").model_preset_snapshot
        snapshot.provider_id = preset.provider_id
        snapshot.model_name = preset.model_name
        snapshot.temperature = preset.temperature
        snapshot.max_tokens = preset.max_tokens
        snapshot.reasoning_effort = preset.reasoning_effort
        snapshot.extra = dict(preset.extra)
        captured = {}

        class DummyChat:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        factory = LangChainModelFactory()
        with patch.object(factory, "_import_provider_class", return_value=DummyChat):
            model = factory.create_chat_model(provider, snapshot)

        self.assertIsInstance(model, LangChainChatModelAdapter)
        self.assertEqual(captured["model"], "gpt-test")
        self.assertTrue(captured["use_responses_api"])
        self.assertEqual(captured["api_key"], "sk-test")
        self.assertEqual(captured["reasoning_effort"], "medium")
        self.assertEqual(captured["top_p"], 0.9)


if __name__ == "__main__":
    unittest.main()
