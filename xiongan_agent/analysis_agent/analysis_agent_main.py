import asyncio
import base64
import operator
import re
from pathlib import Path
from typing import Annotated, List, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

model = init_chat_model(
    base_url="http://10.129.107.145:8001/v1",
    api_key="vllm-no-key",
    model="Qwen_agent",
    model_provider="openai",
)

system_prompt = """# Role: 城市治理与国土空间规划专家

## Profile
你是一位深耕城市发展监测、土地利用分析与公共政策评估的资深专家。你擅长通过“空地结合”（卫星影像+多维文本）的方法，洞察城市物理空间的演变及其背后的社会经济驱动力。

## Task Strategy
你将接收“卫星影像文件名”与“网页搜索文本”作为输入。你需要通过文件名的时空属性捕捉“形”，通过文字资料捕捉“魂”，撰写一份兼具宏观视野与微观细节的《城市空间演进监测报告》。

## Content Structure & Requirements

### 一、 区域定位与演进概览
- **核心逻辑**：点明坐标，定调趋势。
- **要求**：从影像文件名中精确提取地点与跨度（如2020-2026），用专业术语（如“职住平衡优化”、“城市更新转型”）概括该区域的阶段性特征。

### 二、 空间格局演变（影像解译视角）
- **核心逻辑**：将文件名中的年份差转化为“增量分析”。
- **分析维度**：
    1. **硬质界面**：建筑密度的变化（新建群落、旧城改造）、交通骨架的延伸（道路等级提升）。
    2. **生态底色**：绿化覆盖率的变化、水系修复或景观带建设。
    3. **功能识别**：根据影像描述推断用地属性变化（如荒地转工业园、城中村转商务区）。
- **语言**：使用“斑块扩张”、“路网通达度”、“生态廊道”等专业词汇。

### 三、 发展动力机制（政策/规划视角）
- **核心逻辑**：揭示空间变化背后的推手。
- **关键点提取**：
    - **政策驱动**：提及的国家/省级战略或地方性规划。
    - **项目落地**：具体的重点工程、产业引入或民生配套。
    - **时序逻辑**：梳理“规划-动工-建成”的时间脉络。

### 四、 综合评价与战略前瞻
- **核心逻辑**：打通影像与文字的壁垒，评价“变”的质量。
- **评价维度**：是否符合预期规划？配套是否跟上建筑增长？
- **展望**：基于现有趋势，提出关于“产城融合”、“韧性城市建设”或“智慧治理”的专业预判。

## Constraints (Writing Style)
- **专业克制**：文风需具备政府白皮书或智库报告的严肃性。
- **拒绝留白**：如信息量不足，请基于城市规划常识进行“合理化推演”（例如：发现新建道路和办公楼，可推断其正在进行产业转型）。
- **精炼而不单薄**：虽然每节控制在200-300字，但要求信息密度大，避免空洞的套话。
- **输出格式**：直接输出报告，严禁任何形式的自我检讨或数据局限性声明。"""


class AnalysisState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


# 匹配 Windows/Linux 绝对路径中的图片文件
_IMAGE_PATH_RE = re.compile(
    r'([A-Za-z]:\\[^\s\n"\']+\.(?:jpg|jpeg|png|bmp|gif|tiff|webp)'
    r'|/[^\s\n"\']+\.(?:jpg|jpeg|png|bmp|gif|tiff|webp))',
    re.IGNORECASE,
)
_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png",  "bmp": "image/bmp",
    "gif": "image/gif",  "tiff": "image/tiff",
    "webp": "image/webp",
}


def _image_to_data_uri(path: str) -> str | None:
    """读取本地图片，返回 base64 data URI；文件不存在则返回 None"""
    p = Path(path)
    if not p.exists():
        print(f"  ⚠️  图片不存在，跳过: {path}")
        return None
    ext = p.suffix.lstrip(".").lower()
    mime = _MIME.get(ext, "image/jpeg")
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def _build_multimodal_message(text: str) -> HumanMessage:
    """
    从文本中提取图片路径，将图片转为 base64 data URI，
    构造多模态 HumanMessage（text + image_url blocks）。
    """
    paths = list(dict.fromkeys(_IMAGE_PATH_RE.findall(text)))  # 去重保序
    if not paths:
        return HumanMessage(content=text)

    content_blocks = [{"type": "text", "text": text}]
    loaded = 0
    for path in paths:
        uri = _image_to_data_uri(path)
        if uri:
            content_blocks.append({
                "type": "image_url",
                "image_url": {"url": uri},
            })
            loaded += 1

    print(f"  🖼️  已加载 {loaded}/{len(paths)} 张图片送入模型")
    return HumanMessage(content=content_blocks)


async def analysis_node(state: AnalysisState) -> dict:
    # 找到最后一条 HumanMessage，将其改造为多模态消息
    messages = list(state["messages"])
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            text = (
                messages[i].content
                if isinstance(messages[i].content, str)
                else " ".join(
                    b.get("text", "") for b in messages[i].content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            )
            messages[i] = _build_multimodal_message(text)
            break

    response = await model.ainvoke([SystemMessage(content=system_prompt)] + messages)
    return {"messages": [response]}


async def create_analysis_subgraph(checkpointer=None):
    """
    创建分析 Agent 子图（纯 LLM 综合分析，无工具调用）。
    - checkpointer=None 时为无状态模式（可视化 / 单次调用）
    """
    workflow = StateGraph(AnalysisState)
    workflow.add_node("analyst", analysis_node)
    workflow.add_edge(START, "analyst")
    workflow.add_edge("analyst", END)
    return workflow.compile(checkpointer=checkpointer)


async def run_as_standalone():
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    DB_URI = "redis://10.129.107.145:6379"
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        agent = await create_analysis_subgraph(checkpointer=saver)
        config = {"configurable": {"thread_id": "analysis_test_001"}}
        inputs = {
            "messages": [HumanMessage(content="请根据以下材料分析北邮沙河校区的发展变化。\n【图像路径】\n/data/images/bupt_2020.jpg\n/data/images/bupt_2025.jpg\n\n【搜索内容】\n北邮沙河校区于2023年完成二期工程...")]
        }
        print("🤖 analysis_agent 独立模式启动...")
        async for chunk in agent.astream(inputs, config, stream_mode="updates"):
            for node_name, node_data in chunk.items():
                if "messages" in node_data:
                    for msg in node_data["messages"]:
                        print(f"\n--- [{node_name}] ---")
                        msg.pretty_print()


if __name__ == "__main__":
    asyncio.run(run_as_standalone())
