from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import shlex
import sys
import threading
from typing import Any

from .client import ApiClient, ApiError, normalize_server_url
from .renderer import (
    item_label,
    print_command_help,
    print_events as render_events,
    print_player_info,
    print_room,
    print_visible_state,
)
from .websocket_client import WebSocketClient, WebSocketError


GAME_COMMAND_HINT = "a 命令说明 | i 玩家信息 | r 同步 | q 退出"
COMMAND_PROMPT = "> "


class TerminalCommandPrompt:
    def __init__(self, help_text: str) -> None:
        self.help_text = help_text
        self._buffer: list[str] = []
        self._mounted = False

    def append(self, char: str) -> None:
        self._buffer.append(char)

    def backspace(self) -> None:
        if self._buffer:
            self._buffer.pop()

    def value(self) -> str:
        return "".join(self._buffer)

    def render(self) -> None:
        text = self.value()
        if not self._mounted:
            self._mounted = True
            sys.stdout.write("\n")
        sys.stdout.write(f"\r\x1b[2K{COMMAND_PROMPT}{text}")
        sys.stdout.write(f"\n\r\x1b[2K")
        sys.stdout.write(f"\n\r\x1b[2K{self.help_text}")
        sys.stdout.write(f"\x1b[2A\r{COMMAND_PROMPT}{text}")
        sys.stdout.flush()

    def clear(self) -> None:
        if not self._mounted:
            return
        sys.stdout.write("\r\x1b[2K\n\r\x1b[2K\n\r\x1b[2K\x1b[2A\r")
        sys.stdout.flush()
        self._mounted = False


_TERMINAL_LOCK = threading.RLock()
_ACTIVE_COMMAND_PROMPT: TerminalCommandPrompt | None = None


class RoomSession:
    def __init__(
        self,
        api: ApiClient,
        room: dict[str, Any],
        player_id: str,
        player_token: str,
    ) -> None:
        self.api = api
        self.room = room
        self.player_id = player_id
        self.player_token = player_token
        self.visible_state: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ws: WebSocketClient | None = None
        self._ws_connected = False
        self._listener: threading.Thread | None = None
        self._printed_event_keys: set[tuple[str, int]] = set()

    @property
    def room_code(self) -> str:
        return self.room["room_code"]

    def start(self) -> None:
        self.refresh(mark_events=True)
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()

    def close(self) -> None:
        self._stop.set()
        if self._ws is not None:
            self._ws.close()

    def refresh(
        self, *, print_updates: bool = False, mark_events: bool = False
    ) -> None:
        room = self.api.get_room(self.room_code)
        state = self.api.visible_state(self.room_code, self.player_token)
        with self._lock:
            self.room = room
            self._set_visible_state(state)
        events = list(state.get("visible_events") or [])
        if mark_events:
            self._mark_events(events)
        elif print_updates:
            events = self._new_events(events)
            if events:
                print_events(events)

    def room_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.room)

    def state_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self.visible_state) if self.visible_state is not None else None

    def submit_action(self, action: dict[str, Any]) -> None:
        state = self.state_snapshot()
        if state is None:
            raise ApiError("尚未收到可见状态。")
        envelope = self.api.submit_action(
            self.room_code,
            self.player_token,
            int(state["revision"]),
            action,
        )
        self._apply_envelope(envelope, print_updates=not self.has_websocket())

    def set_ready(self, ready: bool) -> None:
        self.room = self.api.set_ready(self.room_code, self.player_token, ready)

    def start_game(self) -> None:
        envelope = self.api.start_game(self.room_code, self.player_token)
        self._apply_envelope(envelope, print_updates=not self.has_websocket())

    def add_ai_player(self, ai_player_preset_id: str) -> None:
        self.room = self.api.add_ai_player(
            self.room_code,
            self.player_token,
            ai_player_preset_id,
        )

    def send_chat(self, message: str) -> None:
        envelope = self.api.send_chat(self.room_code, self.player_token, message)
        self._apply_envelope(envelope, print_updates=not self.has_websocket())

    def leave(self) -> None:
        self.room = self.api.leave_room(self.room_code, self.player_token)
        self.close()

    def has_websocket(self) -> bool:
        with self._lock:
            return self._ws_connected

    def _listen(self) -> None:
        try:
            ws = WebSocketClient(self.api.websocket_url(self.room_code, self.player_token))
            self._ws = ws
            ws.connect()
            with self._lock:
                self._ws_connected = True
            while not self._stop.is_set():
                text = ws.recv_text()
                if text is None:
                    break
                envelope = json.loads(text)
                self._apply_envelope(envelope, print_updates=True)
        except (OSError, WebSocketError, json.JSONDecodeError) as exc:
            if not self._stop.is_set():
                print_terminal_message(f"\n[连接] WebSocket 已断开：{exc}")
        finally:
            with self._lock:
                self._ws_connected = False

    def _apply_envelope(
        self, envelope: dict[str, Any], *, print_updates: bool
    ) -> None:
        with self._lock:
            if envelope.get("room") is not None:
                self.room = envelope["room"]
            if envelope.get("visible_state") is not None:
                self._set_visible_state(envelope["visible_state"])
        if not print_updates:
            return
        events = list(envelope.get("events") or [])
        if envelope.get("event") is not None:
            events.append(envelope["event"])
        events = self._new_events(events)
        if events:
            print_events(events)

    def _new_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new_events: list[dict[str, Any]] = []
        with self._lock:
            for event in events:
                event_key = self._event_key(event)
                if event_key is None:
                    new_events.append(event)
                    continue
                if event_key in self._printed_event_keys:
                    continue
                self._printed_event_keys.add(event_key)
                new_events.append(event)
        return new_events

    def _mark_events(self, events: list[dict[str, Any]]) -> None:
        with self._lock:
            for event in events:
                event_key = self._event_key(event)
                if event_key is not None:
                    self._printed_event_keys.add(event_key)

    def _set_visible_state(self, state: dict[str, Any]) -> None:
        if self.visible_state is None:
            self.visible_state = state
            return
        current_revision = int(self.visible_state.get("revision", -1))
        incoming_revision = int(state.get("revision", -1))
        if incoming_revision >= current_revision:
            self.visible_state = state

    def _event_key(self, event: dict[str, Any]) -> tuple[str, int] | None:
        game_id = event.get("game_id")
        event_id = event.get("event_id")
        if game_id is None or event_id is None:
            return None
        return str(game_id), int(event_id)


