# xiongan_frontend

xiongan_agent 的前端服务，包含 LangGraph API 服务器配置和自定义 Chat UI。

## 目录结构

```
xiongan_frontend/
├── graph.py            # LangGraph 服务端入口（非交互式，monkey-patch 绕过 questionary）
├── langgraph.json      # langgraph dev 配置
├── pyproject.toml      # 最简包声明（供 langgraph CLI 识别依赖）
├── pyrightconfig.json  # IDE 静态分析路径配置
├── .env.example        # 需要追加到根目录 .env 的环境变量模板
├── README.md
└── ui/                 # 本地 Chat UI（基于 agent-chat-ui，支持思考过程折叠展示）
    ├── src/
    │   └── components/thread/messages/
    │       ├── ai.tsx              # AI 消息渲染（已改：解析 <think> 块）
    │       └── thinking-block.tsx  # 可折叠思考过程组件
    └── ...
```

---

## 快速启动

需要同时启动两个服务：**LangGraph API 服务器** 和 **前端 UI**，分别开两个终端窗口。

---

### 终端 1：启动 LangGraph API 服务器

#### 1. 安装 langgraph-cli

```bash
pip install "langgraph-cli[inmem]"
```

#### 2. 配置环境变量

确认项目根目录的 `.env` 包含以下内容：

```
VLLM_MAIN_PORT=8002       # vLLM 主模型端口（多个端口可用时指定）
ANALYSIS_MODEL=remote     # analysis_agent 模型：remote（主模型）或 local（urban-vlm）
```

#### 3. 启动服务器

**Linux / macOS：**

```bash
cd xiongan_frontend
langgraph dev --allow-blocking --host 0.0.0.0
```

**Windows（PowerShell）：**

Windows 中文系统必须设置 `PYTHONUTF8=1`，否则 langgraph-api 内部读取 `.env` 时会报 GBK 解码错误。

```powershell
$env:PYTHONUTF8=1; cd xiongan_frontend; langgraph dev --allow-blocking --host 0.0.0.0
```

如果 `langgraph.exe` 被应用程序控制策略（AppLocker/WDAC）拦截，报错"应用程序控制策略已阻止此文件"，改用 Python 模块方式启动：

```powershell
$env:PYTHONUTF8=1; cd xiongan_frontend; python -m langgraph_cli dev --allow-blocking --host 0.0.0.0
```

> 前提：需要先在 langgraph_cli 包目录下创建 `__main__.py`（内容见下方），或确认已存在。
>
> ```python
> # <site-packages>/langgraph_cli/__main__.py
> from langgraph_cli.cli import cli
>
> cli()
> ```

启动成功后终端会打印：

```
🚀 API: http://0.0.0.0:2024
🎨 Studio UI: https://smith.langchain.com/studio/?baseUrl=http://0.0.0.0:2024
```

局域网内其他设备可通过 `http://<服务器IP>:2024` 访问。

> ⚠️ 开发服务器无鉴权，暴露到局域网前请确认环境安全。

---

### 终端 2：启动本地 Chat UI

#### 1. 安装 pnpm（首次，仅需一次）

```powershell
# 若尚未安装 pnpm
npm install -g pnpm

# 若 pnpm 在 PATH 中找不到（Windows 常见），运行
pnpm setup
# 然后关闭终端重新打开，PATH 才会生效
```

> Node.js 未安装的话先从 https://nodejs.org 下载 LTS 版本安装。

#### 2. 安装项目依赖（首次运行）

```powershell
cd xiongan_frontend/ui
pnpm install
```

#### 3. 启动开发服务器

```powershell
pnpm dev
```

UI 默认运行在 `http://localhost:3000`。

#### 4. 连接 Agent

浏览器打开 `http://localhost:3000`，填写连接参数：

| 参数 | 值 |
|---|---|
| Deployment URL | `http://localhost:2024`（局域网访问填 `http://<服务器IP>:2024`） |
| Graph ID | `agent` |
| LangSmith API Key | 本地运行留空 |

> Graph ID 必须填 `agent`（与 `langgraph.json` 中的 key 一致），填 `xiongan_agent` 会报 HTTP 422 错误。

