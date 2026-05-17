"""连接远程 MCP 服务器并获取动态工具"""
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio
from dotenv import load_dotenv

load_dotenv()


async def get_gaode_tools():
    api_key = os.getenv('GAODE_API_KEY')
    if not api_key:
        print("[!] 警告: 未找到 GAODE_API_KEY，将跳过高德地图工具。")
        return []
        
    mcp_servers = {
        "amap-maps": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@amap/amap-maps-mcp-server"],
            "env": {
                "AMAP_MAPS_API_KEY": f"{os.getenv('GAODE_API_KEY')}"
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
    asyncio.run(get_gaode_tools())
