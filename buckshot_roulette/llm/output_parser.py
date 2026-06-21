from __future__ import annotations

import json
from typing import Any

from buckshot_roulette.llm.models import SingleActionDecision


class OutputParserError(ValueError):
    pass


class OutputParser:
    def parse(self, output: str | dict[str, Any]) -> SingleActionDecision:
        if isinstance(output, str):
            try:
                data = json.loads(output)
            except json.JSONDecodeError as exc:
                data = self._parse_embedded_json(output, exc)
        else:
            data = output
        if not isinstance(data, dict):
            raise OutputParserError("模型输出必须是 JSON object。")
        action = data.get("action")
        if not isinstance(action, dict):
            raise OutputParserError("模型输出缺少 action object。")
        action_type = action.get("type")
        if action_type not in {"shoot_self", "shoot_player", "use_item"}:
            raise OutputParserError("模型输出 action.type 无效。")
        if action_type == "shoot_player" and "target_player_id" not in action:
            raise OutputParserError("shoot_player 缺少 target_player_id。")
        if action_type == "use_item" and "item" not in action:
            raise OutputParserError("use_item 缺少 item。")
        thought = data.get("thought_summary", "")
        if not isinstance(thought, str):
            thought = str(thought)
        return SingleActionDecision(thought_summary=thought, action=action)

    def _parse_embedded_json(
        self, output: str, original_error: json.JSONDecodeError
    ) -> Any:
        json_text = self._extract_json_object(output)
        if json_text is None:
            raise OutputParserError("模型输出不是有效 JSON。") from original_error
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise OutputParserError("模型输出不是有效 JSON。") from exc

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
