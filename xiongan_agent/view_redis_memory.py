"""
查看 / 删除 LangGraph AsyncRedisSaver 存储在 Redis 中的 Checkpoint 记忆
key 格式: checkpoint:{thread_id}:{ns}:{checkpoint_id}  (ReJSON-RL 类型)

查看用法:
  python view_redis_memory.py              # 列出所有 thread 的最新 3 个 checkpoint
  python view_redis_memory.py main_001     # 只看指定 thread

删除用法:
  python view_redis_memory.py --delete              # 删除全部 checkpoint（谨慎！）
  python view_redis_memory.py --delete main_001     # 只删除指定 thread 的 checkpoint
  python view_redis_memory.py --delete sub_image_agent_of_main_001  # 删除指定子图的 checkpoint

查看原始 Redis 格式:
  python view_redis_memory.py --raw              # 输出所有 checkpoint 的原始 JSON
  python view_redis_memory.py --raw main_001     # 只输出指定 thread 的原始 JSON

删除范围说明:
  - 同时清理 checkpoint* 和 write_keys_zset* 两类 key
  - 子图 checkpoint 的 thread_id 格式为 sub_{agent}_of_{parent_thread_id}
  - 删除父 thread 不会自动删除其子图 thread，需分别执行

也可直接用 redis-cli 删除:
  redis-cli -h 10.129.107.145 DEL $(redis-cli -h 10.129.107.145 KEYS "checkpoint:main_001:*")
"""

import asyncio
import json
import sys
import io

# Windows 终端强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from redis.asyncio import Redis

REDIS_URL = "redis://10.129.107.145:6379"

