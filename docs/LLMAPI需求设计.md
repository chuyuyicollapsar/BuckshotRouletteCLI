# LLM API 需求设计

## 1. 目标

为恶魔轮盘 CLI/后端提供统一的 LLM 调用层，使 AI 玩家可以通过 LangChain 调用不同模型服务。

必须支持：
- 官方模型服务：OpenAI/ChatGPT、Anthropic/Claude、Google Gemini、DeepSeek
- 第三方模型服务：通过配置填写服务地址、API Key、协议、模型名和额外参数
- 后台管理：编辑 provider、模型预设、AI 玩家预设，并测试连接
- CLI 创建房间时选择 AI 玩家预设加入游戏
- 稳定输出：LLM 必须返回可校验的游戏行动，不能直接信任自然语言结果
- 可选 AI 聊天：AI 可在明确触发时生成聊天回复，但聊天回复必须与行动决策解耦

不在本阶段处理：
- 模型计费系统
- RAG、长期记忆、复杂 Agent 工具链
- 本地模型推理服务部署
- 完整用户账号和后台权限系统，首版只要求区分普通 CLI 用户与管理员操作边界

## 2. 设计原则

### 2.1 Provider、模型预设、AI 玩家预设解耦

后台管理需要把模型调用配置做成对象，但不能把真实模型名再套成业务模型别名。

对象分三层：

| 对象 | 职责 |
|---|---|
| `ProviderConfig` | 服务来源、协议、base URL、密钥来源 |
| `ModelPreset` | 一套模型调用参数，必须包含真实 `model_name` |
| `AIPlayerPreset` | 一个可加入房间的 AI 玩家模板，引用 `ModelPreset`，并包含名称、角色提示词、决策策略、聊天配置和保底策略 |

`ModelPreset.id` 是后台管理对象 id，不是模型别名。真正传给 provider 的始终是 `model_name`。

示例：

```yaml
model_presets:
  openai_reasoning_default:
    provider_id: openai_official
    model_name: "<openai-real-model-name>"
    temperature: 0.3
    max_tokens: 800

ai_player_presets:
  cautious_dealer:
    display_name: Cautious Dealer
    model_preset_id: openai_reasoning_default
    persona_prompt: "You are a careful Buckshot Roulette player."
    strategy_prompt: "Prefer information-gathering items before shooting."
```

CLI 创建房间时只选择 `AIPlayerPreset`，不能直接提交 provider、base URL、API Key。房间保存 AI 玩家预设快照，避免后台配置在对局中途改变正在进行的游戏。

### 2.2 官方服务优先走官方 LangChain 集成

官方服务使用 provider-specific package，不默认拿 `ChatOpenAI(base_url=...)` 混接所有服务。

| Provider | LangChain 类 | 包 | 默认密钥来源 |
|---|---|---|---|
| OpenAI / ChatGPT | `ChatOpenAI`，默认启用 Responses API | `langchain-openai` | `OPENAI_API_KEY` |
| Anthropic / Claude | `ChatAnthropic` | `langchain-anthropic` | `ANTHROPIC_API_KEY` |
| Google Gemini | `ChatGoogleGenerativeAI` | `langchain-google-genai` | `GOOGLE_API_KEY` / `GEMINI_API_KEY` |
| DeepSeek | `ChatDeepSeek` | `langchain-deepseek` | `DEEPSEEK_API_KEY` |

原因：第三方 OpenAI-compatible 服务经常有额外字段、不同流式格式、不同工具调用行为。LangChain 文档也明确提醒 `ChatOpenAI` 只面向官方 OpenAI API 规范；如果 provider 扩展了 Chat Completions 或 Responses 格式，应使用 provider-specific 包或自定义适配器。

OpenAI 官方集成优先使用 Responses API。Responses API 是 OpenAI 当前面向直接模型请求、工具使用、状态管理和多模态输入输出的主接口；Chat Completions 仍可用，并且仍支持函数/工具调用，但不应作为新 OpenAI 官方集成的默认协议。

### 2.3 第三方服务按协议适配

第三方模型不是“随便填个 URL 就能稳定工作”。配置必须声明协议。

支持协议：

