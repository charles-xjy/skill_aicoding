'''
测试远程 mineru-api GPU 占用状态
运行: python test_remote_gpu.py
'''
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
from tool.tool_pdf2md import REMOTE_BASE_URL, SSH_USER, MINERU_API_HOST, MIN_FREE_VRAM_MB, _remote_gpu_available

def test_remote_gpu():
    print(f'远程服务地址: {REMOTE_BASE_URL}')
    print(f'SSH: {SSH_USER}@{MINERU_API_HOST}')
    print(f'最低显存阈值: {MIN_FREE_VRAM_MB} MiB ({MIN_FREE_VRAM_MB // 1024} GB)')
    print('-' * 50)

    # 1. nvidia-smi 原始输出
    print('nvidia-smi 各 GPU 空闲显存 (MiB):')
    try:
        result = subprocess.run(
            [
                'ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes',
                f'{SSH_USER}@{MINERU_API_HOST}',
                'nvidia-smi --query-gpu=index,memory.free,memory.total --format=csv,noheader,nounits',
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                idx, free, total = [x.strip() for x in line.split(',')]
                print(f'  GPU {idx}: {free} / {total} MiB 空闲')
        else:
            print(f'  SSH 失败: {result.stderr.strip()}')
    except Exception as e:
        print(f'  SSH 异常: {e}')

    print('-' * 50)

    # 2. GPU 可用性判断结果
    available = _remote_gpu_available()
    print(f'GPU 可用: {available}')
    print(f'将使用后端: {"hybrid-auto-engine (远程GPU)" if available else "pipeline (本地CPU)"}')

if __name__ == '__main__':
    test_remote_gpu()
