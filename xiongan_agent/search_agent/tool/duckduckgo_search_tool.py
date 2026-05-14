from ddgs import DDGS
import datetime
import json
from pathlib import Path
from langchain_core.tools import tool
from langgraph.types import interrupt as lg_interrupt

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


def make_search_tool(round_counter: list):
    """
    工厂函数：创建带轮次追踪的多源搜索工具。

    round_counter: 长度为 1 的列表 [已用轮次]，
                   每次 create_search_subgraph() 调用时传入新的 [0] 以重置。
    """

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
        if round_counter[0] >= MAX_ROUNDS:
            # 暂停图执行，等待用户提供关键词
            user_keywords: str = lg_interrupt(
                f"search_agent 已完成 {MAX_ROUNDS} 轮搜索。\n"
                f"请输入强制搜索关键词（2-3个词，空格分隔），模型将直接使用这些关键词再搜索一轮："
            )
            query = _trim_query(str(user_keywords).strip())
            print(f"\n{BOLD}{'━' * 52}{RESET}")
            print(f"{BOLD}  🔑 强制搜索（用户提供）| 关键词: {query}{RESET}")
            print(f"{BOLD}{'━' * 52}{RESET}")
        else:
            round_counter[0] += 1
            query = _trim_query(query)
            print(f"\n{BOLD}{'━' * 52}{RESET}")
            print(f"{BOLD}  🔍 第 {round_counter[0]}/{MAX_ROUNDS} 轮搜索 | 关键词: {query}{RESET}")
            print(f"{BOLD}{'━' * 52}{RESET}")

        all_results: list = []
        seen_hrefs: set = set()

        for source_name, site_filter in _SOURCES:
            q = f"{query} {site_filter}".strip() if site_filter else query
            print(f"  [{source_name}] 搜索中...", end=" ", flush=True)
            results = _ddgs_text(q, max_results=5)
            added = 0
            expected_domain = site_filter.replace("site:", "") if site_filter else ""
            for r in results:
                href = r.get("href", "")
                if not href or href in seen_hrefs:
                    continue
                # 若有域名过滤，丢弃不匹配的结果（DuckDuckGo site: 并不可靠）
                if expected_domain and expected_domain not in href:
                    continue
                seen_hrefs.add(href)
                r["source"] = source_name
                all_results.append(r)
                added += 1
            print(f"获得 {added} 条去重结果")

        total = len(all_results)
        round_label = f"{round_counter[0]}/{MAX_ROUNDS}" if round_counter[0] <= MAX_ROUNDS else "强制"
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