点击 Connect 即可开始对话。

---

## 思考过程显示

本地 UI 对模型的 `<think>...</think>` 内容做了特殊处理：

- **默认折叠**：思考过程显示为灰色标题栏，不占用主界面空间
- **点击展开**：点击「思考过程」标题栏可查看完整推理内容
- **主回复**：正常白色区域展示，不受影响

相关文件：
- `ui/src/components/thread/messages/thinking-block.tsx` — 折叠组件
- `ui/src/components/thread/messages/ai.tsx` — 解析 `<think>` 并分流渲染

---

## 工作原理

### graph.py（服务端适配）

在导入时通过 monkey-patch 解决两个交互式阻塞问题：

1. **跳过端口选择**：直接用 httpx 探测 vLLM 端口，将结果写入 `model_probe._cached`，避免 `questionary` 弹出交互式菜单。
2. **跳过模型选择**：将 `supervisor_agent_main._select_analysis_model` 替换为读取 `ANALYSIS_MODEL` 环境变量的函数。

`checkpointer=None` 传给 `create_supervisor_graph`，图本身不创建 Checkpointer。
LangGraph Server 根据 `langgraph.json` 的 `checkpointer.path` 加载
`checkpointer.py`，将线程状态和消息 checkpoint 持久化到
`xiongan_frontend/checkpoints.db`。

### 对话历史持久化

本项目显式使用 `AsyncSqliteSaver`，避免 `langgraph dev` 重启后出现
“历史列表仍有标题，但线程状态为空”的情况：

```json
"checkpointer": {
  "path": "./checkpointer.py:checkpointer"
}
```

启动时应能看到类似日志：

```text
Configuring custom checkpointer at ./checkpointer.py:checkpointer
Using custom checkpointer: AsyncSqliteSaver
```

首次产生 checkpoint 后会自动创建 `xiongan_frontend/checkpoints.db`。
该文件及 SQLite 的 `-shm`、`-wal` sidecar 文件均为运行时数据，已加入
`.gitignore`。

SQLite 适合当前单机、局域网少量用户的部署方式。它不适合多个服务实例
共享同一数据库；并发量或部署规模增加后，应迁移到 PostgreSQL。

> **权限提示：** SQLite 只负责持久化，不负责用户隔离。当前服务没有登录
> 和服务端 owner 过滤，连接到同一 LangGraph Server 的局域网用户可能看到
> 彼此的历史线程。不要将未鉴权的 `2024` 端口暴露到不可信网络。

`AsyncSqliteSaver` 支持对话恢复所需的核心 checkpoint 读写和线程删除。
部分高级能力（取消运行后的 rollback 清理、历史 `keep_latest` 裁剪等）
可能降级；长期运行时旧 checkpoint 会持续累积，需要定期删除不再使用的
线程或迁移到完整的生产持久化后端。

### Skill 路由（意图识别）

用户消息进入后，supervisor 会先扫描 `xiongan_agent/skills/` 目录，读取各技能的描述（frontmatter），由 LLM 判断意图：

- **命中技能**（如 `remote-sensing-analysis`）→ 加载完整 `SKILL.md` 作为规划提示，启动完整分析流水线
- **普通对话**（问候、询问身份等）→ 直接回答，不走流水线

新增技能只需在 `xiongan_agent/skills/` 下创建新文件夹 + `SKILL.md`，无需改代码。

### Human-in-the-loop

search_agent 3 次失败后触发中断，UI 中以消息气泡形式弹出，用户在对话框内输入补充关键词即可恢复执行。

---

## 依赖前提

运行前请确认以下服务已就绪：

| 服务 | 地址 | 说明 |
|---|---|---|
| vLLM（主模型） | `10.129.107.145:8002` | Supervisor / Search / Image 规划 |
| vLLM（视觉模型） | `10.129.107.145:8002` | `ANALYSIS_MODEL=local` 时需要 |
| MCP Fetch Server | localhost（npx 自动启动） | 网页内容抓取 |
| Baidu / Gaode MCP | npx 自动启动 | 地图与地理编码 |
