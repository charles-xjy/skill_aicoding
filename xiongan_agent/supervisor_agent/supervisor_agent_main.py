"""
================================================
LangGraph Supervisor Pattern - 规划式重构
================================================
核心流程：
1. ✅ 规划阶段：Supervisor 先将用户请求拆解为有序任务列表（1. 2. 3. ...）
2. ✅ 逐步执行：每次只执行一个任务，执行完后回到 Supervisor 确认
3. ✅ 状态追踪：每个任务有 pending / in_progress / completed / error 四种状态
4. ✅ 任务列表打印：每次状态变化后打印带图标的任务列表
5. ✅ 共享 Checkpointer：主图和子图共享同一个 Redis 连接
6. ✅ 层级 Thread ID：main_001 → sub_{agent}_of_main_001
"""

import operator
import json
import re as _re
from pathlib import Path
from typing import Annotated, List, Dict, Literal, Optional, TypedDict
from datetime import datetime


def _renumber_search_report(text: str, offset: int) -> tuple[str, int]:
    """
    将 search_agent 报告中所有 [n] 引注和来源列表按 offset 连续偏移。
    返回 (重编号后的文本, 本报告包含的最大引用编号)。
    offset=0 时原样返回，只统计数量。
    """
    nums = [int(m) for m in _re.findall(r'\[(\d+)\]', text)]
    if not nums:
        return text, 0
    max_num = max(nums)
    if offset == 0:
        return text, max_num
    result = _re.sub(r'\[(\d+)\]', lambda m: f'[{int(m.group(1)) + offset}]', text)
    return result, max_num

# ── Skill 工具函数 ────────────────────────────────────────────────────────────
_SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _read_skill_descriptions() -> list[dict]:
    """扫描 skills/ 目录，只读各 SKILL.md 的 frontmatter，不加载正文。"""
    result = []
    if not _SKILLS_DIR.exists():
        return result
    for folder in _SKILLS_DIR.iterdir():
        skill_file = folder / "SKILL.md"
        if not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        fm_match = _re.match(r"^---\n(.*?)\n---", text, _re.DOTALL)
        if not fm_match:
            continue
        fm = {}
        for line in fm_match.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
        result.append({
            "name": fm.get("name", folder.name),
            "description": fm.get("description", ""),
            "path": skill_file,
        })
    return result


def _load_skill_body(skill_path: Path) -> str:
    """读取 SKILL.md，去掉 frontmatter 后返回正文。"""
    text = skill_path.read_text(encoding="utf-8")
    return _re.sub(r"^---\n.*?\n---\n*", "", text, flags=_re.DOTALL).strip()

# LangChain imports
from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    HumanMessage,
    AIMessage,
)
from langchain_core.runnables import RunnableConfig

# LangGraph imports
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

# Subgraph imports
from image_agent import create_image_subgraph
from search_agent import create_search_subgraph
from analysis_agent import create_analysis_subgraph

# =============================================================================================
# 1. 定义模型
# =============================================================================================
_main_model = None


async def _get_main_model():
    global _main_model
    if _main_model is None:
        from model_probe import make_vllm_model
        _main_model = await make_vllm_model()
    return _main_model


# =============================================================================================
# 2. State 定义
# =============================================================================================
class SupervisorState(TypedDict):
    """
    Supervisor 状态：
    - messages:            对话历史（reducer: append）
    - task_plan:           任务列表，每项: {id, description, agent, status, result}
    - current_task_index:  当前执行到第几个任务（0-based）
    - next_step:           下一步路由目标
    - execution_log:       执行日志（整体覆盖，节点自行维护）
    - retry_count:         当前任务重试次数
    """

    messages: Annotated[List[BaseMessage], operator.add]
    task_plan: List[Dict]
    current_task_index: int
    next_step: Optional[
        Literal["image_agent", "search_agent", "analysis_agent", "supervisor", "end"]
    ]
    execution_log: List[str]
    retry_count: int


def create_supervisor_state() -> Dict:
    return {
        "messages": [],
        "task_plan": [],
        "current_task_index": 0,
        "next_step": "supervisor",
        "execution_log": [],
        "retry_count": 0,
    }


