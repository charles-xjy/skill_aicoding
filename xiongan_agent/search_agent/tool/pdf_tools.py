"""
PDF 工具：网页 → PDF（Playwright）+ PDF → Markdown（MinerU hybrid-auto-engine）
解析路径：
  1. SSH 检测远程 GPU 空闲量，若最大空闲 >= 30 GB → 发送到远程 MinerU API
  2. 否则 → 本地启动 LocalAPIServer（本地 GPU）解析
"""

import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import nest_asyncio
from langchain_core.tools import tool
from mineru.cli import api_client as _mc

nest_asyncio.apply()
os.environ['MINERU_MODEL_SOURCE'] = "modelscope"
MINERU_REMOTE_URL = os.environ.get("MINERU_API_URL", "http://10.129.107.145:30000")
MINERU_REMOTE_HOST = os.environ.get("MINERU_HOST", "10.129.107.145")
GPU_FREE_THRESHOLD_MB = 30 * 1024  # 30 GB in MB
MAX_CHARS = 40000
_MD_OUT = Path(__file__).parent.parent / "search_result" / "pdf2md"


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


def _max_free_gpu_mb(host: str, timeout: int = 8) -> float:
    """SSH to host, return max free GPU memory in MB across all GPUs. Returns 0 on failure."""
    try:
        result = subprocess.run(
            [
                "ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", host,
                "nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            print(f"  [GPU检查] ssh 返回码 {result.returncode}: {result.stderr.strip()}")
            return 0
        values = [float(v.strip()) for v in result.stdout.strip().splitlines() if v.strip()]
        return max(values) if values else 0
    except Exception as e:
        print(f"  [GPU检查] SSH 失败: {e}")
        return 0


def _prepare_local_tmp() -> None:
    """Fix vLLM/ZeroMQ IPC socket failures on drvfs-backed /tmp under WSL."""
    current_tmp = Path(tempfile.gettempdir())
    if os.name == "nt" or not Path("/tmp").exists():
        return
    if str(current_tmp).startswith("/mnt/"):
        os.environ["TMPDIR"] = "/tmp"
        tempfile.tempdir = None


# ── 网页 → PDF（Playwright）─────────────────────────────────────────────────

async def _playwright_to_pdf(url: str, output_dir: Path) -> str:
    from playwright.async_api import async_playwright
    print(f"\n  [Playwright] 正在访问并渲染页面为 PDF: {url}")
    output_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="load")
        await page.wait_for_timeout(1000)
        await page.emulate_media(media="screen")
        title = _sanitize(await page.title() or "untitled")
        pdf_path = str(output_dir / f"{title}.pdf")
        if not os.path.exists(pdf_path):
            await page.pdf(
                path=pdf_path, format="A4", print_background=True,
                margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
            )
        await browser.close()
    print(f"  [Playwright] PDF 已保存: {pdf_path}")
    return pdf_path


def _export_pdf(url: str, output_dir: Path) -> str:
    # Windows SelectorEventLoop 不支持子进程，必须用 ProactorEventLoop
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_playwright_to_pdf(url, output_dir))
    finally:
        loop.close()


# ── PDF → Markdown（MinerU）────────────────────────────────────────────────

def _build_form_data() -> dict:
    return _mc.build_parse_request_form_data(
        lang_list=["ch"],
        backend="pipeline",
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
        image_analysis=True,
        server_url=None,
        start_page_id=0,
        end_page_id=None,
        return_md=True,
        return_middle_json=False,
        return_model_output=False,
        return_content_list=False,
        return_images=False,
        response_format_zip=True,
        return_original_file=False,
    )


