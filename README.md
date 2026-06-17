# Buckshot Roulette CLI

恶魔轮盘赌的 Python 实现。当前仓库已包含核心游戏引擎和内存版后端房间 MVP，后续会扩展联机 CLI 客户端和 LLM AI 玩家。

## 当前状态

- **游戏引擎**：已实现核心规则、道具、装弹、回合切换、三场比赛流程。
- **后端房间 MVP**：已实现创建房间、搜索公开房间、输入房间号加入、准备、开始、提交行动、WebSocket 事件推送和聊天事件。
- **LLM AI 玩家**：设计中，目标是通过后台配置 provider、模型预设和 AI 玩家预设，再由 CLI 选择 AI 玩家加入房间。

## 技术栈

- Python 3.14+
- 标准库 `unittest`
- 后端计划使用 FastAPI + HTTP + WebSocket/SSE
- LLM 计划通过 LangChain 接入 OpenAI、Anthropic、Gemini、DeepSeek 和第三方兼容服务

## 文档

- [游戏引擎设计](docs/游戏引擎设计.md)：核心规则、领域模型和 `GameEngine` 边界。
- [后端架构设计](docs/后端架构设计.md)：房间管理、HTTP API、事件推送、CLI 入口和 AI 玩家调度。
- [LLM API 需求设计](docs/LLMAPI需求设计.md)：provider、模型预设、AI 玩家预设、结构化输出和保底策略。

## 开发

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## 启动后端

```bash
python main.py
```

默认监听 `http://127.0.0.1:8000`。API 文档可访问 `http://127.0.0.1:8000/docs`。

当前后端是内存版 MVP，重启后房间和对局会清空。

## 架构原则

- `GameEngine` 只处理游戏规则，不依赖 HTTP、CLI、LLM。
- 联机模式下，权威 `GameState` 只存在于后端。
- CLI 是客户端入口，负责展示状态和提交玩家意图。
- LLM 只作为服务端内部 AI 玩家决策器，模型输出必须经过后端校验后才能进入游戏引擎。
