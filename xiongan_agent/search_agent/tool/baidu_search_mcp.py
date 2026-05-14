"""
百度 AppBuilder 搜索工具（百度百科 + 百度搜索）
免费额度：1500 次/月（按天发放）
当 DuckDuckGo 返回空结果时作为备用搜索源。
"""
import os
import json
import datetime
import requests
from pathlib import Path
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

_SAVE_DIR = Path(__file__).resolve().parent.parent / "search_result" / "baidu_appbuilder"
_API_KEY  = lambda: os.getenv("BAIDU_API_KEY", "")
_HEADERS  = lambda: {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {_API_KEY()}",
}


def _save_result(query: str, source: str, data: dict):
    try:
        _SAVE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y年%m月%d日_%H%M%S")
        fname = _SAVE_DIR / f"{query}_{source}_{ts}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  {DIM}[百度] 结果保存失败: {e}{RESET}")


def _baidu_baike(query: str) -> list:
    """百度百科词条检索，返回 DDGS 兼容格式列表。"""
    params = {"search_type": "lemmaTitle", "search_key": query}
    url = f"https://appbuilder.baidu.com/v2/baike/lemma/get_content?{urlencode(params)}"
    try:
        resp = requests.get(url, headers=_HEADERS(), data=b'""', timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        _save_result(query, "baike", data)

        results = []
        # AppBuilder 百科返回结构：data.result 或 data.results 列表
        items = data.get("result") or data.get("results") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            title = item.get("lemmaTitle") or item.get("title") or query
            href  = item.get("url") or item.get("lemmaUrl") or ""
            body  = (item.get("lemmaMainContent") or item.get("summary")
                     or item.get("content") or "")[:500]
            results.append({"title": title, "href": href, "body": body, "source": "百度百科"})
        return results
    except Exception as e:
        print(f"  [百度百科] 请求失败: {e}")
        return []


def _baidu_web_search(query: str) -> list:
    """百度网页搜索，返回 DDGS 兼容格式列表。"""
    params = {"search_type": "normal", "search_key": query}
    url = f"https://appbuilder.baidu.com/v2/search/get_content?{urlencode(params)}"
    try:
        resp = requests.get(url, headers=_HEADERS(), data=b'""', timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        _save_result(query, "websearch", data)

        results = []
        items = data.get("result") or data.get("results") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            title = item.get("title") or ""
            href  = item.get("url") or item.get("link") or ""
            body  = (item.get("content") or item.get("summary") or item.get("body") or "")[:500]
            if title or href:
                results.append({"title": title, "href": href, "body": body, "source": "百度搜索"})
        return results
    except Exception as e:
        print(f"  [百度搜索] 请求失败: {e}")
        return []


def baidu_search_fallback(query: str, max_results: int = 5) -> list:
    """
    同步入口：先调百度网页搜索，无结果再调百度百科。
    供 duckduckgo_search_tool 在 DDGS 返回空结果时调用。
    """
    print(f"\n{BOLD}{'━' * 52}{RESET}")
    print(f"{BOLD}  🔄 切换至百度 AppBuilder | 关键词: {query}{RESET}")
    print(f"{BOLD}{'━' * 52}{RESET}")

    # 1. 先试网页搜索
    results = _baidu_web_search(query)
    if results:
        print(f"  [百度搜索] 获得 {len(results)} 条结果")
        return results[:max_results]

    # 2. 再试百科
    print(f"  [百度搜索] 无结果，尝试百度百科...")
    results = _baidu_baike(query)
    if results:
        print(f"  [百度百科] 获得 {len(results)} 条结果")
    else:
        print(f"  [百度百科] 亦无结果")
    return results[:max_results]


if __name__ == "__main__":
    r = baidu_search_fallback("北京邮电大学沙河校区")
    print(json.dumps(r, ensure_ascii=False, indent=2))
