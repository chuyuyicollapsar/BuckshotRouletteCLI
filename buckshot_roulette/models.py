from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ShellType(str, Enum):
    LIVE = "LIVE"
    BLANK = "BLANK"


class ItemType(str, Enum):
    JAMMER = "JAMMER"
    HAND_SAW = "HAND_SAW"
    MAGNIFYING_GLASS = "MAGNIFYING_GLASS"
    BEER = "BEER"
    CIGARETTE_PACK = "CIGARETTE_PACK"
    INVERTER = "INVERTER"
    BURNER_PHONE = "BURNER_PHONE"
    ADRENALINE = "ADRENALINE"
    REMOTE = "REMOTE"


class ActionType(str, Enum):
    SHOOT_SELF = "SHOOT_SELF"
    SHOOT_OPPONENT = "SHOOT_OPPONENT"
    USE_ITEM = "USE_ITEM"


SHELL_LABELS: dict[ShellType, str] = {
    ShellType.LIVE: "实弹",
    ShellType.BLANK: "空包弹",
}

ITEM_LABELS: dict[ItemType, str] = {
    ItemType.JAMMER: "干扰器",
    ItemType.HAND_SAW: "手锯",
    ItemType.MAGNIFYING_GLASS: "放大镜",
    ItemType.BEER: "啤酒",
    ItemType.CIGARETTE_PACK: "香烟",
    ItemType.INVERTER: "逆转器",
    ItemType.BURNER_PHONE: "手机",
    ItemType.ADRENALINE: "兴奋剂",
    ItemType.REMOTE: "遥控器",
}


def shell_label(shell: ShellType) -> str:
    return SHELL_LABELS[shell]


def item_label(item: ItemType) -> str:
    return ITEM_LABELS[item]


def item_display(item: ItemType) -> str:
    return f"{ITEM_LABELS[item]}({item.value})"


@dataclass(slots=True)
class Player:
    id: int
    name: str
    hp: int = 0
    max_hp: int = 0
    items: list[ItemType] = field(default_factory=list)
    alive: bool = True
    hand_saw_active: bool = False

    def reset_for_match(self, hp: int) -> None:
        self.hp = hp
        self.max_hp = hp
        self.items.clear()
        self.alive = True
        self.hand_saw_active = False


@dataclass(slots=True)
class MatchConfig:
    initial_hp_values: tuple[int, ...] = (3, 4, 5)
    fixed_initial_hp: int | None = None
    shell_count_range: tuple[int, int] = (2, 8)
    fixed_shell_sequence: tuple[ShellType, ...] | None = None
    items_per_reload: int | None = None
    enabled_items: frozenset[ItemType] = field(
        default_factory=lambda: frozenset(ItemType)
    )
    max_items_per_player: int = 8
    item_player_limits: dict[ItemType, int] = field(default_factory=dict)
    item_table_limits: dict[ItemType, int] = field(default_factory=dict)
    matches_per_game: int = 3


@dataclass(slots=True)
class RoundStartResult:
    round_number: int
    shell_count: int
    live_count: int
    blank_count: int
    dealt_items: dict[int, list[ItemType]]


@dataclass(slots=True)
class MatchState:
    players: list[Player]
    config: MatchConfig
    match_index: int = 0
    chambers: list[ShellType] = field(default_factory=list)
    chamber_index: int = 0
    current_player_idx: int = 0
    turn_direction: int = 1
    round_number: int = 0
    jammer_target: int | None = None
    last_action: dict[str, Any] = field(default_factory=dict)
    match_over: bool = False
    winner_idx: int | None = None
    turn_count: int = 0


@dataclass(slots=True)
class GameState:
    player_names: list[str]
    config: MatchConfig
    match_results: list[int] = field(default_factory=list)
    current_match: int = 0
    current_match_state: MatchState | None = None
    game_over: bool = False
    final_winner_idx: int | None = None


@dataclass(slots=True)
class ActionResult:
    action_type: ActionType
    actor_idx: int
    message: str
    events: list[str] = field(default_factory=list)
    item_used: ItemType | None = None
    shell: ShellType | None = None
    target_idx: int | None = None
    damage: int = 0
    turn_retained: bool = False
    round_ended: bool = False
    match_over: bool = False
    winner_idx: int | None = None
    skipped_players: list[int] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