| 协议 | 用途 | 适配方式 |
|---|---|---|
| `openai_responses` | OpenAI 官方 Responses API，或明确支持 Responses API 的兼容服务 | `ChatOpenAI(use_responses_api=True, base_url=..., api_key=...)` |
| `openai_chat_completions` | OpenAI Chat Completions 兼容服务，主要用于第三方 OpenAI-compatible 服务 | `ChatOpenAI(base_url=..., api_key=...)` |
| `anthropic` | Anthropic 官方 Messages API | `ChatAnthropic(...)` |
| `anthropic_messages` | Anthropic Messages 兼容服务 | `ChatAnthropic(base_url=..., api_key=...)` |
| `gemini` | Google Gemini 官方 API | `ChatGoogleGenerativeAI(...)` |
| `deepseek` | DeepSeek 官方服务 | `ChatDeepSeek(...)` |
| `custom_langchain` | 其他 LangChain chat model | 通过 import path 加载自定义类 |

首版实现优先级：
1. OpenAI 官方 `openai_responses`
2. Anthropic、Gemini、DeepSeek 官方 provider
3. 第三方 `openai_chat_completions`
4. `custom_langchain`

这不是永久砍掉其他协议，而是避免把“全兼容”写成无法验证的承诺。不同 provider 对 structured output、函数调用、内置工具、流式格式、错误码、token usage、重试语义的支持差异很大。配置层可以预留 `openai_responses` 第三方兼容服务和 `anthropic_messages` 第三方兼容服务，但必须通过 `model-preset test` 标记实际能力，不能只因为 URL 兼容就默认完全兼容。

## 3. 后台管理与配置设计

### 3.1 Provider 配置

Provider 表示一个服务来源，不一定等于某个模型。

```yaml
llm:
  providers:
    openai_official:
      type: official
      protocol: openai_responses
      api_key_env: OPENAI_API_KEY

    anthropic_official:
      type: official
      protocol: anthropic
      api_key_env: ANTHROPIC_API_KEY

    gemini_official:
      type: official
      protocol: gemini
      api_key_env: GEMINI_API_KEY

    deepseek_official:
      type: official
      protocol: deepseek
      api_key_env: DEEPSEEK_API_KEY

    openrouter:
      type: third_party
      protocol: openai_chat_completions
      base_url: https://openrouter.ai/api/v1
      api_key_env: OPENROUTER_API_KEY

    local_proxy:
      type: third_party
      protocol: openai_chat_completions
      base_url: http://127.0.0.1:8000/v1
      api_key_env: LOCAL_PROXY_API_KEY
```

规则：
- API Key 优先从环境变量读取，不建议写入配置文件
- 允许 `api_key` 明文字段只用于本地开发，并在日志中强制脱敏
- `base_url` 只对第三方或 Azure/代理类服务开放
- 配置加载时要校验 URL、协议、必填字段和 provider id 唯一性

### 3.2 Model Preset 配置

`ModelPreset` 是后台管理对象，用于保存一套模型调用参数。它有自己的 `id`，但必须显式保存真实 `model_name`。

```yaml
llm:
  default_model_preset_id: openai_reasoning_default

  model_presets:
    openai_reasoning_default:
      display_name: OpenAI Balanced
      provider_id: openai_official
      model_name: "<openai-real-model-name>"
      temperature: 0.2
      max_tokens: 800
      reasoning_effort: medium
      timeout_seconds: 30
      max_retries: 2

    claude_table_reader:
      display_name: Claude Table Reader
      provider_id: anthropic_official
      model_name: "<anthropic-real-model-name>"
      temperature: 0.2
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2

    gemini_fast:
      display_name: Gemini Fast
      provider_id: gemini_official
      model_name: "<gemini-real-model-name>"
      temperature: 0.3
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2

    deepseek_budget:
      display_name: DeepSeek Budget
      provider_id: deepseek_official
      model_name: "<deepseek-real-model-name>"
      temperature: 0.3
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2

    openrouter_model:
      display_name: OpenRouter Model
      provider_id: openrouter
      model_name: provider/model-name
      temperature: 0.3
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2
      extra:
        top_p: 0.9
```

说明：
- `model_name` 是外部服务的真实模型名，不在代码里硬编码
- `id` 是后台对象标识，不传给模型服务
- `display_name` 用于后台和 CLI 展示，不参与模型解析
- `extra` 透传给对应 LangChain 构造器或调用参数，但必须做 allowlist，避免误传危险字段
- `reasoning_effort` 属于 provider-aware 字段，不是所有 provider 都支持；不支持时必须在模型预设测试中暴露或忽略并记录
- 不建议把“最新模型”写死进代码，真实模型名应完全由后台配置控制

### 3.3 AI Player Preset 配置

`AIPlayerPreset` 是 CLI 创建房间时可选择的 AI 玩家模板。

