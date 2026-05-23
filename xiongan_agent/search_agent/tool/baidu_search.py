'''
百度搜索工具
优先使用百度 AppBuilder MCP（AIsearch），不可用时降级到 AppBuilder REST API。
'''

import asyncio
import datetime
import json
import os
import re
import threading
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

import nest_asyncio
from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.tools import tool
from .fetch_web_content import fetch_and_summarize_sync

load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")
nest_asyncio.apply()

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

_SAVE_DIR = Path(__file__).parent.parent / "search_result" / "baidu"


def _save_result(query: str, source: str, data) -> None:
    try:
        _SAVE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = _SAVE_DIR / f"{query}_{source}_{ts}.json"
        if hasattr(data, "content"):
            out = {"content": [
                {"type": b.type, "text": b.text} if hasattr(b, "text") else str(b)
                for b in data.content
            ]}
        else:
            out = data if isinstance(data, (dict, list)) else str(data)
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  {DIM}[百度] 结果保存失败: {e}{RESET}")


# ── MCP 搜索（主路径）────────────────────────────────────────────────────────

async def _mcp_search(query: str, max_results: int = 5) -> list:
    api_key = os.getenv("BAIDU_API_KEY")
    if not api_key:
        print(f"  {BOLD}[!] 未找到 BAIDU_API_KEY{RESET}")
        return []
    url = f"https://appbuilder.baidu.com/v2/ai_search/mcp/sse?api_key=Bearer+{api_key}"
    results = []
    try:
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_result = await session.call_tool("AIsearch", arguments={
                    "query": query,
                    "resource_type_filter": [{"type": "web", "top_k": max_results}]
                })
                _save_result(query, "mcp", mcp_result)
                if not mcp_result.content:
                    return []
                for block in mcp_result.content:
                    if block.type != "text":
                        continue
                    text = block.text.strip()
                    # JSON 格式
                    if text.startswith(("{", "[")):
                        try:
                            data = json.loads(text)
                            items = data if isinstance(data, list) else (
                                data.get("references") or data.get("search_results") or []
                            )
                            for item in items:
                                results.append({
                                    "title": item.get("title") or "",
                                    "href": item.get("url") or "",
                                    "body": (item.get("content") or item.get("snippet") or "")[:800],
                                    "source": "百度MCP",
                                })
                            if results:
                                continue
                        except json.JSONDecodeError:
                            pass
                    # 文本块格式（Title: / Content: / URL:）
                    pattern = re.compile(
                        r"Title:\s*(?P<title>[^\n]+)\nContent:\s*(?P<body>.*?)\nURL:\s*(?P<href>[^\n]*)",
                        re.DOTALL,
                    )
                    for m in pattern.finditer(text):
                        results.append({
                            "title": m.group("title").strip(),
                            "href": m.group("href").strip(),
                            "body": m.group("body").strip()[:800],
                            "source": "百度MCP",
                        })
                    if not results:
                        results.append({
                            "title": f"百度搜索: {query}",
                            "href": "",
                            "body": text[:800],
                            "source": "百度MCP",
                        })
        return results
    except Exception as e:
        print(f"  [百度MCP] 请求失败: {e}")
        return []


def _mcp_search_sync(query: str, max_results: int = 5) -> list:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        return loop.run_until_complete(_mcp_search(query, max_results))
    return asyncio.run(_mcp_search(query, max_results))


# ── AppBuilder REST（降级路径）──────────────────────────────────────────────

def _rest_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('BAIDU_API_KEY', '')}",
    }


