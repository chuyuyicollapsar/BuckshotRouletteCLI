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


if __name__ == "__main__":
    unittest.main()
