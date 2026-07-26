import asyncio
import base64
import operator
import re
from pathlib import Path
from typing import Annotated, List, TypedDict

from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

_LOCAL_BASE_URL = "http://10.129.107.145:8002/v1"
_LOCAL_MODEL_NAME = "urban-vlm"

system_prompt = """# Role: 城市治理与国土空间规划专家

## Profile
你是一位深耕城市发展监测、土地利用分析与公共政策评估的资深专家。你擅长通过”空地结合”（卫星影像+多维文本）的方法，洞察城市物理空间的演变及其背后的社会经济驱动力。

## Task Strategy
你将接收”卫星影像路径”与”网页搜索文本”作为输入材料。你需要：
- 从影像路径的文件名中提取地点、年份等时空属性，捕捉”形”的变化；
- 从搜索文本中提炼政策、项目、数据等关键信息，捕捉”魂”的驱动；
- **每一个论断必须对应一条具体证据**，明确标注来源（影像/哪篇文章/哪段原文）。

## Content Structure & Requirements
每个章节不少于400字，禁止以概括性套话代替实质内容。

### 一、 区域定位与演进概览（≥400字）
必须覆盖以下全部要点：
1. **时空锚定**：从影像文件名精确提取地点名称、经纬度（如有）、监测年份跨度，说明本次分析覆盖的时间窗口。
2. **阶段定性**：用2-3个核心关键词定性该区域在监测期内所处的城市化阶段（如”建设期→成熟期”、”扩张型→内涵提升型”），并说明判断依据。
3. **宏观背景**：结合搜索文本，说明该区域所在行政区或园区的整体发展战略定位，引用至少1条原文信息（加引号标注出处）。
4. **核心变化摘要**：用3-5条要点式陈述，列出监测期内最显著的空间变化事件，作为后续章节的提纲式索引。

### 二、 空间格局演变（影像解译视角）（≥400字）
对照两个年份的影像，逐维度进行增量对比分析，每个维度须给出”2020年状态→2025年状态→变化量/变化性质”的三段式表述：

1. **建筑与用地**
   - 新增建筑群落的位置、规模估算（如”东南角新增约X公顷建设用地”）
   - 旧有建筑的保留、改造或拆除情况
   - 用地属性的转变（教学用地/科研用地/生活配套用地占比变化）

2. **交通与可达性**
   - 内部路网新增或改造情况（道路等级、宽度、走向）
   - 对外联系通道的变化（与城市主干道、地铁站点的接驳）
   - 停车设施、非机动车道等慢行系统配置

3. **生态与景观**
   - 绿地斑块的面积、形态变化（是否形成连续生态廊道）
   - 水系、硬质铺装与软质景观的比例变化
   - 生态品质提升的直接证据（如新建景观湖、林荫道延伸）

4. **功能边界**
   - 校园与周边城市空间的界面变化（围墙开放、共享界面增加）
   - 新增功能性设施（体育场馆、创新孵化楼、对外开放的商业配套）

### 三、 发展动力机制（政策/规划视角）（≥400字）
必须从搜索文本中提炼实证，不得凭空推断：

1. **政策层级梳理**
   - 国家/市级层面：引用具体规划名称、文件编号或发布年份（如”《北京市'十四五'教育规划》明确……”）
   - 区级层面：昌平区或沙河高教园的专项政策，引用原文关键句
   - 校级层面：北邮自身公布的校园建设计划或年度报告内容

2. **重点项目清单**
   逐条列举搜索文本中提及的具体工程项目，包含：项目名称、建设主体、开工/竣工时间、建筑面积或投资额（若有）、功能定位。至少列举3个项目。

3. **资金与资源配置**
   - 政府财政投入、专项债、高校自筹等资金来源
   - 师资引进、重点实验室落地等非物质资源的配置

4. **时序逻辑还原**
   以时间轴形式（年份→事件）梳理”规划批复→土地供应→开工建设→竣工验收”的完整脉络，揭示各阶段驱动力的切换。

### 四、 问题诊断与短板识别（≥300字）
这是报告中最具价值的批判性章节，禁止只写正面内容：

1. **供需错配风险**：建设速度与配套服务（餐饮、宿舍、医疗）之间的缺口
2. **交通瓶颈**：末端出行难题、高峰时段拥堵节点（结合影像中路网密度判断）
3. **生态压力**：建设扩张对原有绿地的侵占风险
4. **数据盲区**：本次分析中因影像分辨率或文本缺失导致无法判断的内容（一条即可，之后不再重复声明）

### 五、 综合评价与战略前瞻（≥400字）

1. **综合评分**：从”规划符合度、配套完善度、生态品质、交通效率”四个维度各给出高/中/低评价，并说明理由。
2. **对标分析**：将该校区与同类高教园区（如中关村科学城、天津大学北洋园校区）进行横向比较，指出优势与差距。
3. **三年行动建议**：针对第四章识别的短板，提出3条可落地的具体建议，每条须包含”行动主体、具体措施、预期效果”三要素。
4. **远期战略预判**：基于当前趋势，对2030年该区域的空间形态和功能定位作出专业预判，说明最可能实现的发展路径及其前提条件。

## Constraints (Writing Style)
- **引用格式**：每个论断末尾嵌入 `[n]`（精确到每句，不允许段落末尾统一标注）；`n` 直接使用输入材料中已给出的编号，不要重新编号。卫星影像来源标注为（影像）。
- **统一来源列表**：报告最后输出”## 来源”列表，将所有搜索报告的来源原样汇总（编号连续，不重复）。每条来源必须使用 Markdown 无序列表格式 `- [n] 标题 - URL`，一条来源独占一行，来源之间不得写在同一行。
- **数据具体**：凡涉及规模、面积、距离、时间，必须给出具体数字，禁止使用”大幅”、”显著”等模糊表述。
- **拒绝留白**：若原始材料信息不足，须基于专业知识作合理推演，并在句末注明（推演）以示区分。
- **文风严肃**：政府白皮书或顶级智库报告风格，禁止口语化表达。
- **直接输出**：不写任何前言、后记或免责声明，直接从报告标题开始。"""


