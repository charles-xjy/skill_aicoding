"""
MinerU PDF 解析工具
使用 mineru-api 将 PDF 文件解析为 Markdown 文本
"""

import os
import time
import subprocess
import requests
from pathlib import Path
from langchain_core.tools import tool


def _start_mineru_api(port: int) -> subprocess.Popen:
    """在后台启动 mineru-api 服务"""
    env = os.environ.copy()
    env["MINERU_MODEL_SOURCE"] = "modelscope"  # 国内用 modelscope，访问更快
    proc = subprocess.Popen(
        ["mineru-api", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    return proc


def _wait_for_api(base_url: str, timeout: int = 120) -> bool:
    """等待 mineru-api 服务启动就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{base_url}/health", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _parse_pdf_via_api(pdf_path: str, base_url: str) -> str:
    """
    通过 mineru-api 同步接口解析 PDF，返回 Markdown 文本。
    使用 POST /file_parse 同步端点，等待解析完成后直接返回结果。
    """
    with open(pdf_path, "rb") as f:
        response = requests.post(
            f"{base_url}/file_parse",
            files={"files": (Path(pdf_path).name, f, "application/pdf")},
            data={"return_md": "true"},
            timeout=300,
        )
    response.raise_for_status()

    result = response.json()
    results = result.get("results", [])
    if not results:
        raise ValueError(f"API 返回结果为空: {result}")

    md_content = results[0].get("md_content", "")
    if not md_content:
        raise ValueError(f"未找到 md_content 字段，返回数据: {list(results[0].keys())}")

    return md_content


@tool
def pdf2md(path: str) -> str:
    """
    将指定的本地 PDF 文件解析并返回其 Markdown 文本内容。

    支持提取文字、复杂的 LaTeX 公式和表格。
    当需要深入分析某个特定的 PDF 文档（如论文、报告）时，请调用此工具。

    参数:
        path (str): 待解析的 PDF 文件路径（例如 "download_pdf/test.pdf"）。

    返回:
        str: 解析后的 Markdown 文本。如果解析失败，返回错误描述。
    """
    pdf_path = Path(path).resolve()

    if not pdf_path.exists():
        return f"错误：文件不存在 -> {pdf_path}"
    if pdf_path.suffix.lower() != ".pdf":
        return f"错误：文件不是 PDF 格式 -> {pdf_path.name}"

    port = 57321
    base_url = f"http://127.0.0.1:{port}"
    proc = None

    try:
        # 检查服务是否已在运行
        already_running = False
        try:
            r = requests.get(f"{base_url}/health", timeout=2)
            already_running = r.status_code == 200
        except Exception:
            pass

        if not already_running:
            print(f"🚀 启动 mineru-api 服务（端口 {port}）...")
            proc = _start_mineru_api(port)
            ready = _wait_for_api(base_url, timeout=120)
            if not ready:
                return "错误：mineru-api 服务启动超时，请检查 mineru 是否已正确安装。"
            print("✅ mineru-api 已就绪")

        print(f"📄 正在解析: {pdf_path.name}")
        md_text = _parse_pdf_via_api(str(pdf_path), base_url)
        print(f"✅ 解析完成，内容长度: {len(md_text)} 字符")
        return md_text

    except requests.exceptions.RequestException as e:
        return f"错误：API 请求失败 -> {e}"
    except Exception as e:
        return f"错误：解析失败 -> {e}"
    finally:
        # 仅当本次调用启动了服务时才关闭
        if proc is not None:
            proc.terminate()


# ── 多文件批量解析（非 tool，供直接调用）──────────────────────────────────────

def pdf2md_batch(paths: list[str]) -> list[str]:
    """批量解析多个 PDF 文件，返回对应的 Markdown 文本列表。"""
    port = 57321
    base_url = f"http://127.0.0.1:{port}"
    proc = None

    try:
        r = requests.get(f"{base_url}/health", timeout=2)
        already_running = r.status_code == 200
    except Exception:
        already_running = False

    if not already_running:
        proc = _start_mineru_api(port)
        ready = _wait_for_api(base_url, timeout=120)
        if not ready:
            return [f"错误：mineru-api 服务启动超时"] * len(paths)

    results = []
    try:
        for path in paths:
            pdf_path = Path(path).resolve()
            if not pdf_path.exists():
                results.append(f"错误：文件不存在 -> {pdf_path}")
                continue
            if pdf_path.suffix.lower() != ".pdf":
                results.append(f"错误：非 PDF 文件 -> {pdf_path.name}")
                continue
            try:
                md = _parse_pdf_via_api(str(pdf_path), base_url)
                results.append(md)
            except Exception as e:
                results.append(f"错误：解析失败 -> {e}")
    finally:
        if proc is not None:
            proc.terminate()

    return results


# ── 快速测试 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python tool_pdf2md.py <pdf文件路径> [pdf文件路径2 ...]")
        sys.exit(1)

    pdf_files = sys.argv[1:]

    if len(pdf_files) == 1:
        result = pdf2md.invoke({"path": pdf_files[0]})
        print(result[:2000])
    else:
        results = pdf2md_batch(pdf_files)
        for i, (f, r) in enumerate(zip(pdf_files, results)):
            print(f"\n{'='*60}")
            print(f"文件 {i+1}: {f}")
            print(r[:1000])
