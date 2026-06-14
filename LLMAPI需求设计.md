# LLM API 需求设计

## 1. 目标

为恶魔轮盘 CLI/后端提供统一的 LLM 调用层，使 AI 玩家可以通过 LangChain 调用不同模型服务。

必须支持：
- 官方模型服务：OpenAI/ChatGPT、Anthropic/Claude、Google Gemini、DeepSeek
- 第三方模型服务：通过配置填写服务地址、API Key、协议、模型名和额外参数
- 模型选择：支持全局默认模型、房间默认模型、单个 AI 玩家模型
- 稳定输出：LLM 必须返回可校验的游戏行动，不能直接信任自然语言结果

不在本阶段处理：
- 后端房间/玩家接入完整设计
- 模型计费系统
- RAG、长期记忆、复杂 Agent 工具链
- 本地模型推理服务部署

## 2. 设计原则

### 2.1 Provider 与模型选择解耦

业务层直接使用外部服务的真实 `model` 字符串，不再额外套一层自定义模型别名。

业务层仍然不直接写 provider、API Key、base URL 等调用细节。真实模型名如何映射到 provider 和协议，由 LLM API 层解析。

示例：

```yaml
ai_players:
  dealer_bot:
    model: gpt-5.5
  risk_bot:
    model: "<anthropic-real-model-name>"
```

实际调用配置由 LLM API 层解析：

```yaml
models:
  gpt-5.5:
    provider_id: openai_official
    temperature: 0.3
    max_tokens: 800
```

这样游戏逻辑只关心“这个 AI 用哪个真实模型”，不会关心 provider 的认证、协议和 SDK 创建细节。如果多个 provider 暴露了相同模型字符串，配置加载阶段应要求显式指定 provider 或拒绝该歧义。

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

这不是永久砍掉其他协议，而是避免把“全兼容”写成无法验证的承诺。不同 provider 对 structured output、函数调用、内置工具、流式格式、错误码、token usage、重试语义的支持差异很大。配置层可以预留 `openai_responses` 第三方兼容服务和 `anthropic_messages` 第三方兼容服务，但必须通过 `llm test` 标记实际能力，不能只因为 URL 兼容就默认完全兼容。

## 3. 配置设计

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

### 3.2 Model 配置

`models` 使用真实模型名作为 key，表示某个模型的调用配置。

```yaml
llm:
  default_model: gpt-5.5

  models:
    gpt-5.5:
      display_name: GPT-5.5
      provider_id: openai_official
      temperature: 0.2
      max_tokens: 800
      timeout_seconds: 30
      max_retries: 2

    "<anthropic-real-model-name>":
      display_name: Claude
      provider_id: anthropic_official
      temperature: 0.2
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2

    "<gemini-real-model-name>":
      display_name: Gemini
      provider_id: gemini_official
      temperature: 0.3
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2

    "<deepseek-real-model-name>":
      display_name: DeepSeek
      provider_id: deepseek_official
      temperature: 0.3
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2

    "provider/model-name":
      display_name: Third Party Model
      provider_id: openrouter
      temperature: 0.3
      max_tokens: 1000
      timeout_seconds: 45
      max_retries: 2
      extra:
        top_p: 0.9
```

说明：
- `models` 的 key 就是外部服务的真实模型名，不再使用二次别名
- `display_name` 可选，仅用于 CLI 展示，不参与模型解析
- `extra` 透传给对应 LangChain 构造器或调用参数，但必须做 allowlist，避免误传危险字段
- 不建议把“最新模型”写死进代码，模型名应完全由配置控制

### 3.3 运行时选择

支持三层覆盖：

1. 全局默认：`llm.default_model`
2. 房间默认：创建房间时指定 `room.llm_model`
3. AI 玩家指定：创建 AI 玩家时指定 `player.llm_model`

优先级：

```text
player.llm_model > room.llm_model > llm.default_model
```

CLI 可提供：

```bash
python main.py llm list
python main.py llm test gpt-5.5
python main.py room create --ai dealer_bot=gpt-5.5
python main.py room create --default-llm gpt-5.5
```

## 4. 调用流程

### 4.1 架构

```text
Game Engine
  -> AIPlayerController
    -> LLMDecisionService
      -> ModelResolver
      -> LangChainModelFactory
      -> OutputParser / ActionValidator
```

职责：

| 模块 | 职责 |
|---|---|
| `AIPlayerController` | 在 AI 玩家回合发起决策请求 |
| `LLMDecisionService` | 拼装提示词、调用模型、解析单步行动、执行反馈循环、重试 |
| `ModelResolver` | 根据玩家/房间/全局配置选择真实模型名，并解析到 provider 配置 |
| `LangChainModelFactory` | 按 provider/protocol 创建 LangChain chat model |
| `OutputParser` | 将模型输出解析成一个结构化行动 |
| `ActionValidator` | 用当前游戏规则校验行动是否合法 |

### 4.2 输入给 LLM 的信息

LLM 接收三类上下文：初始信息记忆、行动事件列表、当前可见信息。不接收隐藏弹序。

