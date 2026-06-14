from __future__ import annotations

from collections import Counter
import random
from typing import Iterable

from .models import (
    ActionResult,
    ActionType,
    GameState,
    ItemType,
    MatchConfig,
    MatchState,
    Player,
    RoundStartResult,
    ShellType,
    item_display,
    item_label,
    shell_label,
)


class GameEngine:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def init_game(
        self, player_names: Iterable[str], config: MatchConfig | None = None
    ) -> GameState:
        names = [name.strip() for name in player_names if name.strip()]
        if not 2 <= len(names) <= 4:
            raise ValueError("玩家数量必须是 2 到 4 人。")
        return GameState(player_names=names, config=config or MatchConfig())

    def start_match(self, game_state: GameState) -> MatchState:
        if game_state.game_over:
            raise ValueError("整局游戏已经结束。")
        if game_state.current_match_state is not None:
            raise ValueError("当前比赛尚未结束。")
        if len(game_state.match_results) >= game_state.config.matches_per_game:
            raise ValueError("比赛场数已经打满。")

        initial_hp = self._choose_initial_hp(game_state.config)
        players = [
            Player(id=index, name=name)
            for index, name in enumerate(game_state.player_names)
        ]
        for player in players:
            player.reset_for_match(initial_hp)

        match = MatchState(
            players=players,
            config=game_state.config,
            match_index=len(game_state.match_results),
            current_player_idx=0,
            turn_direction=1,
        )
        game_state.current_match = match.match_index
        game_state.current_match_state = match
        return match

    def finish_match(self, game_state: GameState) -> None:
        match = game_state.current_match_state
        if match is None or not match.match_over or match.winner_idx is None:
            raise ValueError("当前没有可结算的比赛。")

        game_state.match_results.append(match.winner_idx)
        game_state.current_match_state = None
        game_state.current_match = len(game_state.match_results)

        if len(game_state.match_results) >= game_state.config.matches_per_game:
            game_state.game_over = True
            winner_counts = Counter(game_state.match_results)
            max_wins = max(winner_counts.values())
            leaders = [
                player_idx
                for player_idx, wins in winner_counts.items()
                if wins == max_wins
            ]
            game_state.final_winner_idx = leaders[0] if len(leaders) == 1 else None

    def start_round(self, match: MatchState) -> RoundStartResult:
        self._ensure_match_active(match)
        match.round_number += 1
        match.chambers = self.generate_chambers(match.config)
        match.chamber_index = 0
        match.last_action = {}
        dealt = self.distribute_items(match)
        live_count, blank_count = self.shell_counts(match)
        return RoundStartResult(
            round_number=match.round_number,
            shell_count=len(match.chambers),
            live_count=live_count,
            blank_count=blank_count,
            dealt_items=dealt,
        )

    def generate_chambers(self, config: MatchConfig) -> list[ShellType]:
        if config.fixed_shell_sequence is not None:
            if not config.fixed_shell_sequence:
                raise ValueError("固定弹序列不能为空。")
            return [self._coerce_shell(shell) for shell in config.fixed_shell_sequence]

        min_shells, max_shells = config.shell_count_range
        if min_shells < 2 or max_shells < min_shells:
            raise ValueError("随机弹匣数量范围必须满足 2 <= min <= max。")

        shell_count = self.rng.randint(min_shells, max_shells)
        chambers = [
            self.rng.choice((ShellType.LIVE, ShellType.BLANK))
            for _ in range(shell_count)
        ]
        if ShellType.LIVE not in chambers:
            chambers[self.rng.randrange(shell_count)] = ShellType.LIVE
        if ShellType.BLANK not in chambers:
            chambers[self.rng.randrange(shell_count)] = ShellType.BLANK
        self.rng.shuffle(chambers)
        return chambers

    def distribute_items(self, match: MatchState) -> dict[int, list[ItemType]]:
        dealt: dict[int, list[ItemType]] = {}
        pool = self._enabled_item_pool(match)
        if not pool:
            return dealt

        for player in match.players:
            if not player.alive:
                continue
            item_count = self._items_to_deal(player, match)
            received: list[ItemType] = []
            for _ in range(item_count):
                if len(player.items) >= match.config.max_items_per_player:
                    break
                candidates = self._eligible_items_for_player(match, player, pool)
                if not candidates:
                    break
                item = self.rng.choice(candidates)
                player.items.append(item)
                received.append(item)
            dealt[player.id] = received
        return dealt

    def execute_action(
        self,
        match: MatchState,
        action_type: ActionType,
        *,
        target_idx: int | None = None,
        item_type: ItemType | None = None,
        item_index: int | None = None,
        target_item_idx: int | None = None,
        secondary_target_player_idx: int | None = None,
        secondary_target_item_idx: int | None = None,
    ) -> ActionResult:
        if action_type == ActionType.SHOOT_SELF:
            return self.shoot_self(match)
        if action_type == ActionType.SHOOT_OPPONENT:
            if target_idx is None:
                raise ValueError("射击对手需要指定目标玩家。")
            return self.shoot_opponent(match, target_idx)
        if action_type == ActionType.USE_ITEM:
            if item_type is None:
                raise ValueError("使用道具需要指定道具类型。")
            return self.use_item(
                match,
                item_type,
                item_index=item_index,
                target_player_idx=target_idx,
                target_item_idx=target_item_idx,
                secondary_target_player_idx=secondary_target_player_idx,
                secondary_target_item_idx=secondary_target_item_idx,
            )
        raise ValueError(f"未知行动类型：{action_type}")

    def use_item(
        self,
        match: MatchState,
        item_type: ItemType,
        *,
        item_index: int | None = None,
        target_player_idx: int | None = None,
        target_item_idx: int | None = None,
        secondary_target_player_idx: int | None = None,
        secondary_target_item_idx: int | None = None,
    ) -> ActionResult:
        self._ensure_ready_for_action(match)
        actor = self.current_player(match)
        if not actor.alive:
            raise ValueError("当前玩家已经出局。")
        item_type = self._coerce_item(item_type)
        self._validate_item_use(
            match,
            actor.id,
            item_type,
            target_player_idx=target_player_idx,
            target_item_idx=target_item_idx,
            secondary_target_player_idx=secondary_target_player_idx,
            secondary_target_item_idx=secondary_target_item_idx,
        )
        self._remove_item(actor, item_type, item_index)

        result = self._apply_item_effect(
            match,
            actor.id,
            item_type,
            target_player_idx=target_player_idx,
            target_item_idx=target_item_idx,
            secondary_target_player_idx=secondary_target_player_idx,
            secondary_target_item_idx=secondary_target_item_idx,
        )
        match.last_action = result.details.copy()
        return result

    def shoot_self(self, match: MatchState) -> ActionResult:
        return self._shoot(match, match.current_player_idx, shoot_self=True)

    def shoot_opponent(self, match: MatchState, target_idx: int) -> ActionResult:
        self._validate_shoot_target(match, target_idx)
        return self._shoot(match, target_idx, shoot_self=False)

    def next_turn(self, match: MatchState) -> list[int]:
        skipped: list[int] = []
        alive_count = len(self.alive_players(match))
        if alive_count <= 1:
            return skipped
        if (
            match.jammer_target is not None
            and not match.players[match.jammer_target].alive
        ):
            match.jammer_target = None

        start_idx = match.current_player_idx
        idx = start_idx
        attempts = 0
        max_attempts = len(match.players) * 3
        while attempts < max_attempts:
            idx = (idx + match.turn_direction) % len(match.players)
            attempts += 1
            player = match.players[idx]
            if not player.alive:
                if match.jammer_target == idx:
                    match.jammer_target = None
                continue
            if match.jammer_target is not None:
                target = match.jammer_target
                if not match.players[target].alive:
                    match.jammer_target = None
                elif idx == target:
                    skipped.append(idx)
                    match.jammer_target = None
                    continue
            match.current_player_idx = idx
            return skipped

        raise RuntimeError("无法找到下一名可行动玩家。")

    def check_round_end(self, match: MatchState) -> bool:
        return match.chamber_index >= len(match.chambers)

    def check_match_end(self, match: MatchState) -> bool:
        alive_players = self.alive_players(match)
        if len(alive_players) <= 1:
            match.match_over = True
            match.winner_idx = alive_players[0].id if alive_players else None
            return True
        return False

    def alive_players(self, match: MatchState) -> list[Player]:
        return [player for player in match.players if player.alive]

    def current_player(self, match: MatchState) -> Player:
        return match.players[match.current_player_idx]

    def remaining_shells(self, match: MatchState) -> list[ShellType]:
        return match.chambers[match.chamber_index :]

    def shell_counts(self, match: MatchState) -> tuple[int, int]:
        remaining = self.remaining_shells(match)
        return remaining.count(ShellType.LIVE), remaining.count(ShellType.BLANK)

    def legal_targets(self, match: MatchState) -> list[Player]:
        actor_idx = match.current_player_idx
        return [
            player
            for player in match.players
            if player.alive and player.id != actor_idx
        ]

    def _shoot(
        self, match: MatchState, target_idx: int, *, shoot_self: bool
    ) -> ActionResult:
        self._ensure_ready_for_action(match)
        actor = self.current_player(match)
        target = match.players[target_idx]
        shell = self._current_shell(match)
        damage = 0
        events: list[str] = []

        if shell == ShellType.LIVE:
            damage = 2 if actor.hand_saw_active else 1
            target.hp = max(0, target.hp - damage)
            if target.hp <= 0 and target.alive:
                target.alive = False
                target.hand_saw_active = False
                events.append(f"{target.name} 出局。")

        actor.hand_saw_active = False
        self.advance_chamber(match)
        round_ended = self.check_round_end(match)
        match_over = self.check_match_end(match)
        skipped = []
        turn_retained = shoot_self and shell == ShellType.BLANK and not match_over

        if not match_over and not turn_retained:
            skipped = self.next_turn(match)
        if skipped:
            events.extend(self._format_skipped_events(match, skipped))

        action_type = (
            ActionType.SHOOT_SELF if shoot_self else ActionType.SHOOT_OPPONENT
        )
        if shoot_self:
            if shell == ShellType.BLANK:
                message = f"{actor.name} 对自己开枪，是{shell_label(shell)}，没有受伤。"
            else:
                message = (
                    f"{actor.name} 对自己开枪，是{shell_label(shell)}，"
                    f"受到 {damage} 点伤害。"
                )
        else:
            if shell == ShellType.BLANK:
                message = (
                    f"{actor.name} 对 {target.name} 开枪，是{shell_label(shell)}，"
                    "没有造成伤害。"
                )
            else:
                message = (
                    f"{actor.name} 对 {target.name} 开枪，是{shell_label(shell)}，"
                    f"造成 {damage} 点伤害。"
                )

        result = ActionResult(
            action_type=action_type,
            actor_idx=actor.id,
            target_idx=target.id,
            shell=shell,
            damage=damage,
            message=message,
            events=events,
            turn_retained=turn_retained,
            round_ended=round_ended,
            match_over=match.match_over,
            winner_idx=match.winner_idx,
            skipped_players=skipped,
            details={
                "shell": shell.value,
                "damage": damage,
                "target_hp_after": target.hp,
                "turn_retained": turn_retained,
            },
        )
        match.last_action = result.details.copy()
        match.turn_count += 1
        return result

    def advance_chamber(self, match: MatchState) -> None:
        if self.check_round_end(match):
            raise ValueError("当前弹匣已经打空。")
        match.chamber_index += 1

    def _apply_item_effect(
        self,
        match: MatchState,
        actor_idx: int,
        item_type: ItemType,
        *,
        target_player_idx: int | None = None,
        target_item_idx: int | None = None,
        secondary_target_player_idx: int | None = None,
        secondary_target_item_idx: int | None = None,
    ) -> ActionResult:
        actor = match.players[actor_idx]
        events: list[str] = []
        skipped: list[int] = []
        round_ended = False
        details: dict[str, object] = {"item": item_type.value}

        if item_type == ItemType.JAMMER:
            target = match.players[self._required_idx(target_player_idx)]
            match.jammer_target = target.id
            message = f"{actor.name} 使用{item_label(item_type)}，{target.name} 的下一回合将被跳过。"
            details["target_player_id"] = target.id

        elif item_type == ItemType.HAND_SAW:
            actor.hand_saw_active = True
            message = f"{actor.name} 使用{item_label(item_type)}，下一次实弹伤害翻倍。"

        elif item_type == ItemType.MAGNIFYING_GLASS:
            shell = self._current_shell(match)
            message = f"{actor.name} 使用{item_label(item_type)}，当前子弹是{shell_label(shell)}。"
            details["revealed_shell"] = shell.value

        elif item_type == ItemType.BEER:
            shell = self._current_shell(match)
            self.advance_chamber(match)
            round_ended = self.check_round_end(match)
            details["ejected_shell"] = shell.value
            message = f"{actor.name} 使用{item_label(item_type)}退弹，弹出的是{shell_label(shell)}。"
            if round_ended:
                skipped = self.next_turn(match)
                if skipped:
                    events.extend(self._format_skipped_events(match, skipped))

        elif item_type == ItemType.CIGARETTE_PACK:
            before = actor.hp
            actor.hp = min(actor.max_hp, actor.hp + 1)
            healed = actor.hp - before
            if healed:
                message = f"{actor.name} 使用{item_label(item_type)}，恢复 1 点生命。"
            else:
                message = f"{actor.name} 使用{item_label(item_type)}，生命值已经满了。"
            details["hp_after"] = actor.hp

        elif item_type == ItemType.INVERTER:
            shell = self._current_shell(match)
            inverted = (
                ShellType.BLANK if shell == ShellType.LIVE else ShellType.LIVE
            )
            match.chambers[match.chamber_index] = inverted
            message = (
                f"{actor.name} 使用{item_label(item_type)}，当前子弹变为"
                f"{shell_label(inverted)}。"
            )
            details["shell_after"] = inverted.value

        elif item_type == ItemType.BURNER_PHONE:
            remaining = self.remaining_shells(match)
            if len(remaining) <= 2:
                message = f"{actor.name} 使用{item_label(item_type)}，但剩余子弹太少，没有得到信息。"
                details["failed"] = True
            else:
                offset = self.rng.randrange(1, len(remaining))
                shell = remaining[offset]
                message = (
                    f"{actor.name} 使用{item_label(item_type)}，得知往后第 "
                    f"{offset} 发是{shell_label(shell)}。"
                )
                details["offset"] = offset
                details["revealed_shell"] = shell.value

        elif item_type == ItemType.ADRENALINE:
            stealable_players = self._players_with_stealable_items(match, actor_idx)
            if target_player_idx is None and not stealable_players:
                message = f"{actor.name} 使用{item_label(item_type)}，但场上没有可偷的道具。"
                details["failed"] = True
            else:
                victim = match.players[self._required_idx(target_player_idx)]
                stolen_idx = self._required_idx(target_item_idx)
                stolen_item = victim.items.pop(stolen_idx)
                child = self._apply_item_effect(
                    match,
                    actor_idx,
                    stolen_item,
                    target_player_idx=secondary_target_player_idx,
                    target_item_idx=secondary_target_item_idx,
                )
                message = (
                    f"{actor.name} 使用{item_label(item_type)}，偷走 {victim.name} 的"
                    f"{item_display(stolen_item)}并立即使用。"
                )
                events.append(child.message)
                events.extend(child.events)
                skipped = child.skipped_players
                round_ended = child.round_ended
                details["target_player_id"] = victim.id
                details["stolen_item"] = stolen_item.value
                details["stolen_result"] = child.details

        elif item_type == ItemType.REMOTE:
            if len(match.players) < 3:
                message = f"{actor.name} 使用{item_label(item_type)}，但两人局中没有效果。"
                details["failed"] = True
            else:
                match.turn_direction *= -1
                direction = "正向" if match.turn_direction == 1 else "反向"
                message = f"{actor.name} 使用{item_label(item_type)}，回合方向变为{direction}。"
                details["turn_direction"] = match.turn_direction

        else:
            raise ValueError(f"未知道具：{item_type}")

        result = ActionResult(
            action_type=ActionType.USE_ITEM,
            actor_idx=actor_idx,
            item_used=item_type,
            target_idx=target_player_idx,
            message=message,
            events=events,
            round_ended=round_ended,
            match_over=match.match_over,
            winner_idx=match.winner_idx,
            skipped_players=skipped,
            details=details,
        )
        return result

    def _validate_item_use(
        self,
        match: MatchState,
        actor_idx: int,
        item_type: ItemType,
        *,
        target_player_idx: int | None = None,
        target_item_idx: int | None = None,
        secondary_target_player_idx: int | None = None,
        secondary_target_item_idx: int | None = None,
    ) -> None:
        self._ensure_ready_for_action(match)
        if item_type == ItemType.JAMMER:
            if match.jammer_target is not None:
                raise ValueError("场上已经存在一个干扰器效果。")
            self._validate_other_alive_player(match, actor_idx, target_player_idx)
        elif item_type == ItemType.ADRENALINE:
            stealable_players = self._players_with_stealable_items(match, actor_idx)
            if target_player_idx is None and not stealable_players:
                return
            victim = self._validate_other_alive_player(
                match, actor_idx, target_player_idx
            )
            if target_item_idx is None:
                raise ValueError("兴奋剂需要指定要偷取的道具。")
            if not 0 <= target_item_idx < len(victim.items):
                raise ValueError("目标道具编号无效。")
            stolen_item = victim.items[target_item_idx]
            if stolen_item == ItemType.ADRENALINE:
                raise ValueError("兴奋剂不能偷取兴奋剂。")
            self._validate_stolen_item_use(
                match,
                actor_idx,
                stolen_item,
                secondary_target_player_idx=secondary_target_player_idx,
                secondary_target_item_idx=secondary_target_item_idx,
            )
        elif item_type in {
            ItemType.HAND_SAW,
            ItemType.MAGNIFYING_GLASS,
            ItemType.BEER,
            ItemType.CIGARETTE_PACK,
            ItemType.INVERTER,
            ItemType.BURNER_PHONE,
            ItemType.REMOTE,
        }:
            return
        else:
            raise ValueError(f"未知道具：{item_type}")

    def _validate_stolen_item_use(
        self,
        match: MatchState,
        actor_idx: int,
        stolen_item: ItemType,
        *,
        secondary_target_player_idx: int | None,
        secondary_target_item_idx: int | None,
    ) -> None:
        if stolen_item == ItemType.JAMMER:
            if match.jammer_target is not None:
                raise ValueError("场上已经存在一个干扰器效果。")
            self._validate_other_alive_player(
                match, actor_idx, secondary_target_player_idx
            )
        elif stolen_item == ItemType.ADRENALINE:
            raise ValueError("兴奋剂不能偷取兴奋剂。")
        elif secondary_target_item_idx is not None:
            raise ValueError("该道具不需要第二个目标道具编号。")

    def _validate_shoot_target(self, match: MatchState, target_idx: int) -> None:
        self._ensure_ready_for_action(match)
        self._validate_other_alive_player(match, match.current_player_idx, target_idx)

    def _validate_other_alive_player(
        self, match: MatchState, actor_idx: int, target_idx: int | None
    ) -> Player:
        target_idx = self._required_idx(target_idx)
        if not 0 <= target_idx < len(match.players):
            raise ValueError("目标玩家编号无效。")
        if target_idx == actor_idx:
            raise ValueError("目标必须是其他存活玩家。")
        target = match.players[target_idx]
        if not target.alive:
            raise ValueError("目标玩家已经出局。")
        return target

    def _current_shell(self, match: MatchState) -> ShellType:
        if self.check_round_end(match):
            raise ValueError("当前弹匣已经打空，请先进入下一轮。")
        return match.chambers[match.chamber_index]

    def _ensure_match_active(self, match: MatchState) -> None:
        if match.match_over:
            raise ValueError("当前比赛已经结束。")

    def _ensure_ready_for_action(self, match: MatchState) -> None:
        self._ensure_match_active(match)
        if not match.chambers or self.check_round_end(match):
            raise ValueError("当前没有可用子弹，请先开始新一轮。")

    def _choose_initial_hp(self, config: MatchConfig) -> int:
        if config.fixed_initial_hp is not None:
            if config.fixed_initial_hp <= 0:
                raise ValueError("固定初始生命值必须大于 0。")
            return config.fixed_initial_hp
        if not config.initial_hp_values:
            raise ValueError("初始生命值池不能为空。")
        return self.rng.choice(config.initial_hp_values)

    def _items_to_deal(self, player: Player, match: MatchState) -> int:
        if match.config.items_per_reload is not None:
            return max(0, match.config.items_per_reload)
        return min(player.max_hp // 2 + match.round_number, 5)

    def _enabled_item_pool(self, match: MatchState) -> list[ItemType]:
        pool = list(match.config.enabled_items)
        if len(match.players) < 3 and ItemType.REMOTE in pool:
            pool.remove(ItemType.REMOTE)
        return pool

    def _eligible_items_for_player(
        self, match: MatchState, player: Player, pool: list[ItemType]
    ) -> list[ItemType]:
        table_counts = Counter(
            item for table_player in match.players for item in table_player.items
        )
        player_counts = Counter(player.items)
        candidates: list[ItemType] = []
        for item in pool:
            player_limit = match.config.item_player_limits.get(item)
            if player_limit is not None and player_counts[item] >= player_limit:
                continue
            table_limit = match.config.item_table_limits.get(item)
            if table_limit is not None and table_counts[item] >= table_limit:
                continue
            candidates.append(item)
        return candidates

    def _players_with_stealable_items(
        self, match: MatchState, actor_idx: int
    ) -> list[Player]:
        return [
            player
            for player in match.players
            if player.alive
            and player.id != actor_idx
            and any(item != ItemType.ADRENALINE for item in player.items)
        ]

    def _remove_item(
        self, player: Player, item_type: ItemType, item_index: int | None
    ) -> None:
        if item_index is not None:
            if not 0 <= item_index < len(player.items):
                raise ValueError("道具编号无效。")
            if player.items[item_index] != item_type:
                raise ValueError("道具编号与道具类型不匹配。")
            player.items.pop(item_index)
            return
        try:
            player.items.remove(item_type)
        except ValueError as exc:
            raise ValueError(f"玩家没有{item_label(item_type)}。") from exc

    def _format_skipped_events(
        self, match: MatchState, skipped: list[int]
    ) -> list[str]:
        return [f"{match.players[idx].name} 被干扰器跳过了回合。" for idx in skipped]

    def _required_idx(self, value: int | None) -> int:
        if value is None:
            raise ValueError("缺少必要的目标编号。")
        return value

    def _coerce_shell(self, shell: ShellType | str) -> ShellType:
        if isinstance(shell, ShellType):
            return shell
        return ShellType(shell)

    def _coerce_item(self, item: ItemType | str) -> ItemType:
        if isinstance(item, ItemType):
            return item
        return ItemType(item)


def init_game(
    player_names: Iterable[str],
    config: MatchConfig | None = None,
    rng: random.Random | None = None,
) -> GameState:
    return GameEngine(rng).init_game(player_names, config)