```yaml
llm:
  ai_player_presets:
    cautious_dealer:
      display_name: Cautious Dealer
      enabled: true
      model_preset_id: openai_reasoning_default
      persona_prompt: "You are a careful Buckshot Roulette player."
      strategy_prompt: "Prefer information-gathering items before high-risk shots."
      chat_enabled: true
      chat_prompt: "Keep table talk short, in character, and never reveal hidden information."
      chat_trigger_mode: mention
      chat_model_preset_id: null
      chat_max_chars: 160
      chat_cooldown_seconds: 5
      max_item_actions_per_turn: 8
      max_parse_failures_per_turn: 2
      max_illegal_actions_per_turn: 2
      fallback_policy: conservative_shot

    aggressive_dealer:
      display_name: Aggressive Dealer
      enabled: true
      model_preset_id: deepseek_budget
      persona_prompt: "You are an aggressive Buckshot Roulette player."
      strategy_prompt: "Prefer pressure and damage when the visible risk is acceptable."
      max_item_actions_per_turn: 6
      fallback_policy: attack_lowest_hp
```

规则：
- 普通 CLI 用户只能选择 `enabled=true` 的 AI 玩家预设
- CLI 不接收 provider、API Key、base URL 等后台字段
- 房间添加 AI 玩家时保存 `AIPlayerPreset` 与 `ModelPreset` 的快照
- 快照包含 `preset_id`、`preset_version`、`model_name`、模型参数、persona、strategy、聊天配置和行动上限
- 后台编辑预设只影响之后新建的 AI 玩家，不影响正在进行的房间

聊天配置规则：
- `chat_enabled=false` 时，AI 不响应聊天，只参与游戏行动决策。
- `chat_trigger_mode=mention` 表示只有玩家使用 `@AI名` 或 `@all` 明确点名时才触发 AI 回复；不建议默认响应所有聊天，避免刷屏、额外成本和提示注入。
- `chat_prompt` 只用于聊天回复，不进入行动决策提示。
- `chat_model_preset_id=null` 表示聊天复用 `model_preset_id`。如果需要“强模型决策、便宜模型聊天”，可以单独指定聊天模型预设。
- 聊天回复必须有长度限制、冷却时间和并发保护；同一个 AI 同一时刻只处理一个聊天请求。

### 3.4 运行时选择

首版运行时不让 CLI 直接选择模型。CLI 只选择 AI 玩家预设，模型来源于该 AI 玩家预设引用的 `ModelPreset`。

运行时链路：

```text
CLI 选择 ai_player_preset_id
  -> 后端读取 AIPlayerPreset
  -> 后端读取 AIPlayerPreset.model_preset_id 对应的 ModelPreset
  -> 如果 chat_model_preset_id 非空，后端同时读取聊天模型预设
  -> 创建 RoomPlayer.ai_preset_snapshot
  -> AI 回合从快照创建决策模型客户端
  -> AI 聊天从快照创建聊天模型客户端
```

`llm.default_model_preset_id` 只作为后台创建新 AI 玩家预设时的默认填充值，不作为房间对局中的隐式 fallback。首版要求每个启用的 `AIPlayerPreset` 都必须显式绑定 `model_preset_id`。

CLI 可提供：

```bash
python main.py ai list
python main.py room create --ai cautious_dealer
python main.py room add-ai cautious_dealer
```

后台管理可提供：

```bash
python main.py admin llm provider list
python main.py admin llm model-preset test openai_reasoning_default
python main.py admin ai-preset list
```

## 4. 调用流程

### 4.1 架构

```text
RoomService / TurnCoordinator
  -> AIPlayerController
    -> LLMDecisionService
      -> PresetSnapshotResolver
      -> LangChainModelFactory
      -> OutputParser / ActionValidator
```

职责：

| 模块 | 职责 |
|---|---|
| `TurnCoordinator` | 串行推进房间回合；轮到 AI 玩家时触发 AI 控制器 |
| `AIPlayerController` | 读取房间内 AI 玩家预设快照，发起决策请求 |
| `LLMDecisionService` | 拼装行动决策提示词、调用模型、解析单步行动、执行反馈循环、重试 |
| `LLMChatService` | 拼装聊天回复提示词、调用模型、解析短文本回复、限流和兜底 |
| `PresetSnapshotResolver` | 从 `RoomPlayer.ai_preset_snapshot` 获取模型参数、persona、strategy 和行动上限 |
| `LangChainModelFactory` | 按快照中的 provider/protocol/model_name 创建 LangChain chat model |
| `OutputParser` | 将模型输出解析成一个结构化行动 |
| `ActionValidator` | 用当前游戏规则校验行动是否合法 |