class AnalysisState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


# 匹配 Windows/Linux 绝对路径中的图片文件
# 优化：
# 1. Windows: 必须以 A-Z: 开头
# 2. Linux: 必须以 / 开头，且排除 // (协议相对路径)，且至少包含两级目录以排除常见网页相对路径 (如 /search.png)
_IMAGE_PATH_RE = re.compile(
    r'([A-Za-z]:\\[^\s\n"\'`]+\.(?:jpg|jpeg|png|bmp|gif|tif|tiff|webp)'
    r'|/(?!/)(?:[\w\-. ]+/){2,}[\w\-. ]+\.(?:jpg|jpeg|png|bmp|gif|tif|tiff|webp))',
    re.IGNORECASE,
)
_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "bmp": "image/bmp",
    "gif": "image/gif", "tif": "image/tiff", "tiff": "image/tiff",
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


def _make_analysis_node(model):
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

        # ── DEBUG: 打印送给模型的消息结构 ──────────────────────────────
        final_messages = [SystemMessage(content=system_prompt)] + messages
        print(f"\n\033[35m{'─' * 60}\033[0m")
        print(f"\033[35m  [DEBUG] analysis_agent 送入模型的消息（共 {len(final_messages)} 条）\033[0m")
        for idx, msg in enumerate(final_messages):
            role = type(msg).__name__
            if isinstance(msg.content, str):
                preview = msg.content[:200].replace("\n", "↵")
                print(f"\033[35m  [{idx}] {role}: \"{preview}{'...' if len(msg.content) > 200 else ''}\"\033[0m")
            elif isinstance(msg.content, list):
                print(f"\033[35m  [{idx}] {role}: [多模态 {len(msg.content)} 个 block]\033[0m")
                for j, block in enumerate(msg.content):
                    btype = block.get("type", "?") if isinstance(block, dict) else "?"
                    if btype == "text":
                        txt = block.get("text", "")[:150].replace("\n", "↵")
                        print(
                            f"\033[35m      block[{j}] text: \"{txt}{'...' if len(block.get('text', '')) > 150 else ''}\"\033[0m")
                    elif btype == "image_url":
                        url_val = block.get("image_url", {}).get("url", "")
                        if url_val.startswith("data:"):
                            print(
                                f"\033[35m      block[{j}] image_url: data:{url_val[5:20]}... (base64, {len(url_val)} chars)\033[0m")
                        else:
                            print(f"\033[35m      block[{j}] image_url: {url_val[:80]}\033[0m")
                    else:
                        print(f"\033[35m      block[{j}] {btype}\033[0m")
        print(f"\033[35m{'─' * 60}\033[0m\n")
        # ── END DEBUG ───────────────────────────────────────────────

        response = await model.ainvoke(final_messages)
        return {"messages": [response]}

    return analysis_node


async def create_analysis_subgraph(checkpointer=None, model_name: str = "remote"):
    """
    创建分析 Agent 子图（纯 LLM 综合分析，无工具调用）。
    - checkpointer=None 时为无状态模式（可视化 / 单次调用）
    - model_name: "remote"（探测到的主模型端口）或 "local"（urban-vlm @ 8002）
    """
    if model_name == "local":
        model = init_chat_model(
            base_url=_LOCAL_BASE_URL,
            api_key="vllm-no-key",
            model=_LOCAL_MODEL_NAME,
            model_provider="openai",
        )
        print(f"  🤖 analysis_agent 使用模型: {_LOCAL_MODEL_NAME} @ {_LOCAL_BASE_URL}")
    else:
        from model_probe import make_vllm_model, probe_vllm_model
        model = await make_vllm_model()
        base_url, mn, _ = await probe_vllm_model()
        print(f"  🤖 analysis_agent 使用模型: {mn} @ {base_url}")
    workflow = StateGraph(AnalysisState)
    workflow.add_node("analyst", _make_analysis_node(model))
    workflow.add_edge(START, "analyst")
    workflow.add_edge("analyst", END)
    return workflow.compile(checkpointer=checkpointer)


async def run_as_standalone():
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver
    DB_URI = "redis://127.0.0.1:6390"
    async with AsyncRedisSaver.from_conn_string(DB_URI) as saver:
        agent = await create_analysis_subgraph(checkpointer=saver)
        config = {"configurable": {"thread_id": "analysis_test_001"}}
        inputs = {
            "messages": [HumanMessage(
                content="请根据以下材料分析北邮沙河校区的发展变化。\n【图像路径】\n/data/images/bupt_2020.jpg\n/data/images/bupt_2025.jpg\n\n【搜索内容】\n北邮沙河校区于2023年完成二期工程...")]
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
