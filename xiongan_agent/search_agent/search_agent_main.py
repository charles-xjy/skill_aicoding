import asyncio
import datetime
from typing import Annotated

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

try:
    from xiongan_agent.memory_manager import DB_URI, make_sub_thread_id
except ModuleNotFoundError:
    from memory_manager import DB_URI, make_sub_thread_id
from .tool import make_search_tool, make_baidu_search_tool

DDGS_MAX = 2
BAIDU_MAX = 1

system_prompt = """# Role: 深度信息调研专家 (Search & Retrieval Agent)

## 核心约束
1. **单工具调用**：每次只调用一个搜索工具，等待结果返回后再决定下一步。
2. **缺口驱动**：每次搜索前，先明确"我需要了解XX方面的信息"，再搜索。

## 搜索工具说明
搜索工具会自动完成"搜索 → 相关性筛选 → 抓取全文 → 提炼摘要"全流程，
直接返回带编号的内容摘要：

```
[1] 标题 - https://url1.com

摘要内容...

---

[2] 标题 - https://url2.com

摘要内容...
```

可用工具由系统根据已用轮次自动控制：
- `duckduckgo_search`：Google + Wikipedia，优先使用，最多 **2 轮**
- `baidu_search`：百度，ddgs 耗尽后系统自动开放，最多 **1 轮**
- 两者均耗尽时系统不再提供工具，**停止调用工具**，系统将自动进入总结节点

## 工作流程

### 第一步：缺口分析
- 我已掌握：[已知事实，首轮可为空]
- 我需要了解：[具体信息缺口]
- 搜索关键词：[2-3 个词]

### 第二步：搜索
调用当前可用的搜索工具，每次只调用一个，关键词 2-3 个词。

### 第三步：整合信息
阅读摘要，写出推理：> 根据 [1]，XX 表明 YY。
- 缺口已填补 → **停止调用工具**，输出一句话说明已收集到足够信息，系统将进入总结节点
- 仍有缺口且有可用工具 → 回到第一步"""

summarize_prompt = """你是深度研究报告撰写专家。上方对话包含了完整的搜索过程与搜索结果。

请基于所有搜索结果，撰写一份完整的最终报告。

## 格式要求
- 每句话末尾嵌入 `[n]`（精确到每句，不允许段落末尾统一标注）
- 来源列表放最后

## 示例
## 搜索发现
雄安新区于2024年8月发布《关于支持低空经济产业发展的若干措施》[1]，文号雄安政办字〔2024〕26号[1]。
该政策对eVTOL企业给予实缴资本1%的奖励，上限1000万元[1]。

## 来源
[1] 标题 - https://url1.com
[2] 标题 - https://url2.com"""


# ── State ────────────────────────────────────────────────────────────────────

class SearchAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    ddgs_rounds: int
    baidu_rounds: int


# ── 子图工厂 ──────────────────────────────────────────────────────────────────

