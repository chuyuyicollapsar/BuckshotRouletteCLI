import random
import unittest
from fastapi.testclient import TestClient

from buckshot_roulette.backend.app import create_app
from buckshot_roulette.backend.models import RoomVisibility
from buckshot_roulette.backend.repositories import InMemoryStore
from buckshot_roulette.backend.services import (
    GameSessionService,
    RoomService,
    ServiceError,
    TurnCoordinator,
)
from buckshot_roulette.engine import GameEngine
from buckshot_roulette.llm.ai_player_controller import AIPlayerController
from buckshot_roulette.llm.context_builder import LLMContextBuilder
from buckshot_roulette.llm.repositories import LLMConfigStore
from buckshot_roulette.llm.services import LLMAdminService, LLMDecisionService
from buckshot_roulette.models import ItemType, MatchConfig, ShellType


class BackendServiceTests(unittest.TestCase):
    def make_services(self, config=None):
        store = InMemoryStore()
        engine = GameEngine(random.Random(1))
        room_service = RoomService(store)
        session_service = GameSessionService(store, engine)
        coordinator = TurnCoordinator(room_service, session_service, engine)
        room, owner = room_service.create_room(
            owner_name="Alice",
            room_name="Test",
            visibility=RoomVisibility.PUBLIC,
            max_players=4,
            config=config,
        )
        return store, engine, room_service, coordinator, room, owner

    def make_ai_services(self, config=None):
        store = InMemoryStore()
        engine = GameEngine(random.Random(1))
        room_service = RoomService(store)
        session_service = GameSessionService(store, engine)
        llm_store = LLMConfigStore()
        coordinator = TurnCoordinator(
            room_service,
            session_service,
            engine,
            AIPlayerController(LLMDecisionService(llm_store)),
        )
        room, owner = room_service.create_room(
            owner_name="Alice",
            room_name="Test",
            visibility=RoomVisibility.PUBLIC,
            max_players=4,
            config=config,
        )
        llm_admin = LLMAdminService(llm_store)
        return store, engine, room_service, coordinator, room, owner, llm_admin

    def test_room_lifecycle_starts_game_and_builds_visible_state(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.BLANK, ShellType.LIVE),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)

        session, events = coordinator.start_game(room.room_code, owner.token)
        visible = coordinator.build_visible_state_by_token(room.room_code, owner.token)

        self.assertEqual(session.revision, 2)
        self.assertEqual(room.status.value, "IN_GAME")
        self.assertEqual([event.event_type for event in events], [
            "game_started",
            "match_started",
            "player_hp_set",
            "round_started",
            "turn_started",
        ])
        self.assertEqual(visible.current_player_id, 0)
        self.assertEqual(visible.public_shell_counts["remaining"], 2)
        self.assertNotIn("LIVE", visible.public_shell_counts)
        self.assertNotIn("BLANK", visible.public_shell_counts)
        hp_events = [event for event in events if event.event_type == "player_hp_set"]
        self.assertEqual(len(hp_events), 1)
        self.assertEqual(hp_events[0].message, "本场游戏玩家的初始生命值为 3。")
        self.assertEqual(hp_events[0].payload, {
            "initial_hp": 3,
            "players": [
                {"player_id": 0, "hp": 3, "max_hp": 3},
                {"player_id": 1, "hp": 3, "max_hp": 3},
            ],
        })
        round_event = events[-2]
        self.assertEqual(round_event.payload["live_count"], 1)
        self.assertEqual(round_event.payload["blank_count"], 1)
        turn_event = events[-1]
        self.assertEqual(turn_event.message, "轮到 Alice 行动。")
        self.assertEqual(turn_event.payload, {"player_id": 0})
        self.assertIn({"type": "shoot_self"}, visible.legal_actions)

    def test_round_start_deals_items_before_shell_reveal_in_turn_order(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.BLANK, ShellType.LIVE),
            enabled_items=frozenset({ItemType.BEER}),
            items_per_reload=2,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)

        _, events = coordinator.start_game(room.room_code, owner.token)

        self.assertEqual([event.event_type for event in events], [
            "game_started",
            "match_started",
            "player_hp_set",
            "item_dealt",
            "item_dealt",
            "item_dealt",
            "item_dealt",
            "round_started",
            "turn_started",
        ])
        dealt_events = [event for event in events if event.event_type == "item_dealt"]
        self.assertEqual([event.actor_player_id for event in dealt_events], [
            None,
            None,
            None,
            None,
        ])
        self.assertEqual([event.message for event in dealt_events], [
            "Alice 获得啤酒。",
            "Bob 获得啤酒。",
            "Alice 获得啤酒。",
            "Bob 获得啤酒。",
        ])
        self.assertEqual([event.payload for event in dealt_events], [
            {"player_id": 0, "item": "BEER", "item_index": 0},
            {"player_id": 1, "item": "BEER", "item_index": 0},
            {"player_id": 0, "item": "BEER", "item_index": 1},
            {"player_id": 1, "item": "BEER", "item_index": 1},
        ])
        self.assertEqual(events[-2].event_type, "round_started")
        self.assertEqual(events[-1].event_type, "turn_started")

    def test_turn_started_event_is_appended_when_turn_changes(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        session, _ = coordinator.start_game(room.room_code, owner.token)

        _, events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {"type": "shoot_player", "target_player_id": 1},
            run_ai_turns=False,
        )

        self.assertEqual([event.event_type for event in events], [
            "shoot_player",
            "turn_started",
        ])
        self.assertEqual(events[-1].message, "轮到 Bob 行动。")
        self.assertEqual(events[-1].payload, {"player_id": 1})

    def test_blank_self_shot_does_not_repeat_turn_started_event(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.BLANK, ShellType.LIVE),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        session, _ = coordinator.start_game(room.room_code, owner.token)

        _, events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {"type": "shoot_self"},
            run_ai_turns=False,
        )

        self.assertEqual([event.event_type for event in events], ["shoot_self"])

    def test_new_match_repeats_hp_events_before_round_events(self):
        config = MatchConfig(
            fixed_initial_hp=1,
            fixed_shell_sequence=(ShellType.LIVE,),
            items_per_reload=0,
            matches_per_game=2,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        session, _ = coordinator.start_game(room.room_code, owner.token)

        _, events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {"type": "shoot_player", "target_player_id": 1},
            run_ai_turns=False,
        )

        self.assertEqual([event.event_type for event in events], [
            "shoot_player",
            "action_result",
            "match_ended",
            "match_started",
            "player_hp_set",
            "round_started",
            "turn_started",
        ])
        hp_events = [event for event in events if event.event_type == "player_hp_set"]
        self.assertEqual(len(hp_events), 1)
        self.assertEqual(hp_events[0].message, "本场游戏玩家的初始生命值为 1。")
        self.assertEqual(hp_events[0].payload, {
            "initial_hp": 1,
            "players": [
                {"player_id": 0, "hp": 1, "max_hp": 1},
                {"player_id": 1, "hp": 1, "max_hp": 1},
            ],
        })

    def test_only_current_player_can_submit_action(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.BLANK, ShellType.LIVE),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        session, _ = coordinator.start_game(room.room_code, owner.token)

        with self.assertRaises(ServiceError):
            coordinator.submit_action(
                room.room_code,
                bob.token,
                session.revision,
                {"type": "shoot_self"},
            )

    def test_revision_must_match(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.BLANK, ShellType.LIVE),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        coordinator.start_game(room.room_code, owner.token)

        with self.assertRaises(ServiceError):
            coordinator.submit_action(
                room.room_code,
                owner.token,
                0,
                {"type": "shoot_self"},
            )

    def test_private_item_result_is_visible_only_to_actor(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        session, _ = coordinator.start_game(room.room_code, owner.token)
        match = session.state.current_match_state
        match.players[0].items.append(ItemType.MAGNIFYING_GLASS)

        _, events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {
                "type": "use_item",
                "item": "MAGNIFYING_GLASS",
                "item_index": 0,
            },
        )

        private_events = [event for event in events if event.visible_to != "ALL"]
        self.assertEqual(len(private_events), 1)
        self.assertEqual(private_events[0].visible_to, [0])
        self.assertIn("当前子弹是实弹", private_events[0].message)
        public_events = [event for event in events if event.visible_to == "ALL"]
        self.assertIn("使用了放大镜", public_events[0].message)

    def test_inverter_event_does_not_reveal_shell_until_shot(self):
        config = MatchConfig(
            fixed_initial_hp=3,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner = self.make_services(config)
        room, bob = room_service.join_room(room.room_code, "Bob")
        room_service.set_ready(room.room_code, bob.token, True)
        session, _ = coordinator.start_game(room.room_code, owner.token)
        match = session.state.current_match_state
        match.players[0].items.append(ItemType.INVERTER)

        _, events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {
                "type": "use_item",
                "item": "INVERTER",
                "item_index": 0,
            },
        )

        public_event = events[0]
        self.assertEqual(public_event.visible_to, "ALL")
        self.assertEqual(public_event.message, "Alice 使用逆转器，反转了当前子弹。")
        self.assertNotIn("实弹", public_event.message)
        self.assertNotIn("空包弹", public_event.message)
        self.assertNotIn("shell_after", public_event.payload.get("details", {}))

        _, shot_events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {"type": "shoot_self"},
        )

        self.assertIn("是空包弹", shot_events[0].message)

    def test_owner_leave_transfers_owner_in_lobby(self):
        _, _, room_service, _, room, owner = self.make_services()
        room, bob = room_service.join_room(room.room_code, "Bob")

        room_service.leave_room(room.room_code, owner.token)

        self.assertEqual(room.owner_player_id, bob.player_id)
        self.assertEqual(room.players[0].status.value, "LEFT")

    def test_owner_can_add_ai_player_snapshot(self):
        _, _, room_service, _, room, owner = self.make_services()
        llm_admin = LLMAdminService(LLMConfigStore())
        snapshot = llm_admin.create_ai_snapshot("fake_cautious")

        room_service.add_ai_player(room.room_code, owner.token, snapshot)

        self.assertEqual(len(room.players), 2)
        self.assertEqual(room.players[1].type.value, "AI")
        self.assertEqual(room.players[1].status.value, "READY")
        self.assertEqual(room.players[1].ai_preset_snapshot.preset_id, "fake_cautious")

    def test_ai_acts_automatically_when_game_starts_on_ai_turn(self):
        config = MatchConfig(
            fixed_initial_hp=1,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner, llm_admin = self.make_ai_services(
            config
        )
        snapshot = llm_admin.create_ai_snapshot("fake_cautious")
        room_service.add_ai_player(room.room_code, owner.token, snapshot)
        # Put the AI in seat 0 so the first turn belongs to AI.
        room.players = [room.players[1], room.players[0]]
        room.owner_player_id = room.players[1].id

        session, events = coordinator.start_game(room.room_code, owner.token)

        event_types = [event.event_type for event in events]
        self.assertIn("ai_decision", event_types)
        self.assertIn("shoot_player", event_types)
        self.assertEqual(session.state.match_results, [0, 0, 0])
        self.assertTrue(session.state.game_over)
        self.assertEqual(room.status.value, "FINISHED")
        self.assertIn("match_ended", event_types)

    def test_ai_acts_after_human_turn_switches_to_ai(self):
        config = MatchConfig(
            fixed_initial_hp=2,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner, llm_admin = self.make_ai_services(
            config
        )
        snapshot = llm_admin.create_ai_snapshot("fake_cautious")
        room_service.add_ai_player(room.room_code, owner.token, snapshot)
        session, _ = coordinator.start_game(room.room_code, owner.token)

        _, events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {"type": "shoot_player", "target_player_id": 1},
        )

        event_types = [event.event_type for event in events]
        self.assertIn("shoot_player", event_types)
        self.assertIn("ai_decision", event_types)
        self.assertEqual(session.state.current_match_state.players[0].hp, 1)

    def test_human_action_can_publish_before_ai_turn_runs(self):
        config = MatchConfig(
            fixed_initial_hp=2,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        _, _, room_service, coordinator, room, owner, llm_admin = self.make_ai_services(
            config
        )
        snapshot = llm_admin.create_ai_snapshot("fake_cautious")
        room_service.add_ai_player(room.room_code, owner.token, snapshot)
        session, _ = coordinator.start_game(room.room_code, owner.token)

        _, human_events = coordinator.submit_action(
            room.room_code,
            owner.token,
            session.revision,
            {"type": "shoot_player", "target_player_id": 1},
            run_ai_turns=False,
        )

        self.assertEqual([event.event_type for event in human_events], [
            "shoot_player",
            "turn_started",
        ])
        self.assertEqual(session.state.current_match_state.current_player_idx, 1)

        ai_events = coordinator.run_ai_turns(room, session)

        event_types = [event.event_type for event in ai_events]
        self.assertIn("ai_decision", event_types)
        self.assertIn("shoot_player", event_types)

    def test_llm_context_includes_ai_profile(self):
        config = MatchConfig(
            fixed_initial_hp=2,
            fixed_shell_sequence=(ShellType.LIVE, ShellType.BLANK),
            items_per_reload=0,
        )
        store, _, room_service, coordinator, room, owner, llm_admin = (
            self.make_ai_services(config)
        )
        snapshot = llm_admin.create_ai_snapshot("fake_cautious")
        room_service.add_ai_player(room.room_code, owner.token, snapshot)
        room.players = [room.players[1], room.players[0]]
        room.owner_player_id = room.players[1].id
        session, _ = coordinator.start_game(room.room_code, owner.token)
        ai_player = room.players[0]
        visible_state = coordinator.build_visible_state(room, ai_player)

        context = LLMContextBuilder().build_context(
            room,
            ai_player,
            session,
            visible_state,
        )

        self.assertEqual(context["ai_profile"]["display_name"], "Fake Cautious")
        self.assertIn("deterministic fake player", context["ai_profile"]["persona_prompt"])

    def test_admin_ai_action_test_accepts_custom_context(self):
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

        with TestClient(create_app(LLMConfigStore())) as client:
            response = client.post(
                "/admin/ai-player-presets/fake_cautious/test-action",
                json={"context": context},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["details"]["action"],
            {"type": "shoot_player", "target_player_id": 0},
        )


if __name__ == "__main__":
    unittest.main()
