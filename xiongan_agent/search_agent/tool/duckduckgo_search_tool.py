from ddgs import DDGS
import datetime
import json
import threading
from pathlib import Path
from langchain_core.tools import tool
from langgraph.types import interrupt as lg_interrupt
from .baidu_search_mcp import baidu_search_fallback

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

MAX_ROUNDS = 3

# 每轮依次从三个来源搜索，site_filter 为空表示通用搜索
_SOURCES = [
    ("通用",    ""),
    ("百度百科", "site:baike.baidu.com"),
]


def _trim_query(query: str, max_terms: int = 3) -> str:
    query = query.strip()
    parts = query.split()
    if len(parts) > max_terms:
        trimmed = " ".join(parts[:max_terms])
        print(f"  ⚠️  搜索词过多（{len(parts)}个），已截断为：{trimmed}")
        return trimmed
    if len(parts) == 1 and len(query) > 12:
        trimmed = query[:12]
        print(f"  ⚠️  搜索词过长，已截断为：{trimmed}")
        return trimmed
    return query


def _ddgs_text(query: str, max_results: int = 5) -> list:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"  ⚠️  DDGS 请求失败: {e}")
        return []


def _search_with_fallback(query: str, source_name: str, site_filter: str, max_results: int = 5) -> list:
    """先用 DDGS 搜索；若返回空结果，自动切换到百度 MCP 搜索。"""
    q = f"{query} {site_filter}".strip() if site_filter else query
    print(f"  [{source_name}] 搜索中...", end=" ", flush=True)

    results = _ddgs_text(q, max_results=max_results)

    if site_filter:
        expected_domain = site_filter.replace("site:", "")
        results = [r for r in results if expected_domain in r.get("href", "")]

    if results:
        print(f"获得 {len(results)} 条结果")
        return results

    # DDGS 返回空 → 切换百度 MCP
    print(f"0 条结果，切换百度搜索...")
    baidu_results = baidu_search_fallback(query, max_results=max_results)
    if baidu_results:
        print(f"  [百度MCP] 获得 {len(baidu_results)} 条结果")
    else:
        print(f"  [百度MCP] 亦无结果")
    return baidu_results


def make_search_tool(round_counter: list):
    """
    工厂函数：创建带轮次追踪的多源搜索工具。

    round_counter: 长度为 1 的列表 [已用轮次]，
                   每次 create_search_subgraph() 调用时传入新的 [0] 以重置。
    """
    _lock = threading.Lock()  # 保护 check+increment 原子性，防止并行工具调用竞态

    @tool
    def duckduckgo_search(query: str) -> str:
        """
        多源联网搜索工具，每次调用视为一轮，最多 3 轮。
        每轮自动并发搜索「通用 / 百度百科 / 中文维基百科」三个来源并合并去重。

        Args:
            query: 2-3 个精准关键词，例如"北邮 沙河 发展"，严禁传入完整句子。

        Returns:
            JSON 字符串，每项包含 title、href、body、source 字段。
        """
        # 原子化：在 lock 内完成 check + increment，避免并行调用拿到相同轮次编号
        with _lock:
            over_limit = round_counter[0] >= MAX_ROUNDS
            if not over_limit:
                round_counter[0] += 1
                current_round = round_counter[0]

        if over_limit:
            # 暂停图执行，等待用户提供关键词
            user_keywords: str = lg_interrupt(
                f"search_agent 已完成 {MAX_ROUNDS} 轮搜索。\n"
                f"请输入强制搜索关键词（2-3个词，空格分隔），模型将直接使用这些关键词再搜索一轮："
            )
            query = _trim_query(str(user_keywords).strip())
            round_label = "强制"
            print(f"\n{BOLD}{'━' * 52}{RESET}")
            print(f"{BOLD}  🔑 强制搜索（用户提供）| 关键词: {query}{RESET}")
            print(f"{BOLD}{'━' * 52}{RESET}")
        else:
            query = _trim_query(query)
            round_label = f"{current_round}/{MAX_ROUNDS}"
            print(f"\n{BOLD}{'━' * 52}{RESET}")
            print(f"{BOLD}  🔍 第 {round_label} 轮搜索 | 关键词: {query}{RESET}")
            print(f"{BOLD}{'━' * 52}{RESET}")

        all_results: list = []
        seen_hrefs: set = set()

        for source_name, site_filter in _SOURCES:
            results = _search_with_fallback(query, source_name, site_filter, max_results=5)
            added = 0
            for r in results:
                href = r.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                r["source"] = source_name
                all_results.append(r)
                added += 1

        total = len(all_results)
        print(f"\n  第 {round_label} 轮合计 {total} 条结果")
        if total:
            for i, r in enumerate(all_results[:5], 1):
                title = r.get('title', '')
                body = r.get('body', '') or r.get('snippet', '')
                href = r.get('href', '')
                print(f"\n  {i}. [{r.get('source','?')}] {title}")
                print(f"     {DIM}{href}{RESET}")
                if body:
                    print(f"     {body[:200]}{'...' if len(body) > 200 else ''}")

        # 保存到本地 JSON
        try:
            output_dir = Path(__file__).resolve().parent.parent / "search_result" / "duckduckgo"
            output_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = output_dir / f"{query}_r{round_label.replace('/', '-')}_{date_str}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  ⚠️  结果保存失败: {e}")

        return json.dumps(all_results, ensure_ascii=False)

    return duckduckgo_search
