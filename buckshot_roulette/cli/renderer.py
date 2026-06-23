from __future__ import annotations

from typing import Any


ITEM_LABELS = {
    "JAMMER": "干扰器",
    "HAND_SAW": "手锯",
    "MAGNIFYING_GLASS": "放大镜",
    "BEER": "啤酒",
    "CIGARETTE_PACK": "香烟",
    "INVERTER": "逆转器",
    "BURNER_PHONE": "手机",
    "ADRENALINE": "兴奋剂",
    "REMOTE": "遥控器",
}


def print_room(room: dict[str, Any], player_id: str | None = None) -> None:
    print(f"\n房间 {room['room_code']} | {room['name']} | {room['status']}")
    print(f"人数：{len(room['players'])}/{room['max_players']} | 可见性：{room['visibility']}")
    print("玩家：")
    for player in room["players"]:
        owner = " 房主" if player.get("is_owner") else ""
        me = " 你" if player.get("id") == player_id else ""
        seat = player.get("seat_index")
        seat_text = "-" if seat is None else str(seat)
        print(
            f"  [{seat_text}] {player['name']} "
            f"{player['type']} {player['status']}{owner}{me}"
        )


def print_game_header(room: dict[str, Any]) -> None:
    print(f"\n房间 {room['room_code']} | {room['name']}")


def print_visible_state(state: dict[str, Any]) -> None:
    print(
        f"状态：revision {state['revision']} | "
        f"比分 {format_match_results(state.get('match_results', []))}"
    )
    counts = state.get("public_shell_counts", {})
    if counts.get("remaining", 0):
        print(f"弹匣：剩余 {counts.get('remaining', 0)}")
    current_id = state.get("current_player_id")
    current_name = player_name(state, current_id)
    if current_name:
        print(f"当前行动：[{current_id}] {current_name}")

    print("玩家：")
    for player in state.get("visible_players", []):
        if "hp" in player:
            marker = "->" if player.get("player_id") == current_id else "  "
            alive = "存活" if player.get("alive") else "出局"
            saw = " 手锯" if player.get("hand_saw_active") else ""
            items = ", ".join(item_label(item) for item in player.get("items", [])) or "无"
            print(
                f"{marker} [{player.get('player_id')}] {player.get('name')}: "
                f"HP {player.get('hp')}/{player.get('max_hp')} {alive}{saw} | {items}"
            )
        else:
            print(
                f"  [{player.get('player_id')}] {player.get('name')} "
                f"{player.get('type')} {player.get('status')}"
            )


def print_player_info(state: dict[str, Any]) -> None:
    current_id = state.get("current_player_id")
    current_name = player_name(state, current_id)
    if current_name:
        print(f"\n当前回合：[{current_id}] {current_name}")
    else:
        print("\n当前回合：-")

    print("玩家：")
    for player in state.get("visible_players", []):
        if "hp" not in player:
            continue
        marker = "->" if player.get("player_id") == current_id else "  "
        items = ", ".join(item_label(item) for item in player.get("items", [])) or "无"
        if player.get("hand_saw_active"):
            items = f"{items}, 手锯生效" if items != "无" else "手锯生效"
        print(
            f"{marker} [{player.get('player_id')}] {player.get('name')}: "
            f"HP {player.get('hp')}/{player.get('max_hp')} | 道具：{items}"
        )


def print_events(events: list[dict[str, Any]]) -> None:
    for event in events:
        message = event.get("message")
        if message:
            print(f"\n[{event_prefix(event)}] {message}")


def event_prefix(event: dict[str, Any]) -> str:
    if event.get("event_type") == "chat_message":
        return "聊天"
    if event.get("actor_player_id") is None:
        return "系统"
    return "事件"


