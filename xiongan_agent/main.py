"""
xiongan_agent 启动入口

用法：
  python main.py                    # 交互式输入问题后运行
  python main.py "你的问题"          # 直接传入问题
  python main.py --visualize        # 生成图结构可视化
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from datetime import datetime
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from supervisor_agent import create_supervisor_graph, create_supervisor_state

DB_URI = "redis://10.129.107.145:6379"

RESET = "\033[0m"


async def run(query: str):
    thread_id = f"main_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print("\n\033[32m════════════════════ 创建 Supervisor 图 ════════════════════\033[0m")
    async with AsyncRedisSaver.from_conn_string(DB_URI) as checkpointer:
        graph = await create_supervisor_graph(checkpointer)

        initial_state = create_supervisor_state()
        initial_state["messages"] = [HumanMessage(content=query)]
        config = {"configurable": {"thread_id": thread_id}}

        print("\n\033[32m════════════════════ 开始执行 ════════════════════\033[0m")
        final_report = ""

        async for chunk in graph.astream(initial_state, config, stream_mode="updates"):
            for node_name, node_data in chunk.items():
                if "messages" in node_data:
                    for msg in node_data["messages"]:
                        if node_name == "analysis_agent" and hasattr(msg, "content"):
                            final_report = msg.content

    print("\n\033[32m════════════════════ 执行完毕 ════════════════════\033[0m")

    if final_report:
        if "<think>" in final_report or "</think>" in final_report:
            final_report = final_report.split("</think>", 1)[-1].strip()
        print(f"\n\033[1;32m{'═' * 60}{RESET}")
        print(f"\033[1;32m  最终分析报告{RESET}")
        print(f"\033[1;32m{'═' * 60}{RESET}")
        print(final_report)
        print(f"\033[1;32m{'═' * 60}{RESET}\n")


async def visualize():
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


if __name__ == "__main__":
    print("\n\033[1;32m╔════════════════════════════════════════════════════════════╗\033[0m")
    print("\033[1;32m║   LangGraph Supervisor Pattern - 城市治理分析智能体        ║\033[0m")
    print("\033[1;32m╚════════════════════════════════════════════════════════════╝\033[0m")

    if "--visualize" in sys.argv:
        asyncio.run(visualize())
    else:
        query = " ".join(sys.argv[1:]).strip()
        if not query:
            query = input("请输入你的问题: ").strip()
        if not query:
            print("未输入问题，已退出。")
            sys.exit(0)
        asyncio.run(run(query))

# 我想要了解北邮沙河校区2020、2025的发展情况