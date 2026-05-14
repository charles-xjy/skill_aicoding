import asyncio
import os
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.prebuilt import create_react_agent

from .tool import (
    make_search_tool,
    langgraph_fetch_web_content,
    export_webpage_to_pdf,
    pdf2md,
)

load_dotenv()
BASE_LLM_URL = os.getenv("BASE_LLM_URL")

model = init_chat_model(
    base_url=BASE_LLM_URL,
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)

system_prompt = """# Role: 深度信息采集专家 (Search & Retrieval Agent)

## 工作流水线（必须严格按顺序执行）

### 阶段一：URL 发现（duckduckgo_search）
`duckduckgo_search` 的唯一职责是**返回相关网页的 URL 列表**，其摘要（body/snippet）仅供判断相关性，绝对不能作为最终内容使用。

针对目标地点，从以下三个维度各生成 **2-3 个词** 的关键词并调用：
1. **时空节点词**：`北邮沙河 2020 建设`、`北邮沙河 2025 现状`
2. **专项规划词**：`北邮沙河 扩建 规划`、`沙河高教园 重点工程`
3. **宏观背景词**：`昌平区 城市更新 政策`、`沙河高教园 2025 规划`

### 阶段二：正文抓取（langgraph_fetch_web_content）
阶段一结束后，**立即**对搜索结果中相关性最高的 URL 逐一调用 `langgraph_fetch_web_content` 抓取完整正文。
- 这一步是**必须执行的**，不是可选的，不是降级方案。
- 目标：至少成功抓取 **2 个 URL** 的正文。

### 阶段三：PDF 兜底（仅当 MCP 抓取失败时）
若某个 URL 调用 `langgraph_fetch_web_content` 返回 `[FETCH_FAILED]`，则对**该 URL** 执行：
1. `export_webpage_to_pdf` → 下载为 PDF
2. `pdf2md` → 解析为 Markdown 正文

## 输出规范
- **只输出原文**：直接返回抓取到的网页正文或 PDF 转换后的 Markdown，保留来源 URL。
- **禁止总结**：严禁输出”综上所述”、”该地区发展良好”等概括性废话。
- ❌ 禁止把 duckduckgo 的摘要（snippet/body）当作最终内容输出。
- ❌ 禁止使用超过 3 个词的搜索关键词。
- ❌ 禁止在抓取失败后直接放弃，必须尝试 PDF 兜底路径。"""


async def create_search_subgraph(checkpointer=None):
    """
    创建一个 CompiledGraph 实例。
    - 如果传入 checkpointer，它就拥有独立记忆。
    - 如果不传，它就是一个纯函数工具。
    """
    # 🌟 round_counter 仍然作为闭包变量，但我们通过 supervisor 的重试逻辑确保其行为符合预期
    # 每次重新 compile 图时，这个变量会被重置为 [0]
    round_counter = [0]
    tools = [
        make_search_tool(round_counter),
        langgraph_fetch_web_content,
        export_webpage_to_pdf,
        pdf2md,
    ]
    
    # 使用 create_react_agent 简化构建，它内部处理了 StateGraph
    agent = create_react_agent(
        model=model, tools=tools, checkpointer=checkpointer, state_modifier=system_prompt
    )
    return agent


# --- 2. 独立运行入口 (Standalone Mode) ---
async def run_as_standalone():
    """
    当此文件被直接运行时，作为一个独立的智能体启动
    """
    DB_URI = "redis://10.129.107.145:6379"
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        agent = await create_search_subgraph(checkpointer=saver)
        config = {"configurable": {"thread_id": "search_test_001"}}
        inputs = {"messages": [HumanMessage(content="请介绍雄安新区")]}
        print("🤖 独立智能体模式启动...")
        async for chunk in agent.astream(inputs, config, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                if "messages" in node_update:
                    for msg in node_update["messages"]:
                        print(f"\n--- 节点 [{node_name}] 输出 ---")
                        msg.pretty_print()


if __name__ == "__main__":
    asyncio.run(run_as_standalone())