def print_command_help(actions: list[dict[str, Any]], state: dict[str, Any]) -> None:
    print("\n命令说明：")
    print("直接输入文字：发送聊天")
    print(f"玩家编号：{format_player_command_refs(state)}")

    if not actions:
        print("当前没有可提交行动。")
        return

    shot_lines = [
        command_shot_label(action, state)
        for action in actions
        if action.get("type") in {"shoot_self", "shoot_player"}
    ]
    if shot_lines:
        print("射击：")
        for line in shot_lines:
            print(f"  {line}")

    item_actions = [
        action for action in actions if action.get("type") == "use_item"
    ]
    item_counts: dict[str, int] = {}
    for action in item_actions:
        item = str(action.get("item", ""))
        item_counts[item] = item_counts.get(item, 0) + 1
    item_lines = [
        command_use_label(action, state, item_counts)
        for action in item_actions
    ]
    if item_lines:
        print("道具：")
        for line in item_lines:
            print(f"  {line}")


def command_shot_label(action: dict[str, Any], state: dict[str, Any]) -> str:
    if action.get("type") == "shoot_self":
        player_id = state.get("player_seat_index")
        ref = player_command_ref(state, player_id) or str(player_id)
        return f"/shot {ref}  射击自己"
    target = action.get("target_player_id")
    ref = player_command_ref(state, target) or str(target)
    name = player_name(state, target) or "未知玩家"
    return f"/shot {ref}  射击 [{target}] {name}"


def command_use_label(
    action: dict[str, Any], state: dict[str, Any], item_counts: dict[str, int]
) -> str:
    item = str(action.get("item", ""))
    label = item_label(item)
    item_ref = item.lower()
    if item_counts.get(item, 0) > 1 and action.get("item_index") is not None:
        item_ref = str(int(action["item_index"]) + 1)
    if item == "JAMMER":
        target = first_opponent(state)
        target_ref = player_command_ref(state, target.get("player_id")) if target else "player"
        return f"/use {item_ref} --{target_ref}  使用{label}"
    if item == "ADRENALINE":
        target = first_stealable_opponent(state)
        target_ref = player_command_ref(state, target.get("player_id")) if target else "player"
        steal_ref = first_stealable_item_ref(target) if target else "item"
        secondary = " --player" if steal_ref == "jammer" else ""
        return (
            f"/use {item_ref} --{target_ref} --{steal_ref}{secondary}  "
            f"偷取并使用目标道具"
        )
    return f"/use {item_ref}  使用{label}"


def format_player_command_refs(state: dict[str, Any]) -> str:
    refs = []
    for player in players_in_command_order(state):
        suffix = "（你）" if player.get("player_id") == state.get("player_seat_index") else ""
        refs.append(f"{player.get('player_id')}={player.get('name')}{suffix}")
    return " | ".join(refs) if refs else "-"


def player_command_ref(state: dict[str, Any], player_id: int | None) -> str | None:
    for player in players_in_command_order(state):
        if player.get("player_id") == player_id:
            return str(player_id)
    return None


def players_in_command_order(state: dict[str, Any]) -> list[dict[str, Any]]:
    players = [
        player
        for player in state.get("visible_players", [])
        if player.get("player_id") is not None
    ]
    return sorted(players, key=lambda player: int(player["player_id"]))


def first_opponent(state: dict[str, Any]) -> dict[str, Any] | None:
    for player in players_in_command_order(state):
        if player.get("player_id") == state.get("player_seat_index"):
            continue
        if player.get("alive", True):
            return player
    return None


def first_stealable_opponent(state: dict[str, Any]) -> dict[str, Any] | None:
    for player in players_in_command_order(state):
        if player.get("player_id") == state.get("player_seat_index"):
            continue
        if player.get("alive", True) and any(
            item != "ADRENALINE" for item in player.get("items", [])
        ):
            return player
    return None


def first_stealable_item_ref(player: dict[str, Any] | None) -> str:
    if player is None:
        return "item"
    for item in player.get("items", []):
        if item != "ADRENALINE":
            return str(item).lower()
    return "item"


def player_name(state: dict[str, Any], player_id: int | None) -> str | None:
    if player_id is None:
        return None
    for player in state.get("visible_players", []):
        if player.get("player_id") == player_id:
            return player.get("name")
    return None


def item_label(item: str) -> str:
    return ITEM_LABELS.get(item, item)


def format_match_results(results: list[int]) -> str:
    if not results:
        return "-"
    counts: dict[int, int] = {}
    for player_id in results:
        counts[player_id] = counts.get(player_id, 0) + 1
    return " / ".join(f"{player_id}:{wins}" for player_id, wins in sorted(counts.items()))
