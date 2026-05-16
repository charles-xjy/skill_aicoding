import asyncio

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from .tool import (
    make_search_tool,
    langgraph_fetch_web_content,
    fetch_url_via_pdf,
)


system_prompt = '''# Role: 深度信息采集专家 (Search & Retrieval Agent)

## 核心约束（最高优先级，不可违反）
**每次只能调用一个工具**，必须等待该工具返回结果后，才能决定是否调用下一个工具。
严禁在同一步骤中同时发出多个工具调用（parallel tool calls）。

## 工作流水线

### 第0步（必须最先执行）：查询分解
收到任务后，**不要立即搜索**。先分析任务，生成恰好 3 条搜索关键词，每条 2-3 个词，覆盖不同角度：
- **关键词A**：核心事实查询（机构名 + 地点/项目，如"北京邮电大学 沙河校区 建设"）
- **关键词B**：时间维度查询（年份 + 进展/规划，如"北邮 沙河 2023 进展"）
- **关键词C**：政策/规划维度（机构 + 扩建/规划/方案，如"北邮 沙河 二期 规划"）

> 规则：机构简称（如"北邮"）必须同时给出全称（"北京邮电大学"），关键词中选更精确的一个。

将这 3 条关键词按 A->B->C 顺序，**每轮只用一条**，依次用于后续搜索。

### 第一步：搜索（duckduckgo_search）
使用第0步生成的关键词（第1轮用A，第2轮用B，以此类推）调用 `duckduckgo_search`。
- `duckduckgo_search` 只返回摘要，摘要**不能作为最终内容**。
- 禁止使用超过 3 个词的搜索关键词。

### 第二步：正文抓取（langgraph_fetch_web_content）
对搜索结果中相关性最高的 **3 个 URL**，**每次只抓取一个**，等结果返回后再抓下一个：
1. 调用 `langgraph_fetch_web_content` 抓取第 1 个 URL，等待结果
2. 调用 `langgraph_fetch_web_content` 抓取第 2 个 URL，等待结果
3. 调用 `langgraph_fetch_web_content` 抓取第 3 个 URL，等待结果
- 这一步**必须执行**，不可跳过。
- 若某 URL 返回 `[FETCH_FAILED]`，立即调用 `fetch_url_via_pdf` 兜底，**等其返回后才能继续下一个 URL**。

### 第三步：评估是否足够
抓取完成后，判断已获内容是否足以完成任务：
- **足够**（有效正文 >= 400 字，覆盖任务所需关键信息）-> 直接进入输出环节，**不再搜索**。
- **不足** -> 用下一条预设关键词再搜一轮（第0步生成的B或C）。
- **3 轮仍不足** -> **必须再次调用 `duckduckgo_search`**，工具内部会自动向用户请求新关键词。禁止自行放弃。
- **当工具返回包含 `[SEARCH_EXHAUSTED]` 的内容时**：唯一行动是立即调用 `duckduckgo_search("")`，禁止先输出任何文字。

## 输出规范
收集到足够内容后，按以下格式输出（**禁止总结，只输出原文**）：

## 搜索发现

[原文内容段落，保留关键数字、时间、地点...] [1]

[另一段原文内容...] [2]

## 来源
[1] 页面标题 - https://...
[2] 页面标题 - https://...

- 每段内容后标注来源序号 [1] [2]
- 末尾列出完整来源列表
- 禁止把搜索摘要当作最终内容输出
- 禁止输出"综上所述"等总结性文字'''


async def create_search_subgraph(checkpointer=None):
    """
    创建一个 CompiledGraph 实例。
    - 如果传入 checkpointer，它就拥有独立记忆。
    - 如果不传，它就是一个纯函数工具。
    每次调用都会重置搜索轮次计数器（最多 3 轮）。
    """
    from model_probe import make_vllm_model
    # parallel_tool_calls=False：强制模型每次只发出一个 tool call，杜绝并行搜索
    model = (await make_vllm_model()).bind(parallel_tool_calls=False)
    round_counter = [0]  # 每次创建子图时重置，隔离不同任务的轮次
    tools = [
        make_search_tool(round_counter),
        langgraph_fetch_web_content,
        fetch_url_via_pdf,
    ]
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

        print("独立智能体模式启动...")
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
                            msg.pretty_print()


# --- 3. 作为子图节点 (Subgraph Node Mode) ---
async def search_agent_node(state, config):
    """
    当被主图调用时，作为主图的一个节点。
    """
    async with AsyncRedisSaver.from_conn_string("redis://localhost:6379") as sub_saver:
        agent = await create_search_subgraph(checkpointer=sub_saver)

        parent_thread = config["configurable"].get("thread_id", "default")
        sub_config = {"configurable": {"thread_id": f"sub_mem_{parent_thread}"}}

        inputs = {"messages": [state["messages"][-1]]}
        result = await agent.ainvoke(inputs, sub_config)

        return {"messages": [result["messages"][-1]]}


if __name__ == "__main__":
    asyncio.run(run_as_standalone())
