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
  │   │ MCP Fetch   │  │
  │   │ Playwright  │  │
  │   │ MinerU PDF  │  │
  │   └─────────────┘  │
  │                    │
Google Earth Engine   Qwen VLM
(卫星影像下载)        (多模态分析)
```

### 各子图职责

| 子图 | 作用 | 核心工具 |
|------|------|----------|
| `supervisor_agent` | 将用户请求拆解为有序任务列表，逐一调度子图，审核结果质量，遇到失败时触发人机交互 | Qwen LLM |
| `image_agent` | 通过高德/百度地图 API 获取精确坐标，调用 Google Earth Engine 下载指定年份的卫星影像 | Gaode MCP · Baidu MCP · GEE |
| `search_agent` | 多策略网络搜索 + 深度正文抓取，支持三级降级：DuckDuckGo → MCP Fetch → Playwright PDF → MinerU | DuckDuckGo · MCP · Playwright · MinerU |
| `analysis_agent` | 将卫星影像（base64 多模态）与搜索文本合并，驱动 VLM 生成结构化分析报告 | urban-vlm (本地) · Qwen (远程) |

## 目录结构

```
xiongan_agent/
├── main.py                          # 程序入口
├── memory_manager.py                # Redis 检查点管理 TUI
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
│   ├── search_agent_main.py         # Search Agent 图定义
│   └── tool/
│       ├── duckduckgo_search_tool.py    # DuckDuckGo 搜索
│       ├── fetch_webcontent_bymcp.py    # MCP 网页正文抓取
│       ├── playwright_download_pdf.py   # Playwright PDF 下载
│       └── tool_pdf2md.py               # MinerU PDF 解析
│
├── analysis_agent/
│   └── analysis_agent_main.py       # Analysis Agent 图定义
│
└── search_agent/search_result/      # 搜索结果缓存
    ├── duckduckgo/                  # 搜索摘要 JSON
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

| 服务 | 地址 | 用途 |
|------|------|------|
| vLLM (Qwen_agent) | `http://10.129.107.145:8001/v1` | Supervisor · Search · Image Agent |
| vLLM (urban-vlm) | `http://10.129.107.145:8002/v1` | Analysis Agent 多模态推理 |
| Redis | `redis://10.129.107.145:6379` | LangGraph 检查点持久化 |
| MCP Fetch Server | 本地 (npx 自动启动) | 网页正文抓取 |
| mineru-api | `http://127.0.0.1:57321` (自动启动) | PDF 解析 |

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

1. **区域定位与演进概览** — 时空锚定、阶段定性、宏观背景
2. **空间格局演变（影像解译视角）** — 建筑用地、交通、生态、功能边界的增量对比
3. **发展动力机制（政策/规划视角）** — 政策层级、重点项目、资金来源、时序逻辑
4. **问题诊断与短板识别** — 供需错配、交通瓶颈、生态压力、数据盲区
5. **综合评价与战略前瞻** — 综合评分、对标分析、三年行动建议、远期预判

## 搜索三阶段流水线

DuckDuckGo 只负责发现 URL，正文抓取始终由 MCP 或 Playwright+MinerU 完成。

```
阶段一：URL 发现
  DuckDuckGo（通用 + 百度百科）
  → 返回相关网页 URL 列表（摘要 snippet 仅供参考，不作为内容输出）

阶段二：正文抓取（对每个 URL 执行，必须成功 ≥2 个）
  MCP Fetch (mcp-server-fetch-typescript)
  → 返回网页 Markdown 正文

阶段三：PDF 兜底（仅当某 URL 的 MCP 返回 [FETCH_FAILED] 时）
  Playwright → 下载 PDF
  MinerU    → 解析 PDF → Markdown
```

所有内容截断至 4000 字以保护模型上下文窗口。

## 会话管理

`memory_manager.py` 提供交互式 TUI，可查看、删除 Redis 中保存的历史会话检查点：

```bash
python memory_manager.py
```

- 列出所有历史会话（thread_id · 时间 · 状态）
- 查看某会话的消息记录
- 删除单条或全部会话

## Windows 注意事项

- 程序启动时自动设置 `WindowsSelectorEventLoopPolicy`（Redis asyncio 兼容）
- Playwright 在独立的 `ProactorEventLoop` 中运行，避免与 Redis 事件循环冲突
- 卫星影像保存路径基于 `__file__` 自动推导，无需修改硬编码路径
