import asyncio

from langchain_core.tools import tool
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
# 直接从 tool 包导入
from tool import tool_download_image, get_baidu_tools, get_gaode_tools

model = init_chat_model(
    base_url="http://localhost:8001/v1",
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)

system_prompt = """你是一个专业的地理空间情报分析助手。
你的任务是根据用户的需求，通过调用不同的工具获取地理信息、下载卫星遥感影像并进行展示。

### 工作流指南：
1. **地点定位**：当用户提到一个地标时，首先调用高德或百度地图工具获取该地点的精确经纬度（lon, lat）。
2. **影像获取**：获取坐标后，调用 `tool_download_image` 工具。你需要根据用户要求的年份（如 2015 和 2025）传入对应的年份列表、经纬度以及地点名称。
3. **路径记忆**：下载成功后，`tool_download_image` 会返回文件的本地路径（path）。请务必记住这些路径。


### 影像展示规范（必须严格执行）：
1. 当调用 tool_download_image 成功后，你必须使用转化为base64格式展示图片。
✅ 正确示范（图片能显示）：
![2020年影像](data:image/jpeg;base64,xxxx...)

❌ 错误示范（图片无法显示）：
![2020年影像]
(data:image/jpeg;base64,xxxx...)

### 注意事项：
- 在调用下载工具前，必须确保已经拿到了准确的经纬度。
- 如果用户没有指定具体的年份，默认对比近 10 年的变化。
- 只返回base64内容
"""
import base64
from pathlib import Path


@tool
def get_image_base64_content(file_path: str) -> str:
    """
    读取指定路径的图片文件，并返回其 Base64 编码的 Data URI。
    支持的格式包括 jpg, jpeg, png 等。
    """
    try:
        path = Path(file_path)
        with open(path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")

        ext = path.suffix.lower().lstrip('.')
        mime_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"

        return f"data:{mime_type};base64,{b64_data}"
    except Exception as e:
        return f"转换失败: {str(e)}"


# 2. 定义统一的异步函数
async def get_all_tools():
    """汇总所有静态工具和动态 MCP 工具，返回一个扁平的列表"""
    # 静态工具（已经是对象了，直接放进列表）
    static_tools = [tool_download_image]

    # 动态工具（因为是异步获取，必须使用 await）
    # 这样拿到的才是真正的 [tool1, tool2...] 列表
    gaode = await get_gaode_tools()
    baidu = await get_baidu_tools()

    # 合并成一个扁平的列表返回
    return static_tools + gaode + baidu


tools = asyncio.run(get_all_tools()) + [get_image_base64_content]

agent = create_agent(
    model=model,
    tools=tools,
    system_prompt=system_prompt
)

# 我想知道北京邮电大学沙河校区2020和2025年的变化，请在分析结果的时候，展示前后对比图
