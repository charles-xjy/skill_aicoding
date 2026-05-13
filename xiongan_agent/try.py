# =============================================================================================
# 1. 定义模型
# =============================================================================================
from langchain.tools import tool
from langchain.chat_models import init_chat_model

model = init_chat_model(
    base_url="http://localhost:8001/v1",
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)

# =============================================================================================
# 2. 定义工具
# =============================================================================================
from typing import List


@tool
def todo_manager(items: List[dict]) -> str:
    """
    更新当前会话的任务列表

    主动使用此工具来跟踪进度和管理任务执行。

    ## 何时使用此工具
    在以下场景中主动使用此工具：
    1. 收到复杂的多步骤任务时 - 立即分解为子任务
    2. 开始执行任务时 - 将任务标记为 in_progress
    3. 完成任务后 - 将任务标记为 completed
    4. 遇到错误时 - 将任务标记为 failed 并记录错误

    ## 任务状态管理
    1. **任务状态**: 使用这些状态来跟踪进度：
       - pending: 任务尚未开始
       - in_progress: 当前正在执行（同一时间最多3个）
       - completed: 任务成功完成
       - failed: 任务遇到错误

    2. **任务管理规则**:
       - 实时更新任务状态
       - 同一时间最多1个任务处于 in_progress
       - 必须按顺序处理任务
       - 任务失败时，标记为 failed 并包含错误详情

    3. **任务完成要求**:
       - 只有在完全完成时才标记为 completed
       - 如果遇到错误，标记为 failed
       - 绝不要在以下情况标记为 completed：
         * 实现不完整
         * 遇到未解决的错误
         * 找不到必要的文件或依赖


    Args:
    items: 任务对象列表。每个对象必须严格包含以下键：
           - 'id': 任务编号 (如 "1")
           - 'text': 任务描述内容
           - 'status': 状态，只能是 "pending", "in_progress", "completed","failed"之一。
    """
    status_headers = {
        "in_progress": "🔄进行中:",
        "pending": "⏳待处理:",
        "completed": "✅已完成:",
        "failed": "❌失败:",
    }
    # 2. 逐行构造结果
    lines = []
    for item in items:
        raw_status = item.get("status", "❌error")
        # 获取对应的标题，如果模型传错了，保底显示 pending
        header = status_headers.get(raw_status, "❌error")

        tid = item.get("id", "❌id?")
        text = item.get("text", "❌无内容")

        # 拼接成你要求的格式：状态标题 + #ID + 内容
        lines.append(f"{header} #{tid} {text}")

    if not lines:
        return "任务列表为空。"

    summary = "\n".join(lines)
    return f"--- 当前任务面板 ---\n{summary}"


# =============================================================================================
# 2.2 调用工具，实现子agent功能
# =============================================================================================
from image_agent import create_image_subgraph
from search_agent import create_search_subgraph
from langchain_core.messages import AIMessage


@tool
async def task_tool(description: str, subagent_type: str) -> str:
    """委派复杂的专项任务给专家处理。"""

    # 1. 映射专家类型到对应的工厂函数
    subgraph_factories = {
        "search_agent": create_search_subgraph,
        "image_agent": create_image_subgraph,
    }

    if subagent_type not in subgraph_factories:
        return f"Error: 找不到专家 '{subagent_type}'"

    DB_URI = "redis://localhost:6379"
    # 2. 统一处理异步上下文
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        # 这里不需要手动 setup，async with 自动做了
        factory = subgraph_factories[subagent_type]
        agent = await factory(checkpointer=saver)

        # 统一的配置
        thread_id = f"{subagent_type}_test_001"
        config = {"configurable": {"thread_id": thread_id}}

        print(f"\n\033[35m[系统] >>> 子 Agent ({subagent_type}) 开始工作...\033[0m")

        full_output = ""
        # 3. 统一的流式处理逻辑
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content=description)]},
            config,
            stream_mode="updates",
        ):
            for node, data in chunk.items():
                print(f"  \033[34m└─ [{subagent_type}.{node}]\033[0m 正在处理...")
                if "messages" in data:
                    for msg in data["messages"]:
                        if isinstance(msg, AIMessage):
                            if msg.content:
                                print(f"    \033[37m思考: {msg.content[:50]}...\033[0m")
                            if msg.tool_calls:
                                for tc in msg.tool_calls:
                                    print(f"    \033[32m工具调用: {tc['name']}\033[0m")
                            full_output = msg.content

        return f"--- SubAgent [{subagent_type}] 执行报告 ---\n\n{full_output}"


