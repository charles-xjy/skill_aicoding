'''
MinerU PDF 解析工具
使用本地 mineru-api 异步接口将 PDF 解析为 Markdown 文本。
流程：POST /tasks 提交 -> 轮询 GET /tasks/{task_id}/result -> 返回 md_content
'''

import os
import time
import subprocess
import requests
from pathlib import Path

PORT = 57321
BASE_URL = f'http://127.0.0.1:{PORT}'
MAX_CHARS = 4000


def _start_mineru_api() -> subprocess.Popen:
    env = os.environ.copy()
    env['MINERU_MODEL_SOURCE'] = 'modelscope'
    if 'CUDA_PATH' not in env:
        cuda_default = r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8'
        if Path(cuda_default).exists():
            env['CUDA_PATH'] = cuda_default
    return subprocess.Popen(
        ['mineru-api', '--host', '127.0.0.1', '--port', str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def _wait_for_api(timeout: int = 120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f'{BASE_URL}/health', timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _ensure_running() -> 'subprocess.Popen | None':
    '''确保 mineru-api 在运行，返回进程对象（仅当本次启动时），否则返回 None'''
    try:
        r = requests.get(f'{BASE_URL}/health', timeout=2)
        if r.status_code == 200:
            return None
    except Exception:
        pass
    print(f'启动 mineru-api（端口 {PORT}）...')
    proc = _start_mineru_api()
    if not _wait_for_api():
        proc.terminate()
        raise RuntimeError('mineru-api 启动超时，请检查 mineru 是否已正确安装')
    print('mineru-api 已就绪')
    return proc


def _submit_task(pdf_path: str) -> str:
    '''POST /tasks 提交异步解析任务，返回 task_id'''
    with open(pdf_path, 'rb') as f:
        resp = requests.post(
            f'{BASE_URL}/tasks',
            files={'files': (Path(pdf_path).name, f, 'application/pdf')},
            data={'return_md': 'true', 'backend': 'pipeline'},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    task_id = data.get('task_id')
    if not task_id:
        raise ValueError(f'未返回 task_id: {data}')
    return task_id


def _poll_result(task_id: str, poll_interval: int = 5, timeout: int = 300) -> str:
    '''轮询 GET /tasks/{task_id}/result，直到完成或超时，返回 md_content'''
    deadline = time.time() + timeout
    result_url = f'{BASE_URL}/tasks/{task_id}/result'
    while time.time() < deadline:
        resp = requests.get(result_url, timeout=30)
        if resp.status_code == 202:
            # 还在排队或处理中
            data = resp.json()
            queued = data.get('queued_ahead')
            if queued is not None:
                print(f'  排队中，前方还有 {queued} 个任务...')
            time.sleep(poll_interval)
            continue
        if resp.status_code == 409:
            data = resp.json()
            raise RuntimeError(f'mineru 解析失败: {data.get("error") or data}')
        resp.raise_for_status()
        # 200: 完成
        data = resp.json()
        results = data.get('results', {})
        if not results:
            raise ValueError(f'results 为空: {data}')
        first = next(iter(results.values()))
        md_content = first.get('md_content', '')
        if not md_content:
            raise ValueError(f'md_content 为空，字段列表: {list(first.keys())}')
        return md_content
    raise TimeoutError(f'等待 mineru 解析结果超时（task_id={task_id}）')


def parse_pdf(pdf_path: str) -> str:
    '''
    解析单个 PDF 文件，返回 Markdown 文本（截断至 MAX_CHARS）。
    调用方负责管理 mineru-api 的生命周期（见 pdf2md / pdf2md_batch）。
    '''
    print(f'正在解析: {Path(pdf_path).name}')
    task_id = _submit_task(pdf_path)
    md_text = _poll_result(task_id)
    print(f'解析完成，内容长度: {len(md_text)} 字符')
    if len(md_text) > MAX_CHARS:
        print(f'  内容过长，已截断至 {MAX_CHARS} 字')
        md_text = md_text[:MAX_CHARS] + f'\n\n[内容已截断，原始长度 {len(md_text)} 字符]'
    return md_text


def pdf2md(path: str) -> str:
    '''解析单个 PDF 文件为 Markdown，自动管理 mineru-api 生命周期'''
    pdf_path = Path(path).resolve()
    if not pdf_path.exists():
        return f'错误：文件不存在 -> {pdf_path}'
    if pdf_path.suffix.lower() != '.pdf':
        return f'错误：文件不是 PDF 格式 -> {pdf_path.name}'

    proc = None
    try:
        proc = _ensure_running()
        return parse_pdf(str(pdf_path))
    except Exception as e:
        return f'错误：解析失败 -> {e}'
    finally:
        if proc is not None:
            proc.terminate()


def pdf2md_batch(paths: list) -> list:
    '''批量解析多个 PDF，共用同一个 mineru-api 进程（并发提交，各自轮询）'''
    proc = None
    try:
        proc = _ensure_running()
        results = []
        for path in paths:
            pdf_path = Path(path).resolve()
            if not pdf_path.exists():
                results.append(f'错误：文件不存在 -> {pdf_path}')
                continue
            if pdf_path.suffix.lower() != '.pdf':
                results.append(f'错误：非 PDF 文件 -> {pdf_path.name}')
                continue
            try:
                results.append(parse_pdf(str(pdf_path)))
            except Exception as e:
                results.append(f'错误：解析失败 -> {e}')
        return results
    finally:
        if proc is not None:
            proc.terminate()


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('用法: python tool_pdf2md.py <pdf文件路径> [pdf文件路径2 ...]')
        sys.exit(1)
    pdf_files = sys.argv[1:]
    if len(pdf_files) == 1:
        print(pdf2md(pdf_files[0])[:2000])
    else:
        for f, r in zip(pdf_files, pdf2md_batch(pdf_files)):
            print(f'\n{"=" * 60}\n文件: {f}')
            print(r[:1000])
