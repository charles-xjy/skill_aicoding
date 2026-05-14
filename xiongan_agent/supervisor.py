"""
================================================
LangGraph Supervisor Pattern - 规划式重构
================================================
核心流程：
1. ✅ 规划阶段：Supervisor 先将用户请求拆解为有序任务列表（1. 2. 3. ...）
2. ✅ 逐步执行：每次只执行一个任务，执行完后回到 Supervisor 确认
3. ✅ 状态追踪：每个任务有 pending / in_progress / completed / error 四种状态
4. ✅ 任务列表打印：每次状态变化后打印带图标的任务列表
5. ✅ 共享 Checkpointer：主图和子图共享同一个 Redis 连接
6. ✅ 层级 Thread ID：main_001 → sub_{agent}_of_main_001
"""

import asyncio
import operator
import json
from typing import Annotated, List, Dict, Literal, Optional, TypedDict
from datetime import datetime

# LangChain imports
from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

# LangGraph imports
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

# Subgraph imports
from image_agent import create_image_subgraph
from search_agent import create_search_subgraph
from analysis_agent import create_analysis_subgraph

# =============================================================================================
# 1. 定义模型
# =============================================================================================
model = init_chat_model(
    base_url="http://10.129.107.145:8001/v1",
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)


# =============================================================================================
# 2. State 定义
# =============================================================================================
class SupervisorState(TypedDict):
    """
    Supervisor 状态：
    - messages:            对话历史（reducer: append）
    - task_plan:           任务列表，每项: {id, description, agent, status, result}
    - current_task_index:  当前执行到第几个任务（0-based）
    - next_step:           下一步路由目标
    - execution_log:       执行日志（整体覆盖，节点自行维护）
    - retry_count:         当前任务重试次数
    """

    messages: Annotated[List[BaseMessage], operator.add]
    task_plan: List[Dict]
    current_task_index: int
    next_step: Optional[
        Literal["image_agent", "search_agent", "analysis_agent", "human_input", "supervisor", "end"]
    ]
    execution_log: List[str]
    retry_count: int


def create_supervisor_state() -> Dict:
    return {
        "messages": [],
        "task_plan": [],
        "current_task_index": 0,
        "next_step": "supervisor",
        "execution_log": [],
        "retry_count": 0,
    }


