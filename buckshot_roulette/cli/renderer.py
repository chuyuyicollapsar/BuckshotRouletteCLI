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
    print_item_command_help()

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

def print_item_command_help() -> None:
    print("道具：")
    print(f"  名称：{format_item_command_refs()}")
    print("  无对象：/use 道具，例如：/use beer")
    print("  有对象（干扰器）：/use jammer --玩家，例如：/use jammer --1")
    print(
        "  有对象且更多参数（兴奋剂）：/use adrenaline --玩家 --道具 [--玩家]，"
        "例如：/use adrenaline --1 --beer；偷取干扰器时：/use adrenaline --1 --jammer --2"
    )


def command_shot_label(action: dict[str, Any], state: dict[str, Any]) -> str:
    if action.get("type") == "shoot_self":
        player_id = state.get("player_seat_index")
        ref = player_command_ref(state, player_id) or str(player_id)
        return f"/shot {ref}  射击自己"
    target = action.get("target_player_id")
    ref = player_command_ref(state, target) or str(target)
    name = player_name(state, target) or "未知玩家"
    return f"/shot {ref}  射击 [{target}] {name}"


def format_player_command_refs(state: dict[str, Any]) -> str:
    refs = []
    for player in players_in_command_order(state):
        suffix = "（你）" if player.get("player_id") == state.get("player_seat_index") else ""
        refs.append(f"{player.get('player_id')}={player.get('name')}{suffix}")
    return " | ".join(refs) if refs else "-"


def format_item_command_refs() -> str:
    refs = [
        f"{item.lower()}（{label}）"
        for item, label in ITEM_LABELS.items()
    ]
    return " | ".join(refs)


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
