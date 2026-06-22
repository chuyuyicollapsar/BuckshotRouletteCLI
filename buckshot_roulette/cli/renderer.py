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


def print_events(events: list[dict[str, Any]]) -> None:
    for event in events:
        message = event.get("message")
        if message:
            print(f"\n[事件] {message}")


def action_label(action: dict[str, Any], state: dict[str, Any]) -> str:
    action_type = action.get("type")
    if action_type == "shoot_self":
        return "射自己"
    if action_type == "shoot_player":
        target = action.get("target_player_id")
        return f"射击 [{target}] {player_name(state, target) or '未知玩家'}"
    if action_type == "use_item":
        item = action.get("item", "")
        index = action.get("item_index")
        index_text = "" if index is None else f"#{int(index) + 1} "
        extra = ""
        if action.get("requires_target_player_id"):
            extra = "（需选择目标）"
        return f"使用 {index_text}{item_label(item)}{extra}"
    return str(action)


def player_name(state: dict[str, Any], player_id: int | None) -> str | None:
    if player_id is None:
        return None
    for player in state.get("visible_players", []):
        if player.get("player_id") == player_id:
            return player.get("name")
    return None


def alive_opponents(state: dict[str, Any]) -> list[dict[str, Any]]:
    me = state.get("player_seat_index")
    return [
        player
        for player in state.get("visible_players", [])
        if player.get("alive") and player.get("player_id") != me
    ]


def item_label(item: str) -> str:
    return ITEM_LABELS.get(item, item)


def format_match_results(results: list[int]) -> str:
    if not results:
        return "-"
    counts: dict[int, int] = {}
    for player_id in results:
        counts[player_id] = counts.get(player_id, 0) + 1
    return " / ".join(f"{player_id}:{wins}" for player_id, wins in sorted(counts.items()))
