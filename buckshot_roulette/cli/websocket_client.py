from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.parse import urlparse


class WebSocketError(RuntimeError):
    pass


class WebSocketClient:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, url: str, timeout: float | None = None) -> None:
        self.url = url
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise WebSocketError("WebSocket 地址无效。")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        raw_sock = socket.create_connection((parsed.hostname, port), timeout=self.timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            raw_sock = context.wrap_socket(raw_sock, server_hostname=parsed.hostname)
        self.sock = raw_sock

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        raw_sock.sendall(request.encode("ascii"))
        response = self._read_http_response()
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise WebSocketError("WebSocket 握手失败。")
        expected = base64.b64encode(
            hashlib.sha1((key + self.GUID).encode("ascii")).digest()
        ).decode("ascii")
        if f"sec-websocket-accept: {expected.lower()}".encode("ascii") not in response.lower():
            raise WebSocketError("WebSocket 握手校验失败。")

    def recv_text(self) -> str | None:
        while True:
            first = self._read_exact(2)
            b1, b2 = first[0], first[1]
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

            if opcode == 0x8:
                return None
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                return payload.decode("utf-8")
            raise WebSocketError(f"不支持的 WebSocket 帧类型：{opcode}")

    def send_text(self, text: str) -> None:
        self._send_frame(text.encode("utf-8"), opcode=0x1)

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self._send_frame(b"", opcode=0x8)
        except OSError:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    def _send_frame(self, payload: bytes, *, opcode: int) -> None:
        if self.sock is None:
            raise WebSocketError("WebSocket 尚未连接。")
        mask = os.urandom(4)
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        masked_payload = bytes(
            byte ^ mask[index % 4] for index, byte in enumerate(payload)
        )
        self.sock.sendall(header + mask + masked_payload)

    def _read_http_response(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = self._read_exact(1)
            chunks.append(chunk)
            data = b"".join(chunks)
            if data.endswith(b"\r\n\r\n"):
                return data

    def _read_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise WebSocketError("WebSocket 尚未连接。")
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise WebSocketError("WebSocket 连接已关闭。")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
