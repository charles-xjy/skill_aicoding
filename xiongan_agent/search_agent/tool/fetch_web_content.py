import asyncio
import json
import re
import select
import subprocess
import time
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

# 单个 URL 的 MCP 抓取整体超时（wall-clock）。超时即 kill 子进程返回空，
# 由上层 fallback_body（搜索摘要）兜底，避免 _recv() 无限阻塞导致整图卡死。
_FETCH_TIMEOUT = 30.0


def _strip_thinking(text: str) -> str:
    """剥离 Qwen3 等思考模型的 <think>...</think> 推理块，只保留最终回复。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</think>", "", text)
    return text.strip()


def _fetch_raw_via_stdio(url: str) -> str:
    """
    直接用 subprocess.Popen 调用 MCP fetch 服务器，实现同步 JSON-RPC 通信。

    subprocess.Popen 走 C 层 CreateProcess/fork_exec，不经过 Python os.access，
    因此 blockbuster 无法拦截，可安全地在无 event loop 的线程中调用。

    整体受 _FETCH_TIMEOUT 限制：超时 kill 子进程并返回空串，
    避免对端反爬挂起连接时 _recv() 无限阻塞。
    """
    try:
        proc = subprocess.Popen(
            ["npx", "-y", "mcp-server-fetch-typescript"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        print(f"  [MCP stdio] 启动失败: {e}")
        return ""

    deadline = time.monotonic() + _FETCH_TIMEOUT

    def _send(msg: dict) -> None:
        data = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        proc.stdin.write(header + data)
        proc.stdin.flush()

    def _recv() -> dict:
        """带超时地读取一个 JSON-RPC 响应。超时或对端关闭返回 {}。"""
        headers: dict[str, str] = {}
        # 读 headers：逐行读直到空行，每行受剩余 deadline 约束
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {}
            # 用 select 等待 stdout 可读，避免 readline 永久阻塞
            rlist, _, _ = select.select([proc.stdout], [], [], remaining)
            if not rlist:
                return {}  # 超时
            line = proc.stdout.readline()
            if not line:
                return {}  # 对端关闭
            decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not decoded:
                break
            if ":" in decoded:
                key, _, val = decoded.partition(":")
                headers[key.strip().lower()] = val.strip()
        length = int(headers.get("content-length", 0))
        if not length:
            return {}
        data = b""
        while len(data) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {}
            rlist, _, _ = select.select([proc.stdout], [], [], remaining)
            if not rlist:
                return {}
            chunk = proc.stdout.read(length - len(data))
            if not chunk:
                break
            data += chunk
        try:
            return json.loads(data.decode("utf-8"))
        except Exception:
            return {}

    timed_out = False
    try:
        # 1. Initialize 握手
        _send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "xiongan-fetch", "version": "1.0"},
            },
        })
        init_resp = _recv()
        if not init_resp:
            timed_out = True
            print(f"  [MCP stdio] initialize 超时（>{_FETCH_TIMEOUT:.0f}s），放弃: {url}")
            return ""
        if "error" in init_resp:
            print(f"  [MCP stdio] initialize 失败: {init_resp['error']}")
            return ""

        # 2. Initialized 通知
        _send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        # 3. 调用 get_markdown_summary
        _send({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get_markdown_summary", "arguments": {"url": url}},
        })
        call_resp = _recv()

        if not call_resp:
            timed_out = True
            print(f"  [MCP stdio] 抓取超时（>{_FETCH_TIMEOUT:.0f}s），放弃: {url}")
            return ""

        if "error" in call_resp:
            print(f"  [MCP stdio] tool 调用失败: {call_resp['error']}")
            return ""

        content_blocks = (call_resp.get("result") or {}).get("content") or []
        if content_blocks and isinstance(content_blocks, list):
            text = content_blocks[0].get("text", "")
            return text if len(text) > 100 else ""
        return ""

    except Exception as e:
        print(f"  [MCP stdio] 通信失败: {e}")
        return ""
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            # 超时场景下进程可能还在跑，先 terminate 再 wait；杀不掉就 kill
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


def _save_raw(url: str, content: str) -> None:
    try:
        output_dir = Path(__file__).parent.parent / "search_result" / "mcp_fetch"
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

_MAX_INPUT_CHARS = 40000


async def _fetch_raw(url: str) -> str:
    """在无 event loop 的独立线程中运行 _fetch_raw_via_stdio，绕过 blockbuster。"""
    content = await asyncio.to_thread(_fetch_raw_via_stdio, url)
    if content:
        _save_raw(url, content)
    return content


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
        content = _fetch_raw_via_stdio(url)

        if not content:
            return (
                f"[FETCH_FAILED] {url} 抓取内容为空（页面可能需要 JS 渲染或启用了反爬）。"
                "请立即调用 fetch_url_via_pdf。"
            )

        _save_raw(url, content)
        print(f"  ✅ 抓取成功，原始长度 {len(content)} 字，正在生成摘要...")

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

    微信公众号文章（mp.weixin.qq.com）反爬严重，MCP 几乎必失败且易卡住，
    直接判定不可访问，由上层用搜索摘要兜底，不再白等一次 MCP 超时。
    """
    import urllib.request
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if "mp.weixin.qq.com" in host:
            print(f"  [预检] 微信公众号文章，反爬跳过: {url}")
            return False
    except Exception:
        pass
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
        return True


def fetch_and_summarize_sync(
    url: str, model, query: str = "", fallback_body: str = ""
) -> tuple[str, str] | None:
    """
    抓取 URL 并用 LLM 生成摘要（完全同步，无 event loop，可在 ToolNode 线程中直接调用）。
    先做 HTTP 预检，4xx 直接放弃；MCP 拿不到内容时若有 fallback_body 则用它兜底。
    返回 (url, summary)，完全失败时返回 None。
    """
    if not _check_url_accessible(url):
        if fallback_body:
            print(f"  [预检] URL 不可达，使用搜索摘要兜底 (长度 {len(fallback_body)} 字)")
            return url, fallback_body
        return None

    content = _fetch_raw_via_stdio(url)

    if not content:
        if fallback_body:
            print(f"  [MCP] 抓取为空，使用搜索摘要兜底 (长度 {len(fallback_body)} 字)")
            return url, fallback_body
        print(f"  [MCP] 内容为空，无兜底，放弃: {url}")
        return None

    _save_raw(url, content)
    print(f"  ✅ 抓取成功，长度 {len(content)} 字，生成摘要...")

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