# =============================================================================================
# 3. 任务列表打印
# =============================================================================================
_STATUS_ICON = {
    "pending": "⬜",
    "in_progress": "🔄",
    "completed": "✅",
    "error": "❌",
}
_STATUS_COLOR = {
    "pending": "\033[2m",
    "in_progress": "\033[33m",
    "completed": "\033[32m",
    "error": "\033[31m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def print_task_list(task_plan: List[Dict]):
    total = len(task_plan)
    completed = sum(1 for t in task_plan if t["status"] == "completed")
    errors = sum(1 for t in task_plan if t["status"] == "error")
    err_tag = f"  {errors} 出错" if errors else ""

    print(f"\n{BOLD}{'━' * 58}{RESET}")
    print(f"{BOLD}  任务进度  {completed}/{total} 完成{err_tag}{RESET}")
    print(f"{BOLD}{'━' * 58}{RESET}")
    for t in task_plan:
        icon = _STATUS_ICON.get(t["status"], "?")
        color = _STATUS_COLOR.get(t["status"], "")
        agent_tag = f"{DIM}[{t['agent']}]{RESET}" if t.get("agent") else ""
        # 只显示 description 的第一行（\n\n 后面是追加的上下文，不展示）
        desc_first_line = t["description"].split("\n")[0][:70]
        print(f"  {icon} {color}{t['id']}. {desc_first_line}{RESET}  {agent_tag}")
        if t.get("result"):
            result_text = str(t["result"])
            # 去掉 【xxx 执行结果】\n 前缀，只展示实际内容
            if "执行结果】\n" in result_text:
                result_text = result_text.split("执行结果】\n", 1)[1]
            # 去掉 <think>...</think> 思考过程
            if "<think>" in result_text and "</think>" in result_text:
                result_text = result_text.split("</think>", 1)[-1].strip()
            snippet = result_text[:100]
            suffix = "..." if len(result_text) > 100 else ""
            print(f"       {DIM}└─ {snippet}{suffix}{RESET}")
    print(f"{BOLD}{'━' * 58}{RESET}\n")


# =============================================================================================
# 4. Supervisor 节点：规划 + 逐步调度
# =============================================================================================
async def supervisor_node(state: Dict) -> Dict:
    messages = state.get("messages", [])
    task_plan = list(state.get("task_plan", []))  # 浅拷贝，避免直接修改
    current_index = state.get("current_task_index", 0)
    execution_log = list(state.get("execution_log", []))

    # ── 规划阶段：task_plan 为空，第一次进入 ─────────────────────────────
    if not task_plan:
        system_prompt = SystemMessage(content="""
你是一个城市治理分析专家，也是一个任务规划 Supervisor。

你的职责：分析用户请求，制定一个有序的任务执行计划。

可用 Agent 及其能力说明：
- "image_agent"：获取并保存卫星影像/地图，**只返回图片本地路径，不做分析**；支持在单次调用中传入多个年份列表，一次性下载多年影像
- "search_agent"：搜索并抓取网页原始内容，**只返回原始文字资料，不做分析**
- "analysis_agent"：综合分析专家，接收前序所有结果后**输出最终分析报告**

规划原则：
- image_agent 和 search_agent 负责采集，analysis_agent 负责最终分析
- analysis_agent 必须是最后一个任务
- 不要期望 image_agent 或 search_agent 输出分析报告
- **image_agent 可以一次处理多个年份，不要为不同年份分别创建多个 image_agent 任务**；在任务描述中直接列出所有需要的年份即可

输出格式（必须严格遵守，只输出 JSON，不要有其他文字）：
```json
{
  "tasks": [
    {"id": 1, "description": "具体任务描述", "agent": "image_agent"},
    {"id": 2, "description": "具体任务描述", "agent": "search_agent"},
    {"id": 3, "description": "综合分析以上收集的材料，输出完整报告", "agent": "analysis_agent"}
  ],
  "reasoning": "简述整体规划思路"
}
```
""")
        response = await model.ainvoke([system_prompt] + messages)

        try:
            content = response.content
            start_idx = content.find("{")
            end_idx = content.rfind("}") + 1
            plan_data = (
                json.loads(content[start_idx:end_idx])
                if start_idx >= 0 and end_idx > start_idx
                else {}
            )
        except (json.JSONDecodeError, AttributeError) as e:
            plan_data = {}
            execution_log.append(f"[{datetime.now().isoformat()}] ❌ 规划解析失败: {e}")

        raw_tasks = plan_data.get("tasks", [])
        task_plan = [
            {
                "id": t.get("id", i + 1),
                "description": t.get("description", ""),
                "agent": t.get("agent", "search_agent"),
                "status": "pending",
                "result": None,
            }
            for i, t in enumerate(raw_tasks)
        ]

        if not task_plan:
            execution_log.append(
                f"[{datetime.now().isoformat()}] ❌ 规划失败，任务列表为空"
            )
            return {
                "messages": [response],
                "task_plan": [],
                "next_step": "end",
                "execution_log": execution_log,
            }

        # 第1次打印：全部 pending，展示规划结果
        log = f"[{datetime.now().isoformat()}] 📋 规划完成，共 {len(task_plan)} 个任务"
        execution_log.append(log)
        print(f"\n\033[36m{log}\033[0m")
        print_task_list(task_plan)

        # 第2次打印：第一个任务切为 in_progress
        task_plan[0]["status"] = "in_progress"
        log = f"[{datetime.now().isoformat()}] ▶️  开始任务 1: {task_plan[0]['description'][:50]}"
        execution_log.append(log)
        print(f"\n\033[36m{log}\033[0m")
        print_task_list(task_plan)

        return {
            "messages": [response],
            "task_plan": task_plan,
            "current_task_index": 0,
            "next_step": task_plan[0]["agent"],
            "execution_log": execution_log,
            "retry_count": 0,
        }

    # ── 复查阶段：子图完成后回到 Supervisor ──────────────────────────────
    # 取最新的 AI 消息作为上一任务结果
    last_result = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_result = msg.content
            break

    # 判断上一任务是否出错（子图失败时消息内容带有固定标记）
    task_failed = "执行失败" in last_result

    if current_index < len(task_plan):
        task_plan[current_index]["status"] = "error" if task_failed else "completed"
        task_plan[current_index]["result"] = last_result[:200] if last_result else ""

    # 第N次打印：当前任务标为 completed / error
    log = (
        f"[{datetime.now().isoformat()}] "
        f"{'❌' if task_failed else '✅'} "
        f"任务 {current_index + 1} {'出错' if task_failed else '完成'}: "
        f"{task_plan[current_index]['description'][:40]}"
    )
    execution_log.append(log)
    print(f"\n\033[{'31' if task_failed else '32'}m{log}{RESET}")
    print_task_list(task_plan)

    # 移动到下一个任务
    next_index = current_index + 1
    if next_index >= len(task_plan):
        log = f"[{datetime.now().isoformat()}] 🎉 所有任务执行完毕"
        execution_log.append(log)
        print(f"\n\033[32m{log}{RESET}\n")
        return {
            "task_plan": task_plan,
            "current_task_index": next_index,
            "next_step": "end",
            "execution_log": execution_log,
        }

    # analysis_agent 是最终汇总任务：收集所有前序任务的结果
    if task_plan[next_index]["agent"] == "analysis_agent":
        label_map = {
            "image_agent": "卫星影像路径",
            "search_agent": "搜索与抓取内容",
        }
        context_parts = [
            f"【任务{t['id']} - {label_map.get(t['agent'], t['agent'])}】\n{t['result']}"
            for t in task_plan[:next_index]
            if t.get("result") and t["status"] == "completed"
        ]
        if context_parts:
            task_plan[next_index]["description"] += "\n\n" + "\n\n".join(context_parts)
            log = f"[{datetime.now().isoformat()}] 📎 已将 {len(context_parts)} 个前序任务结果汇总给 analysis_agent"
            execution_log.append(log)
            print(f"\n\033[33m{log}{RESET}")
    # image_agent → 非 analysis_agent 的下一任务：只透传图片路径
    elif (
        not task_failed
        and task_plan[current_index]["agent"] == "image_agent"
        and last_result.strip()
    ):
        task_plan[next_index][
            "description"
        ] += f"\n\n【来自 image_agent 的图像路径】\n{last_result.strip()}"
        log = (
            f"[{datetime.now().isoformat()}] 📎 已将图像路径附加到任务 {next_index + 1}"
        )
        execution_log.append(log)
        print(f"\n\033[33m{log}{RESET}")

    # 第N+1次打印：下一个任务切为 in_progress
    task_plan[next_index]["status"] = "in_progress"
    log = (
        f"[{datetime.now().isoformat()}] ▶️  开始任务 {next_index + 1}: "
        f"{task_plan[next_index]['description'][:50]}"
    )
    execution_log.append(log)
    print(f"\n\033[36m{log}{RESET}")
    print_task_list(task_plan)

    return {
        "task_plan": task_plan,
        "current_task_index": next_index,
        "next_step": task_plan[next_index]["agent"],
        "execution_log": execution_log,
        "retry_count": 0,
    }


# =============================================================================================
# 5. 子图节点包装器
# =============================================================================================
async def create_subgraph_node(subgraph_name: str, checkpointer):
    """工厂函数：为每个子图创建一个节点包装器"""
    subgraph_factories = {
        "image_agent": create_image_subgraph,
        "search_agent": create_search_subgraph,
        "analysis_agent": create_analysis_subgraph,
    }
    factory = subgraph_factories[subgraph_name]

    async def subgraph_node(state: Dict, config: RunnableConfig) -> Dict:
        execution_log = list(state.get("execution_log", []))
        retry_count = state.get("retry_count", 0)

        # 从 task_plan 读取当前任务描述
        task_plan = state.get("task_plan", [])
        current_index = state.get("current_task_index", 0)
        task_description = (
            task_plan[current_index]["description"]
            if task_plan and current_index < len(task_plan)
            else "无任务"
        )

        parent_thread_id = config.get("configurable", {}).get("thread_id", "default")
        sub_thread_id = f"sub_{subgraph_name}_of_{parent_thread_id}"
        sub_config = {"configurable": {"thread_id": sub_thread_id}}

        log_entry = (
            f"[{datetime.now().isoformat()}] 🚀 启动 {subgraph_name} | {sub_thread_id}"
        )
        execution_log.append(log_entry)
        print(f"\n\033[35m{log_entry}{RESET}")

        try:
            subgraph = await factory(checkpointer=checkpointer)
            inputs = {"messages": [HumanMessage(content=task_description)]}

            result = None
            async for chunk in subgraph.astream(
                inputs, sub_config, stream_mode="updates", version="v2"
            ):
                for node_name, node_data in chunk.get("data", {}).items():
                    if "messages" in node_data:
                        result = node_data

            if result and "messages" in result:
                last_msg = result["messages"][-1]
                response_content = (
                    last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                )

                log_entry = f"[{datetime.now().isoformat()}] ✅ {subgraph_name} 完成 | 结果长度: {len(response_content)}"
                execution_log.append(log_entry)
                print(f"\n\033[32m{log_entry}{RESET}")

                return {
                    "messages": [
                        AIMessage(
                            content=f"【{subgraph_name} 执行结果】\n{response_content}",
                            metadata={
                                "source": subgraph_name,
                                "thread_id": sub_thread_id,
                            },
                        )
                    ],
                    "next_step": "supervisor",
                    "execution_log": execution_log,
                    "retry_count": 0,
                }

        except Exception as e:
            error_msg = (
                f"[{datetime.now().isoformat()}] ❌ {subgraph_name} 执行失败: {e}"
            )
            execution_log.append(error_msg)
            print(f"\n\033[31m{error_msg}{RESET}")

            if retry_count < 2:
                log_entry = f"[{datetime.now().isoformat()}] 🔄 重试 {subgraph_name} ({retry_count + 1}/3)"
                execution_log.append(log_entry)
                print(f"\n\033[33m{log_entry}{RESET}")
                return {"execution_log": execution_log, "retry_count": retry_count + 1}

            # 3次均失败
            if subgraph_name == "search_agent":
                log_entry = f"[{datetime.now().isoformat()}] ⏸️  search_agent 3次重试均失败，等待用户提供关键词"
                execution_log.append(log_entry)
                print(f"\n\033[33m{log_entry}{RESET}")
                return {
                    "execution_log": execution_log,
                    "next_step": "human_input",
                    "retry_count": 0,
                }

            return {
                "messages": [
                    AIMessage(
                        content=f"【{subgraph_name} 执行失败】\n多次重试后仍然失败: {e}"
                    )
                ],
                "next_step": "supervisor",
                "execution_log": execution_log,
                "retry_count": 0,
            }

        return {"next_step": "supervisor", "execution_log": execution_log}

    return subgraph_node


# =============================================================================================
# 6. 条件路由
# =============================================================================================
def should_continue(state: Dict) -> str:
    next_step = state.get("next_step", "end")
    route_map = {
        "image_agent": "image_agent",
        "search_agent": "search_agent",
        "analysis_agent": "analysis_agent",
        "human_input": "human_input",
        "end": END,
    }
    return route_map.get(next_step, END)


def search_agent_routing(state: Dict) -> str:
    """search_agent 完成后：3次失败则转 human_input，否则回 supervisor。"""
    return "human_input" if state.get("next_step") == "human_input" else "supervisor"


# =============================================================================================
# 7. Human-in-the-loop：用户补充搜索关键词
# =============================================================================================
async def human_input_node(state: Dict) -> Dict:
    task_plan = list(state.get("task_plan", []))
    current_index = state.get("current_task_index", 0)
    execution_log = list(state.get("execution_log", []))

    current_desc = ""
    if task_plan and current_index < len(task_plan):
        current_desc = task_plan[current_index]["description"].split("\n")[0][:80]

    # 暂停图执行，等待用户输入
    user_keywords: str = interrupt(
        f"search_agent 经过 3 次重试仍然失败。\n"
        f"当前任务：{current_desc}\n"
        f"请输入搜索关键词，agent 将强制使用这些关键词进行搜索（多个关键词用逗号分隔）："
    )

    # 将用户关键词追加到任务描述，供 search_agent 使用
    if task_plan and current_index < len(task_plan):
        task_plan[current_index] = dict(task_plan[current_index])
        task_plan[current_index]["description"] += (
            f"\n\n【强制搜索指令】前几次搜索已失败。"
            f"你必须严格使用以下关键词调用搜索工具，不得自行修改或替换：\n{user_keywords}"
        )
        task_plan[current_index]["status"] = "in_progress"

    log = f"[{datetime.now().isoformat()}] 🔑 用户提供了新关键词: {str(user_keywords)[:60]}"
    execution_log.append(log)
    print(f"\n\033[36m{log}{RESET}")
    print_task_list(task_plan)

    return {
        "task_plan": task_plan,
        "next_step": "search_agent",
        "execution_log": execution_log,
        "retry_count": 0,
    }


# =============================================================================================
# 8. 构建 Supervisor 图
# =============================================================================================
async def create_supervisor_graph(checkpointer):
    """
    创建并编译 Supervisor 图。
    checkpointer 为 None 时可用于可视化（不需要 Redis）。
    """
    workflow = StateGraph(SupervisorState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("human_input", human_input_node)

    image_node = await create_subgraph_node("image_agent", checkpointer)
    search_node = await create_subgraph_node("search_agent", checkpointer)
    analysis_node = await create_subgraph_node("analysis_agent", checkpointer)
    workflow.add_node("image_agent", image_node)
    workflow.add_node("search_agent", search_node)
    workflow.add_node("analysis_agent", analysis_node)

    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        should_continue,
        {
            "image_agent": "image_agent",
            "search_agent": "search_agent",
            "analysis_agent": "analysis_agent",
            "human_input": "human_input",
            END: END,
        },
    )
    workflow.add_edge("image_agent", "supervisor")
    # search_agent 正常完成 → supervisor；3次失败 → human_input
    workflow.add_conditional_edges(
        "search_agent",
        search_agent_routing,
        {"supervisor": "supervisor", "human_input": "human_input"},
    )
    workflow.add_edge("human_input", "search_agent")  # 用户提供关键词后重新搜索
    workflow.add_edge("analysis_agent", "supervisor")

    return workflow.compile(checkpointer=checkpointer)


# =============================================================================================
# 9. 主函数
# =============================================================================================
async def main():
    db_uri = "redis://10.129.107.145:6379"
    thread_id = "main_001"

    print(
        "\n\033[32m════════════════════ 创建 Supervisor 图 ════════════════════\033[0m"
    )
    async with AsyncRedisSaver.from_conn_string(db_uri) as checkpointer:
        graph = await create_supervisor_graph(checkpointer)

        initial_state = create_supervisor_state()
        initial_state["messages"] = [
            HumanMessage(
                content="请你根据2020和2025的卫星变化图，介绍北邮沙河校区近几年的发展"
            )
        ]
        config = {"configurable": {"thread_id": thread_id}}

        print("\n\033[32m════════════════════ 开始执行 ════════════════════\033[0m")
        final_report = ""

        # ── 阶段1：正常运行，直到遇到 interrupt ──────────────────────────────
        interrupted = False
        async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
            if "__interrupt__" in chunk:
                prompt = chunk["__interrupt__"][0].value
                print(f"\n\033[33m{'━' * 58}\033[0m")
                print(f"\033[33m  图执行已暂停（search_agent 3次失败）\033[0m")
                print(f"\033[33m  {prompt}\033[0m")
                print(f"\033[33m{'━' * 58}\033[0m")
                user_keywords = input("\n>>> 请输入关键词: ").strip()
                if not user_keywords:
                    user_keywords = "北邮沙河 2025 建设"
                interrupted = True
                break

            for node_name, node_data in chunk.items():
                if "messages" in node_data:
                    for msg in node_data["messages"]:
                        if node_name == "analysis_agent" and hasattr(msg, "content"):
                            final_report = msg.content

        # ── 阶段2：用 Command(resume=...) 恢复执行（如果发生过中断）─────────
        if interrupted:
            from langgraph.types import Command
            print(f"\n\033[36m[恢复] 以关键词「{user_keywords}」继续执行...\033[0m")
            async for chunk in graph.astream(
                Command(resume=user_keywords), config, stream_mode="updates"
            ):
                for node_name, node_data in chunk.items():
                    if "messages" in node_data:
                        for msg in node_data["messages"]:
                            if node_name == "analysis_agent" and hasattr(msg, "content"):
                                final_report = msg.content

    print("\n\033[32m════════════════════ 执行完毕 ════════════════════\033[0m")

    # 打印最终分析报告（去掉 <think>...</think> 部分）
    if final_report:
        if "<think>" in final_report or "</think>" in final_report:
            final_report = final_report.split("</think>", 1)[-1].strip()

        print(f"\n\033[1;32m{'═' * 60}\033[0m")
        print(f"\033[1;32m  最终分析报告\033[0m")
        print(f"\033[1;32m{'═' * 60}\033[0m")
        print(final_report)
        print(f"\033[1;32m{'═' * 60}\033[0m\n")


# =============================================================================================
# 10. 可视化
# =============================================================================================
async def visualize_graph():
    """生成图的可视化并自动打开（无需 Redis）"""
    import os

    output_path = os.path.abspath("supervisor_graph.png")

    graph = await create_supervisor_graph(checkpointer=None)
    try:
        png_data = graph.get_graph(xray=True).draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png_data)
        print(f"✅ 图已保存为 {output_path}")
        os.startfile(output_path)
    except Exception as e:
        print(f"⚠️ 可视化失败: {e}")


# =============================================================================================
# 运行入口
# =============================================================================================
if __name__ == "__main__":
    print(
        "\n\033[1;32m╔════════════════════════════════════════════════════════════╗\033[0m"
    )
    print(
        "\033[1;32m║   LangGraph Supervisor Pattern - 城市治理分析智能体        ║\033[0m"
    )
    print(
        "\033[1;32m╚════════════════════════════════════════════════════════════╝\033[0m"
    )

    asyncio.run(main())
    asyncio.run(visualize_graph())
