import unittest

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

    def test_fake_decision_service_returns_legal_action(self):
        store = LLMConfigStore()
        decision_service = LLMDecisionService(store)

        result = decision_service.test_ai_action("fake_cautious")

        self.assertTrue(result.ok)
        self.assertIn(result.details["action"]["type"], {"shoot_player", "shoot_self"})


if __name__ == "__main__":
    unittest.main()