LLM API 层不暴露给模型调用；它是后端内部服务。模型不能直接调用房间 HTTP API。

LLM 调用按用途分为两类：

| 调用类型 | 触发时机 | 输入 | 输出 |
|---|---|---|---|
| `action_decision` | 轮到 AI 行动 | 游戏规则提示、AI 决策策略、公开游戏事件、当前可见局面 | 一个结构化行动 |
| `chat_reply` | 玩家明确点名 AI 聊天 | AI 聊天提示、最近聊天消息、必要的公开局面摘要 | 一段短聊天文本 |

两类调用必须分开构造上下文和输出 schema。行动决策不能输出聊天文本；聊天回复不能输出或提交游戏行动。

### 4.2 行动决策输入给 LLM 的信息

行动决策 LLM 接收三类上下文：初始信息记忆、行动事件列表、当前可见信息。不接收隐藏弹序，也不接收聊天消息。

核心要求：上下文应接近人类玩家接收的信息模式。系统不应额外整理大量推理统计给模型，而应提供真实发生过的公开游戏信息和当前面板信息，让模型自己从历史事件中推断玩家水平、倾向和可能的下一步行为。

AI 玩家预设中的 `persona_prompt` 和 `strategy_prompt` 可以作为系统提示词的一部分。`ModelPreset` 的 provider、base URL、API Key、后台对象完整配置不能进入模型上下文。

聊天消息默认不进入行动决策上下文。原因：
- 聊天内容不属于游戏规则、公开局面或行动事件，容易引入提示注入。
- AI 玩家强弱应由模型能力、决策策略提示和可见局面推理能力决定，而不是被玩家聊天内容临时改变。
- 如果未来要支持“读聊天进行心理博弈”的 AI，应作为显式策略开关，而不是默认行为。

每次模型调用的输入结构：

```json
{
  "initial_info_memory": {
    "game_id": "room-1-game-7",
    "players": [
      {"player_id": 0, "name": "Alice", "type": "human"},
      {"player_id": 1, "name": "Bot", "type": "ai"}
    ],
    "match_initializations": [
      {
        "match_index": 0,
        "initial_hp": 4,
        "turn_order": [0, 1, 2],
        "enabled_items": ["JAMMER", "HAND_SAW", "MAGNIFYING_GLASS"]
      }
    ]
  },
  "action_event_list": [
    {
      "event_id": 18,
      "match_index": 0,
      "reload_round": 2,
      "turn_index": 7,
      "actor_player_id": 0,
      "event_type": "shoot_self",
      "payload": {
        "shell": "BLANK",
        "actor_hp_after": 3,
        "turn_retained": true
      }
    }
  ],
  "current_visible_state": {
    "match_index": 0,
    "reload_round": 2,
    "current_player_id": 1,
    "turn_direction": 1,
    "players": [
      {"player_id": 0, "hp": 3, "alive": true, "items": ["BEER"]},
      {"player_id": 1, "hp": 4, "alive": true, "items": ["MAGNIFYING_GLASS", "HAND_SAW"]}
    ],
    "legal_actions": [
      {"type": "use_item", "item": "MAGNIFYING_GLASS"},
      {"type": "shoot_self"},
      {"type": "shoot_player", "target_player_id": 0}
    ]
  }
}
```

三段输入含义：

| 字段 | 内容 |
|---|---|
| `initial_info_memory` | 比赛和每局游戏初始化信息，例如玩家、初始血量、回合顺序、启用道具 |
| `action_event_list` | 每局游戏、每轮装弹、每次回合中的每个公开行动决策与对应结果；不包含 `chat_message` |
| `current_visible_state` | 当前人类玩家也能看到的面板信息，例如每个玩家血量、每个玩家当前持有的可见道具、当前行动权、合法行动；用于决策时应去掉聊天事件列表 |

不输入：
- 未公开的完整弹匣顺序
- 其他玩家不可见的内部调试状态
- 服务端额外推导出的胜率、概率建议、玩家画像结论
- 玩家聊天消息，除非该 AI 预设显式启用“聊天影响决策”策略
- API Key、服务端配置、系统内部路径

### 4.3 行动事件列表

服务端需要维护 `action_event_list`，记录整场比赛内所有玩家可见的事件。该日志跨 reload round 和 match 保留，直到一场比赛结束后归档；事件通过 `match_index` 和 `reload_round` 区分阶段。

