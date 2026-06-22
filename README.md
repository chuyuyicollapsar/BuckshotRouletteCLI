# Buckshot Roulette CLI

恶魔轮盘赌的 Python 实现。当前仓库已包含核心游戏引擎、内存版后端房间 MVP 和 CLI 客户端 MVP，后续会扩展 LLM AI 玩家。

## 当前状态

- **游戏引擎**：已实现核心规则、道具、装弹、回合切换、三场比赛流程。
- **后端房间 MVP**：已实现创建房间、搜索公开房间、输入房间号加入、准备、开始、提交行动、WebSocket 事件推送和聊天事件。
- **CLI 客户端 MVP**：已实现薄 CLI 客户端、事件渲染和用户操作指令。
- **LLM AI 玩家**：已实现 provider、模型预设、AI 玩家预设的文件持久化管理 API，支持 fake AI 预设测试、房间添加 AI 玩家和服务端自动 AI 回合控制。

## 技术栈

- Python 3.14+
- 标准库 `unittest`
- 后端使用 FastAPI + HTTP + WebSocket/SSE
- LLM 通过 LangChain 接入 OpenAI、Anthropic、Gemini、DeepSeek 和第三方兼容服务

## 文档

- [游戏引擎设计](docs/游戏引擎设计.md)：核心规则、领域模型和 `GameEngine` 边界。
- [后端架构设计](docs/后端架构设计.md)：房间管理、HTTP API、事件推送、CLI 入口和 AI 玩家调度。
- [LLM API 需求设计](docs/LLMAPI需求设计.md)：provider、模型预设、AI 玩家预设、结构化输出和保底策略。
- [部署指南](docs/部署指南.md)：服务端 Docker、客户端独立程序、镜像分发和升级流程。

## 开发

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```

也可以用可编辑安装获得独立的服务端和客户端命令：

```bash
python -m pip install -e .
```

## 启动后端

```bash
buckshot-server
```

默认监听 `http://127.0.0.1:8000`。API 文档可访问 `http://127.0.0.1:8000/docs`。
源码运行时也可以使用 `python main.py` 或 `python -m buckshot_roulette.server`。

当前房间和对局是内存版 MVP，重启后会清空；LLM/API 配置会写入本地配置文件。

WebSocket 事件推送需要安装 `uvicorn[standard]` 或等价的 WebSocket 协议依赖。

## 启动 CLI 客户端

```bash
buckshot-client --server http://127.0.0.1:8000 --name Alice
```

CLI 是薄客户端：通过 HTTP 管理房间和提交行动，通过 WebSocket 接收房间事件、可见状态和聊天消息。
源码运行时也可以使用 `python -m buckshot_roulette.cli --server http://127.0.0.1:8000 --name Alice`。

## LLM / AI 预设 API

当前提供后台管理和一个默认 fake AI：

```bash
GET  /ai-player-presets
GET  /admin/llm/providers
POST /admin/llm/providers
GET  /admin/llm/model-presets
POST /admin/llm/model-presets
GET  /admin/ai-player-presets
POST /admin/ai-player-presets
POST /admin/ai-player-presets/fake_cautious/test-action
POST /rooms/{room_code}/ai-players
```

真实 LangChain provider 使用可选依赖懒加载。需要哪个 provider 就安装对应包：

```bash
python -m pip install langchain-openai
python -m pip install langchain-anthropic
python -m pip install langchain-google-genai
python -m pip install langchain-deepseek
```

`model-preset test` 会检查 API Key、provider 依赖和模型构造。默认 `fake_local` 用于本地流程测试，不调用外部网络。

LLM/API 配置会保存到 `llm_config.json`。默认位置：

- Windows：`%APPDATA%\BuckshotRoulette\llm_config.json`
- Linux/macOS：`$XDG_CONFIG_HOME/buckshot-roulette/llm_config.json`，未设置时使用 `~/.config/buckshot-roulette/llm_config.json`

可以用 `BUCKSHOT_LLM_CONFIG_FILE` 指定完整配置文件路径，或用 `BUCKSHOT_DATA_DIR` 指定配置目录。真实 API Key 推荐通过 `api_key_env` 引用环境变量；`api_key` 明文写入配置文件，只建议本地开发使用。

配置 provider、model preset 和 AI player preset 的标准脚本模板见 `scripts/config_llm_presets.ps1`。

