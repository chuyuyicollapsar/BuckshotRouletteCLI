from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    pass


def normalize_server_url(value: str) -> str:
    server = value.strip()
    if not server:
        server = "http://127.0.0.1:8000"
    if "://" not in server:
        server = "http://" + server
    parsed = urlparse(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiError("服务器地址必须是 http(s)://host[:port] 格式。")
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


class ApiClient:
    def __init__(self, server_url: str, timeout: float = 10.0) -> None:
        self.server_url = normalize_server_url(server_url)
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self.get("/health")

    def create_room(
        self,
        *,
        player_name: str,
        room_name: str | None,
        visibility: str,
        max_players: int,
    ) -> dict[str, Any]:
        return self.post(
            "/rooms",
            {
                "player_name": player_name,
                "room_name": room_name,
                "visibility": visibility,
                "max_players": max_players,
            },
        )

    def list_rooms(self) -> list[dict[str, Any]]:
        return self.get("/rooms")

    def get_room(self, room_code: str) -> dict[str, Any]:
        return self.get(f"/rooms/{quote(room_code.upper())}")

    def join_room(self, room_code: str, player_name: str) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/join",
            {"player_name": player_name},
        )

    def list_ai_player_presets(self) -> list[dict[str, Any]]:
        return self.get("/ai-player-presets")

    def add_ai_player(
        self,
        room_code: str,
        player_token: str,
        ai_player_preset_id: str,
    ) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/ai-players",
            {
                "player_token": player_token,
                "ai_player_preset_id": ai_player_preset_id,
            },
        )

    def leave_room(self, room_code: str, player_token: str) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/leave",
            {"player_token": player_token},
        )

    def set_ready(self, room_code: str, player_token: str, ready: bool) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/ready",
            {"player_token": player_token, "ready": ready},
        )

    def start_game(self, room_code: str, player_token: str) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/start",
            {"player_token": player_token},
        )

    def submit_action(
        self,
        room_code: str,
        player_token: str,
        revision: int,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/actions",
            {
                "player_token": player_token,
                "revision": revision,
                "action": action,
            },
        )

    def send_chat(self, room_code: str, player_token: str, message: str) -> dict[str, Any]:
        return self.post(
            f"/rooms/{quote(room_code.upper())}/chat",
            {"player_token": player_token, "message": message},
        )

    def visible_state(self, room_code: str, player_token: str) -> dict[str, Any]:
        query = urlencode({"player_token": player_token})
        return self.get(f"/rooms/{quote(room_code.upper())}/visible-state?{query}")

    def websocket_url(self, room_code: str, player_token: str) -> str:
        parsed = urlparse(self.server_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path_prefix = parsed.path.rstrip("/")
        path = f"{path_prefix}/rooms/{quote(room_code.upper())}/events"
        query = urlencode({"player_token": player_token})
        return urlunparse((scheme, parsed.netloc, path, "", query, ""))

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        url = urljoin(self.server_url + "/", path.lstrip("/"))
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raise ApiError(self._read_error(exc)) from exc
        except URLError as exc:
            raise ApiError(f"无法连接服务器：{exc.reason}") from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def _read_error(self, exc: HTTPError) -> str:
        try:
            data = json.loads(exc.read().decode("utf-8"))
            detail = data.get("detail")
            if detail:
                return str(detail)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return f"HTTP {exc.code}"
