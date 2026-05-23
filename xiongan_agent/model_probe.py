"""
动态探测 vLLM 服务端口，收集所有可用端口后让用户选择（仅一个可用时自动选定）。
若所有本地端口均不可用，自动回落到硅基流动 API。
选择结果在进程生命周期内缓存，多次调用只选一次。
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx
import questionary
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv(Path(__file__).parent.parent / ".env")

BASE_IP = "10.129.107.145"
CANDIDATE_PORTS = [8001, 8002, 8003]

SILICONFLOW_MODEL = "Qwen/Qwen3.6-35B-A3B"
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")

_cached: tuple | None = None  # (base_url, model_name, api_key)


async def probe_vllm_model(ports: list | None = None) -> tuple:
    """
    探测所有 candidate ports，收集可用列表后：
    - 仅一个可用：自动选定，无需交互
    - 多个可用：通过 questionary 让用户选择
    - 全不可用：回落到硅基流动
    结果缓存，后续调用直接返回。
    """
    global _cached
    if _cached is not None:
        return _cached

    probe_ports = list(ports) if ports is not None else list(CANDIDATE_PORTS)
    available: list[tuple[str, str]] = []  # [(base_url, model_name), ...]

    print(f"\033[36m[端口探测] 正在探测 {probe_ports}...\033[0m")
    async with httpx.AsyncClient(timeout=3.0) as client:
        for port in probe_ports:
            url = f"http://{BASE_IP}:{port}/v1/models"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    if models:
                        model_name = models[0]["id"]
                        base_url = f"http://{BASE_IP}:{port}/v1"
                        available.append((base_url, model_name))
                        print(f"\033[36m[端口探测] ✅ port {port}  模型: {model_name}\033[0m")
                    else:
                        print(f"\033[33m[端口探测] ⚠️  port {port} 无模型\033[0m")
            except Exception:
                print(f"\033[33m[端口探测] ⚠️  port {port} 无响应\033[0m")

    if not available:
        if not SILICONFLOW_API_KEY:
            raise RuntimeError(
                f"所有候选端口 {probe_ports} 均无响应，且未配置 SILICONFLOW_API_KEY"
            )
        _cached = (SILICONFLOW_BASE_URL, SILICONFLOW_MODEL, SILICONFLOW_API_KEY)
        print(f"\033[33m[端口探测] 本地 vLLM 不可用，回落到硅基流动  模型: {SILICONFLOW_MODEL}\033[0m")
        return _cached

    if len(available) == 1:
        base_url, model_name = available[0]
        _cached = (base_url, model_name, "vllm-no-key")
        print(f"\033[36m[端口探测] 仅一个可用，自动选定 {base_url}  模型: {model_name}\033[0m")
        return _cached

    # 多个可用，交互选择
    choices = [
        questionary.Choice(
            title=f"{model_name}  @ port {get_port_from_base_url(base_url)}",
            value=(base_url, model_name),
        )
        for base_url, model_name in available
    ]
    selected = await questionary.select(
        "检测到多个可用模型，请选择主模型：",
        choices=choices,
        style=questionary.Style([
            ("selected", "fg:cyan bold"),
            ("pointer", "fg:cyan bold"),
            ("question", "bold"),
        ]),
    ).ask_async()

    if selected is None:
        selected = available[0]  # Ctrl+C fallback

    base_url, model_name = selected
    _cached = (base_url, model_name, "vllm-no-key")
    print(f"\033[36m[端口探测] 已选定 {base_url}  模型: {model_name}\033[0m")
    return _cached


async def make_vllm_model(**kwargs):
    """从探测或回落结果创建 init_chat_model 实例。"""
    base_url, model_name, api_key = await probe_vllm_model()
    return init_chat_model(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        model_provider="openai",
        **kwargs,
    )


def get_port_from_base_url(base_url: str) -> str:
    """从 base_url 提取端口号字符串，如 'http://host:8001/v1' → '8001'"""
    return str(urlparse(base_url).port)