async def _mineru_parse_async(pdf_path: str, use_remote: bool) -> str:
    form_data = _build_form_data()
    upload_assets = [_mc.UploadAsset(path=Path(pdf_path), upload_name=Path(pdf_path).name)]
    local_server = None

    async with httpx.AsyncClient(timeout=_mc.build_http_timeout(), follow_redirects=True) as client:
        try:
            if use_remote:
                health = await _mc.fetch_server_health(
                    client, _mc.normalize_base_url(MINERU_REMOTE_URL)
                )
                print(f"  [MinerU] 远程服务器: {health.base_url}")
            else:
                _prepare_local_tmp()
                local_server = _mc.LocalAPIServer()
                base_url = local_server.start()
                print(f"  [MinerU] 本地 API 已启动: {base_url}")
                health = await _mc.wait_for_local_api_ready(client, local_server)

            submit = await _mc.submit_parse_task(
                base_url=health.base_url,
                upload_assets=upload_assets,
                form_data=form_data,
            )
            print(f"  [MinerU] task_id={submit.task_id}，等待解析...")
            await _mc.wait_for_task_result(
                client=client, submit_response=submit, task_label=Path(pdf_path).name
            )
            result_zip = await _mc.download_result_zip(
                client=client, submit_response=submit, task_label=Path(pdf_path).name
            )
        finally:
            if local_server is not None:
                local_server.stop()

    out_dir = _MD_OUT / Path(pdf_path).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        _mc.safe_extract_zip(result_zip, out_dir)
    finally:
        result_zip.unlink(missing_ok=True)

    md_files = sorted(out_dir.rglob("*.md"))
    if not md_files:
        raise ValueError(f"解压后未找到 .md 文件，目录: {out_dir}")
    content = md_files[0].read_text(encoding="utf-8")
    print(f"  [MinerU] 解析完成，长度 {len(content)} 字符")
    return content


def _parse_pdf(pdf_path: str) -> str:
    print(f"\n  [GPU检查] 正在探测远程 GPU 负载 ({MINERU_REMOTE_HOST})...")
    free_mb = _max_free_gpu_mb(MINERU_REMOTE_HOST)
    use_remote = free_mb >= GPU_FREE_THRESHOLD_MB
    if use_remote:
        print(f"  [GPU检查] 远程最大空闲 {free_mb / 1024:.1f} GB >= 30 GB，使用远程解析")
    else:
        print(f"  [GPU检查] 远程最大空闲 {free_mb / 1024:.1f} GB < 30 GB，改用本地解析")
    return asyncio.run(_mineru_parse_async(pdf_path, use_remote=use_remote))


# ── 核心入口 ─────────────────────────────────────────────────────────────────

def fetch_via_pdf(query: str, url: str) -> str:
    """
    Playwright 将网页保存为 PDF，再用 MinerU hybrid-auto-engine 解析为 Markdown。
    失败时返回以 [PDF_FAILED] 开头的错误描述。
    """
    output_dir = (
            Path(__file__).parent.parent
            / "search_result" / "download_pdf"
            / _sanitize(query)
    )

    try:
        pdf_path = _export_pdf(url, output_dir)
    except Exception as e:
        print(f"  ❌ [Playwright] 导出 PDF 失败: {e}")
        return f"[PDF_FAILED] Playwright 导出失败: {e}"

    print(f"  ✅ [Playwright] PDF 已就绪，正在进入 MinerU 解析环节...")
    try:
        md = _parse_pdf(pdf_path)
        if len(md) > MAX_CHARS:
            md = md[:MAX_CHARS] + f"\n\n[内容已截断，原始长度 {len(md)} 字符]"
        return md
    except Exception as e:
        return f"[PDF_FAILED] MinerU 解析失败: {e}，PDF 已保存: {pdf_path}"


@tool
def fetch_url_via_pdf(query: str, url: str) -> str:
    """
    当 MCP 抓取失败时的兜底工具：Playwright 保存为 PDF，再用 MinerU 解析为 Markdown。
    自动检测远程 GPU 空闲量：>= 30 GB 时使用远程服务器，否则本地启动 MinerU。

    Args:
        query: 用户最初的搜索关键词或提问
        url:   抓取失败的网页 URL

    Returns:
        str: 网页内容的 Markdown 文本；失败时返回错误描述。
    """
    return fetch_via_pdf(query, url)
