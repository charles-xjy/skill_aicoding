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
from .tool import make_baidu_search_tool

MAX_ROUNDS = 3

system_prompt = """# Role: 深度信息调研专家 (Search Agent)

## 核心约束
1. **单工具调用**：每次只调用一个搜索工具，等待结果返回后再决定下一步。
2. **缺口驱动**：每次搜索前，先明确"我需要了解XX方面的信息"，再搜索。

## 搜索工具说明
`baidu_search` 工具会自动完成"百度搜索 → MCP 抓取全文 → 摘要"全流程，
直接返回带编号的内容摘要：

```
[1] 标题 - https://url1.com

摘要内容...

---

[2] 标题 - https://url2.com

摘要内容...
```

- 最多可调用 **{max_rounds} 轮**
- 轮次耗尽后系统不再提供工具，**停止调用工具**，将自动进入总结节点

## 工作流程

### 第一步：缺口分析
- 我已掌握：[已知事实，首轮可为空]
- 我需要了解：[具体信息缺口]
- 搜索关键词：2-3 个中文词

### 第二步：搜索
调用 `baidu_search`，每次只调用一次，关键词 2-3 个词。

### 第三步：整合信息
阅读摘要，写出推理：> 根据 [1]，XX 表明 YY。
- 缺口已填补 → **停止调用工具**，输出一句话说明已收集到足够信息，系统将进入总结节点
- 仍有缺口且有剩余轮次 → 回到第一步""".format(max_rounds=MAX_ROUNDS)

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
    rounds: int


# ── 子图工厂 ──────────────────────────────────────────────────────────────────

async def create_search_subgraph(checkpointer=None):
    """构建搜索子图，只使用百度搜索工具。"""
    try:
        from xiongan_agent.model_probe import make_vllm_model
    except ModuleNotFoundError:
        from model_probe import make_vllm_model
    base_model = await make_vllm_model()

    baidu_tool = make_baidu_search_tool(base_model)

    # ── 节点：调用模型 ────────────────────────────────────────────────────────
    async def call_model(state: SearchAgentState):
        if state["rounds"] < MAX_ROUNDS:
            bound = base_model.bind_tools([baidu_tool], parallel_tool_calls=False)
            print(f"  \033[2m⏳ 正在分析查询，规划搜索策略...\033[0m", flush=True)
        else:
            bound = base_model
            print(f"  \033[2m⏳ 搜索轮次已满，正在生成最终报告...\033[0m", flush=True)

        response = await bound.ainvoke(
            [SystemMessage(content=system_prompt)] + state["messages"]
        )
        return {"messages": [response]}

    # ── 节点：更新轮次计数 ────────────────────────────────────────────────────
    def update_rounds(state: SearchAgentState):
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                delta = len(msg.tool_calls)
                new_rounds = state["rounds"] + delta
                print(f"  [搜索轮次] {new_rounds}/{MAX_ROUNDS}")
                return {"rounds": new_rounds}
        return {}

    # ── 节点：总结 ────────────────────────────────────────────────────────────
    async def summarize(state: SearchAgentState):
        print(f"  \033[2m⏳ 搜索完成，正在撰写最终报告...\033[0m", flush=True)
        # 在末尾追加明确指令，防止思考模型把所有 token 消耗在 <think> 上而不输出正文
        direct_msg = HumanMessage(
            content="请直接输出最终报告正文，不要输出推理过程，从 ## 搜索发现 开始写。"
        )
        response = await base_model.ainvoke(
            [SystemMessage(content=summarize_prompt)] + state["messages"] + [direct_msg]
        )
        raw = response.content if isinstance(response.content, str) else ""

        # 取 </think> 之后的正文
        if "</think>" in raw:
            content = raw.split("</think>", 1)[-1].strip()
        else:
            content = raw.strip()

        # 尝试从 additional_kwargs 取 reasoning_content（部分 API 将思考内容独立返回）
        if not content:
            ak = getattr(response, "additional_kwargs", {}) or {}
            rc = ak.get("reasoning_content", "").strip()
            if rc:
                if "</think>" in rc:
                    content = rc.split("</think>", 1)[-1].strip()
                if not content:
                    content = rc  # 思考内容本身也比空好

        # 最终兜底：raw 原文（含推理，总比空好）
        if not content and raw:
            content = raw

        if not content:
            print("  \033[31m⚠️  summarize 模型返回空内容，请检查模型配置\033[0m", flush=True)
        return {"messages": [AIMessage(content=content)]}

    # ── 路由 ─────────────────────────────────────────────────────────────────
    def should_continue(state: SearchAgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "tools"
        return "summarize"

    # ── 构建图 ────────────────────────────────────────────────────────────────
    graph = StateGraph(SearchAgentState)
    graph.add_node("call_model", call_model)
    graph.add_node("tools", ToolNode([baidu_tool]))
    graph.add_node("update_rounds", update_rounds)
    graph.add_node("summarize", summarize)

    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", should_continue, ["tools", "summarize"])
    graph.add_edge("tools", "update_rounds")
    graph.add_edge("update_rounds", "call_model")
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
            "rounds": 0,
        }

        print(f"独立智能体模式启动... thread_id={thread_id}")

        async for chunk in agent.astream(inputs, config, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                if "messages" in node_update:
                    for msg in node_update["messages"]:
                        print(f"\n--- [{node_name}] ---")
                        msg.pretty_print()


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