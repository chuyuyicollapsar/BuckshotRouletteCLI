import random
import unittest

from buckshot_roulette import GameEngine, ItemType, MatchConfig, ShellType


class GameEngineTests(unittest.TestCase):
    def make_match(self, shells, players=("A", "B"), hp=3):
        engine = GameEngine(random.Random(1))
        config = MatchConfig(
            fixed_initial_hp=hp,
            fixed_shell_sequence=tuple(shells),
            items_per_reload=0,
        )
        game = engine.init_game(players, config)
        match = engine.start_match(game)
        engine.start_round(match)
        return engine, game, match

    def test_random_chambers_always_include_live_and_blank(self):
        engine = GameEngine(random.Random(42))
        config = MatchConfig()
        for _ in range(100):
            chambers = engine.generate_chambers(config)
            self.assertIn(ShellType.LIVE, chambers)
            self.assertIn(ShellType.BLANK, chambers)

    def test_shoot_self_blank_retains_turn(self):
        engine, _, match = self.make_match([ShellType.BLANK, ShellType.LIVE])

        result = engine.shoot_self(match)

        self.assertTrue(result.turn_retained)
        self.assertEqual(match.current_player_idx, 0)
        self.assertFalse(result.round_ended)

    def test_shoot_opponent_live_deals_damage_and_switches_turn(self):
        engine, _, match = self.make_match([ShellType.LIVE, ShellType.BLANK])

        result = engine.shoot_opponent(match, 1)

        self.assertEqual(result.damage, 1)
        self.assertEqual(match.players[1].hp, 2)
        self.assertEqual(match.current_player_idx, 1)

    def test_hand_saw_doubles_live_damage(self):
        engine, _, match = self.make_match([ShellType.LIVE, ShellType.BLANK])
        match.players[0].items.append(ItemType.HAND_SAW)

        engine.use_item(match, ItemType.HAND_SAW)
        result = engine.shoot_opponent(match, 1)

        self.assertEqual(result.damage, 2)
        self.assertEqual(match.players[1].hp, 1)

    def test_beer_on_last_shell_switches_turn(self):
        engine, _, match = self.make_match([ShellType.BLANK])
        match.players[0].items.append(ItemType.BEER)

        result = engine.use_item(match, ItemType.BEER)

        self.assertTrue(result.round_ended)
        self.assertEqual(match.current_player_idx, 1)

    def test_match_finish_updates_game_score(self):
        engine, game, match = self.make_match([ShellType.LIVE, ShellType.BLANK], hp=1)

        result = engine.shoot_opponent(match, 1)
        engine.finish_match(game)

        self.assertTrue(result.match_over)
        self.assertEqual(game.match_results, [0])

    def test_dead_jammer_target_is_cleared_before_next_turn(self):
        engine, _, match = self.make_match(
            [ShellType.LIVE, ShellType.BLANK],
            players=("A", "B", "C"),
            hp=1,
        )
        match.jammer_target = 2

        engine.shoot_opponent(match, 2)

        self.assertIsNone(match.jammer_target)
        self.assertEqual(match.current_player_idx, 1)

    def test_dealt_jammer_is_limited_to_one_on_table(self):
        engine = GameEngine(random.Random(1))
        config = MatchConfig(
            fixed_initial_hp=3,
            enabled_items=frozenset({ItemType.JAMMER}),
            items_per_reload=3,
        )
        game = engine.init_game(["A", "B", "C"], config)
        match = engine.start_match(game)

        dealt = engine.distribute_items(match)

        total_jammers = sum(
            player.items.count(ItemType.JAMMER) for player in match.players
        )
        self.assertEqual(total_jammers, 1)
        self.assertEqual(
            sum(items.count(ItemType.JAMMER) for items in dealt.values()),
            1,
        )

    def test_active_jammer_effect_blocks_dealing_another_jammer(self):
        engine = GameEngine(random.Random(1))
        config = MatchConfig(
            fixed_initial_hp=3,
            enabled_items=frozenset({ItemType.JAMMER}),
            items_per_reload=1,
        )
        game = engine.init_game(["A", "B", "C"], config)
        match = engine.start_match(game)
        match.jammer_target = 1

        dealt = engine.distribute_items(match)

        self.assertEqual(
            sum(player.items.count(ItemType.JAMMER) for player in match.players),
            0,
        )
        self.assertTrue(all(not items for items in dealt.values()))


if __name__ == "__main__":
    unittest.main()
