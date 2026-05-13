import asyncio

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from .tool import (
    duckduckgo_search,
    langgraph_fetch_web_content,
    export_webpage_to_pdf,
    pdf2md,
)

model = init_chat_model(
    base_url="http://10.129.107.145:8001/v1",
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)

system_prompt = """# Role: 深度信息采集专家 (Search & Retrieval Agent)

## Goal
针对特定地点进行多维度的原始资料采集，为后续的城市规划分析提供高密度的信息支撑。

## Step 1: 搜索策略 (Query Generation)
严禁直接搜索模糊的长句。你必须针对该地点，强制从以下三个维度分别生成 **2-3个词** 的查询词并调用 `duckduckgo_search`：

1. **时空节点词**：结合文件名中的年份。
   - *示例*：`北邮沙河 2020 建设`、`北邮沙河 2026 现状`
2. **专项规划词**：针对建设、土地、扩建。
   - *示例*：`北邮沙河 扩建 规划`、`北邮沙河 重点工程`
3. **宏观背景词**：针对所属行政区或园区。
   - *示例*：`沙河高教园 2025 规划`、`昌平区 城市更新 政策`

## Step 2: 抓取与容错 (Extraction)
- **硬性指标**：必须通过 `langgraph_fetch_web_content` 获取至少 2 个深度网页的正文。
- **降级处理**：
    - 若 `fetch` 失败（被反爬或 JS 渲染问题），必须立即调用 `export_webpage_to_pdf` + `pdf2md`。
    - **严禁**仅解析搜索列表的摘要（Snippet），那对分析没有任何价值。

## Step 3: 输出规范
- **只输出原文**：直接返回抓取到的网页正文或 PDF 转换后的 Markdown。
- **禁止总结**：严禁输出类似“综上所述”、“该地区发展良好”的废话。
- **元数据保留**：保留抓取来源的 URL，以便后续 Agent 溯源。

## ⚠️ 负面约束 (Negative Constraints)
- ❌ 禁止搜索 10 年前的陈旧信息（除非用户明确要求历史溯源）。
- ❌ 禁止使用超过 3 个词的搜索语句。
- ❌ 禁止在抓取失败后停止工作，必须尝试 PDF 转换路径。"""


async def create_search_subgraph(checkpointer=None):
    """
    创建一个 CompiledGraph 实例。
    - 如果传入 checkpointer，它就拥有独立记忆。
    - 如果不传，它就是一个纯函数工具。
    """
    tools = [
        duckduckgo_search,
        langgraph_fetch_web_content,
        export_webpage_to_pdf,
        pdf2md,
    ]
    # tools = [duckduckgo_search, export_webpage_to_pdf, pdf2md]

    # 这里的 agent 可以是 LangGraph 的 CompiledGraph
    agent = create_agent(
        model=model, tools=tools, system_prompt=system_prompt, checkpointer=checkpointer
    )
    return agent


# --- 2. 独立运行入口 (Standalone Mode) ---
async def run_as_standalone():
    """
    当此文件被直接运行时，作为一个独立的智能体启动
    """
    DB_URI = "redis://localhost:6379"
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        # 传入独立的 checkpointer 实现独立记忆
        agent = await create_search_subgraph(checkpointer=saver)

        config = {"configurable": {"thread_id": "search_test_001"}}
        inputs = {"messages": [HumanMessage(content="请介绍雄安新区")]}

        print("🤖 独立智能体模式启动...")
        async for chunk in agent.astream(
            inputs,
            config,
            stream_mode="updates",
            version="v2",
        ):
            if chunk["type"] == "updates":
                for node_name, node_update in chunk["data"].items():
                    if "messages" in node_update:
                        for msg in node_update["messages"]:
                            print(f"\n--- 节点 [{node_name}] 输出 ---")
                            # pretty_print 会根据消息类型自动格式化输出
                            msg.pretty_print()


# --- 3. 作为子图节点 (Subgraph Node Mode) ---
async def search_agent_node(state, config):
    """
    当被主图调用时，作为主图的一个节点。
    """
    # 这里你可以选择是否为子图创建全新的独立 Redis 连接
    # 或者从 config 中提取主图的连接，但使用不同的 thread_id
    async with AsyncRedisSaver.from_conn_string("redis://localhost:6379") as sub_saver:
        agent = await create_search_subgraph(checkpointer=sub_saver)

        # 🌟 实现独立记忆的关键：
        # 这里使用一个固定的、或与父 thread 相关联但不相等的 sub_thread_id
        parent_thread = config["configurable"].get("thread_id", "default")
        sub_config = {"configurable": {"thread_id": f"sub_mem_{parent_thread}"}}

        # 只取主图传给它的最后一条需求
        inputs = {"messages": [state["messages"][-1]]}
        result = await agent.ainvoke(inputs, sub_config)

        return {"messages": [result["messages"][-1]]}


if __name__ == "__main__":
    # --- 4. 运行判断 ---
    # 如果直接 python 运行此文件，执行独立模式
    asyncio.run(run_as_standalone())
    # docker exec redis-stack-server redis-cli keys "checkpoint:standalone_test_001:*" | xargs -I {} docker exec redis-stack-server redis-cli del "{}"

    # 查看记忆内容
    from langgraph.checkpoint.redis import RedisSaver

    connection_str = "redis://localhost:6379"

    with RedisSaver.from_conn_string(connection_str) as checkpointer:
        config = {"configurable": {"thread_id": "search_test_001"}}
        print(f"--- 正在查询 Thread ID: search_agent 的所有 Checkpoints ---")

        # 使用 list() 获取所有快照
        for state in checkpointer.list(config):
            checkpoint_id = state.config["configurable"]["checkpoint_id"]
            print(f"\n[Checkpoint ID]: {checkpoint_id}")
            print(f"[metadata]: {state.metadata}")

            # 核心修正：处理可能为 dict 格式的消息
            raw_messages = state.checkpoint.get("channel_values", {}).get(
                "messages", []
            )

            for msg in raw_messages:
                # 兼容处理：如果是字典则取键值，如果是对象则取属性
                if isinstance(msg, dict):
                    # LangGraph 存储的 dict 通常包含 'type' 和 'data'
                    m_type = msg.get("type", "unknown")
                    # 尝试从嵌套的 data 中获取 content，或者直接获取
                    data = msg.get("data", {})
                    content = data.get("content", str(msg))
                else:
                    m_type = getattr(msg, "type", "unknown")
                    content = getattr(msg, "content", "")

                # 截断过长的内容方便阅读
                display_content = content
                print(f"  - [{m_type}]: {display_content}")

            print("-" * 50)
# docker exec redis-stack-server redis-cli keys "checkpoint:search_agent:*" | xargs -I {} docker exec redis-stack-server redis-cli del "{}"
