#!/usr/bin/env bash
set -euo pipefail

SERVER="${SERVER:-http://127.0.0.1:8000}"
SERVER="${SERVER%/}"

post_json() {
  local path="$1"
  local body="$2"

  curl --fail-with-body \
    --silent \
    --show-error \
    --request POST \
    --header "Content-Type: application/json; charset=utf-8" \
    --data "${body}" \
    "${SERVER}${path}"
  printf '\n'
}

provider='{
  "id": "openrouter_main",
  "display_name": "OpenRouter Main",
  "type": "third_party",
  "protocol": "openai_chat_completions",
  "base_url": "https://openrouter.ai/api/v1",
  "api_key_env": "OPENROUTER_API_KEY_MAIN",
  "api_key": null,
  "class_path": null,
  "kwargs": {}
}'

model_preset='{
  "id": "openrouter_default",
  "display_name": "OpenRouter Default",
  "provider_id": "openrouter_main",
  "model_name": "openai/gpt-4o-mini",
  "temperature": 0.3,
  "max_tokens": 500,
  "reasoning_effort": null,
  "timeout_seconds": 30,
  "max_retries": 2,
  "extra": {
    "top_p": 0.9
  }
}'

ai_player_preset='{
  "id": "cautious_openrouter_dealer",
  "display_name": "Cautious OpenRouter Dealer",
  "enabled": true,
  "model_preset_id": "openrouter_default",
  "persona_prompt": "You are a careful Buckshot Roulette AI player.",
  "strategy_prompt": "Prefer legal, conservative actions. Use items when they reduce risk.",
  "max_item_actions_per_turn": 8,
  "max_parse_failures_per_turn": 2,
  "max_illegal_actions_per_turn": 2,
  "fallback_policy": "conservative_shot"
}'

echo "Configuring provider..."
post_json "/admin/llm/providers" "${provider}"

echo "Configuring model preset..."
post_json "/admin/llm/model-presets" "${model_preset}"

echo "Configuring AI player preset..."
post_json "/admin/ai-player-presets" "${ai_player_preset}"

echo "Done."