BOLD  = "\033[1m"
RESET = "\033[0m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RED   = "\033[91m"
DIM   = "\033[2m"
MAG   = "\033[95m"


def sep(char="─", n=70):
    print(DIM + char * n + RESET)


def fmt_msg(msg: dict) -> str:
    role    = msg.get("type") or msg.get("role") or "?"
    content = msg.get("content") or msg.get("data", {}).get("content") or ""
    if isinstance(content, list):
        content = " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    color = GREEN if "human" in role.lower() else CYAN if "ai" in role.lower() else YELLOW
    snippet = str(content)[:300] + ("..." if len(str(content)) > 300 else "")
    return f"  {color}{BOLD}[{role}]{RESET} {snippet}"


async def get_json(client: Redis, key: str):
    """用 RedisJSON 命令读取整个文档"""
    try:
        raw = await client.execute_command("JSON.GET", key, "$")
        if raw is None:
            return None
        data = json.loads(raw)
        # JSON.GET 返回列表包裹
        return data[0] if isinstance(data, list) and data else data
    except Exception as e:
        return {"_error": str(e)}


def extract_content(msg: dict) -> str:
    """从 LangChain constructor 格式或普通格式提取消息内容"""
    # LangChain 序列化格式: {"lc":1,"type":"constructor","id":[...],"kwargs":{...}}
    if msg.get("type") == "constructor":
        kwargs = msg.get("kwargs") or {}
        content = kwargs.get("content", "")
    else:
        content = msg.get("content") or msg.get("data", {}).get("content", "")

    if isinstance(content, list):
        content = " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return str(content)


def get_role(msg: dict) -> str:
    if msg.get("type") == "constructor":
        cls_id = msg.get("id", [])
        cls_name = cls_id[-1] if cls_id else ""
        if "HumanMessage" in cls_name:
            return "human"
        if "AIMessage" in cls_name:
            return "ai"
        if "SystemMessage" in cls_name:
            return "system"
        if "ToolMessage" in cls_name:
            return "tool"
        return cls_name
    return msg.get("type") or msg.get("role") or "?"


def print_channel_values(cv: dict):
    for field, val in cv.items():
        if field == "messages":
            msgs = val if isinstance(val, list) else []
            print(f"\n  {YELLOW}{BOLD}消息历史 ({len(msgs)} 条):{RESET}")
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                role = get_role(m)
                content = extract_content(m)
                color = GREEN if role == "human" else CYAN if role == "ai" else YELLOW
                snippet = content[:400] + ("..." if len(content) > 400 else "")
                print(f"    {color}{BOLD}[{role}]{RESET} {snippet}")
        elif field == "execution_log":
            logs = val if isinstance(val, list) else []
            if logs:
                print(f"\n  {GREEN}{BOLD}执行日志 ({len(logs)} 条):{RESET}")
                for entry in logs:
                    print(f"    {entry}")
        elif field == "task_history":
            tasks = val if isinstance(val, list) else []
            if tasks:
                print(f"\n  {CYAN}{BOLD}任务历史 ({len(tasks)} 条):{RESET}")
                for t in tasks:
                    print(f"    {json.dumps(t, ensure_ascii=False)}")
        elif field not in ("__start__",):
            v_str = str(val)
            if v_str and v_str != "None":
                print(f"  {BOLD}{field}:{RESET} {v_str[:200]}")


def print_checkpoint(data: dict):
    if not isinstance(data, dict):
        print(f"  {data}")
        return
    if "_error" in data:
        print(f"  {RED}读取失败: {data['_error']}{RESET}")
        return

    # 元信息
    step   = data.get("step", "?")
    source = data.get("source", "?")
    ts_ms  = data.get("checkpoint_ts")
    ts_str = f"{ts_ms/1000:.1f}s" if ts_ms else ""
    print(f"  step={step}  source={source}  ts={ts_str}")

    # 真正的状态在 data["checkpoint"]["channel_values"]
    ckpt = data.get("checkpoint")
    if isinstance(ckpt, dict):
        cv = ckpt.get("channel_values") or {}
    else:
        cv = {}

    if cv:
        print_channel_values(cv)
    else:
        print(f"  {DIM}(无 channel_values){RESET}")


async def main(filter_thread: str = None):
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  LangGraph Redis 记忆查看器{RESET}")
    print(f"{DIM}  {REDIS_URL}{RESET}")
    if filter_thread:
        print(f"{DIM}  过滤 thread: {filter_thread}{RESET}")
    print(f"{BOLD}{'═'*70}{RESET}\n")

    client = Redis.from_url(REDIS_URL, decode_responses=False)

    try:
        await client.ping()
        print(f"{GREEN}[OK] Redis 连接成功{RESET}\n")
    except Exception as e:
        print(f"{RED}[ERR] 连接失败: {e}{RESET}")
        return

    # 扫描所有 checkpoint:* key（跳过 checkpoint_write 和 write_keys_zset）
    all_keys = []
    cursor = 0
    while True:
        cursor, batch = await client.scan(cursor, match="checkpoint:*", count=500)
        for k in batch:
            kstr = k.decode("utf-8", errors="replace")
            # 只要主 checkpoint，跳过 checkpoint_write
            if not kstr.startswith("checkpoint_write"):
                if filter_thread is None or filter_thread in kstr:
                    all_keys.append(kstr)
        if cursor == 0:
            break

    if not all_keys:
        print(f"{YELLOW}未找到 checkpoint 记录{RESET}")
        await client.aclose()
        return

    # 按 thread_id 分组
    thread_map: dict[str, list[str]] = {}
    for key in all_keys:
        parts = key.split(":")
        tid = parts[1] if len(parts) > 1 else "unknown"
        thread_map.setdefault(tid, []).append(key)

    print(f"找到 {BOLD}{len(thread_map)}{RESET} 个 thread，共 {len(all_keys)} 个 checkpoint\n")

    for tid, keys in sorted(thread_map.items()):
        print(f"\n{MAG}{BOLD}{'━'*70}{RESET}")
        print(f"{MAG}{BOLD}  Thread: {tid}  ({len(keys)} checkpoints){RESET}")
        print(f"{MAG}{BOLD}{'━'*70}{RESET}")

        # 只显示最新的几个 checkpoint（按 key 字典序倒序，uuid 带时间戳）
        for key in sorted(keys, reverse=True)[:3]:
            sep()
            print(f"  {CYAN}checkpoint_id:{RESET} {DIM}{key.split(':')[-1]}{RESET}")
            data = await get_json(client, key)
            print_checkpoint(data)

        if len(keys) > 3:
            print(f"\n  {DIM}(还有 {len(keys)-3} 个更早的 checkpoint 未显示){RESET}")

    sep("═")
    print(f"\n  查看完毕\n")
    await client.aclose()


async def delete_memory(filter_thread: str = None):
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}  LangGraph Redis 记忆删除{RESET}")
    print(f"{DIM}  {REDIS_URL}{RESET}")
    if filter_thread:
        print(f"{DIM}  只删除 thread: {filter_thread}{RESET}")
    else:
        print(f"{RED}{BOLD}  删除全部 checkpoint！{RESET}")
    print(f"{BOLD}{'═'*70}{RESET}\n")

    client = Redis.from_url(REDIS_URL, decode_responses=False)
    try:
        await client.ping()
        print(f"{GREEN}[OK] Redis 连接成功{RESET}\n")
    except Exception as e:
        print(f"{RED}[ERR] 连接失败: {e}{RESET}")
        return

    patterns = ["checkpoint*", "write_keys_zset*"]
    all_keys = []
    for pat in patterns:
        cursor = 0
        while True:
            cursor, batch = await client.scan(cursor, match=pat, count=500)
            for k in batch:
                kstr = k.decode("utf-8", errors="replace")
                if filter_thread is None or filter_thread in kstr:
                    all_keys.append(k)
            if cursor == 0:
                break

    if not all_keys:
        print(f"{YELLOW}未找到匹配的 key{RESET}")
        await client.aclose()
        return

    print(f"找到 {BOLD}{len(all_keys)}{RESET} 个 key，正在删除...")
    await client.delete(*all_keys)
    print(f"{GREEN}[OK] 已删除 {len(all_keys)} 个 key{RESET}\n")
    await client.aclose()


async def raw_view(filter_thread: str = None):
    """直接输出 Redis 中存储的原始 JSON，不做任何格式化"""
    client = Redis.from_url(REDIS_URL, decode_responses=False)
    try:
        await client.ping()
    except Exception as e:
        print(f"{RED}[ERR] 连接失败: {e}{RESET}")
        return

    all_keys = []
    cursor = 0
    while True:
        cursor, batch = await client.scan(cursor, match="checkpoint:*", count=500)
        for k in batch:
            kstr = k.decode("utf-8", errors="replace")
            if not kstr.startswith("checkpoint_write"):
                if filter_thread is None or filter_thread in kstr:
                    all_keys.append(kstr)
        if cursor == 0:
            break

    if not all_keys:
        print(f"{YELLOW}未找到 checkpoint 记录{RESET}")
        await client.aclose()
        return

    for key in sorted(all_keys):
        print(f"\n{MAG}{BOLD}key: {key}{RESET}")
        raw = await client.execute_command("JSON.GET", key, "$")
        if raw is None:
            print("  (empty)")
        else:
            data = json.loads(raw)
            obj = data[0] if isinstance(data, list) and data else data
            print(json.dumps(obj, ensure_ascii=False, indent=2))

    await client.aclose()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--delete":
        thread = args[1] if len(args) > 1 else None
        asyncio.run(delete_memory(thread))
    elif args and args[0] == "--raw":
        thread = args[1] if len(args) > 1 else None
        asyncio.run(raw_view(thread))
    else:
        asyncio.run(main(args[0] if args else None))
