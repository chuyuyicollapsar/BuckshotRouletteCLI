import unittest
from unittest.mock import patch

from buckshot_roulette.llm.model_factory import (
    LangChainChatModelAdapter,
    LangChainModelFactory,
    ModelFactoryError,
    MissingProviderDependencyError,
)
from buckshot_roulette.llm.models import SingleActionDecision
from buckshot_roulette.llm.output_parser import OutputParser, OutputParserError
from buckshot_roulette.llm.prompt_library import PromptLibrary
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

    def test_prompt_library_resolves_builtin_prompts(self):
        library = PromptLibrary()

        rules_prompt = library.resolve("builtin:ai_game_rules_v1")
        decision_prompt = library.resolve("builtin:ai_decision_hints_v1")

        self.assertIn("一场比赛包含 3 局游戏", rules_prompt)
        self.assertIn("射击对方是最佳策略", decision_prompt)

    def test_ai_snapshot_freezes_builtin_prompt_text(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)

        snapshot = admin.create_ai_snapshot("fake_cautious")

        self.assertIn("可见信息边界", snapshot.rules_prompt)
        self.assertIn("特定局面决策", snapshot.decision_prompt)

    def test_custom_prompts_override_builtin_prompt_text(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)
        admin.create_ai_player_preset(
            {
                "id": "custom_ai",
                "display_name": "Custom AI",
                "enabled": True,
                "model_preset_id": "fake_default",
                "custom_rules_prompt": "custom rules",
                "custom_decision_prompt": "custom decision hints",
            }
        )

        snapshot = admin.create_ai_snapshot("custom_ai")

        self.assertEqual(snapshot.rules_prompt, "custom rules")
        self.assertEqual(snapshot.decision_prompt, "custom decision hints")

    def test_unknown_prompt_id_is_rejected(self):
        store = LLMConfigStore()
        admin = LLMAdminService(store)

        with self.assertRaises(LLMConfigError):
            admin.create_ai_player_preset(
                {
                    "id": "bad_prompt",
                    "display_name": "Bad Prompt",
                    "enabled": True,
                    "model_preset_id": "fake_default",
                    "rules_prompt_id": "builtin:missing",
                }
            )

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

    def test_output_parser_accepts_python_dict_literal(self):
        parser = OutputParser()

        decision = parser.parse(
            "{'thought_summary': 'x', 'action': {'type': 'shoot_self'}}"
        )

        self.assertEqual(decision.action, {"type": "shoot_self"})

    def test_output_parser_error_includes_raw_preview(self):
        parser = OutputParser()

        with self.assertRaises(OutputParserError) as context:
            parser.parse("I choose to shoot myself.")

        self.assertIn("raw_output_preview", str(context.exception))

    def test_langchain_adapter_reports_reasoning_only_response(self):
        class DummyModel:
            def invoke(self, _):
                return type(
                    "DummyResponse",
                    (),
                    {
                        "content": "",
                        "additional_kwargs": {"reasoning_content": "hidden"},
                        "response_metadata": {
                            "finish_reason": "length",
                            "token_usage": {
                                "completion_tokens": 500,
                                "completion_tokens_details": {
                                    "reasoning_tokens": 500,
                                },
                            },
                        },
                    },
                )()

        adapter = LangChainChatModelAdapter(DummyModel())

        with self.assertRaises(ModelFactoryError) as context:
            adapter.invoke({"current_visible_state": {"legal_actions": []}})

        self.assertIn("只返回 reasoning_content", str(context.exception))

    def test_langchain_adapter_includes_prompt_sections(self):
        captured = {}

        class DummyModel:
            def invoke(self, messages):
                captured["messages"] = messages
                return '{"thought_summary":"x","action":{"type":"shoot_self"}}'

        adapter = LangChainChatModelAdapter(DummyModel())

        adapter.invoke(
            {
                "ai_profile": {
                    "rules_prompt": "rules text",
                    "decision_prompt": "decision text",
                    "persona_prompt": "persona text",
                    "strategy_prompt": "strategy text",
                },
                "current_visible_state": {"legal_actions": [{"type": "shoot_self"}]},
            }
        )

        system_prompt = captured["messages"][0][1]
        self.assertIn("Game rules:\nrules text", system_prompt)
        self.assertIn("Decision hints:\ndecision text", system_prompt)
        self.assertIn("Persona:\npersona text", system_prompt)
        self.assertIn("Strategy:\nstrategy text", system_prompt)

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
                "extra": {
                    "top_p": 0.9,
                    "model_kwargs": {"response_format": {"type": "json_object"}},
                    "extra_body": {"thinking": {"type": "disabled"}},
                },
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
        self.assertEqual(
            captured["model_kwargs"],
            {"response_format": {"type": "json_object"}},
        )
        self.assertEqual(
            captured["extra_body"],
            {"thinking": {"type": "disabled"}},
        )


if __name__ == "__main__":
    unittest.main()
