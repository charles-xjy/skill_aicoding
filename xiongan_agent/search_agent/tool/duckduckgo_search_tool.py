from ddgs import DDGS
import datetime
import json
from pathlib import Path
from langchain_core.tools import tool
from langgraph.types import interrupt as lg_interrupt
from .baidu_mcp_search import baidu_mcp_search_sync

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

MAX_ROUNDS = 3

# 每轮依次从以下来源搜索
_SOURCES = [
    ("教育官方", "site:edu.cn"),
    ("雄安官网", "site:xiongan.gov.cn"),
    ("权威媒体", "site:news.cn OR site:people.com.cn OR site:chinanews.com OR site:jstv.com"),
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
            # 使用 region='cn-zh' 优化中文搜索结果，timelimit='y' 限制在一年内
            return list(ddgs.text(query, region='cn-zh', timelimit='y', max_results=max_results))
    except Exception as e:
        print(f"  ⚠️  DDGS 请求失败: {e}")
        return []


def _is_high_quality(result: dict) -> bool:
    """判断搜索结果是否为高质量（排除常见的门户首页、占位符、境外无关媒体等）。"""
    title = result.get("title", "").lower()
    href = result.get("href", "").lower()
    body = (result.get("body", "") or result.get("snippet", "")).lower()

    # 1. 排除境外无关媒体、社交平台、非大陆房地产/生活类网站、以及垃圾站点
    irrelevant_domains = [
        "bbc.com", "nytimes.com", "voachinese.com", "rfa.org",
        "facebook.com", "twitter.com", "instagram.com", "youtube.com",
        "housefeel.com.tw", "mobile01.com", "ptt.cc",
        "twitcasting.tv", "cccgg49.com", "51cg",
        "map.baidu.com", "v.qq.com/404"
    ]
    for domain in irrelevant_domains:
        if domain in href:
            return False

    # 2. 排除极其简短或无意义的标题/描述
    if "site owner hides" in body or "forbidden" in body or "access restriction" in body:
        return False
    
    if title in ["google", "youtube", "baidu", "404", "index", "首页", "登录"]:
        return False

    return True


def _search_with_fallback(query: str, source_name: str, site_filter: str, max_results: int = 5) -> list:
    """先用 DDGS 搜索；若返回空结果或全是低质量结果，自动切换到百度 MCP 搜索。"""
    q = f"{query} {site_filter}".strip() if site_filter else query
    print(f"  [{source_name}] 搜索中...", end=" ", flush=True)

    raw_results = _ddgs_text(q, max_results=max_results)
    
    # 过滤结果
    results = [r for r in raw_results if _is_high_quality(r)]

    if site_filter:
        expected_domain = site_filter.replace("site:", "")
        # 处理可能的 OR 查询
        expected_domains = [d.strip() for d in expected_domain.split("OR")]
        results = [r for r in results if any(d in r.get("href", "") for d in expected_domains)]

    if results and len(results) >= 1: # 至少有 1 条高质量结果才认为成功
        print(f"获得 {len(results)} 条结果")
        return results

    # DDGS 结果不足或全是垃圾 → 切换百度 MCP
    if raw_results:
        print(f"{len(raw_results)} 条结果均为低质量，切换百度搜索...")
    else:
        print(f"0 条结果，切换百度搜索...")
        
    baidu_results = baidu_mcp_search_sync(query, max_results=max_results)
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

    @tool
    def duckduckgo_search(query: str) -> str:
        """
        多源联网搜索工具，每次调用视为一轮，最多 3 轮。
        每轮自动依次搜索「教育官方 / 雄安官网 / 权威媒体 / 百度百科」四个来源并合并去重。

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
