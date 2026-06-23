import io
from unittest.mock import patch
import unittest

from buckshot_roulette.cli.renderer import print_events, print_player_info


class CliRendererTests(unittest.TestCase):
    def test_round_started_event_uses_system_prefix(self):
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            print_events(
                [
                    {
                        "event_type": "round_started",
                        "actor_player_id": None,
                        "message": "第 2 轮装弹：LIVE 3 / BLANK 5。",
                    },
                    {
                        "event_type": "shoot_player",
                        "actor_player_id": 1,
                        "message": "DeepSeekV4Pro 对 Alice 开枪。",
                    },
                ]
            )

        output = stdout.getvalue()
        self.assertIn("[系统] 第 2 轮装弹", output)
        self.assertIn("[事件] DeepSeekV4Pro 对 Alice 开枪", output)

    def test_player_info_keeps_only_turn_hp_and_items(self):
        stdout = io.StringIO()
        state = {
            "revision": 8,
            "current_player_id": 1,
            "public_shell_counts": {"remaining": 5},
            "visible_players": [
                {
                    "player_id": 0,
                    "name": "Alice",
                    "hp": 2,
                    "max_hp": 4,
                    "items": ["BEER"],
                    "hand_saw_active": False,
                },
                {
                    "player_id": 1,
                    "name": "DeepSeekV4Pro",
                    "hp": 3,
                    "max_hp": 4,
                    "items": [],
                    "hand_saw_active": False,
                },
            ],
        }

        with patch("sys.stdout", stdout):
            print_player_info(state)

        output = stdout.getvalue()
        self.assertIn("当前回合：[1] DeepSeekV4Pro", output)
        self.assertIn("HP 2/4 | 道具：啤酒", output)
        self.assertIn("HP 3/4 | 道具：无", output)
        self.assertNotIn("房间", output)
        self.assertNotIn("revision", output)
        self.assertNotIn("弹匣", output)
        self.assertNotIn("剩余", output)


if __name__ == "__main__":
    unittest.main()