class CliApp:
    def __init__(self, api: ApiClient, player_name: str) -> None:
        self.api = api
        self.player_name = player_name

    def run(self) -> int:
        try:
            self.api.health()
        except ApiError as exc:
            print(f"无法连接后端：{exc}")
            return 2

        while True:
            print("\n=== Buckshot Roulette CLI ===")
            print("1. 创建房间")
            print("2. 搜索公开房间")
            print("3. 输入房间号加入")
            print("4. 查看 AI 玩家预设")
            print("5. 退出")
            choice = input("选择：").strip()
            try:
                if choice == "1":
                    self._create_room()
                elif choice == "2":
                    self._search_rooms()
                elif choice == "3":
                    self._join_by_code()
                elif choice == "4":
                    self._list_ai_presets()
                elif choice == "5":
                    return 0
                else:
                    print("请输入有效选项。")
            except ApiError as exc:
                print(f"操作失败：{exc}")

    def _create_room(self) -> None:
        room_name = input("房间名（可空）：").strip() or None
        visibility = prompt_choice("可见性", ["PUBLIC", "PRIVATE"], default="PUBLIC")
        max_players = prompt_int("最大人数（2-4，默认 4）：", 2, 4, default=4)
        response = self.api.create_room(
            player_name=self.player_name,
            room_name=room_name,
            visibility=visibility,
            max_players=max_players,
        )
        self._enter_room(response)

    def _search_rooms(self) -> None:
        rooms = self.api.list_rooms()
        if not rooms:
            print("没有可加入的公开房间。")
            return
        print("\n公开房间：")
        for index, room in enumerate(rooms, start=1):
            print(
                f"{index}. {room['room_code']} | {room['name']} | "
                f"{room['player_count']}/{room['max_players']} | {room['status']}"
            )
        value = input("输入序号加入，或直接回车返回：").strip()
        if not value:
            return
        try:
            index = int(value)
        except ValueError:
            print("请输入数字。")
            return
        if not 1 <= index <= len(rooms):
            print("序号无效。")
            return
        response = self.api.join_room(rooms[index - 1]["room_code"], self.player_name)
        self._enter_room(response)

    def _join_by_code(self) -> None:
        room_code = input("房间号：").strip().upper()
        if not room_code:
            return
        response = self.api.join_room(room_code, self.player_name)
        self._enter_room(response)

    def _list_ai_presets(self) -> None:
        presets = self.api.list_ai_player_presets()
        if not presets:
            print("没有启用的 AI 玩家预设。")
            return
        print("\nAI 玩家预设：")
        for preset in presets:
            print(
                f"- {preset['id']} | {preset['display_name']} | "
                f"model={preset['model_preset_id']}"
            )

    def _enter_room(self, response: dict[str, Any]) -> None:
        session = RoomSession(
            self.api,
            response["room"],
            response["player_id"],
            response["player_token"],
        )
        session.start()
        try:
            self._room_loop(session)
        finally:
            session.close()

    def _room_loop(self, session: RoomSession) -> None:
        while True:
            room = session.room_snapshot()
            state = session.state_snapshot()

            status = room["status"]
            if status == "LOBBY":
                print_room(room, session.player_id)
                if self._lobby_menu(session, room):
                    return
            elif status == "IN_GAME":
                if self._game_menu(session, state):
                    return
            else:
                print_room(room, session.player_id)
                if state is not None:
                    print_visible_state(state)
                if self._finished_menu(session):
                    return

    def _lobby_menu(self, session: RoomSession, room: dict[str, Any]) -> bool:
        me = find_room_player(room, session.player_id)
        ready = me is not None and me.get("status") == "READY"
        print("\n大厅操作：")
        print(f"1. {'取消准备' if ready else '准备'}")
        print("2. 开始游戏（房主）")
        print("3. 添加 AI 玩家（房主）")
        print("4. 聊天")
        print("5. 刷新")
        print("6. 离开房间")
        choice = input("选择：").strip()
        try:
            if choice == "1":
                session.set_ready(not ready)
                session.refresh()
            elif choice == "2":
                session.start_game()
                session.refresh()
            elif choice == "3":
                self._add_ai_player(session)
            elif choice == "4":
                self._chat(session)
            elif choice == "5":
                session.refresh()
            elif choice == "6":
                session.leave()
                return True
            else:
                print("请输入有效选项。")
        except ApiError as exc:
            print(f"操作失败：{exc}")
            safe_refresh(session)
        return False

    def _add_ai_player(self, session: RoomSession) -> None:
        presets = self.api.list_ai_player_presets()
        if not presets:
            print("没有启用的 AI 玩家预设。")
            return
        print("\n选择 AI 玩家预设：")
        for index, preset in enumerate(presets, start=1):
            print(
                f"{index}. {preset['display_name']} "
                f"({preset['id']}, model={preset['model_preset_id']})"
            )
        selected = prompt_int("选择预设：", 1, len(presets))
        session.add_ai_player(presets[selected - 1]["id"])
        session.refresh()

    def _game_menu(
        self, session: RoomSession, state: dict[str, Any] | None
    ) -> bool:
        if state is None:
            print("\n等待状态同步。")
            choice = prompt_command(GAME_COMMAND_HINT)
            try:
                command = choice.strip()
                normalized = command.lower()
                if normalized == "r":
                    session.refresh(print_updates=True)
                elif normalized == "":
                    pass
                elif normalized == "i":
                    self._print_player_info(session)
                elif normalized == "a":
                    print("\n尚未收到状态，无法生成命令说明。")
                elif normalized == "q":
                    session.close()
                    return True
                elif command.startswith("/"):
                    print("尚未收到状态，无法执行命令。")
                else:
                    session.send_chat(command)
            except ApiError as exc:
                print(f"操作失败：{exc}")
                safe_refresh(session)
            return False

        my_turn = (
            state.get("player_seat_index") == state.get("current_player_id")
            and bool(state.get("legal_actions"))
        )
        if my_turn:
            return self._action_menu(session, state)

        choice = prompt_command(GAME_COMMAND_HINT)
        try:
            if self._handle_game_command(session, state, choice):
                return True
        except ApiError as exc:
            print(f"操作失败：{exc}")
            safe_refresh(session)
        return False

    def _action_menu(self, session: RoomSession, state: dict[str, Any]) -> bool:
        actions = state.get("legal_actions", [])
        if not actions:
            print("当前没有可提交行动。")
            return False

        choice = prompt_command(GAME_COMMAND_HINT)
        try:
            if self._handle_game_command(session, state, choice):
                return True
        except ApiError as exc:
            print(f"操作失败：{exc}")
            safe_refresh(session)
        return False

    def _handle_game_command(
        self, session: RoomSession, state: dict[str, Any], raw_command: str
    ) -> bool:
        command = raw_command.strip()
        normalized = command.lower()
        if normalized == "r":
            session.refresh(print_updates=True)
        elif normalized == "":
            pass
        elif normalized == "i":
            self._print_player_info(session)
        elif normalized == "a":
            print_command_help(state.get("legal_actions", []), state)
        elif normalized == "q":
            session.close()
            return True
        elif command.startswith("/"):
            self._submit_command_action(session, state, command)
        else:
            session.send_chat(command)
        return False

    def _submit_command_action(
        self, session: RoomSession, state: dict[str, Any], command: str
    ) -> None:
        action = parse_action_command(command, state)
        if not action:
            return
        session.submit_action(action)

    def _finished_menu(self, session: RoomSession) -> bool:
        print("\n房间已结束：")
        print("1. 聊天")
        print("2. 刷新")
        print("3. 离开")
        choice = input("选择：").strip()
        if choice == "1":
            self._chat(session)
        elif choice == "2":
            safe_refresh(session)
        elif choice == "3":
            session.close()
            return True
        else:
            print("请输入有效选项。")
        return False

    def _chat(self, session: RoomSession) -> None:
        message = input("聊天内容：").strip()
        if message:
            session.send_chat(message)

    def _print_player_info(self, session: RoomSession) -> None:
        session.refresh()
        state = session.state_snapshot()
        if state is None:
            print("\n尚未收到玩家信息。")
            return
        print_player_info(state)