事件建议结构：

```json
{
  "event_id": 42,
  "match_index": 1,
  "reload_round": 3,
  "turn_index": 17,
  "actor_player_id": 2,
  "event_type": "shoot_player",
  "payload": {
    "target_player_id": 0,
    "shell": "LIVE",
    "damage": 2,
    "target_hp_after": 1
  }
}
```

事件类型至少包括：

| event_type | 说明 |
|---|---|
| `match_started` | 一局游戏开始、玩家初始血量 |
| `reload_started` | 新一轮装弹，公开 LIVE/BLANK 数量 |
| `items_dealt` | 玩家获得公开道具信息 |
| `turn_started` | 某玩家获得行动权 |
| `use_item` | 玩家使用道具 |
| `item_result` | 道具结果，例如放大镜看到的当前弹、手机看到的未来弹、啤酒弹出的弹。只对某玩家可见的结果需限制可见性 |
| `shoot_self` | 玩家射自己及结果 |
| `shoot_player` | 玩家射其他玩家及结果 |
| `turn_skipped` | 干扰器跳过回合 |
| `player_eliminated` | 玩家出局 |
| `reload_ended` | 当前弹匣耗尽 |
| `match_ended` | 一局游戏结束 |

可见性规则：
- 公开发生的动作都进日志
- 公开结果进日志，例如开枪结果、啤酒弹出类型、装弹数量分布
- `chat_message` 可以进入房间事件日志，但默认不进入 `action_event_list`
- 只对某玩家可见的结果需要标记 `visible_to`
- 给 AI 构造上下文时，只传入该 AI 玩家可见的事件

单个上下文过长时，不要直接用概率统计替代事件。建议分两层：
- `action_event_list`：最近 N 条完整事件，必须保真
- `compressed_event_memory`：较早事件的事实性压缩记忆，只复述发生过的动作和结果，不给策略建议或玩家画像结论

### 4.4 单步决策循环

LLM 每次只能输出一个行动。一次 LLM 调用结束不等于当前 AI 玩家回合结束。

AI 是否继续决策，不能由 `action.type` 直接判断，必须由游戏引擎执行后的结果决定。原因：
- `shoot_self` 打出 BLANK 时会保留当前玩家行动权，AI 需要继续决策
- `shoot_self` 打出 LIVE 时通常切换到下一玩家，AI 当前控制循环结束
- `shoot_player` 无论 LIVE/BLANK 通常切换到下一玩家
- 多数 `use_item` 不消耗回合，AI 需要继续决策
- `use_item` 中的 BEER 如果退掉最后一发子弹，会结束当前 Reload Round，且不保留当前玩家行动权

每个行动的统一流程：
1. 服务端校验行动是否合法
2. 游戏引擎立即执行行动
3. 服务端把行动结果写入 `action_event_list`
4. 服务端根据游戏引擎返回的 `match_over`、`reload_round_ended`、`current_player_id` 等状态判断是否继续请求模型
5. 如果执行后仍是同一个 AI 玩家持有行动权，服务端将最新结果和更新后的合法行动列表再次传给 AI

伪流程：

```text
while current_player is AI and match not over:
  context = build_visible_context(current_player)
  decision = call_llm_for_one_action(context)
  action = parse_and_validate(decision)

  result = engine.execute_action(action)
  append_visible_events(result)

  if result.match_over:
    break

  if result.reload_round_ended:
    engine.start_next_reload_round()
    append_visible_events(reload_result)

  if current_player is still same AI and match not over:
    continue

  break
```

为避免模型反复使用无意义道具导致卡死，需要设置硬限制：
- 单个 AI 连续道具行动上限，例如 `max_item_actions_per_turn = 8`
- 连续非法行动上限，例如 2 次
- 连续解析失败上限，例如 2 次
- 达到上限后执行保底开枪策略

### 4.5 输出格式

LLM 必须输出一个结构化对象，且一次只能包含一个行动。

建议 schema：

```json
{
  "thought_summary": "简短理由，不能包含隐藏信息",
  "action": {
    "type": "use_item",
    "item": "MAGNIFYING_GLASS"
  }
}
```

行动类型：

| type | 字段 |
|---|---|
| `shoot_self` | 无 |
| `shoot_player` | `target_player_id` |
| `use_item` | `item`、可选 `target_player_id`、可选 `target_item_index` |

