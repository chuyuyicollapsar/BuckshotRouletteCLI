import random
import unittest

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
            "round_started",
        ])
        self.assertEqual(visible.current_player_id, 0)
        self.assertEqual(visible.public_shell_counts["remaining"], 2)
        self.assertNotIn("LIVE", visible.public_shell_counts)
        self.assertNotIn("BLANK", visible.public_shell_counts)
        round_event = events[-1]
        self.assertEqual(round_event.payload["live_count"], 1)
        self.assertEqual(round_event.payload["blank_count"], 1)
        self.assertIn({"type": "shoot_self"}, visible.legal_actions)

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

        self.assertEqual([event.event_type for event in human_events], ["shoot_player"])
        self.assertEqual(session.state.current_match_state.current_player_idx, 1)

        ai_events = coordinator.run_ai_turns(room, session)

        event_types = [event.event_type for event in ai_events]
        self.assertIn("ai_decision", event_types)
        self.assertIn("shoot_player", event_types)


if __name__ == "__main__":
    unittest.main()