# =============================================================================================
# 3. 任务列表打印
# =============================================================================================
_STATUS_ICON = {
    "pending": "⬜",
    "in_progress": "🔄",
    "completed": "✅",
    "error": "❌",
}
_STATUS_COLOR = {
    "pending": "\033[2m",
    "in_progress": "\033[33m",
    "completed": "\033[32m",
    "error": "\033[31m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def print_task_list(task_plan: List[Dict]):
    total = len(task_plan)
    completed = sum(1 for t in task_plan if t["status"] == "completed")
    errors = sum(1 for t in task_plan if t["status"] == "error")
    err_tag = f"  {errors} 出错" if errors else ""

    print(f"\n{BOLD}{'━' * 58}{RESET}")
    print(f"{BOLD}  任务进度  {completed}/{total} 完成{err_tag}{RESET}")
    print(f"{BOLD}{'━' * 58}{RESET}")
    for t in task_plan:
        icon = _STATUS_ICON.get(t["status"], "?")
        color = _STATUS_COLOR.get(t["status"], "")
        agent_tag = f"{DIM}[{t['agent']}]{RESET}" if t.get("agent") else ""
        # 只显示 description 的第一行（\n\n 后面是追加的上下文，不展示）
        desc_first_line = t["description"].split("\n")[0][:70]
        print(f"  {icon} {color}{t['id']}. {desc_first_line}{RESET}  {agent_tag}")
        if t.get("result"):
            result_text = str(t["result"])
            # 去掉 【xxx 执行结果】\n 前缀，只展示实际内容
            if "执行结果】\n" in result_text:
                result_text = result_text.split("执行结果】\n", 1)[1]
            # 去掉 <think>...</think> 思考过程
            if "</think>" in result_text:
                result_text = result_text.split("</think>", 1)[-1].strip()
            snippet = result_text[:100]
            suffix = "..." if len(result_text) > 100 else ""
            print(f"       {DIM}└─ {snippet}{suffix}{RESET}")
    print(f"{BOLD}{'━' * 58}{RESET}\n")


async def _select_analysis_model() -> str:
    """questionary 交互选择分析模型，返回 'remote' 或 'local'"""
    import questionary
    from model_probe import probe_vllm_model, get_port_from_base_url
    base_url, model_name, _ = await probe_vllm_model()
    port = get_port_from_base_url(base_url)
    result = await questionary.select(
        "请选择 analysis_agent 使用的模型：",
        choices=[
            questionary.Choice(f"{model_name}  @ {port}（主模型）", value="remote"),
            questionary.Choice("urban-vlm   @ 8002（视觉模型）", value="local"),
        ],
        style=questionary.Style([
            ("selected", "fg:cyan bold"),
            ("pointer",  "fg:cyan bold"),
            ("question", "bold"),
        ]),
    ).ask_async()
    return result if result is not None else "remote"


# =============================================================================================
# 4. Supervisor 节点：规划 + 逐步调度
# =============================================================================================
async def supervisor_node(state: Dict) -> Dict:
    messages = state.get("messages", [])
    task_plan = list(state.get("task_plan", []))  # 浅拷贝，避免直接修改
    current_index = state.get("current_task_index", 0)
    execution_log = list(state.get("execution_log", []))

    # ── 规划阶段：task_plan 为空，第一次进入 ─────────────────────────────
    if not task_plan:
        # ── 1. 读取技能描述列表（只读 frontmatter，不加载正文）────────────────
        skills = _read_skill_descriptions()

        # ── 2. 路由判断：关键词触发式 prompt + 限制 max_tokens ────────────────
        # 每个 skill 的 description 用于触发判断，格式化为简洁触发说明
        skill_triggers = "\n".join(
            f'- 输出 {{"skill": "{s["name"]}"}} 当用户请求涉及：{s["description"][:80]}'
            for s in skills
        ) or "（暂无技能）"

        system_prompt = SystemMessage(content=f"""你是城市治理分析智能体，判断用户意图并立即响应：

{skill_triggers}
- 其他情况（问候/闲聊/询问功能）：直接用中文简短回复，介绍可用技能

只输出 JSON 或回复文字，禁止解释和分析。""")

        # max_tokens 限制总生成量（含思考块）；思考模型需要足够预算，否则思考耗尽后无法输出 JSON
        router_model = (await _get_main_model()).bind(max_tokens=2048)
        response = await router_model.ainvoke([system_prompt] + messages)
        content = response.content
        if "</think>" in content:
            content = content.split("</think>", 1)[-1].strip()

        # ── 3a. 检测是否调用了 skill ─────────────────────────────────────────
        skill_call = _re.search(r'\{[^{}]*"skill"\s*:\s*"([^"]+)"[^{}]*\}', content)
        matched_skill = None
        if skill_call:
            matched_name = skill_call.group(1).strip()
            matched_skill = next((s for s in skills if s["name"] == matched_name), None)

        if matched_skill is None:
            # 未调用 skill → LLM 已直接回复，结束
            log = f"[{datetime.now().isoformat()}] 💬 普通对话，直接回复"
            execution_log.append(log)
            print(f"\n\033[36m{log}{RESET}")
            return {
                "messages": [AIMessage(content=content)],
                "next_step": "end",
                "execution_log": execution_log,
            }

        # ── 3b. 命中 skill → 加载完整 SKILL.md，进行任务规划 ────────────────
        skill_body = _load_skill_body(matched_skill["path"])
        log = f"[{datetime.now().isoformat()}] 📖 加载技能: {matched_skill['name']}"
        execution_log.append(log)
        print(f"\n\033[36m{log}{RESET}")

        system_prompt = SystemMessage(content=skill_body)
        response = await (await _get_main_model()).ainvoke([system_prompt] + messages)

        try:
            content = response.content

            # 2. 优先从 ```json...``` 代码块提取
            _json_block = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, _re.DOTALL)
            if _json_block:
                plan_data = json.loads(_json_block.group(1))
            else:
                # 3. 回退：找最外层 { ... }
                start_idx = content.find("{")
                end_idx = content.rfind("}") + 1
                plan_data = (
                    json.loads(content[start_idx:end_idx])
                    if start_idx >= 0 and end_idx > start_idx
                    else {}
                )
        except (json.JSONDecodeError, AttributeError) as e:
            plan_data = {}
            log = f"[{datetime.now().isoformat()}] ❌ 规划解析失败: {e}"
            execution_log.append(log)
            print(f"\n\033[31m{log}{RESET}")
            print(f"\033[31m模型原始回复（前500字）:\n{response.content[:500]}{RESET}\n")

        raw_tasks = plan_data.get("tasks", [])
        task_plan = [
            {
                "id": t.get("id", i + 1),
                "description": t.get("description", ""),
                "query": t.get("query", ""),  # search_agent 专用：实际搜索关键词
                "agent": t.get("agent", "search_agent"),
                "status": "pending",
                "result": None,
            }
            for i, t in enumerate(raw_tasks)
        ]

        if not task_plan:
            log = f"[{datetime.now().isoformat()}] ❌ 规划失败，任务列表为空"
            execution_log.append(log)
            print(f"\n\033[31m{log}{RESET}\n")
            return {
                "messages": [response],
                "task_plan": [],
                "next_step": "end",
                "execution_log": execution_log,
            }

        # 第1次打印：全部 pending，展示规划结果
        log = f"[{datetime.now().isoformat()}] 📋 规划完成，共 {len(task_plan)} 个任务"
        execution_log.append(log)
        print(f"\n\033[36m{log}\033[0m")
        print_task_list(task_plan)

        # 第2次打印：第一个任务切为 in_progress
        task_plan[0]["status"] = "in_progress"
        log = f"[{datetime.now().isoformat()}] ▶️  开始任务 1: {task_plan[0]['description'][:50]}"
        execution_log.append(log)
        print(f"\n\033[36m{log}\033[0m")
        print_task_list(task_plan)

        return {
            # 任务规划 JSON 是内部状态，不写入 messages，不展示给用户
            "task_plan": task_plan,
            "current_task_index": 0,
            "next_step": task_plan[0]["agent"],
            "execution_log": execution_log,
            "retry_count": 0,
        }

    # ── 复查阶段：子图完成后回到 Supervisor ──────────────────────────────
    # 取最新的 AI 消息作为上一任务结果
    last_result = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_result = msg.content
            break

    # 判断上一任务是否出错（子图失败时消息内容带有固定标记）
    task_failed = "执行失败" in last_result

    if current_index < len(task_plan):
        task_plan[current_index]["status"] = "error" if task_failed else "completed"
        task_plan[current_index]["result"] = last_result if last_result else ""

    # ── search_agent 质量门控：内容不足时记录警告，但继续推进（不阻塞） ──
    if (not task_failed
            and current_index < len(task_plan)
            and task_plan[current_index]["agent"] == "search_agent"):
        effective = last_result
        if "</think>" in effective:
            effective = effective.split("</think>", 1)[-1]
        effective = effective.strip()
        if len(effective) < 400:
            log = (
                f"[{datetime.now().isoformat()}] ⚠️  search_agent 有效内容不足"
                f"（{len(effective)} 字），继续执行后续任务"
            )
            execution_log.append(log)
            print(f"\n\033[33m{log}{RESET}")
            if effective:
                print(f"\033[33m  当前内容预览: {effective[:200]}\033[0m")

    # 第N次打印：当前任务标为 completed / error
    log = (
        f"[{datetime.now().isoformat()}] "
        f"{'❌' if task_failed else '✅'} "
        f"任务 {current_index + 1} {'出错' if task_failed else '完成'}: "
        f"{task_plan[current_index]['description'][:40]}"
    )
    execution_log.append(log)
    print(f"\n\033[{'31' if task_failed else '32'}m{log}{RESET}")
    print_task_list(task_plan)

    # 移动到下一个任务
    next_index = current_index + 1
    if next_index >= len(task_plan):
        log = f"[{datetime.now().isoformat()}] 🎉 所有任务执行完毕"
        execution_log.append(log)
        print(f"\n\033[32m{log}{RESET}\n")
        return {
            "task_plan": task_plan,
            "current_task_index": next_index,
            "next_step": "end",
            "execution_log": execution_log,
        }

    # analysis_agent 是最终汇总任务：收集所有前序任务的结果，search_agent 引号连续编号
    if task_plan[next_index]["agent"] == "analysis_agent":
        context_parts = []
        ref_offset = 0  # 累计已使用的引用编号数
        for t in task_plan[:next_index]:
            if not t.get("result") or t["status"] != "completed":
                continue
            if t["agent"] == "image_agent":
                label = "卫星影像路径"
                context_parts.append(f"【任务{t['id']} - {label}】\n{t['result']}")
            elif t["agent"] == "search_agent":
                q = t.get("query", "").strip()
                label = f"搜索报告（主题：{q}）" if q else "搜索报告"
                renumbered, count = _renumber_search_report(t["result"], ref_offset)
                ref_offset += count
                context_parts.append(f"【任务{t['id']} - {label}】\n{renumbered}")
            else:
                label = t["agent"]
                context_parts.append(f"【任务{t['id']} - {label}】\n{t['result']}")
        if context_parts:
            task_plan[next_index]["description"] += "\n\n" + "\n\n".join(context_parts)

            # 从所有 search_agent 报告中提取来源行，拼成完整来源块追加到描述末尾
            # 这样即使模型忽略 system_prompt 指令，输入里也明确给出了来源列表
            all_source_lines: list[str] = []
            for part in context_parts:
                if "## 来源" in part:
                    src_section = part.split("## 来源", 1)[1].strip()
                    for line in src_section.splitlines():
                        stripped = line.strip()
                        if stripped and _re.match(r'\[\d+\]', stripped):
                            all_source_lines.append(stripped)
            if all_source_lines:
                sources_block = "\n".join(all_source_lines)
                task_plan[next_index]["description"] += (
                    "\n\n---\n"
                    "**【必须执行】报告最后必须完整附上以下来源列表，一条都不能省略：**\n"
                    "## 来源\n" + sources_block
                )

            log = f"[{datetime.now().isoformat()}] 📎 已将 {len(context_parts)} 个前序任务结果汇总给 analysis_agent（引用编号已连续化，共 {ref_offset} 条来源，{len(all_source_lines)} 行来源列表已追加）"
            execution_log.append(log)
            print(f"\n\033[33m{log}{RESET}")
    # image_agent → 非 analysis_agent 的下一任务：只透传图片路径
    elif (
        not task_failed
        and task_plan[current_index]["agent"] == "image_agent"
        and last_result.strip()
    ):
        task_plan[next_index][
            "description"
        ] += f"\n\n【来自 image_agent 的图像路径】\n{last_result.strip()}"
        log = (
            f"[{datetime.now().isoformat()}] 📎 已将图像路径附加到任务 {next_index + 1}"
        )
        execution_log.append(log)
        print(f"\n\033[33m{log}{RESET}")

    # 第N+1次打印：下一个任务切为 in_progress
    task_plan[next_index]["status"] = "in_progress"
    log = (
        f"[{datetime.now().isoformat()}] ▶️  开始任务 {next_index + 1}: "
        f"{task_plan[next_index]['description'][:50]}"
    )
    execution_log.append(log)
    print(f"\n\033[36m{log}{RESET}")
    print_task_list(task_plan)

    return {
        "task_plan": task_plan,
        "current_task_index": next_index,
        "next_step": task_plan[next_index]["agent"],
        "execution_log": execution_log,
        "retry_count": 0,
    }


