"""
xiongan_agent LangGraph 服务端入口

供 `langgraph dev` 使用，不依赖任何交互式 CLI（questionary / input）。
通过 monkey-patch 替换两处交互点：
  1. model_probe._cached                        —— 预填端口缓存，跳过 questionary
  2. supervisor_agent_main._select_analysis_model —— 改为读环境变量

环境变量（在 ../.env 中配置）：
  VLLM_MAIN_PORT   主模型端口，如 8001（留空则取第一个可用端口）
  ANALYSIS_MODEL   analysis_agent 模型：remote 或 local（默认 remote）

启动：
  cd xiongan_frontend
  langgraph dev
"""

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── sys.path 必须在导入 xiongan_agent 模块之前设置 ──────────────────────────
_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "xiongan_agent"))
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

# 模块级导入，IDE 可静态解析
import model_probe as _mp                              # noqa: E402
import supervisor_agent.supervisor_agent_main as _sam  # noqa: E402
from supervisor_agent import create_supervisor_graph   # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 1. 预探测 vLLM 端口，填充 _mp._cached，跳过 questionary
# ─────────────────────────────────────────────────────────────────────────────

async def _probe_and_cache() -> None:
    if _mp._cached is not None:
        return

    preferred_port = os.environ.get("VLLM_MAIN_PORT", "").strip()
    available: list[tuple[str, str]] = []

    async with httpx.AsyncClient(timeout=3.0) as client:
        for port in _mp.CANDIDATE_PORTS:
            url = f"http://{_mp.BASE_IP}:{port}/v1/models"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    models = resp.json().get("data", [])
                    if models:
                        available.append(
                            (f"http://{_mp.BASE_IP}:{port}/v1", models[0]["id"])
                        )
            except Exception:
                pass

    if not available:
        api_key = _mp.SILICONFLOW_API_KEY
        if not api_key:
            raise RuntimeError(
                f"[xiongan_frontend] 所有候选端口 {_mp.CANDIDATE_PORTS} 均无响应，"
                "且未配置 SILICONFLOW_API_KEY，请确认 vLLM 服务已启动或配置硅基流动"
            )
        _mp._cached = (_mp.SILICONFLOW_BASE_URL, _mp.SILICONFLOW_MODEL, api_key)
        print(f"[xiongan_frontend] 本地 vLLM 不可用，回落到硅基流动  模型: {_mp.SILICONFLOW_MODEL}")
        return

    base_url, model_name = available[0]
    if preferred_port:
        for bu, mn in available:
            if str(urlparse(bu).port) == preferred_port:
                base_url, model_name = bu, mn
                break

    _mp._cached = (base_url, model_name, "vllm-no-key")
    print(f"[xiongan_frontend] vLLM 选定: {base_url}  模型: {model_name}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. 替换 _select_analysis_model，改为读环境变量，无 questionary
# ─────────────────────────────────────────────────────────────────────────────

def _patch_analysis_model_selector() -> None:
    choice = os.environ.get("ANALYSIS_MODEL", "remote").strip().lower()
    if choice not in ("remote", "local"):
        choice = "remote"

    async def _env_model() -> str:
        print(f"[xiongan_frontend] analysis_agent 模型: {choice}")
        return choice

    _sam._select_analysis_model = _env_model


# ─────────────────────────────────────────────────────────────────────────────
# 3. 构建图（checkpointer=None，由 LangGraph server 负责状态持久化）
# ─────────────────────────────────────────────────────────────────────────────

async def _build_graph():
    await _probe_and_cache()
    _patch_analysis_model_selector()
    return await create_supervisor_graph(checkpointer=None)


def _run_build():
    """兼容「已有事件循环」（uvicorn）和「无事件循环」两种启动场景。"""
    try:
        asyncio.get_running_loop()
        # uvicorn 已启动事件循环 → 在独立线程中新建循环执行，避免冲突
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _build_graph()).result(timeout=60)
    except RuntimeError:
        # 没有运行中的事件循环，直接 run
        return asyncio.run(_build_graph())


graph = _run_build()
