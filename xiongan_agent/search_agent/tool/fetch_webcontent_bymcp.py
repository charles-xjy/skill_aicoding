#!/usr/bin/env python3
"""
最简单的方式:使用mcp库调用MCP服务器

需要先安装: pip install mcp
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from langchain_core.tools import tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.sync_api import sync_playwright


# ---------- 反爬站点专用抓取(知乎等) ----------
# 这些站点对 MCP fetch server 通用工具反爬严重:知乎专栏对无登录请求一律
# 返回 zse-ck JS 挑战(403)或重定向到 account/unhuman 安全验证页,导致 MCP
# 静默返回空。需要注入登录 cookie(关键是 z_c0)后用浏览器渲染抓取。

_ZHIHU_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
window.chrome = {runtime: {}};
"""


def _is_zhihu(url: str) -> bool:
    """判断是否知乎站点(zhihu.com 任意子域)。"""
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("zhihu.com")


def _parse_cookie_string(cookie_str: str, domain: str = ".zhihu.com") -> list:
    """把 'k1=v1; k2=v2' 形式的 cookie 串解析成 Playwright add_cookies 所需的 list。"""
    cookies = []
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name = name.strip()
        value = value.strip()
        if name:
            cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
    return cookies


def _fetch_zhihu_via_playwright(url: str) -> str:
    """
    用 Playwright + 登录 cookie 抓取知乎专栏正文。

    从环境变量 ZHIHU_COOKIE 读取登录态(关键是 z_c0)注入浏览器上下文,
    并用轻量 stealth 规避自动化检测。返回正文纯文本;未配置 cookie 或
    抓取失败返回空串。
    """
    cookie_str = os.environ.get("ZHIHU_COOKIE", "").strip()
    if not cookie_str:
        print("❌ [知乎] 未配置 ZHIHU_COOKIE 环境变量,无法抓取(知乎需登录态)。")
        print("   请在浏览器登录知乎后,复制 cookie 串(至少含 z_c0)并执行:")
        print("   export ZHIHU_COOKIE='z_c0=...; ...'")
        return ""

    cookies = _parse_cookie_string(cookie_str)
    if not any(c["name"] == "z_c0" for c in cookies):
        print("⚠️  [知乎] ZHIHU_COOKIE 中未发现 z_c0,可能仍会被要求登录。")

    print(f"🌐 [知乎] Playwright 抓取: {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            ctx.add_init_script(_ZHIHU_STEALTH_JS)
            ctx.add_cookies(cookies)
            page = ctx.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等正文渲染,依次尝试知乎专栏常见正文选择器
            body = ""
            for sel in [".Post-RichText", "article", ".RichText.ztext", ".RichText"]:
                try:
                    page.wait_for_selector(sel, timeout=6000)
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        body = loc.inner_text(timeout=5000)
                        if len(body) > 200:
                            print(f"✅ [知乎] 正文命中选择器 {sel}, 长度 {len(body)}")
                            break
                except Exception:
                    continue

            # 被重定向到安全验证/登录页 -> cookie 失效
            final_url = page.url
            if "/account/unhuman" in final_url or "signin" in final_url:
                print(f"❌ [知乎] 被重定向到登录/验证页: {final_url}")
                print("   cookie 可能已过期,请重新获取 ZHIHU_COOKIE。")
                browser.close()
                return ""

            if not body:
                body = page.inner_text("body")
                print(f"⚠️  [知乎] 回退到 body 正文, 长度 {len(body)}")

            browser.close()
            return body
    except Exception as e:
        print(f"❌ [知乎] Playwright 抓取失败: {e}")
        return ""


def _save_content(content: str) -> str:
    """按标题命名把正文保存到 search_result/mcp_fetch/,返回文件路径。"""

    def extract_title(content):
        """从内容中提取标题"""
        # 1. 处理换行符、制表符,并压缩空格
        title = (
            content.replace("\n", " ").replace("\r", " ").replace("\t", " ")
        )
        title = " ".join(title.split())

        # 2. 针对"xxx_百度百科"或"xxx - 百度百科"进行处理
        # 常见的百度百科标题格式有: "词条名_百度百科" 或 "词条名 - 百度百科"

        # 方案 A: 如果标题包含"百度百科",则取分隔符前的部分
        if "\\" in title:
            # 尝试使用常见的分隔符进行切割(下划线、短横线、中杠、竖线)
            for sep in ["\\", "_", "-", "-", "|"]:
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break

            # 如果没有分隔符,直接把"百度百科"文字删掉
            title = title.replace("百度百科", "").strip()

        return title if title else "网页内容"

    def sanitize_filename(filename):
        """将字符串转换为安全的文件名"""
        # 移除或替换不允许的字符
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, "_")

        # 限制文件名长度(最多50个字符)
        if len(filename) > 50:
            filename = filename[:50]

        # 去除首尾空格
        filename = filename.strip()

        # 如果文件名为空,使用默认名称
        if not filename:
            filename = "untitled"

        return filename

    title = extract_title(content)
    safe_filename = sanitize_filename(title)
    timestamp = datetime.now().strftime("%Y年%m月")
    # 1. 获取当前文件的绝对路径
    current_file = Path(__file__).resolve()

    # 2. 向上回退两级到达 search_agent 目录
    # 1st parent: tool/
    # 2nd parent: search_agent/
    base_dir = current_file.parent.parent

    # 3. 定义输出目录
    output_dir = base_dir / "search_result" / "mcp_fetch"
    # 如果文件夹不存在则创建(parents=True 支持递归创建,exist_ok=True 避免文件夹已存在时报错)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = f"{output_dir}/{safe_filename}_{timestamp}.md"
    if os.path.exists(output_file):
        print(f"🔒文件已存在,跳过生成: {output_file}")
    else:
        print(f"\n✅正在保存到: {output_file}")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n✅完整内容已保存到: {output_file}")
    return output_file


