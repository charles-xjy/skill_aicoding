"""连接远程 MCP 服务器并获取动态工具"""
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
from dotenv import load_dotenv

load_dotenv()


async def get_baidu_tools():
    mcp_servers = {
        "amap-maps": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@baidumap/mcp-server-baidu-map"],
            "env": {
                "BAIDU_MAP_API_KEY": f"{os.getenv("BAIDU_API_KEY")}"
            }
        }
    }
    client = MultiServerMCPClient(mcp_servers)
    try:
        tools = await client.get_tools()
        print(tools)
    except Exception as e:
        print(f"[!] MCP 连接失败: {e}")
    return tools


if __name__ == "__main__":
    asyncio.run(get_baidu_tools())
