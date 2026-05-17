"""连接远程 MCP 服务器并获取动态工具"""
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
from dotenv import load_dotenv

load_dotenv()


async def get_baidu_tools():
    api_key = os.getenv('BAIDU_MAP_AK')
    if not api_key:
        print("[!] 警告: 未找到 BAIDU_MAP_AK，将跳过百度地图工具。")
        return []

    mcp_servers = {
        "amap-maps": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@baidumap/mcp-server-baidu-map"],
            "env": {
                "BAIDU_MAP_API_KEY": api_key
            }
        }
    }
    client = MultiServerMCPClient(mcp_servers)
    try:
        return await client.get_tools()
    except Exception as e:
        print(f"[!] MCP 连接失败: {e}")
        return []


if __name__ == "__main__":
    asyncio.run(get_baidu_tools())
