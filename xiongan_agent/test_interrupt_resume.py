"""
测试 human_input 中断节点的完整恢复流程：
1. 正常启动图，流式接收输出
2. 检测到 __interrupt__ 事件后，从终端读取用户输入
3. 用 Command(resume=...) + 相同 config 恢复图执行
"""

import asyncio
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.types import Command

from supervisor import create_supervisor_graph, create_supervisor_state

DB_URI = "redis://127.0.0.1:6390"
THREAD_ID = "interrupt_test_001"


async def run():
    config = {"configurable": {"thread_id": THREAD_ID}}

    async with AsyncRedisSaver.from_conn_string(DB_URI) as checkpointer:
        graph = await create_supervisor_graph(checkpointer)

        initial_state = create_supervisor_state()
        initial_state["messages"] = [
            HumanMessage(content="请搜索北邮沙河校区2025年最新建设进展")
        ]

        final_report = ""
        interrupted = False

        # ── 阶段1：正常运行，直到遇到 interrupt ──────────────────────────────
        print("\n\033[36m[阶段1] 启动图执行...\033[0m")
        async for chunk in graph.astream(initial_state, config, stream_mode="updates"):

            if "__interrupt__" in chunk:
                # interrupt() 触发：chunk["__interrupt__"] 是 Interrupt 对象的 tuple
                prompt = chunk["__interrupt__"][0].value
                print(f"\n\033[33m{'━'*58}\033[0m")
                print(f"\033[33m  图执行已暂停\033[0m")
                print(f"\033[33m  {prompt}\033[0m")
                print(f"\033[33m{'━'*58}\033[0m")

                user_keywords = input("\n>>> 请输入关键词: ").strip()
                if not user_keywords:
                    user_keywords = "北邮沙河 2025 建设"  # 兜底默认值

                interrupted = True
                break  # 退出阶段1循环，进入阶段2

            for node_name, node_data in chunk.items():
                if "messages" in node_data:
                    for msg in node_data["messages"]:
                        if node_name == "analysis_agent" and hasattr(msg, "content"):
                            final_report = msg.content

        # ── 阶段2：用 Command(resume=...) 恢复执行 ───────────────────────────
        if interrupted:
            print(f"\n\033[36m[阶段2] 以关键词「{user_keywords}」恢复执行...\033[0m")
            async for chunk in graph.astream(
                Command(resume=user_keywords), config, stream_mode="updates"
            ):
                for node_name, node_data in chunk.items():
                    if "messages" in node_data:
                        for msg in node_data["messages"]:
                            if node_name == "analysis_agent" and hasattr(msg, "content"):
                                final_report = msg.content

    # ── 打印最终报告 ─────────────────────────────────────────────────────────
    if final_report:
        if "<think>" in final_report:
            final_report = final_report.split("</think>", 1)[-1].strip()
        print(f"\n\033[1;32m{'═'*60}\033[0m")
        print(f"\033[1;32m  最终分析报告\033[0m")
        print(f"\033[1;32m{'═'*60}\033[0m")
        print(final_report)
        print(f"\033[1;32m{'═'*60}\033[0m\n")


if __name__ == "__main__":
    asyncio.run(run())