def find_room_player(room: dict[str, Any], player_id: str) -> dict[str, Any] | None:
    for player in room.get("players", []):
        if player.get("id") == player_id:
            return player
    return None


def parse_action_command(command: str, state: dict[str, Any]) -> dict[str, Any] | None:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ApiError(f"命令格式错误：{exc}") from exc
    if not parts:
        return None
    verb = parts[0].lower()
    if verb == "/shot":
        return parse_shot_command(parts[1:], state)
    if verb == "/use":
        return parse_use_command(parts[1:], state)
    raise ApiError("未知命令。可用 /shot 或 /use。")


def parse_shot_command(args: list[str], state: dict[str, Any]) -> dict[str, Any]:
    if len(args) != 1:
        raise ApiError("用法：/shot 玩家")
    player = resolve_player_ref(args[0], state)
    player_id = int(player["player_id"])
    if player_id == state.get("player_seat_index"):
        action = find_legal_action(state, "shoot_self")
        if action is None:
            raise ApiError("当前不能射击自己。")
        return sanitize_action(action)
    action = find_legal_action(state, "shoot_player", target_player_id=player_id)
    if action is None:
        raise ApiError("当前不能射击该玩家。")
    return sanitize_action(action)


def parse_use_command(args: list[str], state: dict[str, Any]) -> dict[str, Any]:
    if not args:
        raise ApiError("用法：/use 道具 [--玩家] [--道具] [--玩家]")
    item_token = args[0]
    options = parse_use_options(args[1:])
    item_action = resolve_item_action(item_token, state)
    action = sanitize_action(item_action)
    item = action.get("item")

    if item == "JAMMER":
        target = require_option(options, "target", "用法：/use jammer --player")
        action["target_player_id"] = int(resolve_player_ref(target, state)["player_id"])
    elif item == "ADRENALINE":
        target = require_option(
            options,
            "target",
            "用法：/use adrenaline --1 --beer；偷 jammer：/use adrenaline --1 --jammer --2",
        )
        victim = resolve_player_ref(target, state)
        action["target_player_id"] = int(victim["player_id"])
        item_ref = require_option(
            options,
            "stolen_item",
            "用法：/use adrenaline --1 --beer；偷 jammer：/use adrenaline --1 --jammer --2",
        )
        target_item_index, stolen_item = resolve_target_item_ref(item_ref, victim)
        action["target_item_index"] = target_item_index
        if stolen_item == "JAMMER":
            secondary = require_option(
                options,
                "secondary_target",
                "偷取 jammer 时需要指定使用目标：/use adrenaline --1 --jammer --2",
            )
            action["secondary_target_player_id"] = int(
                resolve_player_ref(secondary, state)["player_id"]
            )
        elif options.get("secondary_target") is not None:
            raise ApiError("偷取该道具不需要第二个玩家参数。")
    elif options:
        raise ApiError(f"{item_label(str(item))} 不需要参数。")
    return action