def _rest_search(query: str) -> list:
    url = "https://appbuilder.baidu.com/v2/ai_search/web_search"
    payload = {"messages": [{"role": "user", "content": query}], "search_source": "baidu_search_v2"}
    try:
        resp = requests.post(url, headers=_rest_headers(), json=payload, timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        _save_result(query, "rest", data)
        results = []
        for item in (data.get("references") or data.get("search_results") or []):
            title = item.get("title") or ""
            href  = item.get("url") or ""
            body  = (item.get("content") or item.get("snippet") or "")[:800]
            if title or href:
                results.append({"title": title, "href": href, "body": body, "source": "百度REST"})
        return results
    except Exception as e:
        print(f"  [百度REST] 请求失败: {e}")
        return []


# ── 工具工厂 ─────────────────────────────────────────────────────────────────

def _score_and_select(results: list, query: str, model, n: int = 2) -> list:
    """LLM 评分，从搜索结果中选出与 query 最相关的 n 条。"""
    fetchable = [r for r in results if r.get("href")]
    if len(fetchable) <= n:
        return fetchable
    items = []
    for i, r in enumerate(fetchable, 1):
        title = r.get("title", "")
        body = (r.get("body", "") or r.get("snippet", ""))[:300]
        items.append(f"[{i}] 标题: {title}\n摘要: {body}")
    from langchain_core.messages import HumanMessage
    prompt = (
        f"查询: {query}\n\n"
        f"以下是 {len(fetchable)} 条搜索结果，请选出与查询最相关的 {n} 条。\n"
        f"仅输出所选结果的编号，用逗号分隔，格式严格为: selected: 1,3\n\n"
        + "\n\n".join(items)
    )
    try:
        resp = model.invoke([HumanMessage(content=prompt)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        m = re.search(r"selected\s*:\s*([\d,\s]+)", text, re.IGNORECASE)
        if not m:
            m = re.search(r"([\d]+(?:\s*,\s*[\d]+)+)", text)
        if m:
            indices = [int(x.strip()) for x in m.group(1).split(",") if x.strip().isdigit()]
            chosen = [fetchable[i - 1] for i in indices if 1 <= i <= len(fetchable)]
            if chosen:
                print(f"  {DIM}[评分] 选中第 {[i for i in indices if 1 <= i <= len(fetchable)]} 条{RESET}")
                return chosen[:n]
    except Exception as e:
        print(f"  ⚠️  相关性评分失败: {e}")
    return fetchable[:n]


def make_baidu_search_tool(model):
    """
    工厂函数：创建百度搜索工具。
    优先走 MCP AIsearch，失败时降级到 AppBuilder REST，自动抓取 top 2 URL 并生成摘要。
    轮次计数由子图 State 管理，工具本身不含计数逻辑。
    """
    _call_count = [0]

    @tool
    def baidu_search(query: str) -> str:
        """
        补充搜索工具（百度），自动抓取前两条结果全文并提炼摘要。
        仅在 duckduckgo_search 不可用时由系统开放此工具。

        Args:
            query: 2-3 个精准中文关键词，例如"雄安新区 建设进展 2024"

        Returns:
            带编号的内容摘要，格式：[1] 标题 - URL\\n\\n摘要...\\n---\\n[2] 标题 - URL\\n\\n摘要...
        """
        _call_count[0] += 1

        print(f"\n{BOLD}{'━' * 52}{RESET}")
        print(f"{BOLD}  🔍 百度搜索 第 {_call_count[0]} 次 | 关键词: {query}{RESET}")
        print(f"{BOLD}{'━' * 52}{RESET}")

        results = _mcp_search_sync(query, max_results=5)
        if not results:
            print(f"  [百度MCP] 无结果，降级到 AppBuilder REST...")
            results = _rest_search(query)

        total = len(results)
        print(f"  [百度] 获得 {total} 条结果")

        try:
            dispatch_custom_event("search_round", {
                "query": query,
                "count": total,
                "titles": [r.get("title", "")[:50] for r in results],
            })
        except Exception:
            pass

        fetchable = _score_and_select(results, query, model)
        sections = []
        for i, r in enumerate(fetchable, 1):
            url   = r["href"]
            title = r.get("title", "")
            print(f"\n  📥 [{i}/2] 抓取: {url}")
            fetched = fetch_and_summarize_sync(url, model, query=query)
            if fetched:
                _, summary = fetched
                sections.append(f"[{i}] {title} - {url}\n\n{summary}")
            else:
                body = r.get("body") or r.get("snippet") or ""
                print(f"  ⚠️  [{i}] 抓取失败，降级使用搜索摘要（长度 {len(body)} 字）")
                sections.append(f"[{i}] {title} - {url}\n\n{body}")

        return "\n\n---\n\n".join(sections) if sections else "[无可用结果]"

    return baidu_search
