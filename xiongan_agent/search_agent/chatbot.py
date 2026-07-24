from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

# 直接从 tool 包导入
from tool import duckduckgo_search, langgraph_fetch_web_content, export_webpage_to_pdf, pdf2md

model = init_chat_model(
    base_url="http://localhost:8001/v1",
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)

system_prompt = """你是一个深度信息调研助手。
当用户提出一个需要详细了解的主题时，请严格执行以下三阶段流程：

1. **搜索阶段**：调用 `duckduckgo_search` 获取相关网址列表。

2. **抓取与深度解析阶段**：
   - 优先尝试：针对前 1-2 个最具代表性的 URL，调用 `langgraph_fetch_web_content` 抓取正文。
   - **容错逻辑（关键）**：如果上述工具报错（如无法获取 HTML、页面跳转中、或内容为空），请立即执行以下备选方案：
     a. 调用 `export_webpage_to_pdf` 将该网页保存为本地 PDF。
     b. 获取 PDF 存储路径后，调用 `pdf2md` 将其转换为 Markdown 文本。

3. **分析阶段**：
   - 整合所有获取到的详细内容（无论是直接抓取的还是通过 PDF 转换的）。
   - 进行对比、整合，输出一份结构清晰、详实且专业的报告。

注意：
- 严禁仅根据搜索摘要（Snippet）回答。
- 必须确保至少有一个 URL 的深度内容（Markdown/正文）被成功获取。
- 若网页具有复杂的排版或公式，优先使用 PDF 转 MD 路径以保证信息还原度。"""

tools = [duckduckgo_search, langgraph_fetch_web_content, export_webpage_to_pdf, pdf2md]
# tools = [duckduckgo_search, export_webpage_to_pdf, pdf2md]
# checkpointer = InMemorySaver()
# 这里的 agent 可以是 LangGraph 的 CompiledGraph
agent = create_agent(
    model=model,
    tools=tools,
    system_prompt=system_prompt
)
