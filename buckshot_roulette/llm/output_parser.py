from __future__ import annotations

import ast
import json
from typing import Any

from buckshot_roulette.llm.models import ChatReply, SingleActionDecision


class OutputParserError(ValueError):
    def __init__(self, message: str, raw_output: Any | None = None) -> None:
        self.raw_output_preview = self._preview(raw_output)
        if self.raw_output_preview:
            message = f"{message} raw_output_preview={self.raw_output_preview!r}"
        super().__init__(message)

    def _preview(self, raw_output: Any | None) -> str:
        if raw_output is None:
            return ""
        text = str(raw_output).replace("\r", "\\r").replace("\n", "\\n")
        return text[:500]


class OutputParser:
    def parse(self, output: str | dict[str, Any]) -> SingleActionDecision:
        if isinstance(output, str):
            try:
                data = json.loads(output)
            except json.JSONDecodeError as exc:
                data = self._parse_embedded_json(output, exc)
        else:
            data = output
        if isinstance(data, str):
            return self.parse(data)
        if not isinstance(data, dict):
            raise OutputParserError("模型输出必须是 JSON object。", output)
        action = data.get("action")
        if not isinstance(action, dict):
            raise OutputParserError("模型输出缺少 action object。", output)
        action_type = action.get("type")
        if action_type not in {"shoot_self", "shoot_player", "use_item"}:
            raise OutputParserError("模型输出 action.type 无效。", output)
        if action_type == "shoot_player" and "target_player_id" not in action:
            raise OutputParserError("shoot_player 缺少 target_player_id。", output)
        if action_type == "use_item" and "item" not in action:
            raise OutputParserError("use_item 缺少 item。", output)
        thought = data.get("thought_summary", "")
        if not isinstance(thought, str):
            thought = str(thought)
        return SingleActionDecision(thought_summary=thought, action=action)

    def parse_chat_reply(self, output: str | dict[str, Any]) -> ChatReply:
        if isinstance(output, str):
            try:
                data = json.loads(output)
            except json.JSONDecodeError as exc:
                data = self._parse_embedded_json(output, exc)
        else:
            data = output
        if not isinstance(data, dict):
            raise OutputParserError("模型聊天输出必须是 JSON object。", output)
        reply = data.get("reply")
        if not isinstance(reply, str):
            reply = "" if reply is None else str(reply)
        reply = reply.strip()
        if not reply:
            raise OutputParserError("模型聊天输出缺少 reply 文本。", output)
        return ChatReply(reply=reply)

    def _parse_embedded_json(
        self, output: str, original_error: json.JSONDecodeError
    ) -> Any:
        json_text = self._extract_json_object(output)
        if json_text is None:
            literal = self._parse_python_literal(output)
            if literal is not None:
                return literal
            raise OutputParserError("模型输出不是有效 JSON。", output) from original_error
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            literal = self._parse_python_literal(json_text)
            if literal is not None:
                return literal
            raise OutputParserError("模型输出不是有效 JSON。", output) from exc

    def _extract_json_object(self, output: str) -> str | None:
        start = output.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(output)):
            char = output[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return output[start : index + 1]
        return None

    def _parse_python_literal(self, output: str) -> Any | None:
        try:
            data = ast.literal_eval(output.strip())
        except (SyntaxError, ValueError):
            return None
        return data if isinstance(data, dict) else None