规则：
- 每次响应只能有一个 `action`
- 行动执行后是否继续请求 AI，必须根据游戏引擎执行结果判断，不能只根据行动类型判断
- `use_item` 通常不结束当前 AI 控制循环，但 BEER 退掉最后一发子弹等特殊情况可能导致行动权切换
- `shoot_self` 打出 BLANK 会保留行动权，必须把开枪结果反馈给 AI 再请求下一步
- `shoot_self` 打出 LIVE 或 `shoot_player` 后通常切换行动权，当前 AI 控制循环结束
- 服务端必须验证行动合法性，非法动作不能进入游戏引擎
- 解析失败或非法动作时，最多向同一模型重试 1 次；仍失败则使用内置保底策略

### 4.6 结构化输出策略

优先使用 LangChain 的 structured output 能力：

```python
model.with_structured_output(SingleActionDecision)
```

但不同 provider 对工具调用、JSON mode、structured output 的支持不完全一致，所以实现上需要降级路径：

1. `with_structured_output(PydanticModel)`
2. JSON mode / tool calling
3. 普通文本 + JSON 解析器
4. 失败后使用保底策略

保底策略示例：
- 如果当前弹更可能是 BLANK，优先射自己
- 如果当前弹更可能是 LIVE，优先射血量最低的对手
- 达到道具行动上限或连续错误上限时，保底策略必须选择开枪，不能继续使用道具

### 4.7 AI 聊天调用

AI 聊天是独立于行动决策的 LLM 调用。聊天不会推进游戏规则，不会提交行动，也不改变 `GameState.revision`；它只追加 `chat_message` 事件并推送给房间内玩家。

触发规则：
- 玩家发送普通聊天时，后端只记录并广播聊天事件。
- 只有消息明确点名 AI，例如 `@DeepSeekV4Pro 你怎么看？`，或使用 `@all`，才触发对应 AI 的聊天回复。
- AI 聊天必须受 `chat_enabled`、`chat_cooldown_seconds`、最大并发数和最大输出长度控制。
- 当前 AI 正在进行行动决策时，可以延迟或丢弃聊天请求，不能打断行动决策循环。

聊天输入结构示例：

```json
{
  "ai_profile": {
    "display_name": "DeepSeekV4Pro",
    "persona_prompt": "A deterministic fake player for local tests.",
    "chat_prompt": "Keep replies short and in character."
  },
  "trigger": {
    "message_id": 88,
    "from_player_id": 0,
    "from_name": "Alice",
    "message": "@DeepSeekV4Pro 你觉得现在谁优势？"
  },
  "chat_event_list": [
    {"event_id": 80, "player_id": 0, "name": "Alice", "message": "这轮有点危险。"},
    {"event_id": 88, "player_id": 0, "name": "Alice", "message": "@DeepSeekV4Pro 你觉得现在谁优势？"}
  ],
  "public_game_context": {
    "current_player_id": 1,
    "players": [
      {"player_id": 0, "name": "Alice", "hp": 2, "alive": true},
      {"player_id": 1, "name": "DeepSeekV4Pro", "hp": 3, "alive": true}
    ],
    "public_shell_counts": {"remaining": 4, "LIVE": 2, "BLANK": 2},
    "recent_game_events": [
      {"event_type": "shoot_player", "message": "Alice 对 DeepSeekV4Pro 开枪，是空包弹，没有造成伤害。"}
    ]
  }
}
```

聊天输入限制：
- `chat_event_list` 只包含聊天消息，数量有限，例如最近 20 条。
- `public_game_context` 只提供公开局面摘要和必要的最近公开游戏事件，不提供合法行动列表，不提供隐藏弹序，不提供私有道具结果。
- 聊天 prompt 必须要求模型不要给出隐藏信息、不要伪造游戏结果、不要返回游戏行动 JSON。

聊天输出 schema：

```json
{
  "reply": "还不好说，但你现在血量压力更大。"
}
```

服务端规则：
- 回复文本需要裁剪到 `chat_max_chars`。
- 空回复或解析失败时不追加 AI 聊天事件。
- AI 回复使用 `chat_message` 事件，`actor_player_id` 为 AI 座位号，payload 标记 `source: "ai"`。
- 聊天失败不能影响房间游戏流程。

## 5. Provider Factory 设计

### 5.1 创建逻辑

伪代码：

