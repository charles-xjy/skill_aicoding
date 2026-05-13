from ddgs import DDGS
import os
from pathlib import Path
import json
import datetime
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


def _trim_query(query: str, max_terms: int = 3) -> str:
    """
    将搜索词限制在 max_terms 个词以内。
    - 有空格时按空格切分，取前 max_terms 个词
    - 无空格时（连续中文）直接截取前 max_terms*4 个字符作为粗略限制
    """
    query = query.strip()
    parts = query.split()
    if len(parts) > max_terms:
        trimmed = " ".join(parts[:max_terms])
        print(f"⚠️  搜索词过多（{len(parts)} 个），已截断为：{trimmed}")
        return trimmed
    # 无空格的连续中文：超过 12 个字符时截断
    if len(parts) == 1 and len(query) > 12:
        trimmed = query[:12]
        print(f"⚠️  搜索词过长，已截断为：{trimmed}")
        return trimmed
    return query


@tool
def duckduckgo_search(query):
    """
    执行联网搜索的工具，用于获取最新的实时信息或背景资料。
    搜索词必须简短精准，不超过 3 个词语（多余的词会被自动截断）。

    Args:
        query (str): 2-3 个精准关键词，例如"北邮 沙河 发展"，严禁传入完整句子。

    Returns:
        str: 返回一个包含搜索结果的列表（JSON 格式字符串），每个结果包含：
            - title (str): 文章或网页的标题。
            - href (str): 网页的原始链接地址。
            - body (str): 网页内容的简要摘要或片段。
    """
    query = _trim_query(query)
    print(f"正在搜索🔍: {query}\n")

    # ✅ 修复点 1：在 try 之前初始化变量，确保下方 prompt 永远能访问到它
    results = []

    try:
        # 注意：DDGS().text 建议使用 context manager (with 语句)
        with DDGS() as ddgs:
            # 这里的 backend="google" 有时会因接口变动失效，默认不传通常更稳
            search_gen = ddgs.text(query)
            results = list(search_gen)  # 转换为列表以便后续操作

        if results:
            print(f"找到 {len(results)} 条结果✨:\n")
            for i, result in enumerate(results[:5], 1):  # 打印前5条即可，避免刷屏
                print(f"{i}. 标题: {result.get('title', 'N/A')}")
                print(f"   摘要: {result.get('body', 'N/A')}\n")

            # ✅ 修复点 2：路径处理建议使用 / 运算符，更符合 pathlib 规范
            current_file = Path(__file__).resolve()
            base_dir = current_file.parent.parent
            output_dir = base_dir / "search_result" / "duckduckgo"
            output_dir.mkdir(parents=True, exist_ok=True)

            current_date = datetime.datetime.now().strftime("%Y年%m月%d日")
            # 使用 / 拼接路径对象，避免手动写反斜杠
            output_file = output_dir / f"{query}_{current_date}_result.json"

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=4, ensure_ascii=False)
        else:
            print("⚠️ 未找到搜索结果")
            return []

    except Exception as e:
        print(f"❌ 搜索出错: {e}")
        return []
    return results


def main(query):
    search_result = duckduckgo_search.invoke(query)
    # ================================== LLM总结答案 ==================================
    load_dotenv()

    # 即使搜索失败，这里也不会报错了，因为 results 至少是个空列表 []
    llm = ChatOpenAI(
        api_key=SecretStr(os.getenv("SILICONFLOW_API_KEY") or "EMPTY"),
        base_url=os.getenv("SILICONFLOW_BASE_URL"),
        # 请确保你的模型名称在 SiliconFlow 后台是正确的，Qwen3-8B 可能是预览版或别名
        model="Qwen/Qwen3-8B",
    )

    prompt = f"""
        你是一个信息整理助手，请根据以下搜索结果回答用户的问题。

        用户问题：{query}

        搜索结果：
        {search_result if search_result else "未搜寻到相关在线实时信息，请根据已知知识库回答。"}

        请提供一个准确、简洁的回答（200字以内）。
        """

    print(
        "================================== LLM总结答案 =================================="
    )
    print("🧠正在为您总结最终答案...")

    try:
        responses = llm.invoke(prompt)
        print(
            "================================== 最终答案 =================================="
        )
        print(f"✅答案总结完成: {responses.content}")
        return responses.content
    except Exception as e:
        print(f"❌ LLM 调用失败: {e}")
        return "抱歉，总结答案时出现错误。"


if __name__ == "__main__":
    query2 = "介绍一下故宫"
    a = main(query2)
