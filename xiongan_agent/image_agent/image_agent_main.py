import asyncio

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from .tool import tool_download_image, get_baidu_tools, get_gaode_tools, baidu_geocode


system_prompt = """你是一个专业的地理空间情报分析助手。
你的任务是根据用户的需求，通过调用不同的工具获取地理信息、下载卫星遥感影像并进行对比分析。

### 工作流指南：
1. **地点定位**：当用户提到一个地标时，首先调用高德或百度地图工具获取该地点的精确经纬度（lon, lat）。
2. **影像获取**：获取坐标后，调用 `tool_download_image` 工具。你需要根据用户要求的年份（如 2015 和 2025）传入对应的年份列表、经纬度以及地点名称。
3. **路径记忆**：下载成功后，`tool_download_image` 会返回文件的本地路径（path）。请务必记住这些路径。
4. **输出路径（最重要）**：
   - 将 `tool_download_image` 返回的 `files` 列表中每条记录的 `path` 字段**原文逐行列出**，不得修改或替换。
   - 格式示例：`D:\mycode\...\image_agent\Google_earth_image\地点名_2020.jpg`
   - 禁止自行编造任何文件路径。

### 注意事项：
- 在调用下载工具前，必须确保已经拿到了准确的经纬度。
- 请以专业、严谨的口吻回复。
- 最终回复必须包含所有已下载文件的完整绝对路径。
"""


# 2. 定义统一的异步函数
async def get_all_tools():
    """汇总所有静态工具和动态 MCP 工具，返回一个扁平的列表"""
    # 静态工具（已经是对象了，直接放进列表）
    static_tools = [tool_download_image, baidu_geocode]

    # 动态工具（因为是异步获取，必须使用 await）
    # 这样拿到的才是真正的 [tool1, tool2...] 列表
    gaode = await get_gaode_tools()
    baidu = await get_baidu_tools()

    # 合并成一个扁平的列表返回
    return static_tools + gaode + baidu


async def create_image_subgraph(checkpointer=None):
    """
    创建一个 CompiledGraph 实例。
    - 如果传入 checkpointer，它就拥有独立记忆。
    - 如果不传，它就是一个纯函数工具。
    """
    from model_probe import make_vllm_model
    model = await make_vllm_model()
    tools = await get_all_tools()
    agent = create_agent(
        model=model, tools=tools, system_prompt=system_prompt, checkpointer=checkpointer
    )
    return agent


from langgraph.checkpoint.redis.aio import AsyncRedisSaver


# --- 2. 独立运行入口 (Standalone Mode) ---
async def run_as_standalone():
    """
    当此文件被直接运行时，作为一个独立的智能体启动
    """
    DB_URI = "redis://localhost:6379"
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        # 传入独立的 checkpointer 实现独立记忆
        agent = await create_image_subgraph(checkpointer=saver)

        config = {"configurable": {"thread_id": "standalone_test_001"}}
        inputs = {
            "messages": [
                HumanMessage(
                    content="我想知道北京邮电大学沙河校区2020和2025年的变化，请下载影像并返回图像。"
                )
            ]
        }

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
async def image_agent_node(state, config):
    """
    当被主图调用时，作为主图的一个节点。
    """
    # 这里你可以选择是否为子图创建全新的独立 Redis 连接
    # 或者从 config 中提取主图的连接，但使用不同的 thread_id
    async with AsyncRedisSaver.from_conn_string("redis://localhost:6379") as sub_saver:
        agent = await create_image_subgraph(checkpointer=sub_saver)

        # 🌟 实现独立记忆的关键：
        # 这里使用一个固定的、或与父 thread 相关联但不相等的 sub_thread_id
        parent_thread = config["configurable"].get("thread_id", "default")
        sub_config = {"configurable": {"thread_id": f"sub_mem_{parent_thread}"}}

        # 只取主图传给它的最后一条需求
        inputs = {"messages": [state["messages"][-1]]}
        result = await agent.ainvoke(inputs, sub_config)

        return {"messages": [result["messages"][-1]]}


# --- 4. 运行判断 ---
if __name__ == "__main__":
    # 如果直接 python 运行此文件，执行独立模式
    asyncio.run(run_as_standalone())
# docker exec redis-stack-server redis-cli keys "checkpoint:standalone_test_001:*" | xargs -I {} docker exec redis-stack-server redis-cli del "{}"