```python
def create_chat_model(model_preset: ModelPresetSnapshot) -> BaseChatModel:
    provider = resolve_provider(model_preset.provider_id)

    if provider.protocol == "openai_responses":
        return ChatOpenAI(
            model=model_preset.model_name,
            use_responses_api=True,
            api_key=get_secret(provider),
            temperature=model_preset.temperature,
            max_tokens=model_preset.max_tokens,
            timeout=model_preset.timeout_seconds,
            max_retries=model_preset.max_retries,
            **map_reasoning_effort(provider, model_preset.reasoning_effort),
            **model_preset.extra,
        )

    if provider.protocol == "anthropic":
        return ChatAnthropic(...)

    if provider.protocol == "gemini":
        return ChatGoogleGenerativeAI(...)

    if provider.protocol == "deepseek":
        return ChatDeepSeek(...)

    if provider.protocol == "openai_chat_completions":
        return ChatOpenAI(
            model=model_preset.model_name,
            base_url=provider.base_url,
            api_key=get_secret(provider),
            ...
        )

    if provider.protocol == "custom_langchain":
        return load_custom_langchain_model(provider, model_preset)
```

### 5.2 自定义 LangChain Provider

`custom_langchain` 用于接入未内置支持的 provider。

配置示例：

```yaml
providers:
  my_provider:
    type: third_party
    protocol: custom_langchain
    class_path: my_project.llm.MyChatModel
    api_key_env: MY_PROVIDER_API_KEY
    kwargs:
      endpoint: https://api.example.com
```

限制：
- `class_path` 只允许从项目白名单模块加载
- 不允许从用户输入任意 import
- 自定义类必须实现 LangChain `BaseChatModel` 兼容接口

## 6. 后台管理 API

后台管理只给管理员使用。普通 CLI 用户只能读取已启用的 AI 玩家预设并添加到房间。

| 接口 | 职责 |
|---|---|
| `GET /admin/llm/providers` | 查看 provider 配置，API Key 必须脱敏 |
| `POST /admin/llm/providers` | 新增 provider |
| `PUT /admin/llm/providers/{provider_id}` | 修改 provider |
| `POST /admin/llm/providers/{provider_id}/test` | 测试 provider 基础连通性 |
| `GET /admin/llm/model-presets` | 查看模型预设 |
| `POST /admin/llm/model-presets` | 新增模型预设 |
| `PUT /admin/llm/model-presets/{preset_id}` | 修改模型预设并递增版本 |
| `POST /admin/llm/model-presets/{preset_id}/test` | 测试模型名、结构化输出、reasoning 参数 |
| `GET /admin/ai-player-presets` | 查看 AI 玩家预设 |
| `POST /admin/ai-player-presets` | 新增 AI 玩家预设 |
| `PUT /admin/ai-player-presets/{preset_id}` | 修改 AI 玩家预设并递增版本 |
| `POST /admin/ai-player-presets/{preset_id}/test-action` | 用 fake 或指定测试局面验证单步行动输出 |
| `GET /ai-player-presets` | 普通 CLI 获取已启用 AI 玩家预设 |

后台测试至少返回：
- provider 是否可达
- API Key 是否存在且可用
- `model_name` 是否有效
- structured output 是否可用
- reasoning/temperature/max_tokens 等参数是否被 provider 接受
- 单步行动 JSON 是否能解析和通过基础 schema 校验

## 7. 错误处理与重试

需要统一错误类型：

| 错误 | 处理 |
|---|---|
| API Key 缺失 | 启动/测试时提示配置错误 |
| Provider 不可达 | 记录错误，AI 玩家使用保底策略 |
| 模型不存在 | `model-preset test` 阶段暴露，房间运行中禁止静默切换 |
| 超时 | 按模型配置重试，失败后保底 |
| 速率限制 | 短退避重试，失败后保底 |
| 输出不可解析 | 追加“只输出 JSON”修复提示重试 1 次 |
| 非法行动 | 把合法行动列表反馈给模型重试 1 次 |

房间对局不能因为 LLM 调用失败而卡死。

## 8. 日志与安全

### 8.1 日志

必须记录：
- provider id
- model preset id/version
- ai player preset id/version
- model
- latency
- token usage（如果 provider 返回）
- 是否重试
- 是否触发保底策略

禁止记录：
- API Key
- 完整服务端配置
- 未公开的隐藏弹序

Prompt 和模型输出建议默认不落盘；如果需要调试日志，应提供显式开关：

```yaml
llm:
  debug_prompt_logging: false
```

### 8.2 API Key 管理

优先级：
1. 环境变量
2. `.env` 本地开发文件
3. 明文配置，仅允许开发环境

