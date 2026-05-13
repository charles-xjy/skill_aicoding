"""
search_agent 的命令行入口，供 Cowork skill 通过 bash 调用。

用法：
    python -m search_agent.run_cli <搜索主题>

示例：
    python -m search_agent.run_cli 雄安新区最新规划进展
    python -m search_agent.run_cli "2024年北京空气质量报告"
"""

import asyncio
import hashlib
import sys

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from .search_agent_main import create_search_subgraph


async def run(query: str) -> None:
    db_uri = "redis://localhost:6379"

    # 用 query 的 MD5 前 8 位生成唯一 thread_id
    # 同一查询复用历史缓存；不同查询互相隔离
    thread_id = "skill_search_" + hashlib.md5(query.encode()).hexdigest()[:8]

    async with AsyncRedisSaver.from_conn_string(db_uri) as saver:
        agent = await create_search_subgraph(checkpointer=saver)
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {"messages": [HumanMessage(content=query)]}

        async for chunk in agent.astream(
            inputs, config, stream_mode="updates", version="v2"
        ):
            if chunk["type"] == "updates":
                for _, node_update in chunk["data"].items():
                    if "messages" in node_update:
                        for msg in node_update["messages"]:
                            content = getattr(msg, "content", "")
                            if content:
                                print(content, flush=True)


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "错误：缺少搜索主题\n用法：python -m search_agent.run_cli <搜索主题>",
            file=sys.stderr,
        )
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    asyncio.run(run(query))


if __name__ == "__main__":
    main()
