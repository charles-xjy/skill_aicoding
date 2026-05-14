# 城市治理分析多智能体系统 (Urban Governance Multi-Agent System)

基于 **LangGraph** 构建的高级多智能体协作系统（Supervisor Pattern），专注于城市治理、区域发展规划与历史沿革的综合分析（例如：根据卫星影像和网络资讯分析特定区域如雄安新区、北邮沙河校区的发展建设情况）。

本项目采用了先进的**规划式重构 (Planning-based Supervisor)** 架构，通过一个核心的主管 (Supervisor) 智能体对复杂任务进行拆解、规划，并协调多个具备特定专业能力的子智能体 (Sub-agents) 共同完成任务。

## ✨ 核心特性

- 🧠 **Supervisor 规划机制**：主节点 (Supervisor) 首先将用户的宏大请求拆解为有序的任务列表（1. 2. 3. ...），并负责任务的分发与状态追踪，避免了模型在执行复杂任务时的迷失。
- 🤖 **多专家协同协作**：
  - **`image_agent` (图像智能体)**：专门负责获取并保存不同年份的卫星影像与地图数据。
  - **`search_agent` (搜索智能体)**：负责在互联网上精准搜索、抓取相关网页内容与新闻资料。
  - **`analysis_agent` (分析智能体)**：综合前序智能体收集到的所有原始多模态数据，进行深入分析并输出最终报告。
- 💾 **统一的共享记忆 (Shared Checkpointer)**：系统使用 Redis 作为共享 Checkpointer，主图与所有子图共享同一个数据连接与状态上下文，实现了完整的执行状态流转和记忆穿透。
- 🛡️ **高可用与错误恢复机制**：
  - **自动重试**：子智能体执行失败时，系统会自动进行最多 3 次的重试。
  - **Human-in-the-loop (人工介入)**：如果 `search_agent` 连续失败，系统会通过 LangGraph 的 `interrupt` 机制暂停，要求用户人工提供更准确的搜索关键词，然后无缝恢复执行。
- 📊 **高度可观测性**：每次状态变化都会在控制台打印美观的任务进度列表（包含 Pending、In Progress、Completed、Error 状态）及层级执行日志，便于调试。

## 🏗️ 架构设计

系统包含一个 Main Graph 和多个 Sub Graph，采用条件路由连接。

```mermaid
graph TD
    START((开始)) --> Supervisor[Supervisor Node\n任务规划与分发]
    Supervisor --"任务指派: image_agent"--> ImageAgent((Image Agent\n抓取影像))
    Supervisor --"任务指派: search_agent"--> SearchAgent((Search Agent\n搜集资料))
    Supervisor --"任务指派: analysis_agent"--> AnalysisAgent((Analysis Agent\n综合生成报告))
    
    ImageAgent -->|返回本地图片路径| Supervisor
    SearchAgent -->|3次失败| HumanInput[Human-in-the-loop\n请求用户输入关键词]
    HumanInput --> SearchAgent
    SearchAgent -->|返回抓取文本| Supervisor
    AnalysisAgent -->|返回分析报告| Supervisor
    
    Supervisor -->|所有任务完成| END((结束))
```

*（详细的架构演进对比请参考 `xiongan_agent/SUPERVISOR_ARCH.md`）*

## 📁 目录结构

```text
skill_aicoding/
└── xiongan_agent/
    ├── supervisor.py              # 系统主入口与 Supervisor 图定义
    ├── SUPERVISOR_ARCH.md         # 架构设计说明文档
    ├── image_agent/               # 图像处理智能体模块
    │   ├── image_agent_main.py    # Image Agent 子图构建
    │   └── tool/                  # 图像抓取相关工具 (Google Earth, 高德, 百度等)
    ├── search_agent/              # 搜索与抓取智能体模块
    │   ├── search_agent_main.py   # Search Agent 子图构建
    │   └── tool/                  # 搜索引擎与网页抓取工具 (DuckDuckGo, PDF转MD等)
    └── analysis_agent/            # 数据综合分析智能体模块
        └── analysis_agent_main.py # Analysis Agent 子图构建
```

## 🚀 快速开始

### 1. 环境准备

- **Python**: Python 3.9+
- **Redis**: 系统依赖 Redis 来保存执行状态 (Checkpointer)。
  请确保本地或远程服务器运行了 Redis 实例，例如通过 Docker 启动：
  ```bash
  docker run -d -p 6379:6379 redis-stack-server
  ```
- **配置大模型 (LLM)**: 系统默认使用 VLLM 提供的 Qwen 模型，需要修改代码中的大模型 API 配置。
  - 如果使用其他模型提供商，请修改 `xiongan_agent/supervisor.py` 及各个子 Agent 目录中的 `init_chat_model` 初始化配置。

### 2. 运行系统

直接执行主程序入口文件：

```bash
cd xiongan_agent
python supervisor.py
```

### 3. 可视化图结构

脚本运行完毕后，会自动生成系统的图结构图，并保存为 `supervisor_graph.png`，您可以直接打开查看完整的状态机拓扑。

## 💡 典型执行流程示例

**用户提问**："请你根据2020和2025的卫星变化图，介绍北邮沙河校区近几年的发展"

1. **[规划]** Supervisor 解析请求，生成 3 步计划：
   - 任务 1: 获取 2020 和 2025 北邮沙河校区卫星影像 (分配给 `image_agent`)
   - 任务 2: 搜索北邮沙河校区 2020-2025 建设新闻 (分配给 `search_agent`)
   - 任务 3: 综合影像路径与新闻资料输出发展报告 (分配给 `analysis_agent`)
2. **[执行任务 1]** `image_agent` 被激活，调用工具下载图像，返回 `image_path` 回给 Supervisor。
3. **[执行任务 2]** `search_agent` 被激活，如果在抓取资料时反复失败（如遇到反爬），触发 `interrupt`，要求用户提供强制搜索关键词；拿到新词后重试并成功。
4. **[汇总任务 3]** Supervisor 将前两步的结果拼接进上下文，分配给 `analysis_agent`。
5. **[输出报告]** `analysis_agent` 完成最终思考与排版，输出深度报告。
