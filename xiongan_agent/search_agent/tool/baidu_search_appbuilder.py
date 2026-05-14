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
        resp = requests.get(url, headers=_HEADERS(), timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        _save_result(query, "baike", data)

        results = []
        # 兼容新旧结构
        res_obj = data.get("result")
        if res_obj:
            title = res_obj.get("lemma_title") or query
            href  = res_obj.get("url") or ""
            body  = (res_obj.get("abstract_plain") or res_obj.get("summary") or "")[:1000]
            results.append({"title": title, "href": href, "body": body, "source": "百度百科"})
        elif data.get("code") == 0 or "lemmaTitle" in data:
            title = data.get("lemmaTitle") or query
            href  = data.get("url") or ""
            body  = (data.get("lemmaMainContent") or data.get("summary") or "")[:800]
            results.append({"title": title, "href": href, "body": body, "source": "百度百科"})
        return results
    except Exception as e:
        print(f"  [百度百科] 请求失败: {e}")
        return []


def _baidu_web_search(query: str) -> list:
    """百度网页搜索 (AppBuilder v2/ai_search/web_search)，返回 DDGS 兼容格式列表。"""
    url = "https://appbuilder.baidu.com/v2/ai_search/web_search"
    payload = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2"
    }
    try:
        resp = requests.post(url, headers=_HEADERS(), json=payload, timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        _save_result(query, "websearch", data)

        results = []
        # 兼容 references 和 search_results
        items = data.get("references") or data.get("search_results") or []
        for item in items:
            title = item.get("title") or ""
            href  = item.get("url") or ""
            body  = (item.get("content") or item.get("snippet") or "")[:800]
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
