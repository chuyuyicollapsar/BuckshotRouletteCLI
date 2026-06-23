import unittest

from buckshot_roulette.cli.main import parse_action_command


class CliCommandTests(unittest.TestCase):
    def make_state(self):
        return {
            "player_seat_index": 0,
            "visible_players": [
                {
                    "player_id": 0,
                    "name": "Alice",
                    "alive": True,
                    "items": ["BEER", "ADRENALINE"],
                },
                {
                    "player_id": 1,
                    "name": "DeepSeekV4Pro",
                    "alive": True,
                    "items": ["JAMMER", "BEER"],
                },
                {
                    "player_id": 2,
                    "name": "Bob",
                    "alive": True,
                    "items": [],
                },
            ],
            "legal_actions": [
                {"type": "shoot_self"},
                {"type": "shoot_player", "target_player_id": 1},
                {"type": "shoot_player", "target_player_id": 2},
                {"type": "use_item", "item": "BEER", "item_index": 0},
                {
                    "type": "use_item",
                    "item": "ADRENALINE",
                    "item_index": 1,
                    "requires_target_player_id": True,
                    "requires_target_item_index": True,
                },
            ],
        }

    def test_shot_numeric_zero_targets_self(self):
        action = parse_action_command("/shot 0", self.make_state())

        self.assertEqual(action, {"type": "shoot_self"})

    def test_shot_accepts_player_name(self):
        action = parse_action_command("/shot Bob", self.make_state())

        self.assertEqual(action, {"type": "shoot_player", "target_player_id": 2})

    def test_use_simple_item_by_name(self):
        action = parse_action_command("/use beer", self.make_state())

        self.assertEqual(
            action,
            {"type": "use_item", "item": "BEER", "item_index": 0},
        )

    def test_use_adrenaline_can_steal_jammer_and_choose_secondary_target(self):
        action = parse_action_command(
            "/use adrenaline --1 --jammer --2",
            self.make_state(),
        )

        self.assertEqual(
            action,
            {
                "type": "use_item",
                "item": "ADRENALINE",
                "item_index": 1,
                "target_player_id": 1,
                "target_item_index": 0,
                "secondary_target_player_id": 2,
            },
        )

    def test_use_adrenaline_can_steal_item_without_secondary_target(self):
        action = parse_action_command(
            "/use adrenaline --1 --beer",
            self.make_state(),
        )

        self.assertEqual(
            action,
            {
                "type": "use_item",
                "item": "ADRENALINE",
                "item_index": 1,
                "target_player_id": 1,
                "target_item_index": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
