#!/usr/bin/env python3
"""
最简单的方式:使用mcp库调用MCP服务器

需要先安装: pip install mcp
"""

import asyncio
import os
from datetime import datetime

from langchain_core.tools import tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pathlib import Path


async def fetch_web_content(url):
    """获取网页内容"""
    # 必须用asyncio.run()来运行
    print("=" * 80)
    print("🚀使用mcp库调用MCP Fetch Server")
    print("=" * 80)
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

            # 提取内容
            if result.content and len(result.content[0].text) > 1000:
                content = result.content[0].text
                print(f"\n🌐获取成功! 内容长度: {len(content)} 字符")

                # 打印前2000个字符
                print("\n内容预览:")
                print("=" * 100)
                print(content[:1000])

                # print("\n... (内容已截断)")

                # 提取标题 - 从Markdown内容的第一行或HTML的title标签中提取

                def extract_title(content):
                    """从内容中提取标题"""
                    # 1. 处理换行符、制表符，并压缩空格
                    title = (
                        content.replace("\n", " ").replace("\r", " ").replace("\t", " ")
                    )
                    title = " ".join(title.split())

                    # 2. 针对“xxx_百度百科”或“xxx - 百度百科”进行处理
                    # 常见的百度百科标题格式有： "词条名_百度百科" 或 "词条名 - 百度百科"

                    # 方案 A: 如果标题包含“百度百科”，则取分隔符前的部分
                    if "\\" in title:
                        # 尝试使用常见的分隔符进行切割（下划线、短横线、中杠、竖线）
                        for sep in ["\\", "_", "-", "—", "|"]:
                            if sep in title:
                                title = title.split(sep)[0].strip()
                                break

                        # 如果没有分隔符，直接把“百度百科”文字删掉
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

                # 生成安全的文件名
                safe_filename = sanitize_filename(title)
                timestamp = datetime.now().strftime("%Y年%m月")
                # 1. 获取当前文件的绝对路径
                current_file = Path(__file__).resolve()

                # 2. 向上回退三级到达 xiongan_agent 目录
                # 1st parent: tool/
                # 2nd parent: search_agent/
                # 3rd parent: xiongan_agent/
                base_dir = current_file.parent.parent

                # 3. 定义输出目录
                output_dir = base_dir / "search_result" / "mcp_fetch"
                # 如果文件夹不存在则创建（parents=True 支持递归创建，exist_ok=True 避免文件夹已存在时报错）
                output_dir.mkdir(parents=True, exist_ok=True)
                output_file = f"{output_dir}/{safe_filename}_{timestamp}.md"
                if os.path.exists(output_file):
                    print(f"🔒文件已存在，跳过生成: {output_file}")
                else:
                    print(f"\n✅正在保存到: {output_file}")
                    with open(output_file, "w", encoding="utf-8") as f:
                        f.write(content)
                    print(f"\n✅完整内容已保存到: {output_file}")
            else:
                print("❌未获取到内容")
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
    MAX_CHARS = 1500  # 每个 URL 限 1500 字，确保 3 个 URL 都能喂进上下文
    try:
        result = asyncio.run(fetch_web_content(url))
        if not result:
            msg = f"[FETCH_FAILED] {url} 抓取内容为空（页面可能需要 JS 渲染或启用了反爬）。请立即改用 export_webpage_to_pdf 工具对此 URL 进行 PDF 下载，再用 pdf2md 转换。"
            print(f"⚠️  {msg}")
            return msg
        if len(result) > MAX_CHARS:
            print(f"  ✂️  内容过长（{len(result)} 字），已截断至 {MAX_CHARS} 字")
            result = result[:MAX_CHARS] + f"\n\n[内容已截断，原始长度 {len(result)} 字符]"
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        msg = f"[FETCH_FAILED] {url} 抓取异常: {e}。请立即改用 export_webpage_to_pdf 工具对此 URL 进行 PDF 下载，再用 pdf2md 转换。"
        print(f"⚠️  {msg}")
        return msg


if __name__ == "__main__":
    url1 = "https://baike.baidu.com/item/%E9%BB%91%E7%A5%9E%E8%AF%9D%EF%BC%9A%E6%82%9F%E7%A9%BA/53303078"
    langgraph_fetch_web_content.invoke(url1)
