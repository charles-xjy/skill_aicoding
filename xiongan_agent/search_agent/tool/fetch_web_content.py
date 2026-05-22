import asyncio
import re
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _strip_thinking(text: str) -> str:
    """剥离 Qwen3 等思考模型的 <think>...</think> 推理块，只保留最终回复。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</think>", "", text)
    return text.strip()


async def _fetch_raw(url: str) -> str:
    """通过 MCP Fetch Server 抓取网页原始 Markdown 内容。"""
    server_params = StdioServerParameters(
        command="npx", args=["-y", "mcp-server-fetch-typescript"]
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_markdown_summary", arguments={"url": url})
            if result.content and len(result.content[0].text) > 100:
                content = result.content[0].text
                _save_raw(url, content)
                return content
            return ""


def _save_raw(url: str, content: str) -> None:
    try:
        output_dir = Path(__file__).resolve().parent.parent / "search_result" / "mcp_fetch"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = url.split("/")[-1][:40].replace("?", "_") or "page"
        (output_dir / f"{safe_name}_{ts}.md").write_text(content, encoding="utf-8")
    except Exception:
        pass


_SUMMARIZE_SYSTEM = (
    "你是一个信息提取专家。请将以下网页内容提炼为详细的事实性摘要，"
    "保留所有关键数字、时间节点、地点、机构名称和政策要点，去除广告、导航菜单等无关内容。"
    "输出 600-1000 字中文摘要。"
)

# 送入 LLM 前的硬上限，防止极长页面超出 context window（约 20k tokens）
_MAX_INPUT_CHARS = 40000


def make_fetch_tool(model):
    """
    工厂函数：创建带 LLM 摘要的网页抓取工具。
    抓取完整正文后调用 model 生成结构化摘要，返回值包含来源 URL。
    """

    @tool
    def langgraph_fetch_web_content(url: str) -> str:
        """
        抓取指定 URL 的网页正文，并用 LLM 提炼为事实性摘要（含来源 URL）。

        当搜索摘要不足以回答问题时调用。
        若返回 [FETCH_FAILED]，立即改用 fetch_url_via_pdf 兜底。

        Args:
            url: 需要访问的网页完整 URL。

        Returns:
            str: "[来源] url\\n\\n摘要文本"；失败时返回 [FETCH_FAILED] 说明。
        """
        # ── 抓取 ──────────────────────────────────────────────────────────────
        try:
            content = asyncio.run(_fetch_raw(url))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"[FETCH_FAILED] {url} 抓取异常: {e}。请立即调用 fetch_url_via_pdf。"

        if not content:
            return (
                f"[FETCH_FAILED] {url} 抓取内容为空（页面可能需要 JS 渲染或启用了反爬）。"
                "请立即调用 fetch_url_via_pdf。"
            )

        print(f"  ✅ 抓取成功，原始长度 {len(content)} 字，正在生成摘要...")

        # ── LLM 摘要 ─────────────────────────────────────────────────────────
        input_text = content[:_MAX_INPUT_CHARS]
        try:
            resp = model.invoke([
                SystemMessage(content=_SUMMARIZE_SYSTEM),
                HumanMessage(content=f"网页来源：{url}\n\n{input_text}"),
            ])
            summary = _strip_thinking(resp.content)
            print(f"  📝 摘要生成完成，长度 {len(summary)} 字")
        except Exception as e:
            print(f"  ⚠️  LLM 摘要失败 ({e})，回退截断原文")
            summary = content[:4000] + f"\n\n[摘要失败，已截断，原始长度 {len(content)} 字]"

        return f"[来源] {url}\n\n{summary}"

    return langgraph_fetch_web_content


def _check_url_accessible(url: str, timeout: float = 5.0) -> bool:
    """
    发送 HEAD 请求预检 URL 是否可访问（4xx/5xx 视为不可访问）。
    网络异常或超时返回 True（交给 MCP 再试一次）。
    """
    import urllib.request
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            if status >= 400:
                print(f"  [预检] HTTP {status}，跳过: {url}")
                return False
            return True
    except Exception:
        return True  # 无法判断时交给 MCP 尝试


def fetch_and_summarize_sync(url: str, model, query: str = "") -> tuple[str, str] | None:
    """
    抓取 URL 并用 LLM 生成摘要。
    先做 HTTP 预检，4xx 直接放弃；MCP 拿不到内容同样放弃，不走 PDF 路径。
    返回 (url, summary)，失败时返回 None。
    """
    # ── HTTP 预检：4xx 直接放弃 ────────────────────────────────────────────────
    if not _check_url_accessible(url):
        return None

    # ── MCP fetch ─────────────────────────────────────────────────────────────
    content = ""
    try:
        content = asyncio.run(_fetch_raw(url))
    except Exception as e:
        print(f"  [MCP] 抓取异常: {e}")

    if not content:
        print(f"  [MCP] 内容为空，放弃该链接: {url}")
        return None

    print(f"  ✅ 抓取成功，长度 {len(content)} 字，生成摘要...")

    # ── LLM 摘要 ──────────────────────────────────────────────────────────────
    input_text = content[:_MAX_INPUT_CHARS]
    try:
        resp = model.invoke([
            SystemMessage(content=_SUMMARIZE_SYSTEM),
            HumanMessage(content=f"网页来源：{url}\n\n{input_text}"),
        ])
        return url, _strip_thinking(resp.content)
    except Exception as e:
        print(f"  ⚠️  摘要失败 ({e})，截断原文")
        return url, content[:2000]
