"""
xiongan_agent 记忆管理器
交互式查看 / 删除 Redis Checkpoint（方向键菜单）

用法:
  python memory_manager.py

会话 ID 格式:
  主 Supervisor : main_YYYYMMDD_HHMMSS（新）/ main_001（旧）
  子 Agent      : sub_{agent_name}_of_{main_id}
"""

import asyncio

import os
import sys

import json
import io
import re

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import questionary
import redis.asyncio as redis
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

DB_URI = "redis://10.129.107.145:6379"

_MAIN_RE       = re.compile(r"^main_\d{8}_\d{6}$")
_STANDALONE_RE = re.compile(r"^main_search_\d{8}_\d{6}$")

_SUB_AGENTS = [
    ("",               "主 Supervisor"),
    ("image_agent",    "图像 Agent"),
    ("search_agent",   "搜索 Agent"),
    ("analysis_agent", "分析 Agent"),
]

# 独立运行的 Agent 会话：前缀匹配，key = thread_id 前缀, value = 显示名称
_STANDALONE_PREFIXES: dict[str, str] = {
    "main_search_": "搜索 Agent（独立模式）",
}


def make_sub_thread_id(agent_name: str, parent_thread_id: str) -> str:
    """生成标准化子 Agent thread ID，与记忆管理器扫描格式一致。"""
    return f"sub_{agent_name}_of_{parent_thread_id}"

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
MAG    = "\033[95m"

def _clear():
    sys.stdout.flush()
    # \033[2J clears entire screen; \033[H moves cursor to top-left
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  xiongan_agent 记忆管理器{RESET}")
    print(f"{DIM}  {DB_URI}{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}\n")
    sys.stdout.flush()


_Q_STYLE = questionary.Style([
    ("selected", "fg:cyan bold"),
    ("pointer",  "fg:cyan bold"),
    ("question", "bold"),
])


# ─────────────────────────────────────────────────────────────
# 方向键交互选择器
# ─────────────────────────────────────────────────────────────

async def _select(prompt: str, options: list) -> str:
    """options = [(label, key), ...]，用 ↑↓ 选择，Enter 确认，返回 key"""
    result = await questionary.select(
        prompt,
        choices=[questionary.Choice(label, value=val) for label, val in options],
        use_shortcuts=False,
        style=_Q_STYLE,
    ).ask_async()
    return result if result is not None else options[-1][1]


async def _confirm(text: str) -> bool:
    result = await _select(text, [("否", "n"), ("是", "y")])
    return result == "y"


async def _select_number(prompt: str, min_val: int, max_val: int) -> int | None:
    """方向键选数字，返回 None 表示取消"""
    choices = [(str(i), str(i)) for i in range(min_val, max_val + 1)]
    choices.append(("取消", "q"))
    result = await _select(prompt, choices)
    return None if result == "q" else int(result)


# ─────────────────────────────────────────────────────────────
# Redis 扫描 / Checkpoint 读取
# ─────────────────────────────────────────────────────────────


async def _scan_sessions(r) -> list:
    """返回所有主会话 ID，时间戳格式在前，旧格式附后"""
    raw_keys = await r.keys("checkpoint:main_*")
    session_ids: set = set()
    for k in raw_keys:
        kstr = k.decode() if isinstance(k, bytes) else k
        parts = kstr.split(":")
        if len(parts) > 1 and parts[1].startswith("main_"):
            session_ids.add(parts[1])
    # 时间戳格式（新）排前面，独立搜索次之，其余（如 main_001）附后
    new_fmt        = sorted([s for s in session_ids if _MAIN_RE.match(s)], reverse=True)
    standalone_fmt = sorted([s for s in session_ids if _STANDALONE_RE.match(s)], reverse=True)
    old_fmt        = sorted([s for s in session_ids if not _MAIN_RE.match(s) and not _STANDALONE_RE.match(s)])
    return new_fmt + standalone_fmt + old_fmt


async def _collect_checkpoints(checkpointer: AsyncRedisSaver, thread_id: str) -> list:
    config = {"configurable": {"thread_id": thread_id}}
    checkpoints = []
    try:
        async for cp in checkpointer.alist(config):
            checkpoints.append(cp)
    except Exception as e:
        print(f"  [警告] 列出检查点时出错: {e}")
    return checkpoints


def _get_messages(checkpoint) -> list:
    try:
        if isinstance(checkpoint, dict):
            cv = checkpoint.get("channel_values", {})
        else:
            cv = getattr(checkpoint, "channel_values", {})
        return cv.get("messages", []) if isinstance(cv, dict) else []
    except Exception:
        return []