生产/公网服务器不允许把玩家提交的 API Key 存到普通配置文件。若后续支持“玩家自带 Key”，需要单独设计加密存储和权限边界。

### 8.3 权限边界

- 普通 CLI 用户不能读取 provider 完整配置
- 普通 CLI 用户不能提交 API Key、base URL、provider 协议
- 普通 CLI 用户只能选择已启用的 `AIPlayerPreset`
- 房间内保存预设快照，后台编辑不影响进行中的房间
- 日志和事件流不能泄露 API Key、完整 provider 配置和隐藏弹序

## 9. 测试需求

### 9.1 配置测试

```bash
python main.py admin llm provider list
python main.py admin llm validate
python main.py admin llm model-preset test openai_reasoning_default
python main.py admin ai-preset test-action cautious_dealer
```

`model-preset test` 只发送一个极短请求，例如：

```text
Return exactly: OK
```

并验证：
- provider 可创建
- API Key 可用
- 模型名有效
- 响应可返回文本
- structured output 能力是否可用

### 9.2 单元测试

需要覆盖：
- AI 玩家预设选择和快照生成
- ModelPreset 版本递增和快照冻结
- provider 配置校验
- API Key 脱敏
- 官方 provider factory
- OpenAI-compatible provider factory
- reasoning_effort provider-aware 映射
- 单步 LLM 输出解析
- `action_event_list` 事件追加和可见性过滤
- `initial_info_memory` 与 `current_visible_state` 上下文构造
- 道具使用后结果反馈并再次请求模型
- 射自己空弹后仍保留行动权并再次请求模型
- 非法行动修复/保底策略

### 9.3 集成测试

集成测试不应默认调用真实 API。使用 fake LangChain chat model 模拟：
- 正常 JSON 输出
- 非 JSON 输出
- 超时
- 速率限制
- 返回非法动作
- 连续返回道具行动直到选择开枪
- 道具行动达到上限后触发保底开枪
- CLI 添加 AI 玩家预设到房间
- 轮到 AI 玩家时由 `TurnCoordinator` 自动触发决策
- 后台修改预设后，进行中的房间仍使用旧快照
- AI 决策请求过期或房间关闭时，结果不能落入游戏状态

真实 API 测试用环境变量显式启用：

```bash
RUN_LLM_API_TESTS=1 pytest tests/integration/test_llm_providers.py
```

## 10. 建议的实现顺序

1. 定义 `ProviderConfig`、`ModelPreset`、`AIPlayerPreset`、快照数据模型
2. 实现后台配置加载和基础管理 API
3. 实现 `LangChainModelFactory`
4. 实现 `model-preset test` 和 `ai-preset test-action`
5. 实现 `initial_info_memory`、`action_event_list`、`current_visible_state` 上下文构造
6. 实现 fake model 和单步输出解析测试
7. 实现 `LLMDecisionService` 的单步反馈循环
8. 接入 `TurnCoordinator`，轮到 AI 玩家时自动行动
9. 增加 CLI：`ai list`、`room create --ai`、`room add-ai`
10. 最后接真实官方 provider 的集成测试

## 11. 参考资料

- LangChain chat model 统一入口：<https://reference.langchain.com/python/langchain/chat_models>
- LangChain provider/model 概览：<https://docs.langchain.com/oss/python/langchain-models>
- LangChain ChatOpenAI：<https://docs.langchain.com/oss/python/integrations/chat/openai>
- OpenAI Responses vs Chat Completions：<https://platform.openai.com/docs/guides/responses-vs-chat-completions>
- OpenAI Function Calling：<https://platform.openai.com/docs/guides/function-calling>
- OpenAI Responses API：<https://platform.openai.com/docs/api-reference/responses>
- OpenAI Chat Completions API：<https://platform.openai.com/docs/api-reference/chat>
- LangChain ChatAnthropic：<https://docs.langchain.com/oss/python/integrations/chat/anthropic>
- LangChain ChatGoogleGenerativeAI：<https://reference.langchain.com/python/langchain-google-genai/chat_models/ChatGoogleGenerativeAI>
- LangChain ChatDeepSeek：<https://docs.langchain.com/oss/python/integrations/chat/deepseek>
- OpenAI 模型与 API：<https://developers.openai.com/api/docs/models/compare>
- Claude API 概览：<https://platform.claude.com/docs/claude/reference/overview>
- Gemini API Quickstart：<https://ai.google.dev/gemini-api/docs/quickstart>
- DeepSeek API Quickstart：<https://api-docs.deepseek.com/>