核心要求：上下文应接近人类玩家接收的信息模式。系统不应额外整理大量推理统计给模型，而应提供真实发生过的公开信息和当前面板信息，让模型自己从历史事件中推断玩家水平、倾向、动机和可能的下一步行为。

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
| `initial_info_memory` | 游戏和每场比赛初始化信息，例如玩家、初始血量、回合顺序、启用道具 |
| `action_event_list` | 每场比赛、每轮装弹、每次回合中的每个公开行动决策与对应结果 |
| `current_visible_state` | 当前人类玩家也能看到的面板信息，例如每个玩家血量、每个玩家当前持有的可见道具、当前行动权、合法行动 |

不输入：
- 未公开的完整弹匣顺序
- 其他玩家不可见的内部调试状态
- 服务端额外推导出的胜率、概率建议、玩家画像结论
- API Key、服务端配置、系统内部路径

### 4.3 行动事件列表

服务端需要维护 `action_event_list`，记录整局游戏内所有玩家可见的事件。该日志跨 reload round 和 match 保留，直到一局游戏结束后归档；事件通过 `match_index` 和 `reload_round` 区分阶段。

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
| `match_started` | 比赛开始、玩家初始血量 |
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
| `match_ended` | 比赛结束 |

可见性规则：
- 公开发生的动作都进日志
- 公开结果进日志，例如开枪结果、啤酒弹出类型、装弹数量分布
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

## 5. Provider Factory 设计

### 5.1 创建逻辑

伪代码：

```python
def create_chat_model(model_name: str) -> BaseChatModel:
    model_config = resolve_model(model_name)
    provider = resolve_provider(model_config.provider_id)

    if provider.protocol == "openai_responses":
        return ChatOpenAI(
            model=model_name,
            use_responses_api=True,
            api_key=get_secret(provider),
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            timeout=model_config.timeout_seconds,
            max_retries=model_config.max_retries,
            **model_config.extra,
        )

    if provider.protocol == "anthropic":
        return ChatAnthropic(...)

    if provider.protocol == "gemini":
        return ChatGoogleGenerativeAI(...)

    if provider.protocol == "deepseek":
        return ChatDeepSeek(...)

    if provider.protocol == "openai_chat_completions":
        return ChatOpenAI(
            model=model_name,
            base_url=provider.base_url,
            api_key=get_secret(provider),
            ...
        )

    if provider.protocol == "custom_langchain":
        return load_custom_langchain_model(provider, model_name, model_config)
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

## 6. 错误处理与重试

需要统一错误类型：

| 错误 | 处理 |
|---|---|
| API Key 缺失 | 启动/测试时提示配置错误 |
| Provider 不可达 | 记录错误，AI 玩家使用保底策略 |
| 模型不存在 | `llm test` 阶段暴露，房间运行中禁止静默切换 |
| 超时 | 按模型配置重试，失败后保底 |
| 速率限制 | 短退避重试，失败后保底 |
| 输出不可解析 | 追加“只输出 JSON”修复提示重试 1 次 |
| 非法行动 | 把合法行动列表反馈给模型重试 1 次 |

房间对局不能因为 LLM 调用失败而卡死。

## 7. 日志与安全

### 7.1 日志

必须记录：
- provider id
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

### 7.2 API Key 管理

优先级：
1. 环境变量
2. `.env` 本地开发文件
3. 明文配置，仅允许开发环境

生产/公网服务器不允许把玩家提交的 API Key 存到普通配置文件。若后续支持“玩家自带 Key”，需要单独设计加密存储和权限边界。

## 8. 测试需求

### 8.1 配置测试

```bash
python main.py llm list
python main.py llm validate
python main.py llm test gpt-5.5
```

`llm test` 只发送一个极短请求，例如：

```text
Return exactly: OK
```

并验证：
- provider 可创建
- API Key 可用
- 模型名有效
- 响应可返回文本
- structured output 能力是否可用

### 8.2 单元测试

需要覆盖：
- 模型选择优先级
- provider 配置校验
- API Key 脱敏
- 官方 provider factory
- OpenAI-compatible provider factory
- 单步 LLM 输出解析
- `action_event_list` 事件追加和可见性过滤
- `initial_info_memory` 与 `current_visible_state` 上下文构造
- 道具使用后结果反馈并再次请求模型
- 射自己空弹后仍保留行动权并再次请求模型
- 非法行动修复/保底策略

### 8.3 集成测试

集成测试不应默认调用真实 API。使用 fake LangChain chat model 模拟：
- 正常 JSON 输出
- 非 JSON 输出
- 超时
- 速率限制
- 返回非法动作
- 连续返回道具行动直到选择开枪
- 道具行动达到上限后触发保底开枪

真实 API 测试用环境变量显式启用：

```bash
RUN_LLM_API_TESTS=1 pytest tests/integration/test_llm_providers.py
```

## 9. 建议的实现顺序

1. 定义 `llm_config` 数据模型和配置加载
2. 实现 `ModelResolver`
3. 实现 `LangChainModelFactory`
4. 实现 `initial_info_memory`、`action_event_list`、`current_visible_state` 上下文构造
5. 实现 fake model 和单步输出解析测试
6. 实现 `LLMDecisionService` 的单步反馈循环
7. 接入 AI 玩家回合
8. 增加 CLI：`llm list`、`llm validate`、`llm test`
9. 最后接真实官方 provider 的集成测试

## 10. 参考资料

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
