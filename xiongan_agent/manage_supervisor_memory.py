"""
Supervisor 记忆管理器
交互式查看 / 删除 Redis 中各 Agent 线程的 Checkpoint
"""

import asyncio
import redis.asyncio as redis
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

DB_URI = "redis://127.0.0.1:6390"

# 颜色常量
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
# 消息类型 → 序号颜色
_MSG_COLOR = {
    "human":    "\033[1;36m",   # 亮青
    "ai":       "\033[1;32m",   # 亮绿
    "tool":     "\033[1;33m",   # 亮黄
    "system":   "\033[1;35m",   # 亮紫
}

# 主线程ID，子线程 ID 由此派生
MAIN_THREAD = "main_001"

THREADS = {
    "1": ("Supervisor (主图)",    MAIN_THREAD),
    "2": ("image_agent  (子图)",  f"sub_image_agent_of_{MAIN_THREAD}"),
    "3": ("search_agent (子图)",  f"sub_search_agent_of_{MAIN_THREAD}"),
    "4": ("analysis_agent (子图)", f"sub_analysis_agent_of_{MAIN_THREAD}"),
}


# ── 查看 ─────────────────────────────────────────────────────────────────────
async def view_memory(checkpointer: AsyncRedisSaver, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    latest = await checkpointer.aget_tuple(config)
    if not latest:
        print(f"\n[!] 线程 '{thread_id}' 没有找到任何记忆。")
        return

    count = 0
    async for _ in checkpointer.alist(config):
        count += 1

    print(f"\n=== 线程 '{thread_id}' 的记忆 ===")
    print(f"总检查点数量: {count}")

    channel = latest.checkpoint.get("channel_values", {}) if latest.checkpoint else {}
    messages = channel.get("messages", [])

    # 对 Supervisor 主图，额外展示 task_plan
    task_plan = channel.get("task_plan", [])
    if task_plan:
        print(f"\n--- 任务计划 (共 {len(task_plan)} 个) ---")
        status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "error": "❌"}
        for t in task_plan:
            icon = status_icon.get(t.get("status", ""), "?")
            desc = t.get("description", "")[:60]
            agent = t.get("agent", "")
            print(f"  {icon} {t.get('id')}. {desc}  [{agent}]")

    if not messages:
        print("\n消息列表为空。")
        return

    total = len(messages)
    print(f"\n共 {total} 条消息。")
    print(f"  直接回车       → 查看最后 5 条")
    print(f"  输入 N         → 查看最后 N 条  (如: 10)")
    print(f"  输入 start-end → 查看指定范围   (如: 3-8，从第3条到第8条)")

    raw = input("请选择查看范围: ").strip()

    # 解析用户输入
    if not raw:
        start, end = max(0, total - 5), total
    elif "-" in raw:
        try:
            a, b = raw.split("-", 1)
            start = max(0, int(a.strip()) - 1)   # 转为 0-based
            end   = min(total, int(b.strip()))
        except ValueError:
            print("格式错误，默认显示最后 5 条。")
            start, end = max(0, total - 5), total
    else:
        try:
            n = int(raw)
            start, end = max(0, total - n), total
        except ValueError:
            print("格式错误，默认显示最后 5 条。")
            start, end = max(0, total - 5), total

    print(f"\n--- 消息 {start + 1} ~ {end}（共 {end - start} 条）---")
    for i, msg in enumerate(messages[start:end], start=start + 1):
        content = msg.content if hasattr(msg, "content") else str(msg)
        # if isinstance(content, str) and len(content) > 300:
        #     content = content[:300] + "... (已截断)"
        # elif not isinstance(content, str):
        #     content = str(content)[:300]
        msg_type = getattr(msg, "type", "unknown")
        color = _MSG_COLOR.get(msg_type, "\033[1;37m")
        label = f"{color}{i}. [{msg_type.upper()}]{_RESET}"
        print(f"\n{label}\n{_DIM}{content}{_RESET}")


# ── 删除 ─────────────────────────────────────────────────────────────────────
async def delete_memory(thread_id: str):
    r = redis.from_url(DB_URI)
    try:
        keys = await r.keys(f"*{thread_id}*")
        if keys:
            await r.delete(*keys)
            print(f"\n[OK] 已清理 {len(keys)} 个 Redis Key（线程: '{thread_id}'）")
        else:
            print(f"\n[!] Redis 中没有找到线程 '{thread_id}' 的相关数据。")
    except Exception as e:
        print(f"\n[Error] 删除失败: {e}")
    finally:
        await r.aclose()


# ── 删除全部 ─────────────────────────────────────────────────────────────────
async def delete_all():
    r = redis.from_url(DB_URI)
    try:
        all_keys = []
        for _, thread_id in THREADS.values():
            keys = await r.keys(f"*{thread_id}*")
            all_keys.extend(keys)
        if all_keys:
            await r.delete(*all_keys)
            print(f"\n[OK] 已清理全部 {len(all_keys)} 个 Redis Key")
        else:
            print("\n[!] Redis 中没有找到任何相关数据。")
    except Exception as e:
        print(f"\n[Error] 删除失败: {e}")
    finally:
        await r.aclose()


# ── 主循环 ───────────────────────────────────────────────────────────────────
async def main():
    async with AsyncRedisSaver.from_conn_string(DB_URI) as checkpointer:
        while True:
            print("\n╔══════════════ Supervisor 记忆管理器 ══════════════╗")
            for key, (name, tid) in THREADS.items():
                print(f"  {key}. {name:<22} (ID: {tid})")
            print(f"  a. 删除全部线程记忆")
            print(f"  q. 退出")
            print("╚═══════════════════════════════════════════════════╝")

            choice = input("请选择 Agent (1-4 / a / q): ").strip().lower()

            if choice == "q":
                break

            if choice == "a":
                confirm = input("确定要删除所有线程的记忆吗？(y/n): ").strip().lower()
                if confirm == "y":
                    await delete_all()
                continue

            if choice not in THREADS:
                print("无效选项，请重新输入。")
                continue

            name, tid = THREADS[choice]
            print(f"\n当前选中: {name}")
            print("  1. 查看记忆")
            print("  2. 删除记忆")

            action = input("请选择操作 (1/2): ").strip()
            if action == "1":
                await view_memory(checkpointer, tid)
            elif action == "2":
                confirm = input(f"确定要删除 [{name}] 的所有记忆吗？(y/n): ").strip().lower()
                if confirm == "y":
                    await delete_memory(tid)
            else:
                print("无效的操作。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