async def create_search_subgraph(checkpointer=None):
    """
    构建搜索子图。
    - ddgs_rounds / baidu_rounds 存于 State，call_model 根据计数动态绑定工具。
    - 工具执行由 ToolNode 负责；计数更新在单独的 update_counters 节点。
    - 当 ddgs 耗尽、baidu 未用时，使用 tool_choice="required" 强制调用 baidu_search。
    """
    try:
        from xiongan_agent.model_probe import make_vllm_model
    except ModuleNotFoundError:
        from model_probe import make_vllm_model
    base_model = await make_vllm_model()

    ddgs_tool = make_search_tool(base_model)
    baidu_tool = make_baidu_search_tool(base_model)
    all_tools = [ddgs_tool, baidu_tool]

    # ── 节点：调用模型（按剩余轮次动态绑定工具）────────────────────────────
    def call_model(state: SearchAgentState):
        if state["ddgs_rounds"] < DDGS_MAX:
            # ddgs 还有余量：提供两个工具，模型自由选择
            bound = base_model.bind_tools(all_tools, parallel_tool_calls=False)
        elif state["baidu_rounds"] < BAIDU_MAX:
            # ddgs 耗尽、baidu 未用：强制调用 baidu_search
            bound = base_model.bind_tools(
                [baidu_tool],
                tool_choice="required",
                parallel_tool_calls=False,
            )
        else:
            # 所有轮次耗尽，模型只能输出最终报告
            bound = base_model

        response = bound.invoke(
            [SystemMessage(content=system_prompt)] + state["messages"]
        )
        return {"messages": [response]}

    # ── 节点：更新轮次计数（在 ToolNode 之后）───────────────────────────────
    def update_counters(state: SearchAgentState):
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                ddgs_delta = sum(1 for tc in msg.tool_calls if tc["name"] == ddgs_tool.name)
                baidu_delta = sum(1 for tc in msg.tool_calls if tc["name"] == baidu_tool.name)
                new_ddgs = state["ddgs_rounds"] + ddgs_delta
                new_baidu = state["baidu_rounds"] + baidu_delta
                print(f"  [搜索轮次] ddgs={new_ddgs}/{DDGS_MAX}  baidu={new_baidu}/{BAIDU_MAX}")
                return {"ddgs_rounds": new_ddgs, "baidu_rounds": new_baidu}
        return {}

    # ── 节点：总结（信息充足后生成最终报告）────────────────────────────────
    def summarize(state: SearchAgentState):
        response = base_model.invoke(
            [SystemMessage(content=summarize_prompt)] + state["messages"]
        )
        return {"messages": [response]}

    # ── 路由 ─────────────────────────────────────────────────────────────────
    def should_continue(state: SearchAgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return "summarize"

    # ── 构建图 ────────────────────────────────────────────────────────────────
    graph = StateGraph(SearchAgentState)
    graph.add_node("call_model", call_model)
    graph.add_node("tools", ToolNode(all_tools))
    graph.add_node("update_counters", update_counters)
    graph.add_node("summarize", summarize)

    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", should_continue, ["tools", "summarize"])
    graph.add_edge("tools", "update_counters")
    graph.add_edge("update_counters", "call_model")
    graph.add_edge("summarize", END)

    return graph.compile(checkpointer=checkpointer)


# ── 独立运行入口 ──────────────────────────────────────────────────────────────

async def run_as_standalone():
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        agent = await create_search_subgraph(checkpointer=saver)

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        thread_id = f"main_search_{ts}"
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {
            "messages": [HumanMessage(content="请介绍雄安新区最新的低空经济政策")],
            "ddgs_rounds": 0,
            "baidu_rounds": 0,
        }

        print(f"独立智能体模式启动... thread_id={thread_id}")

        async for chunk in agent.astream(inputs, config, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                if "messages" in node_update:
                    for msg in node_update["messages"]:
                        print(f"\n--- [{node_name}] ---")
                        msg.pretty_print()


# ── 作为子图节点 ──────────────────────────────────────────────────────────────

async def search_agent_node(state, config):
    """当被主图调用时，作为主图的一个节点，返回最终 AIMessage。"""
    async with AsyncRedisSaver.from_conn_string(DB_URI) as sub_saver:
        agent = await create_search_subgraph(checkpointer=sub_saver)

        parent_thread = config["configurable"].get("thread_id", "default")
        sub_thread_id = make_sub_thread_id("search_agent", parent_thread)
        sub_config = {"configurable": {"thread_id": sub_thread_id}}

        inputs = {
            "messages": [state["messages"][-1]],
            "ddgs_rounds": 0,
            "baidu_rounds": 0,
        }

        async for chunk in agent.astream(inputs, sub_config, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                if "messages" in node_update:
                    for msg in node_update["messages"]:
                        print(f"\n--- [搜索Agent/{node_name}] ---")
                        msg.pretty_print()

        result = await agent.aget_state(sub_config)
        all_msgs = result.values.get("messages", [])
        final = next(
            (m for m in reversed(all_msgs)
             if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)),
            all_msgs[-1] if all_msgs else None,
        )
        return {"messages": [final]} if final else {"messages": []}


async def visualize():
    import os
    output_path = os.path.abspath("search_agent_graph.png")
    agent = await create_search_subgraph(checkpointer=None)
    try:
        png_data = agent.get_graph(xray=True).draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png_data)
        print(f"图已保存为 {output_path}")
        os.startfile(output_path)
    except Exception as e:
        print(f"可视化失败: {e}")


if __name__ == "__main__":
    import os
    import sys

    if "--visualize" in sys.argv:
        asyncio.run(visualize())
    else:
        asyncio.run(run_as_standalone())
    os._exit(0)