# =============================================================================================
# 5. 子图节点包装器
# =============================================================================================
async def create_subgraph_node(subgraph_name: str, checkpointer, factory_kwargs: Dict = {}):
    """工厂函数：为每个子图创建一个节点包装器"""
    subgraph_factories = {
        "image_agent": create_image_subgraph,
        "search_agent": create_search_subgraph,
        "analysis_agent": create_analysis_subgraph,
    }
    factory = subgraph_factories[subgraph_name]

    async def subgraph_node(state: Dict, config: RunnableConfig) -> Dict:
        execution_log = list(state.get("execution_log", []))

        # 从 task_plan 读取当前任务描述 / query
        task_plan = state.get("task_plan", [])
        current_index = state.get("current_task_index", 0)
        current_task = task_plan[current_index] if task_plan and current_index < len(task_plan) else {}
        task_description = current_task.get("description", "无任务")

        # search_agent 只接收 query；其余 agent 接收完整 description（含汇总上下文）
        if subgraph_name == "search_agent":
            query = current_task.get("query", "").strip()
            agent_input = query if query else task_description
        else:
            agent_input = task_description

        parent_thread_id = config.get("configurable", {}).get("thread_id", "default")
        sub_thread_id = f"sub_{subgraph_name}_task{current_index}_of_{parent_thread_id}"
        sub_config = {"configurable": {"thread_id": sub_thread_id}}

        log_entry = (
            f"[{datetime.now().isoformat()}] 🚀 启动 {subgraph_name} | {sub_thread_id}"
        )
        execution_log.append(log_entry)
        print(f"\n\033[35m{log_entry}{RESET}")

        import traceback as _tb
        MAX_ATTEMPTS = 3
        last_exc: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                kwargs = dict(factory_kwargs)
                if subgraph_name == "analysis_agent":
                    kwargs["model_name"] = await _select_analysis_model()
                subgraph = await factory(checkpointer=checkpointer, **kwargs)
                inputs = {"messages": [HumanMessage(content=agent_input)]}
                if subgraph_name == "search_agent":
                    inputs["rounds"] = 0

                result = None
                async for chunk in subgraph.astream(
                    inputs, sub_config, stream_mode="updates", version="v2"
                ):
                    for node_name, node_data in chunk.get("data", {}).items():
                        if "messages" in node_data:
                            result = node_data

                if not (result and "messages" in result):
                    raise RuntimeError(f"{subgraph_name} 子图未返回任何消息")

                last_msg = result["messages"][-1]
                response_content = (
                    last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                )
                # 处理列表型 content（部分多模态 / 思考模型）
                if isinstance(response_content, list):
                    response_content = "\n".join(
                        b.get("text", "") for b in response_content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                # 剥离 <think>...</think> 思考块
                if "</think>" in response_content:
                    response_content = response_content.split("</think>", 1)[-1].strip()
                # content 为空时尝试 reasoning_content
                if not response_content:
                    ak = getattr(last_msg, "additional_kwargs", {}) or {}
                    response_content = ak.get("reasoning_content", "")

                log_entry = f"[{datetime.now().isoformat()}] ✅ {subgraph_name} 完成 | 结果长度: {len(response_content)}"
                execution_log.append(log_entry)
                print(f"\n\033[32m{log_entry}{RESET}")
                preview = response_content.replace("\n", " ")[:400]
                print(f"\033[2m  内容摘要: {preview}{'...' if len(response_content) > 400 else ''}\033[0m")

                is_final = subgraph_name == "analysis_agent"

                # analysis_agent 输出缺少 ## 来源 时，从前序 search 任务自动补充
                if is_final and "## 来源" not in response_content:
                    fallback_lines: list[str] = []
                    ref_off = 0
                    for t in task_plan:
                        if t.get("agent") == "search_agent" and t.get("status") == "completed" and t.get("result"):
                            renumbered, count = _renumber_search_report(t["result"], ref_off)
                            ref_off += count
                            if "## 来源" in renumbered:
                                src = renumbered.split("## 来源", 1)[1].strip()
                                for line in src.splitlines():
                                    s = line.strip()
                                    if s and _re.match(r'\[\d+\]', s):
                                        fallback_lines.append(s)
                    if fallback_lines:
                        response_content += "\n\n## 来源\n" + "\n".join(fallback_lines)

                return {
                    "messages": [
                        AIMessage(
                            # analysis_agent 是最终输出，直接用正文；其余标为 internal 前端过滤掉
                            content=response_content if is_final else f"【{subgraph_name} 执行结果】\n{response_content}",
                            name="final" if is_final else "internal",
                            metadata={
                                "source": subgraph_name,
                                "thread_id": sub_thread_id,
                            },
                        )
                    ],
                    "next_step": "supervisor",
                    "execution_log": execution_log,
                    "retry_count": 0,
                }

            except Exception as e:
                last_exc = e
                error_msg = f"[{datetime.now().isoformat()}] ❌ {subgraph_name} 执行失败 (尝试 {attempt + 1}/{MAX_ATTEMPTS}): {e}"
                execution_log.append(error_msg)
                print(f"\n\033[31m{error_msg}{RESET}")
                print(f"\033[31m{_tb.format_exc()}\033[0m")
                if attempt < MAX_ATTEMPTS - 1:
                    log_retry = f"[{datetime.now().isoformat()}] 🔄 重试 {subgraph_name} ({attempt + 2}/{MAX_ATTEMPTS})"
                    execution_log.append(log_retry)
                    print(f"\n\033[33m{log_retry}{RESET}")

        # 所有重试均失败
        log_entry = f"[{datetime.now().isoformat()}] ❌ {subgraph_name} {MAX_ATTEMPTS} 次均失败，跳过此任务"
        execution_log.append(log_entry)
        print(f"\n\033[31m{log_entry}{RESET}")
        return {
            "messages": [
                AIMessage(
                    content=f"【{subgraph_name} 执行失败】\n{MAX_ATTEMPTS} 次重试后仍失败: {last_exc}",
                    name="internal",
                )
            ],
            "next_step": "supervisor",
            "execution_log": execution_log,
            "retry_count": 0,
        }

    return subgraph_node


# =============================================================================================
# 6. 条件路由
# =============================================================================================
def should_continue(state: Dict) -> str:
    next_step = state.get("next_step", "end")
    route_map = {
        "image_agent": "image_agent",
        "search_agent": "search_agent",
        "analysis_agent": "analysis_agent",
        "end": END,
    }
    return route_map.get(next_step, END)


# =============================================================================================
# 7. 构建 Supervisor 图
# =============================================================================================
async def create_supervisor_graph(checkpointer):
    """
    创建并编译 Supervisor 图。
    checkpointer 为 None 时可用于可视化（不需要 Redis）。
    启动时先探测可用端口并让用户选择主模型；analysis_agent 模型在执行时单独选择。
    """
    # 提前触发端口探测 + 用户选择，结果缓存供后续所有 agent 复用
    from model_probe import probe_vllm_model
    await probe_vllm_model()

    workflow = StateGraph(SupervisorState)

    workflow.add_node("supervisor", supervisor_node)

    image_node = await create_subgraph_node("image_agent", checkpointer)
    search_node = await create_subgraph_node("search_agent", checkpointer)
    analysis_node = await create_subgraph_node("analysis_agent", checkpointer)
    workflow.add_node("image_agent", image_node)
    workflow.add_node("search_agent", search_node)
    workflow.add_node("analysis_agent", analysis_node)

    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        should_continue,
        {
            "image_agent": "image_agent",
            "search_agent": "search_agent",
            "analysis_agent": "analysis_agent",
            END: END,
        },
    )
    workflow.add_edge("image_agent", "supervisor")
    workflow.add_edge("search_agent", "supervisor")
    workflow.add_edge("analysis_agent", "supervisor")

    return workflow.compile(checkpointer=checkpointer)
