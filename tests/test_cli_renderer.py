import io
from unittest.mock import patch
import unittest

from buckshot_roulette.cli.renderer import (
    print_command_help,
    print_events,
    print_player_info,
)


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

    def test_command_help_lists_commands_instead_of_action_numbers(self):
        stdout = io.StringIO()
        state = {
            "player_seat_index": 0,
            "visible_players": [
                {"player_id": 0, "name": "Alice", "alive": True, "items": ["BEER"]},
                {"player_id": 1, "name": "AI", "alive": True, "items": ["JAMMER"]},
            ],
        }
        actions = [
            {"type": "shoot_self"},
            {"type": "shoot_player", "target_player_id": 1},
            {"type": "use_item", "item": "BEER", "item_index": 0},
            {
                "type": "use_item",
                "item": "ADRENALINE",
                "item_index": 1,
                "requires_target_player_id": True,
                "requires_target_item_index": True,
            },
        ]

        with patch("sys.stdout", stdout):
            print_command_help(actions, state)

        output = stdout.getvalue()
        self.assertIn("命令说明：", output)
        self.assertIn("直接输入文字：发送聊天", output)
        self.assertIn("玩家编号：0=Alice（你） | 1=AI", output)
        self.assertIn("/shot 0", output)
        self.assertIn("/shot 1", output)
        self.assertIn("/use beer", output)
        self.assertIn("无对象：/use 道具，例如：/use beer", output)
        self.assertIn("有对象（干扰器）：/use jammer --玩家，例如：/use jammer --1", output)
        self.assertIn(
            "有对象且更多参数（兴奋剂）：/use adrenaline --玩家 --道具 [--玩家]",
            output,
        )
        self.assertIn("例如：/use adrenaline --1 --beer", output)
        self.assertIn("偷取干扰器时：/use adrenaline --1 --jammer --2", output)
        for item in [
            "jammer",
            "hand_saw",
            "magnifying_glass",
            "beer",
            "cigarette_pack",
            "inverter",
            "burner_phone",
            "adrenaline",
            "remote",
        ]:
            self.assertIn(item, output)
        self.assertNotIn("--player", output)
        self.assertNotIn("--item", output)
        self.assertNotIn("--with", output)
        self.assertNotIn("可选行动：", output)


if __name__ == "__main__":
    unittest.main()