async def fetch_web_content(url):
    """获取网页内容"""
    # 必须用asyncio.run()来运行
    print("=" * 80)
    print("🚀使用mcp库调用MCP Fetch Server")
    print("=" * 80)

    # 知乎等强反爬站点:MCP fetch 必返回空,改走 Playwright + 登录 cookie。
    # fetch_web_content 是 async 函数、跑在事件循环里,而 _fetch_zhihu_via_playwright
    # 用的是 Playwright 同步 API(同步 API 不能在事件循环里直接跑),
    # 故用 asyncio.to_thread 把它丢到独立线程执行。
    if _is_zhihu(url):
        content = await asyncio.to_thread(_fetch_zhihu_via_playwright, url)
        if content:
            _save_content(content)
        return content

    # 配置MCP服务器参数
    server_params = StdioServerParameters(
        command="npx", args=["-y", "mcp-server-fetch-typescript"]
    )

    print("🚀正在连接MCP Fetch Server...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 初始化会话
            await session.initialize()
            print("✅ MCP服务器已连接")

            # 列出可用工具
            # tools = await session.list_tools()
            # print(f"\n可用工具:")
            # for tool in tools.tools:
            #     print(f"  - {tool.name}: {tool.description}")

            """
            可用工具:
            - get_raw_text: Retrieves raw text content directly from a URL without browser rendering.
                Ideal for structured data formats like JSON, XML, CSV, TSV, or plain text files.
                Best used when fast, direct access to the source content is needed without processing dynamic elements.
            - get_rendered_html: Fetches fully rendered HTML content using a headless browser, including JavaScript-generated content.
                Essential for modern web applications, single-page applications (SPAs), or any content that requires client-side rendering to be complete.
            - get_markdown: Converts web page content to well-formatted Markdown, preserving structural elements like tables and definition lists.
                Recommended as the default tool for web content extraction when a clean, readable text format is needed while maintaining document structure.
            - get_markdown_summary: Extracts and converts the main content area of a web page to Markdown format,
                automatically removing navigation menus, headers, footers, and other peripheral content.
                Perfect for capturing the core content of articles, blog posts, or documentation pages.
            """

            # 调用get_markdown工具(现在应该可以工作了)

            print(f"\n🌐正在获取: {url}")

            result = await session.call_tool(
                "get_markdown_summary", arguments={"url": url}
            )

            # 提取内容:只要 MCP 返回非空文本就接收。
            # 不再用 >1000 阈值——短文章也是有效内容,原阈值会把短正文误判为"未获取"。
            raw_text = ""
            if result.content:
                raw_text = getattr(result.content[0], "text", "") or ""

            if raw_text.strip():
                content = raw_text
                print(f"\n🌐获取成功! 内容长度: {len(content)} 字符")

                # 打印内容预览
                print("\n内容预览:")
                print("=" * 100)
                print(content[:1000])

                _save_content(content)
            else:
                # MCP 返回空:服务端可能因反爬/JS挑战静默失败,打印线索便于排查
                is_error = getattr(result, "is_error", False)
                print(f"❌未获取到内容 (MCP返回空, is_error={is_error})")
                print("   常见原因:站点反爬(如知乎/微信)、需JS渲染、或网络受限。")
                content = ""
    return content


@tool
def langgraph_fetch_web_content(url):
    """
    抓取并解析指定 URL 网页的完整正文内容。

    当搜索结果（摘要）不足以回答问题，或者需要深入分析某个特定网页的详细信息时，请调用此工具。

    参数:
        url (str): 需要访问的网页完整 URL 地址。

    返回:
        str/list: 网页的 Markdown 格式文本或内容列表。如果抓取失败，将返回错误说明。
    """

    # url1 = "https://baike.baidu.com/item/%E9%BB%91%E7%A5%9E%E8%AF%9D%EF%BC%9A%E6%82%9F%E7%A9%BA/53303078"
    # url2="https://baike.baidu.com/item/%E5%8C%97%E4%BA%AC%E9%82%AE%E7%94%B5%E5%A4%A7%E5%AD%A6?fromtitle=%E5%8C%97%E9%82%AE&fromid=11156402&fromModule=lemma_search-box"
    # 知乎测试: 先 export ZHIHU_COOKIE='z_c0=...; ...'，再抓
    # url_zhihu = "https://zhuanlan.zhihu.com/p/543759795"
    try:
        result = asyncio.run(fetch_web_content(url))
        return result
    except ImportError:
        print("❌ 错误: 未安装mcp库")
        print("\n请先安装:")
        print("  pip install mcp")
        print("\n或者使用另一个示例脚本: simple_mcp_example.py")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        # 它会捕获当前正在处理的异常，并将完整的报错过程打印到标准错误流（通常是你的控制台）。
        traceback.print_exc()

    return "没有获取到内容"


if __name__ == "__main__":
    url1 = "https://baike.baidu.com/item/%E9%BB%91%E7%A5%9E%E8%AF%9D%EF%BC%9A%E6%82%9F%E7%A9%BA/53303078"
    langgraph_fetch_web_content.invoke(url1)
