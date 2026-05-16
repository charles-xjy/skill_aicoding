import asyncio
import os
import json
import datetime
from pathlib import Path
from mcp import ClientSession
from mcp.client.sse import sse_client
from dotenv import load_dotenv
import nest_asyncio

load_dotenv()

# 模块加载时就 patch，允许在已运行的事件循环（LangGraph 的异步上下文）里嵌套调用
nest_asyncio.apply()

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

_SAVE_DIR = Path(__file__).resolve().parent.parent / "search_result" / "baidu_mcp"

def _save_result(query: str, data: any):
    """保存 MCP 原始响应到本地 JSON 文件以便调试"""
    try:
        _SAVE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = _SAVE_DIR / f"{query}_mcp_{ts}.json"
        
        # 处理 MCP 响应对象的序列化
        output_data = {}
        if hasattr(data, "content"):
            output_data["content"] = [
                {"type": block.type, "text": block.text} if hasattr(block, "text") else str(block)
                for block in data.content
            ]
        else:
            output_data = str(data)

        with open(fname, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  {DIM}[百度MCP] 结果保存失败: {e}{RESET}")

async def call_baidu_aisearch(query: str, max_results: int = 10) -> list:
    """
    异步调用百度 AppBuilder MCP AIsearch 工具。
    """
    api_key = os.getenv("BAIDU_API_KEY")
    if not api_key:
        print(f"  {BOLD}[!] 错误: 未找到 BAIDU_API_KEY，请检查 .env 文件{RESET}")
        return []

    # 百度 AppBuilder MCP SSE 终端地址
    url = f"https://appbuilder.baidu.com/v2/ai_search/mcp/sse?api_key=Bearer+{api_key}"
    
    results = []
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                # 1. 初始化会话
                await session.initialize()
                
                # 2. 调用 AIsearch 工具
                # resource_type_filter: web (网页), image (图片), video (视频)
                mcp_result = await session.call_tool("AIsearch", arguments={
                    "query": query,
                    "resource_type_filter": [{"type": "web", "top_k": max_results}]
                })
                
                # 3. 保存原始结果
                _save_result(query, mcp_result)
                
                # 4. 解析结果
                if mcp_result.content:
                    for block in mcp_result.content:
                        if block.type != "text":
                            continue
                        text_content = block.text.strip()

                        # 优先尝试 JSON 格式
                        if text_content.startswith("{") or text_content.startswith("["):
                            try:
                                data = json.loads(text_content)
                                items = data if isinstance(data, list) else (
                                    data.get("references") or data.get("search_results") or []
                                )
                                for item in items:
                                    results.append({
                                        "title": item.get("title") or "",
                                        "href": item.get("url") or "",
                                        "body": (item.get("content") or item.get("snippet") or "")[:800],
                                        "source": "百度MCP"
                                    })
                                if results:
                                    continue
                            except json.JSONDecodeError:
                                pass

                        # 百度 AIsearch 实际返回 "Title: ...\nContent: ...\nURL: ...\n" 块
                        import re
                        pattern = re.compile(
                            r"Title:\s*(?P<title>[^\n]+)\nContent:\s*(?P<body>.*?)\nURL:\s*(?P<href>[^\n]*)",
                            re.DOTALL
                        )
                        for m in pattern.finditer(text_content):
                            results.append({
                                "title": m.group("title").strip(),
                                "href": m.group("href").strip(),
                                "body": m.group("body").strip()[:800],
                                "source": "百度MCP"
                            })

                        # 兜底：整块文本作为单条结果
                        if not results:
                            results.append({
                                "title": f"百度搜索: {query}",
                                "href": "",
                                "body": text_content[:800],
                                "source": "百度MCP"
                            })
                return results
    except Exception as e:
        print(f"  [百度MCP] 请求失败: {e}")
        return []

def baidu_mcp_search_sync(query: str, max_results: int = 5) -> list:
    """
    同步包装器，方便集成到现有的 LangGraph 工具中。
    nest_asyncio 已在模块加载时 apply，支持在已运行的事件循环（LangGraph）里嵌套调用。
    """
    print(f"\n{BOLD}{'━' * 52}{RESET}")
    print(f"{BOLD}  🔄 调用百度 AppBuilder MCP | 关键词: {query}{RESET}")
    print(f"{BOLD}{'━' * 52}{RESET}")

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # 在已运行的事件循环里（LangGraph --allow-blocking 模式）
            results = loop.run_until_complete(call_baidu_aisearch(query, max_results))
        else:
            # 纯同步环境（直接 python 运行脚本）
            results = asyncio.run(call_baidu_aisearch(query, max_results))

        if results:
            print(f"  [百度MCP] 获得 {len(results)} 条结果")
        else:
            print(f"  [百度MCP] 未返回有效结果")
        return results
    except Exception as e:
        print(f"  [百度MCP] 同步调用异常: {e}")
        return []

if __name__ == "__main__":
    # 测试脚本
    test_query = "北京交通大学雄安校区建设进展"
    r = baidu_mcp_search_sync(test_query)
    print("\n--- 最终格式化结果 ---")
    print(json.dumps(r, ensure_ascii=False, indent=2))