tools = [todo_manager, task_tool]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)
# =============================================================================================
# 3. 定义状态
# =============================================================================================


import operator
from langchain_core.messages import BaseMessage
from typing import Annotated, List, TypedDict


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    current_todo: List[dict]


# =============================================================================================
# 4. 定义主agent调用逻辑
# =============================================================================================

from typing import Dict
import json
from langchain_core.messages import SystemMessage


async def call_model(state: AgentState) -> Dict:
    """主 Agent (Manager) 节点：负责分析、规划、委派"""
    todo_status = json.dumps(state.get("current_todo", []), ensure_ascii=False)

    system_prompt = SystemMessage(
        content=(
            f"你是一个城市治理分析专家\n"
            f"当前任务计划进度: {todo_status}\n\n"
            "核心操作守则：\n"
            "1. 规划优先：面对复杂任务，必须先调用 'todo_manager' 编排分步计划。\n"
            "2. 专家委派：你自己不直接完成任务。请通过调用工具完成任务：\n"
            "   - 需要查看地图、下载卫星影像、对比地理变化、获取地理位置等场景 -> 调用 'image_agent'\n"
            "   - 需要搜索资料、查询信息、了解某个主题、获取最新新闻等场景 -> 调用 'search_agent'\n"
            "3. 状态闭环：开始执行步骤前更新为 'in_progress'，完成后更新为 'completed'。\n"
        )
    )

    messages = state["messages"]

    # 异步调用模型
    response = await model_with_tools.ainvoke([system_prompt] + messages)
    return {"messages": [response]}


# =============================================================================================
# 5. 定义子agent调用逻辑
# =============================================================================================

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langchain_core.messages import HumanMessage, ToolMessage

# =============================================================================================
# 6. 定义全局状态图
# =============================================================================================
from langgraph.graph import StateGraph, START, END
from typing import Literal


async def execute_tools(state: AgentState) -> Dict:
    """工具分发节点：异步执行工具并反馈结果"""
    last_message = state["messages"][-1]
    updates = {"messages": []}

    if hasattr(last_message, "tool_calls"):
        for tool_call in last_message.tool_calls:
            name = tool_call["name"]
            print(f"\n\033[33m[Manager 正在分派工具: {name}]\033[0m")

            use_tool = tools_by_name[name]
            try:
                # 异步执行工具
                observation = await use_tool.ainvoke(tool_call["args"])
                # 输出截断保护
                if isinstance(observation, str) and len(observation) > 10000:
                    observation = observation[:10000] + "\n... (内容过长，已自动截断)"
            except Exception as e:
                observation = f"Error executing {name}: {e}"

            updates["messages"].append(
                ToolMessage(content=str(observation), tool_call_id=tool_call["id"])
            )
    return updates


def should_continue(state: AgentState) -> Literal["tools", "END"]:
    last_message = state["messages"][-1]
    # 检查这个消息是否有 tool_calls 属性，且列表不为空
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "END"


config = {"configurable": {"thread_id": "main_test_001"}}
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", execute_tools)

workflow.add_edge(START, "agent")
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {"tools": "tools", "END": END},  # 如果有工具调用，去搜索节点  # 如果没有，结束
)
workflow.add_edge("tools", "agent")

app = workflow.compile()
# 这里的 app 是代码里编译后的工作流对象
png_data = app.get_graph(xray=True).draw_mermaid_png()
with open("my_agent_graph.png", "wb") as f:
    f.write(png_data)


async def main():
    query = "请你根据2020和2025的卫星变化图，介绍北邮沙河校区近几年的发展"
    inputs = {"messages": [HumanMessage(content=query)], "current_todo": []}

    async for chunk in app.astream(inputs, stream_mode="updates", version="v2"):
        if "data" in chunk:
            # 2. 遍历 data 里的所有节点更新（比如 'agent'）
            # .items()是字典（dict）的一个非常重要的方法。它的作用是让你同时拿到字典的“钥匙”（Key）和“柜子里的东西”（Value）。
            for node_name, node_update in chunk["data"].items():
                # 3. 检查该节点是否更新了 messages
                if "messages" in node_update:
                    # 4. 遍历消息列表
                    for msg in node_update["messages"]:
                        # 5. 只有消息对象才能调用 pretty_print
                        print(
                            f"\n================================= 节点 [{node_name}] 输出 ==============================="
                        )
                        msg.pretty_print()


if __name__ == "__main__":
    import asyncio

    print(
        "\033[32m=============================== Nano Claude Code智能体 ================================= \033[0m"
    )
    asyncio.run(main())