def parse_use_options(args: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for token in args:
        if token.startswith("--") and len(token) > 2:
            parse_use_flag(token[2:], options)
            continue
        raise ApiError(f"无法解析参数：{token}")
    return options


def parse_use_flag(value: str, options: dict[str, str]) -> None:
    if not value:
        raise ApiError("参数不能为空。")
    if value.isdigit():
        if "target" not in options:
            options["target"] = value
            return
        if "secondary_target" not in options:
            options["secondary_target"] = value
            return
        raise ApiError("玩家参数过多。")
    if "stolen_item" in options:
        raise ApiError("只能指定一个要偷取的道具。")
    options["stolen_item"] = value


def require_option(options: dict[str, str], key: str, message: str) -> str:
    value = options.get(key)
    if value is None or value == "":
        raise ApiError(message)
    return value


def resolve_player_ref(ref: str, state: dict[str, Any]) -> dict[str, Any]:
    players = players_in_command_order(state)
    if ref.isdigit():
        player_id = int(ref)
        for player in players:
            if player.get("player_id") == player_id:
                return player
        raise ApiError("玩家编号无效。")
    matches = [
        player
        for player in players
        if str(player.get("name", "")).lower() == ref.lower()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ApiError(f"找不到玩家：{ref}")
    raise ApiError(f"玩家名称不唯一：{ref}")


def players_in_command_order(state: dict[str, Any]) -> list[dict[str, Any]]:
    players = [
        player
        for player in state.get("visible_players", [])
        if player.get("player_id") is not None
    ]
    return sorted(players, key=lambda player: int(player["player_id"]))


def resolve_item_action(item_ref: str, state: dict[str, Any]) -> dict[str, Any]:
    actions = [
        action
        for action in state.get("legal_actions", [])
        if action.get("type") == "use_item"
    ]
    if item_ref.isdigit():
        item_index = int(item_ref) - 1
        for action in actions:
            if action.get("item_index") == item_index:
                return action
        raise ApiError("道具编号无效。")
    matches = [
        action
        for action in actions
        if item_matches(item_ref, str(action.get("item", "")))
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ApiError(f"找不到可使用道具：{item_ref}")
    raise ApiError(f"你有多个{item_label(str(matches[0].get('item')))}，请用编号指定。")


def resolve_target_item_ref(
    item_ref: str, player: dict[str, Any]
) -> tuple[int, str]:
    items = list(player.get("items", []))
    if item_ref.isdigit():
        index = int(item_ref) - 1
        if not 0 <= index < len(items):
            raise ApiError("目标道具编号无效。")
        item = str(items[index])
        if item == "ADRENALINE":
            raise ApiError("兴奋剂不能偷取兴奋剂。")
        return index, item
    matches = [
        (index, str(item))
        for index, item in enumerate(items)
        if str(item) != "ADRENALINE" and item_matches(item_ref, str(item))
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ApiError(f"目标没有可偷取道具：{item_ref}")
    raise ApiError(f"目标有多个{item_label(matches[0][1])}，请用编号指定。")


def item_matches(ref: str, item: str) -> bool:
    return ref.lower() == item.lower() or ref == item_label(item)


def find_legal_action(
    state: dict[str, Any], action_type: str, **criteria: Any
) -> dict[str, Any] | None:
    for action in state.get("legal_actions", []):
        if action.get("type") != action_type:
            continue
        if all(action.get(key) == value for key, value in criteria.items()):
            return action
    return None


def sanitize_action(action: dict[str, Any]) -> dict[str, Any]:
    clean = dict(action)
    clean.pop("requires_target_player_id", None)
    clean.pop("requires_target_item_index", None)
    return clean


def prompt_choice(prompt: str, choices: list[str], *, default: str) -> str:
    raw = input(f"{prompt}（{'/'.join(choices)}，默认 {default}）：").strip().upper()
    if not raw:
        return default
    if raw not in choices:
        print(f"无效选项，使用默认值 {default}。")
        return default
    return raw


def prompt_int(
    prompt: str,
    min_value: int,
    max_value: int,
    *,
    default: int | None = None,
) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("请输入数字。")
            continue
        if min_value <= value <= max_value:
            return value
        print(f"请输入 {min_value} 到 {max_value} 之间的数字。")


def safe_refresh(session: RoomSession) -> None:
    try:
        session.refresh()
    except ApiError:
        pass


def prompt_command(help_text: str) -> str:
    if is_interactive_terminal():
        prompt = TerminalCommandPrompt(help_text)
        global _ACTIVE_COMMAND_PROMPT
        with _raw_terminal_input():
            with _TERMINAL_LOCK:
                _ACTIVE_COMMAND_PROMPT = prompt
                prompt.render()
            try:
                while True:
                    key = _read_terminal_key()
                    if key in {"\r", "\n"}:
                        return prompt.value().strip()
                    if key == "\x03":
                        raise KeyboardInterrupt
                    if key == "\x04":
                        raise EOFError

                    changed = False
                    with _TERMINAL_LOCK:
                        if key in {"\b", "\x7f"}:
                            prompt.backspace()
                            changed = True
                        elif key.isprintable():
                            prompt.append(key)
                            changed = True
                        if changed:
                            prompt.render()
            finally:
                with _TERMINAL_LOCK:
                    prompt.clear()
                    if _ACTIVE_COMMAND_PROMPT is prompt:
                        _ACTIVE_COMMAND_PROMPT = None

    print(f"\n{help_text}")
    return input(COMMAND_PROMPT).strip()


def print_events(events: list[dict[str, Any]]) -> None:
    write_above_command_prompt(lambda: render_events(events))


def print_terminal_message(message: str) -> None:
    write_above_command_prompt(lambda: print(message))


def write_above_command_prompt(write: Any) -> None:
    if not is_interactive_terminal():
        write()
        return

    with _TERMINAL_LOCK:
        prompt = _ACTIVE_COMMAND_PROMPT
        if prompt is not None:
            prompt.clear()
        try:
            write()
        finally:
            if prompt is not None:
                prompt.render()
            sys.stdout.flush()


def is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def _raw_terminal_input() -> Any:
    if sys.platform == "win32":
        yield
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def _read_terminal_key() -> str:
    if sys.platform == "win32":
        import msvcrt

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            msvcrt.getwch()
            return ""
        return key

    key = sys.stdin.read(1)
    if key == "\x1b":
        _drain_escape_sequence()
        return ""
    return key


def _drain_escape_sequence() -> None:
    import select

    while select.select([sys.stdin], [], [], 0.001)[0]:
        sys.stdin.read(1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Buckshot Roulette thin CLI client")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8000",
        help="后端地址，默认 http://127.0.0.1:8000",
    )
    parser.add_argument("--name", help="临时显示名")
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="HTTP request timeout in seconds. Default: 60.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        server = normalize_server_url(args.server)
    except ApiError as exc:
        print(f"服务器地址无效：{exc}")
        return 2
    name = args.name or input("临时显示名：").strip()
    if not name:
        print("临时显示名不能为空。")
        return 2
    app = CliApp(ApiClient(server, timeout=args.timeout), name)
    try:
        return app.run()
    except KeyboardInterrupt:
        print("\n已退出。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
