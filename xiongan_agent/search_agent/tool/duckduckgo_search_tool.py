from ddgs import DDGS
import datetime
import hashlib
import json
import re
import threading
from pathlib import Path
from langchain_core.tools import tool
from langchain_core.callbacks.manager import dispatch_custom_event
from langgraph.types import interrupt as lg_interrupt
from .baidu_mcp_search import baidu_mcp_search_sync

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

MAX_ROUNDS = 3

# DDG 站点过滤来源（英文/通用查询兜底用）
_DDG_SOURCES = [
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


def _is_chinese(text: str) -> bool:
    """判断字符串是否包含中文字符。"""
    return bool(re.search(r'[一-鿿]', text))


def _ddgs_text(query: str, max_results: int = 5) -> list:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, region='cn-zh', timelimit='y', max_results=max_results))
    except Exception as e:
        print(f"  ⚠️  DDGS 请求失败: {e}")
        return []


def _is_high_quality(result: dict) -> bool:
    """排除垃圾域名、无意义内容。"""
    href = result.get("href", "").lower()
    body = (result.get("body", "") or result.get("snippet", "")).lower()
    title = result.get("title", "").lower()

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
    if "site owner hides" in body or "forbidden" in body or "access restriction" in body:
        return False
    if title in ["google", "youtube", "baidu", "404", "index", "首页", "登录"]:
        return False
    return True


def _ddgs_search_with_site(query: str, source_name: str, site_filter: str, max_results: int = 3) -> list:
    """DDG 站点过滤搜索，不再 fallback 百度（百度由上层统一调用）。"""
    q = f"{query} {site_filter}".strip() if site_filter else query
    print(f"  [{source_name}] DDG 搜索中...", end=" ", flush=True)
    raw = _ddgs_text(q, max_results=max_results)
    results = [r for r in raw if _is_high_quality(r)]
    if site_filter:
        domains = [d.strip() for d in site_filter.replace("site:", "").split("OR")]
        results = [r for r in results if any(d in r.get("href", "") for d in domains)]
    print(f"获得 {len(results)} 条")
    return results


def make_search_tool(round_counter: list):
    """
    工厂函数：创建带轮次追踪、MD5 缓存的多源搜索工具。

    round_counter: [已用轮次]，每次 create_search_subgraph() 传入新的 [0] 重置。
    """
    _lock = threading.Lock()
    _cache: dict[str, list] = {}  # MD5(query) → results，避免重复搜索同一关键词

    @tool
    def duckduckgo_search(query: str) -> str:
        """
        多源联网搜索工具，每次调用视为一轮，最多 3 轮。
        中文查询优先走百度 MCP（精准），不足时补充 DDG 站点过滤。

        Args:
            query: 2-3 个精准关键词，例如"北邮 沙河 发展"，严禁传入完整句子。

        Returns:
            JSON 字符串，每项包含 title、href、body、source 字段。
        """
        # ── 缓存命中：相同 query 直接返回，不消耗搜索轮次 ──────────────────────
        cache_key = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
        with _lock:
            if cache_key in _cache:
                print(f"\n  💾 缓存命中：{query}，跳过网络请求")
                return json.dumps(_cache[cache_key], ensure_ascii=False)

        # ── 轮次管理 ──────────────────────────────────────────────────────────
        with _lock:
            over_limit = round_counter[0] >= MAX_ROUNDS
            if not over_limit:
                round_counter[0] += 1
                current_round = round_counter[0]

        if over_limit:
            user_keywords: str = lg_interrupt(
                f"search_agent 已完成 {MAX_ROUNDS} 轮搜索。\n"
                f"请输入新的搜索关键词（2-3个词），或输入「结束」直接输出现有内容："
            )
            user_keywords = str(user_keywords).strip()
            if user_keywords in ("结束", "done", ""):
                return json.dumps([], ensure_ascii=False)
            query = _trim_query(user_keywords)
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

        def _add_results(new_results: list, source_tag: str = ""):
            for r in new_results:
                if len(all_results) >= 3:
                    break
                href = r.get("href", "")
                # 无 URL 的结果（百度摘要型）也收录，但每 source 最多 1 条
                if href and href in seen_hrefs:
                    continue
                if href:
                    seen_hrefs.add(href)
                if source_tag:
                    r["source"] = source_tag
                all_results.append(r)

        # ── 策略1：中文查询 → 百度 MCP 优先 ────────────────────────────────
        if _is_chinese(query):
            print(f"  [百度MCP] 中文查询优先...", end=" ", flush=True)
            baidu_results = baidu_mcp_search_sync(query, max_results=5)
            print(f"获得 {len(baidu_results)} 条")
            _add_results(baidu_results, "百度MCP")

        # ── 策略2：不足 3 条时，DDG 站点过滤补充 ───────────────────────────
        if len(all_results) < 3:
            for source_name, site_filter in _DDG_SOURCES:
                if len(all_results) >= 3:
                    break
                results = _ddgs_search_with_site(query, source_name, site_filter, max_results=3)
                _add_results(results, source_name)

        # ── 打印本轮摘要 ─────────────────────────────────────────────────────
        total = len(all_results)
        print(f"\n  第 {round_label} 轮合计 {total} 条结果（上限 3 条）")
        for i, r in enumerate(all_results, 1):
            title = r.get('title', '')
            href = r.get('href', '')
            body = (r.get('body', '') or r.get('snippet', ''))
            print(f"\n  {i}. [{r.get('source','?')}] {title}")
            print(f"     {DIM}{href}{RESET}")
            if body:
                print(f"     {body[:200]}{'...' if len(body) > 200 else ''}")

        # ── 写入缓存 ─────────────────────────────────────────────────────────
        with _lock:
            _cache[cache_key] = all_results

        # ── 保存本地 JSON ─────────────────────────────────────────────────────
        try:
            output_dir = Path(__file__).resolve().parent.parent / "search_result" / "duckduckgo"
            output_dir.mkdir(parents=True, exist_ok=True)
            date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_label = round_label.replace('/', '-')
            output_file = output_dir / f"{query}_r{safe_label}_{date_str}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  ⚠️  结果保存失败: {e}")

        result = json.dumps(all_results, ensure_ascii=False)

        # ── 推送前端事件 ──────────────────────────────────────────────────────
        try:
            dispatch_custom_event("search_round", {
                "round": current_round if not over_limit else MAX_ROUNDS + 1,
                "total": MAX_ROUNDS,
                "query": query,
                "count": total,
                "titles": [r.get("title", "")[:50] for r in all_results],
            })
        except Exception:
            pass

        # ── 第3轮后强制触发 interrupt ─────────────────────────────────────────
        if not over_limit and current_round >= MAX_ROUNDS:
            result += (
                "\n\n[SEARCH_EXHAUSTED] 三轮搜索已全部完成。"
                "你的下一个且唯一的行动是立即调用 duckduckgo_search（查询词填写空字符串即可），"
                "该工具会自动向用户请求新关键词。禁止在此之前输出任何内容。"
            )

        return result

    return duckduckgo_search