def _fmt_msg(msg) -> tuple:
    """返回 (msg_type, content_str, extra)"""
    if hasattr(msg, "content"):
        content = msg.content
        msg_type = getattr(msg, "type", "unknown")
        tool_calls = getattr(msg, "tool_calls", []) or []
        name = getattr(msg, "name", "") or ""
    elif isinstance(msg, dict):
        if msg.get("type") == "constructor":
            kwargs = msg.get("kwargs", {})
            content = kwargs.get("content", "")
            cls_name = (msg.get("id") or [""])[-1]
            role_map = {
                "Human": "human",
                "AI": "ai",
                "Tool": "tool",
                "System": "system",
            }
            msg_type = next((v for k, v in role_map.items() if k in cls_name), cls_name)
            tool_calls = kwargs.get("tool_calls", []) or []
            name = kwargs.get("name", "") or ""
        else:
            content = msg.get("content", "")
            msg_type = msg.get("type", "unknown")
            tool_calls = msg.get("tool_calls", []) or []
            name = msg.get("name", "") or ""
    else:
        return "unknown", str(msg), ""

    content_str = (
        json.dumps(content, ensure_ascii=False, indent=2)
        if isinstance(content, list)
        else str(content)
    )

    extra = ""
    if tool_calls:
        tc_names = [
            tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
            for tc in tool_calls
        ]
        extra += f" [工具: {', '.join(tc_names)}]"
    if name:
        extra += f" [名: {name}]"

    return msg_type, content_str, extra


async def _show_messages(messages: list, start_label: int = 1):
    if not messages:
        print("消息列表为空。")
        return
    for i, msg in enumerate(messages, start=start_label):
        msg_type, content_str, extra = _fmt_msg(msg)
        color = GREEN if "human" in msg_type else CYAN if "ai" in msg_type else YELLOW
        print(f"\n{DIM}{'─' * 62}{RESET}")
        print(f"#{i} {color}{BOLD}[{msg_type.upper()}]{RESET}{extra}")
        print(f"{DIM}{'─' * 62}{RESET}")
        print(content_str)
    print(f"\n{DIM}{'─' * 62}{RESET}")
    print(f"(共 {len(messages)} 条消息)")


# ─────────────────────────────────────────────────────────────
# 查看记忆
# ─────────────────────────────────────────────────────────────


async def view_memory(checkpointer: AsyncRedisSaver, thread_id: str):
    checkpoints = await _collect_checkpoints(checkpointer, thread_id)
    if not checkpoints:
        print(f"\n[!] 线程 '{thread_id}' 没有找到任何记忆。")
        return

    messages = next(
        (
            _get_messages(cp.checkpoint)
            for cp in checkpoints
            if _get_messages(cp.checkpoint)
        ),
        [],
    )
    total = len(messages)

    print(f"\n{MAG}{BOLD}=== {thread_id} ==={RESET}")
    print(f"检查点数量: {len(checkpoints)}  |  最新有效检查点消息数: {total}")

    while True:
        _clear()
        choice = await _select(
            "查看方式：",
            [
                (f"查看全部消息 ({total} 条)", "1"),
                ("查看最后 N 条", "2"),
                ("查看前 N 条", "3"),
                ("查看指定范围（第 X~Y 条）", "4"),
                ("按检查点查看", "5"),
                ("返回", "q"),
            ],
        )

        if choice == "q":
            break

        elif choice == "1":
            await _show_messages(messages)

        elif choice == "2":
            n = await _select_number(f"显示最后几条：", 1, total)
            if n is not None:
                await _show_messages(messages[-n:], start_label=total - n + 1)

        elif choice == "3":
            n = await _select_number(f"显示前几条：", 1, total)
            if n is not None:
                await _show_messages(messages[:n])

        elif choice == "4":
            x = await _select_number(f"起始条数：", 1, total)
            if x is not None:
                y = await _select_number(f"结束条数：", x, total)
                if y is not None:
                    await _show_messages(messages[x - 1 : y], start_label=x)

        elif choice == "5":
            cp_choices = []
            for idx, cp in enumerate(checkpoints):
                cp_id = cp.config.get("configurable", {}).get(
                    "checkpoint_id", f"cp_{idx}"
                )
                n_msgs = len(_get_messages(cp.checkpoint))
                cp_choices.append(
                    (f"[{idx}] {str(cp_id)[:22]}…  消息={n_msgs}", str(idx))
                )
            cp_choices.append(("取消", "q"))
            sel = await _select("选择检查点：", cp_choices)
            if sel != "q":
                cp_msgs = _get_messages(checkpoints[int(sel)].checkpoint)
                print(f"\n{MAG}=== 检查点 {sel} ==={RESET}")
                await _show_messages(cp_msgs)


# ─────────────────────────────────────────────────────────────
# 删除记忆
# ─────────────────────────────────────────────────────────────


async def _delete_by_cp_ids(cp_ids: list) -> int:
    r = redis.from_url(DB_URI)
    total = 0
    for cp_id in cp_ids:
        if not cp_id:
            continue
        keys = await r.keys(f"*{cp_id}*")
        if keys:
            await r.delete(*keys)
            total += len(keys)
    await r.aclose()
    return total


async def _delete_thread(thread_id: str):
    r = redis.from_url(DB_URI)
    keys = await r.keys(f"*{thread_id}*")
    if keys:
        await r.delete(*keys)
        print(f"[OK] 已清理 {len(keys)} 个 Redis 键。")
    else:
        print(f"[!] 未找到 '{thread_id}' 相关数据。")
    await r.aclose()


