<#
Configure one LLM provider, one model preset, and one AI player preset.

Usage:
  1. Start backend:
       buckshot-server
  2. Set the real API key in the environment variable used by provider.api_key_env.
  3. Edit the three request bodies below.
  4. Run:
       .\scripts\config_llm_presets.ps1

Notes:
  - api_key_env is the environment variable name, not the API key value.
  - api_key is written to llm_config.json in plaintext. Prefer api_key_env.
  - Requests are applied in dependency order:
      ProviderConfig -> ModelPreset -> AIPlayerPreset
#>

param(
    [string]$Server = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$Server = $Server.TrimEnd("/")

function Invoke-JsonPost {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [hashtable]$Body
    )

    Invoke-RestMethod `
        -Method Post `
        -Uri "$Server$Path" `
        -ContentType "application/json; charset=utf-8" `
        -Body ($Body | ConvertTo-Json -Depth 20)
}

# ---------------------------------------------------------------------------
# 1. ProviderConfig: one concrete API access configuration.
#
# Fields:
#   id          Required. Stable provider id. ModelPreset.provider_id points here.
#   display_name Optional. Human-readable name for admin/client display.
#   type        Optional. "official" or "third_party". Default: "third_party".
#   protocol    Required. Supported values:
#                 "openai_responses"
#                 "openai_chat_completions"
#                 "anthropic"
#                 "anthropic_messages"
#                 "gemini"
#                 "deepseek"
#                 "custom_langchain"
#                 "fake"
#   base_url    Optional. Required for third-party OpenAI/Anthropic compatible APIs.
#   api_key_env Optional. Environment variable name that stores the real API key.
#   api_key     Optional. Plaintext API key. Local development only.
#   class_path  Optional. Required when protocol is "custom_langchain".
#   kwargs      Optional. Extra provider construction options.
# ---------------------------------------------------------------------------

$provider = @{
    id = "openrouter_main"
    display_name = "OpenRouter Main"
    type = "third_party"
    protocol = "openai_chat_completions"
    base_url = "https://openrouter.ai/api/v1"
    api_key_env = "OPENROUTER_API_KEY_MAIN"
    api_key = $null
    class_path = $null
    kwargs = @{}
}

# ---------------------------------------------------------------------------
# 2. ModelPreset: model and generation settings bound to one provider.
#
# Fields:
#   id               Required. Stable model preset id.
#   display_name     Optional. Human-readable preset name.
#   provider_id      Required. Must match an existing ProviderConfig.id.
#   model_name       Required. Real model name used by the provider.
#   temperature      Optional. Number from 0 to 2.
#   max_tokens       Optional. Positive integer.
#   reasoning_effort Optional. Provider-specific value, for example "low",
#                    "medium", or "high" when supported.
#   timeout_seconds  Optional. Request timeout. Default: 30.
#   max_retries      Optional. Retry count. Default: 2.
#   extra            Optional. Allowed keys:
#                      top_p
#                      frequency_penalty
#                      presence_penalty
#                      stop
#                      model_kwargs
#                      extra_body
#
# Stored version is managed by the backend. Updating the same id increments it.
# ---------------------------------------------------------------------------

$modelPreset = @{
    id = "openrouter_default"
    display_name = "OpenRouter Default"
    provider_id = "openrouter_main"
    model_name = "openai/gpt-4o-mini"
    temperature = 0.3
    max_tokens = 500
    reasoning_effort = $null
    timeout_seconds = 30
    max_retries = 2
    extra = @{
        top_p = 0.9
    }
}

# ---------------------------------------------------------------------------
# 3. AIPlayerPreset: player behavior settings bound to one model preset.
#
# Fields:
#   id                                Required. Stable AI player preset id.
#   display_name                      Optional. Name shown to client/admin.
#   enabled                           Optional. Only enabled presets appear to
#                                     normal clients. Default: true.
#   model_preset_id                   Required. Must match an existing ModelPreset.id.
#   rules_prompt_id                   Optional. Built-in game rules prompt id.
#                                     Default: "builtin:ai_game_rules_v1".
#   decision_prompt_id                Optional. Built-in decision prompt id.
#                                     Default: "builtin:ai_decision_hints_v1".
#   custom_rules_prompt               Optional. Non-empty value overrides rules_prompt_id.
#   custom_decision_prompt            Optional. Non-empty value overrides decision_prompt_id.
#   persona_prompt                    Optional. AI role/personality prompt.
#   strategy_prompt                   Optional. AI play-style prompt.
#   chat_enabled                      Optional. Whether this AI replies to chat.
#                                     Default: false.
#   chat_prompt                       Optional. Chat style prompt, used only for chat replies.
#   chat_trigger_mode                 Optional. Currently supported value: "mention".
#   chat_model_preset_id              Optional. Null means chat reuses model_preset_id.
#   chat_max_chars                    Optional. Max AI chat reply length. Default: 160.
#   chat_cooldown_seconds             Optional. Per-AI chat cooldown. Default: 5.
#   max_item_actions_per_turn          Optional. Max item actions before shooting.
#                                     Default: 8.
#   max_parse_failures_per_turn        Optional. Max malformed model outputs before
#                                     fallback. Default: 2.
#   max_illegal_actions_per_turn       Optional. Max illegal model actions before
#                                     fallback. Default: 2.
#   fallback_policy                   Optional. Supported values:
#                                       "conservative_shot"
#                                       "attack_lowest_hp"
#
# Stored version is managed by the backend. Updating the same id increments it.
# ---------------------------------------------------------------------------

$aiPlayerPreset = @{
    id = "cautious_openrouter_dealer"
    display_name = "Cautious OpenRouter Dealer"
    enabled = $true
    model_preset_id = "openrouter_default"
    rules_prompt_id = "builtin:ai_game_rules_v1"
    decision_prompt_id = "builtin:ai_decision_hints_v1"
    custom_rules_prompt = $null
    custom_decision_prompt = $null
    persona_prompt = "You are a careful Buckshot Roulette AI player."
    strategy_prompt = "Prefer legal, conservative actions. Use items when they reduce risk."
    chat_enabled = $true
    chat_prompt = "Keep table talk short and in character. Check hp, visible items, public events, and player-claimed private info before judging lethal lines."
    chat_trigger_mode = "mention"
    chat_model_preset_id = $null
    chat_max_chars = 160
    chat_cooldown_seconds = 5
    max_item_actions_per_turn = 8
    max_parse_failures_per_turn = 2
    max_illegal_actions_per_turn = 2
    fallback_policy = "conservative_shot"
}

Write-Host "Configuring provider..."
$providerResult = Invoke-JsonPost -Path "/admin/llm/providers" -Body $provider
$providerResult | ConvertTo-Json -Depth 20

Write-Host "Configuring model preset..."
$modelResult = Invoke-JsonPost -Path "/admin/llm/model-presets" -Body $modelPreset
$modelResult | ConvertTo-Json -Depth 20

Write-Host "Configuring AI player preset..."
$aiResult = Invoke-JsonPost -Path "/admin/ai-player-presets" -Body $aiPlayerPreset
$aiResult | ConvertTo-Json -Depth 20

Write-Host "Done."
