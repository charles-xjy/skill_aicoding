import asyncio
import os
import re
import sys
from pathlib import Path

import httpx


def _sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", filename).strip()


async def _export_with_async_playwright(url: str, output_dir: Path, query: str) -> str:
    from playwright.async_api import async_playwright

    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"正在访问: {url} ...")
        await page.goto(url, wait_until="load")
        await page.wait_for_timeout(1000)
        await page.emulate_media(media="screen")
        raw_title = await page.title() or "untitled"

        clean_title = _sanitize_filename(raw_title)
        output_path = str(output_dir / f"{clean_title}.pdf")

        print(f"🧠 [AI] 检测到网页标题: {raw_title}")
        print(f"✍️ [SYSTEM] 正在生成 PDF: {output_path} ...")

        if os.path.exists(output_path):
            print(f"⚠️ [SKIP] 文件已存在，跳过生成: {output_path}")
            await browser.close()
            return output_path

        await page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"},
        )
        await browser.close()
        print("✅ 导出完成！")
        return output_path


def _run_in_proactor(url: str, output_dir: Path, query: str) -> str:
    """在独立的 ProactorEventLoop 里运行 playwright（Windows SelectorEventLoop 不支持子进程）。"""
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_export_with_async_playwright(url, output_dir, query))
    finally:
        loop.close()


def export_webpage_to_pdf(query: str, url: str):
    """
    将指定的网页完整内容导出并保存为本地 PDF 文件。

    当用户需要保存网页资料、打印文章、或者要求"下载/保存"某个网页为文件时，应调用此工具。
    该工具会模拟浏览器渲染页面，包含图片和背景，并自动根据网页标题生成文件名。

    参数:
        query(str): 用户最初的提问
        url (str): 想要导出的网页完整 URL 地址。

    返回:
        str: 导出的 PDF 文件在本地的绝对路径。如果导出失败，将返回错误描述。
    """
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / "search_result" / "download_pdf" / _sanitize_filename(query)

    # 直接 PDF 链接：用 httpx 下载，不走 playwright
    if url.lower().split("?")[0].endswith(".pdf"):
        print(f"检测到直接 PDF 链接，正在下载: {url}")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            clean_title = _sanitize_filename(url.split("/")[-1]) or "document.pdf"
            output_path = str(output_dir / clean_title)
            with httpx.Client(follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    f.write(resp.content)
            return output_path
        except Exception as e:
            return f"直接下载 PDF 失败: {str(e)}"

    try:
        return _run_in_proactor(url, output_dir, query)
    except Exception as e:
        return f"Playwright 导出失败: {str(e)}"