async def delete_checkpoints(checkpointer: AsyncRedisSaver, thread_id: str) -> bool:
    """Returns True if all checkpoints were deleted."""
    checkpoints = await _collect_checkpoints(checkpointer, thread_id)
    if not checkpoints:
        print(f"\n[!] 线程 '{thread_id}' 没有找到任何检查点。")
        return False

    while True:
        _clear()
        choice = await _select(
            f"删除检查点（共 {len(checkpoints)} 个）：",
            [
                ("删除指定检查点", "1"),
                ("仅保留最近 N 个（删除其余）", "2"),
                ("删除全部", "3"),
                ("返回", "q"),
            ],
        )

        if choice == "q":
            break

        elif choice == "1":
            cp_choices = []
            for idx, cp in enumerate(checkpoints):
                cp_id = cp.config.get("configurable", {}).get(
                    "checkpoint_id", f"cp_{idx}"
                )
                n_msgs = len(_get_messages(cp.checkpoint))
                cp_choices.append(
                    (f"[{idx}] {str(cp_id)[:22]}…  消息={n_msgs}", str(idx))
                )
            cp_choices.append(("取消", "q"))
            sel = await _select("选择要删除的检查点：", cp_choices)
            if sel == "q":
                continue
            target = checkpoints[int(sel)]
            cp_id = target.config.get("configurable", {}).get("checkpoint_id", "")
            if await _confirm(f"确认删除检查点 [{sel}]？"):
                deleted = await _delete_by_cp_ids([cp_id])
                print(f"[OK] 已删除 1 个检查点（清理 {deleted} 个 Redis 键）。")
                checkpoints = await _collect_checkpoints(checkpointer, thread_id)

        elif choice == "2":
            max_keep = len(checkpoints) - 1
            if max_keep < 1:
                print("检查点数量不足，无需操作。")
                continue
            n = await _select_number("保留最近几个检查点：", 1, max_keep)
            if n is None:
                continue
            targets = checkpoints[n:]
            cp_ids = [
                cp.config.get("configurable", {}).get("checkpoint_id", "")
                for cp in targets
            ]
            if await _confirm(
                f"将删除 {len(targets)} 个旧检查点，保留最近 {n} 个，确认？"
            ):
                deleted = await _delete_by_cp_ids(cp_ids)
                print(
                    f"[OK] 已删除 {len(targets)} 个检查点（清理 {deleted} 个 Redis 键）。"
                )
                checkpoints = await _collect_checkpoints(checkpointer, thread_id)

        elif choice == "3":
            if await _confirm(f"确认删除 '{thread_id}' 的全部检查点？"):
                await _delete_thread(thread_id)
                return True

    return False


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────


async def main():
    async with AsyncRedisSaver.from_conn_string(DB_URI) as checkpointer:
        while True:
            _clear()
            # ── 层级 1：会话选择 ───────────────────────────────────────
            r_scan = redis.from_url(DB_URI, decode_responses=True)
            sessions = await _scan_sessions(r_scan)
            await r_scan.aclose()

            if not sessions:
                print(f"{YELLOW}Redis 中暂无会话记录。{RESET}")
                break

            choices = [(sid, sid) for sid in sessions]
            choices.append(("退出", "q"))
            base_sid = await _select(
                f"选择会话（共 {len(sessions)} 条，最新在前）：", choices
            )
            if base_sid == "q":
                break

            # ── 层级 2：Agent 选择（可循环返回） ──────────────────────
            session_fully_deleted = False
            should_quit = False
            while True:
                _clear()
                agent_choices = []
                standalone_label = next(
                    (lbl for prefix, lbl in _STANDALONE_PREFIXES.items() if base_sid.startswith(prefix)),
                    None,
                )
                if standalone_label is not None:
                    # 独立会话：thread_id 本身就是数据位置，直接列出
                    agent_choices.append((f"{standalone_label}  ({base_sid})", base_sid))
                else:
                    for suffix, label in _SUB_AGENTS:
                        tid = f"sub_{suffix}_of_{base_sid}" if suffix else base_sid
                        agent_choices.append((f"{label}  ({tid})", tid))
                agent_choices.append(("← 返回会话列表", "back"))
                agent_choices.append(("退出", "quit"))

                agent_tid = await _select(
                    f"会话 {base_sid} — 选择 Agent：", agent_choices
                )
                if agent_tid == "back":
                    break
                if agent_tid == "quit":
                    should_quit = True
                    break

                # ── 层级 3：操作（可循环返回） ─────────────────────────
                while True:
                    _clear()
                    action = await _select(
                        f"{agent_tid}：",
                        [
                            ("查看记忆", "view"),
                            ("删除记忆", "delete"),
                            ("← 返回 Agent 列表", "q"),
                        ],
                    )
                    if action == "q":
                        break
                    elif action == "view":
                        await view_memory(checkpointer, agent_tid)
                    elif action == "delete":
                        if await delete_checkpoints(checkpointer, agent_tid):
                            session_fully_deleted = True
                            break

                if session_fully_deleted:
                    break

            if should_quit:
                break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n已退出。")
