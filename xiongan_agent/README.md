# xiongan_agent — 城市空间演变分析智能体

基于 **LangGraph Supervisor Pattern** 构建的多智能体系统，通过整合卫星遥感影像与网络文本信息，自动生成城市区域的空间演变分析报告。

## 系统架构

```
用户输入 (自然语言问题)
      │
      ▼
┌─────────────────────┐
│   supervisor_agent  │  ← 任务规划 · 路由 · 质量审核
└──────┬──────────────┘
       │
   ┌───┼──────────────┐
   ▼   ▼              ▼
image  search      analysis
agent  agent        agent
  │      │             │
  │   ┌──┴──────────┐  │
  │   │ DuckDuckGo  │  │
  │   │ Baidu Search│  │
  │   │ MCP Fetch   │  │
  │   │ Playwright  │  │
  │   │ MinerU PDF  │  │
  │   └─────────────┘  │
  │                    │
Google Earth Engine   Qwen VLM
(卫星影像下载)        (多模态分析)
```

### 各子图职责

子图

作用

核心工具

`supervisor_agent`

将用户请求拆解为有序任务列表，逐一调度子图，审核结果质量，遇到失败时触发人机交互

Qwen LLM

`image_agent`

通过高德/百度地图 API 获取精确坐标，调用 Google Earth Engine 下载指定年份的卫星影像

Gaode MCP · Baidu MCP · GEE

`search_agent`

多策略网络搜索 + 深度正文抓取，支持三级降级：DuckDuckGo/Baidu → MCP Fetch → Playwright PDF → MinerU

DuckDuckGo · Baidu Search · MCP · Playwright · MinerU

`analysis_agent`

将卫星影像（base64 多模态）与搜索文本合并，驱动 VLM 生成结构化分析报告

urban-vlm (本地) · Qwen (远程)

## 目录结构

```
xiongan_agent/
├── main.py                          # 程序入口
├── memory_manager.py                # Redis 检查点管理 TUI
├── model_probe.py                   # vLLM 端口探测器（自动发现可用模型端口）
│
├── supervisor_agent/
│   └── supervisor_agent_main.py     # Supervisor 图定义 & 路由逻辑
│
├── image_agent/
│   ├── image_agent_main.py          # Image Agent 图定义
│   └── tool/
│       ├── google_earth_api.py      # GEE 卫星影像下载
│       ├── gaode_mcp.py             # 高德地图 MCP 工具
│       └── baidu_mcp.py             # 百度地图 MCP 工具
│
├── search_agent/
│   ├── search_agent_main.py          # Search Agent 图定义
│   └── tool/
│       ├── duckduckgo_search_tool.py    # DuckDuckGo 搜索
│       ├── baidu_mcp_search.py          # Baidu 搜索 MCP (新实现)
│       ├── baidu_search_appbuilder.py   # Baidu 搜索 API (备用/已修复)
│       ├── fetch_webcontent_bymcp.py    # MCP 网页正文抓取
│       ├── playwright_download_pdf.py   # Playwright PDF 下载
│       └── tool_pdf2md.py               # MinerU PDF 解析
│
├── analysis_agent/
│   └── analysis_agent_main.py       # Analysis Agent 图定义
│
└── search_agent/search_result/      # 搜索结果缓存
    ├── duckduckgo/                  # 搜索摘要 JSON
    ├── baidu_mcp/                   # 百度 MCP 搜索结果 JSON (新)
    ├── baidu_appbuilder/            # 百度 API 搜索结果 JSON
    ├── mcp_fetch/                   # 网页正文 Markdown
    ├── download_pdf/                # 下载的 PDF 原文
    └── pdf2md/                      # MinerU 解析输出
```

## 快速开始

### 环境依赖

```bash
# Python 3.12+
pip install langgraph langchain langchain-openai
pip install duckduckgo-search playwright mcp
pip install mineru-api redis questionary

# Playwright 浏览器内核
playwright install chromium
```

### 服务依赖

服务

地址

用途

vLLM (Qwen_agent)

`http://10.129.107.145:8001/v1`

Supervisor · Search · Image Agent

vLLM (urban-vlm)

`http://10.129.107.145:8002/v1`

Analysis Agent 多模态推理

Redis

`redis://10.129.107.145:6379`

LangGraph 检查点持久化

MCP Fetch Server

本地 (npx 自动启动)

网页正文抓取

mineru-api

`http://127.0.0.1:57321` (自动启动)

PDF 解析

### 运行

```bash
cd xiongan_agent

# 交互式输入问题
python main.py

# 直接传入问题
python main.py "分析北邮沙河校区2020年到2025年的空间演变"

# 生成图结构可视化（输出 supervisor_graph.png）
python main.py --visualize

# 管理 Redis 历史会话
python memory_manager.py
```

## 执行流程

```
1. Supervisor 规划
   用户问题 → LLM 拆解 → JSON 任务列表
   [image_agent: 下载卫星影像] → [search_agent: 采集文本] → [analysis_agent: 生成报告]

2. 逐任务执行
   每个任务执行完毕后回到 Supervisor 审核
   ├── 质量合格 → 推进下一任务
   ├── 失败可重试（最多 3 次）→ 标记 error 跳过
   └── search_agent 有效内容 < 400 字 → 触发 human_input 中断

3. 人机交互（search_agent 失败时）
   图执行暂停 → 提示用户输入新关键词 → Command(resume=...) 恢复执行

4. 最终输出
   analysis_agent 生成结构化报告（五章节，每章 ≥ 300 字）
```

