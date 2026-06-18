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
                raise OutputParserError("模型输出不是有效 JSON。") from exc
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