AI 玩家不走 CLI/HTTP 行动协议。轮到 AI 时，服务端会构造该 AI 可见状态、请求单步决策、复用后端行动校验并写入事件日志；如果 AI 返回非法行动或 provider 失败，会使用保底开枪策略。

## 构建与使用

### 服务端 Docker

#### 本地启动

本地有项目源码时，打开 Docker Desktop 后，在项目根目录执行：

```bash
docker compose up -d --build
```

这会构建服务端镜像并启动容器：

```text
image:     buckshot-roulette-server:0.1.0
container: buckshot-roulette-server
port:      127.0.0.1:8000
```

验证服务：

```bash
curl http://127.0.0.1:8000/health
```

停止服务：

```bash
docker compose down
```

#### Docker Desktop 管理

容器启动后，可以在 Docker Desktop 的 Containers 页面管理 `buckshot-roulette-server`，包括 Start、Stop、Restart 和查看日志。

如果容器已经创建好，后续普通启动/停止可以直接用 Docker Desktop，不需要每次重新输入 `docker run` 参数。新增 provider 依赖时需要重新构建镜像；只新增 API Key 环境变量时，重新创建容器即可。

#### 真实 LLM provider

如果需要真实 LLM provider，可以复制 `.env.example` 为 `.env`，填写构建 extras 和需要传入容器的 API Key 环境变量，然后重新构建镜像并启动容器：

```bash
cp .env.example .env
docker compose up -d --build
```

`.env` 是 Docker Compose 使用的本地变量文件，不提交到 Git。更完整的 Docker 配置说明见 [部署指南](docs/部署指南.md)。

只新增或修改 API Key 环境变量、不新增 provider 依赖时，不需要重新构建镜像。可以停止并删除旧容器，再用 `docker run -e` 创建新容器：

```bash
docker stop buckshot-roulette-server
docker rm buckshot-roulette-server
docker run -d --name buckshot-roulette-server --restart unless-stopped -p 8000:8000 -v buckshot-data:/data -e MY_PROVIDER_API_KEY=your_api_key buckshot-roulette-server:0.1.0
```

配置 provider/model/AI preset 可以在宿主机上调用后端 HTTP API。Windows 使用：

```powershell
.\scripts\config_llm_presets.ps1
```

Linux / WSL 使用：

```bash
bash scripts/config_llm_presets.sh
```

配置脚本写入的是容器内服务端使用的 `/data/llm_config.json`。真实 API Key 不写入配置文件，而是通过 Docker 环境变量传入容器。

#### 发布镜像

如果要把服务端分发给服主，推荐发布镜像：

```bash
docker build -t buckshot-roulette-server:0.1.0 .
docker tag buckshot-roulette-server:0.1.0 yourname/buckshot-roulette-server:0.1.0
docker push yourname/buckshot-roulette-server:0.1.0
```

服主获取并运行：

```bash
docker pull yourname/buckshot-roulette-server:0.1.0
docker run -d --name buckshot-roulette-server --restart unless-stopped -p 8000:8000 -v buckshot-data:/data yourname/buckshot-roulette-server:0.1.0
```

### 客户端独立程序

Windows 客户端：

```powershell
.\scripts\build_client_windows.ps1
.\dist\client\windows\buckshot-client.exe --server http://127.0.0.1:8000 --name Alice
```

Linux 客户端：

```powershell
.\scripts\build_client_linux.ps1
```

在 Linux / WSL 中运行：

```bash
/mnt/c/swnfv/code/BuckshotRouletteCLI/dist/client/linux/buckshot-client --server http://127.0.0.1:8000 --name Alice
```

客户端构建产物位于：

```text
dist/client/windows/buckshot-client.exe
dist/client/linux/buckshot-client
```

`dist/` 和 `build/` 是构建输出目录，不提交到 Git。修改客户端代码后，重新运行对应构建脚本即可生成新的客户端程序。

## 架构原则

- `GameEngine` 只处理游戏规则，不依赖 HTTP、CLI、LLM。
- 联机模式下，权威 `GameState` 只存在于后端。
- CLI 是客户端入口，负责展示状态和提交玩家意图。
- LLM 只作为服务端内部 AI 玩家决策器，模型输出必须经过后端校验后才能进入游戏引擎。