## 任务状态机

```
pending → in_progress → completed
                     ↘ error (重试耗尽)
              ↑ human_input (质量不足时回退)
```

## 分析报告结构

analysis_agent 固定输出以下五个章节：

1.  **区域定位与演进概览** — 时空锚定、阶段定性、宏观背景
2.  **空间格局演变（影像解译视角）** — 建筑用地、交通、生态、功能边界的增量对比
3.  **发展动力机制（政策/规划视角）** — 政策层级、重点项目、资金来源、时序逻辑
4.  **问题诊断与短板识别** — 供需错配、交通瓶颈、生态压力、数据盲区
5.  **综合评价与战略前瞻** — 综合评分、对标分析、三年行动建议、远期预判

## 搜索三阶段流水线

DuckDuckGo / Baidu 只负责发现 URL，正文抓取始终由 MCP Fetch 或 Playwright+MinerU 完成。

### 阶段一：URL 发现

-   **DuckDuckGo (默认)**：
    -   **优先来源**：`site:edu.cn` (教育)、`site:xiongan.gov.cn` (政府)、`site:news.cn` 等权威媒体、`site:baike.baidu.com` (百科)。
    -   **黑名单过滤**：自动排除 `bbc.com`, `nytimes.com`, `voachinese.com` 等境外媒体，以及社交平台和广告页面。
    -   **质量判定**：自动排除标题为“404”、“首页”、“登录”或描述包含“forbidden”、“access restriction”的无效结果。
-   **百度搜索 MCP (回退)**：当 DDGS 返回空结果或全是低质量链接时，由 `baidu_mcp_search.py` 自动接管，通过百度 AppBuilder MCP 终端获取结果。

### 阶段二：正文抓取

-   **MCP Fetch** (`mcp-server-fetch-typescript`)：对阶段一获得的每个 URL 执行，必须成功获取 ≥2 个 URL 的正文。
-   **内容截断**：所有抓取内容限制在 4000 字以内，以平衡模型上下文和性能。

### 阶段三：PDF 兜底

-   仅当某 URL 的 MCP Fetch 返回 `[FETCH_FAILED]` 时，启动 Playwright 下载 PDF 并通过 MinerU 解析。

## 任务质量门控 (Quality Gating)

系统在 Supervisor 层级对子图输出进行严格审核：

1.  **搜索内容阈值**：`search_agent` 返回的有效正文（扣除思考过程后）若 **少于 400 字**，Supervisor 会判定为“质量不足”，图执行会进入 `human_input` 状态，暂停并请求用户提供更精准的关键词进行重试。
2.  **图像下载优化**：`image_agent` 支持单次任务下载多年份卫星影像。任务描述中只需列出年份列表（如 2019-2025），即可在一次调用中完成采集。
3.  **重试机制**：子图任务若执行失败（出现“执行失败”标记），Supervisor 支持最多 3 次自动重试，耗尽后标记为 `error` 并跳过。

## 关键技术配置

### MCP 服务器 (Model Context Protocol)

-   **百度搜索**：`https://appbuilder.baidu.com/v2/ai_search/mcp/sse` (SSE 终端)
-   **高德地图**：`@amap/amap-maps-mcp-server` (npx 运行，用于坐标转换)
-   **百度地图**：`@baidumap/mcp-server-baidu-map` (npx 运行，用于地理编码)
-   **网页抓取**：`mcp-server-fetch-typescript` (npx 运行)

### model_probe.py — vLLM 端口探测器

服务器上同时跑着多个 vLLM 进程（主模型 @ 8001、视觉模型 @ 8002 等），端口不固定，所以所有 agent 统一通过 `model_probe.py` 获取模型连接，而不是在各处硬编码端口。

**工作流程：**

1. **探测**：依次向 `10.129.107.145` 的 8001、8002、8003 端口发 HTTP 请求，收集有响应的端口及其模型名称
2. **选择**：
   - 只有一个端口可用 → 自动选定，不打扰用户
   - 多个端口可用 → 弹出 `questionary` 交互菜单，让用户手动选定主模型
3. **缓存**：结果存入模块级变量 `_cached`，整个进程只探测一次，后续调用直接返回缓存

**使用方式：**

```python
from model_probe import make_vllm_model
model = await make_vllm_model()  # 自动探测并返回已初始化的 LangChain 模型实例
```

### 模型选择

-   **主模型（规划 / 搜索 / 图像）**：启动时通过 `model_probe.py` 探测端口后确定，若多个可用则交互选择。
-   **多模态分析（analysis_agent）**：每次 analysis 任务开始前单独选择，可选远端 `Qwen_agent` (8001) 或本地 `urban-vlm` (8002)。

所有内容截断至 4000 字以保护模型上下文窗口。

## 会话管理

`memory_manager.py` 提供交互式 TUI，可查看、删除 Redis 中保存的历史会话检查点：

```bash
python memory_manager.py
```

-   列出所有历史会话（thread_id · 时间 · 状态）
-   查看某会话的消息记录
-   删除单条或全部会话

## Windows 注意事项

-   程序启动时自动设置 `WindowsSelectorEventLoopPolicy`（Redis asyncio 兼容）
-   Playwright 在独立的 `ProactorEventLoop` 中运行，避免与 Redis 事件循环冲突
-   卫星影像保存路径基于 `__file__` 自动推导，无需修改硬编码路径