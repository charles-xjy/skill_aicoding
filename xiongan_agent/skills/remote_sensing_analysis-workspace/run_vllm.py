#!/usr/bin/env python3
"""Drive remote-sensing-analysis skill test runs through the vLLM Qwen endpoint.

Faithfully mirrors how the production supervisor (supervisor_agent_main.py) calls
the model: LangChain init_chat_model against the OpenAI-compatible vLLM endpoint
(Qwen_agent @ 10.129.107.145:8001). We do the same via a direct OpenAI-format call.

Mirrors the CURRENT production code:
  - router: full description (no 80-char truncation) + the new router system prompt
  - planner: skill body as system prompt, with current-time injected

Usage:
  python run_vllm.py --iter iteration-2 --skill-dir <new-skill> [--baseline-skill-dir <old-skill>] --mode all
"""
import argparse
import asyncio
import json
import re
import time
from pathlib import Path

import httpx

VLLM_URL = "http://10.129.107.145:8001/v1/chat/completions"
VLLM_MODEL = "Qwen_agent"
WORKSPACE = Path(__file__).parent
CURRENT_YEAR = 2026  # mirror test assumption; production injects real datetime

CASES = [
    {"id": 1, "name": "pathA-explicit-years", "prompt": "请你根据2020和2025的卫星变化图，介绍北邮沙河校区近几年的发展", "should_trigger": True, "path": "A", "years": [2020, 2025]},
    {"id": 2, "name": "pathA-default-years", "prompt": "雄安新区这几年建设得怎么样了？我想看看空间上的变化", "should_trigger": True, "path": "A", "years": [2021, 2026]},
    {"id": 3, "name": "pathB-pure-research", "prompt": "帮我梳理一下雄安新区的总体规划和主要政策文件，不用看卫星图", "should_trigger": True, "path": "B", "years": None},
    {"id": 4, "name": "notrigger-city-year-fact", "prompt": "北京2022年冬奥会是在哪些场馆举办的？", "should_trigger": False, "path": None, "years": None},
    {"id": 5, "name": "notrigger-city-restaurant", "prompt": "下周去上海出差，推荐几家陆家嘴附近好吃的本帮菜馆子", "should_trigger": False, "path": None, "years": None},
    {"id": 6, "name": "notrigger-rs-concept", "prompt": "光学遥感和雷达遥感的区别是什么？空间分辨率越高越好吗？", "should_trigger": False, "path": None, "years": None},
]


def load_skill(skill_dir):
    text = (Path(skill_dir) / "SKILL.md").read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    fm = {}
    for line in fm_match.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    name = fm.get("name", "remote-sensing-analysis")
    description = fm.get("description", "")  # FULL description, no truncation
    body = re.sub(r"^---\n.*?\n---\n*", "", text, flags=re.DOTALL).strip()
    return name, description, body


def build_router_prompt(name, description):
    """Mirror the NEW supervisor_agent_main.py router system prompt (full description)."""
    skill_triggers = f'- 输出 {{"skill": "{name}"}} 当用户请求涉及：{description}'
    return f"""你是城市治理分析智能体，负责判断用户意图并立即响应。

## 可用技能（仅限以下名称，禁止自创）
{skill_triggers}

## 判断规则
- 用户请求明确匹配上述某个技能：只输出对应 JSON，如 {{"skill": "<技能名>"}}
- 用户请求是事实问答 / 推荐 / 概念解释 / 闲聊问候等，不属于任何技能：直接用中文回复，不要输出 JSON
- 用户似乎有分析需求但关键信息缺失（区域/时间/角度不明）：用中文反问确认

技能名只能从上方列表里选一个，绝对不要编造列表里没有的技能名；不确定是否该触发时，倾向于直接回复而非强行匹配。

只输出 JSON 或回复文字，禁止解释和分析。"""


BASELINE_PLANNER = """你是一个任务规划器。请把用户的请求拆解成一个有序的任务列表，输出 JSON。

可用的执行 agent 有：image_agent（获取卫星影像）、search_agent（搜索网络资料）、analysis_agent（综合分析出报告）。

只输出 JSON，不要其他文字。"""


def planner_system_prompt(body, with_skill):
    """Mirror NEW code: inject current time before skill body (with_skill) or use baseline."""
    now_prefix = f"（当前时间：{CURRENT_YEAR}年07月，用于「未提及年份则默认 [当前年份-5, 当前年份]」的规则）\n\n"
    if with_skill:
        return now_prefix + body
    return now_prefix + BASELINE_PLANNER


async def call_model(client, system_prompt, user_prompt, max_tokens=2048, timeout=120):
    t0 = time.time()
    resp = await client.post(
        VLLM_URL,
        json={"model": VLLM_MODEL, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system_prompt},
                           {"role": "user", "content": user_prompt}]},
        timeout=timeout,
    )
    elapsed = time.time() - t0
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {}), elapsed


def write_meta(eval_dir, eval_id, eval_name, prompt, assertions, note=""):
    eval_dir.mkdir(parents=True, exist_ok=True)
    meta = {"eval_id": eval_id, "eval_name": eval_name, "prompt": prompt,
            "assertions": assertions, "note": note}
    (eval_dir / "eval_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def route_assertions(case):
    return [{"text": f"路由决策正确（{'应触发技能' if case['should_trigger'] else '不应触发'}）",
             "type": "routing_correct"}]


def plan_assertions(case):
    a = [
        {"text": "输出是合法 JSON 且含 tasks 数组", "type": "valid_json"},
        {"text": "最后一个任务的 agent 是 analysis_agent", "type": "analysis_last"},
        {"text": f"image_agent 数量正确（路径{'A:1' if case['path']=='A' else 'B:0'}）", "type": "image_agent_correct", "expected_path": case["path"]},
        {"text": "search_agent 任务数量在 2-4 之间", "type": "search_count_2to4"},
    ]
    if case.get("years") and case["path"] == "A":
        a.append({"text": f"image_agent years={case['years']}", "type": "years_correct", "expected_years": case["years"]})
    return a


async def run_route(client, skill_dir, case, config):
    name, description, _ = load_skill(skill_dir)
    sys_prompt = build_router_prompt(name, description)
    eval_dir = WORKSPACE / args.iter / f"eval-{case['id']}-route-{case['name']}"
    write_meta(eval_dir, case["id"], f"route-{case['name']}", case["prompt"], route_assertions(case),
               note=f"should_trigger={case['should_trigger']}, config={config}")
    out_dir = eval_dir / config / "run-1"
    (out_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (eval_dir / config / "eval_metadata.json").write_text((eval_dir / "eval_metadata.json").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        content, usage, elapsed = await call_model(client, sys_prompt, case["prompt"], max_tokens=2048)
        (out_dir / "outputs" / "decision.md").write_text(content, encoding="utf-8")
        (out_dir / "timing.json").write_text(json.dumps({"total_tokens": usage.get("total_tokens", 0),
                                                          "duration_ms": int(elapsed * 1000),
                                                          "total_duration_seconds": round(elapsed, 1)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return (case["name"], config, "route", True, elapsed, usage.get("total_tokens", 0), None)
    except Exception as e:
        (out_dir / "outputs" / "decision.md").write_text(f"__ERROR__\n{e}", encoding="utf-8")
        return (case["name"], config, "route", False, 0, 0, str(e))


async def run_plan(client, skill_dir, case, config, with_skill):
    _, _, body = load_skill(skill_dir)
    sys_prompt = planner_system_prompt(body, with_skill)
    pid = 6 + case["id"]
    eval_dir = WORKSPACE / args.iter / f"eval-{pid}-plan-{case['name']}"
    write_meta(eval_dir, pid, f"plan-{case['name']}", case["prompt"], plan_assertions(case),
               note=f"case={case['name']}, expected_path={case['path']}, expected_years={case['years']}, config={config}")
    out_dir = eval_dir / config / "run-1"
    (out_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (eval_dir / config / "eval_metadata.json").write_text((eval_dir / "eval_metadata.json").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        content, usage, elapsed = await call_model(client, sys_prompt, case["prompt"], max_tokens=2048)
        (out_dir / "outputs" / "task_plan.md").write_text(content, encoding="utf-8")
        (out_dir / "timing.json").write_text(json.dumps({"total_tokens": usage.get("total_tokens", 0),
                                                          "duration_ms": int(elapsed * 1000),
                                                          "total_duration_seconds": round(elapsed, 1)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return (case["name"], config, "plan", True, elapsed, usage.get("total_tokens", 0), None)
    except Exception as e:
        (out_dir / "outputs" / "task_plan.md").write_text(f"__ERROR__\n{e}", encoding="utf-8")
        return (case["name"], config, "plan", False, 0, 0, str(e))


args = None


async def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", default="iteration-2")
    ap.add_argument("--skill-dir", required=True)
    ap.add_argument("--baseline-skill-dir", default=None)
    ap.add_argument("--mode", default="all", choices=["all", "route", "plan"])
    args = ap.parse_args()

    new_name, new_desc, new_body = load_skill(args.skill_dir)
    print(f"Iter: {args.iter}")
    print(f"New skill: {new_name}  (desc {len(new_desc)} chars, body {len(new_body)} chars)")
    if args.baseline_skill_dir:
        old_name, old_desc, old_body = load_skill(args.baseline_skill_dir)
        print(f"Baseline skill: {old_name}  (desc {len(old_desc)} chars, body {len(old_body)} chars)")
    print()

    tasks = []
    async with httpx.AsyncClient() as client:
        if args.mode in ("all", "route"):
            for c in CASES:
                tasks.append(run_route(client, args.skill_dir, c, "with_skill"))
                if args.baseline_skill_dir:
                    tasks.append(run_route(client, args.baseline_skill_dir, c, "old_skill"))
        if args.mode in ("all", "plan"):
            for c in CASES:
                if c["should_trigger"]:
                    tasks.append(run_plan(client, args.skill_dir, c, "with_skill", with_skill=True))
                    if args.baseline_skill_dir:
                        tasks.append(run_plan(client, args.baseline_skill_dir, c, "old_skill", with_skill=True))

        print(f"Launching {len(tasks)} runs in parallel...\n")
        results = await asyncio.gather(*tasks)

    print("=== RUN RESULTS ===")
    for rname, cfg, kind, ok, elapsed, tokens, err in results:
        print(f"  {'✅' if ok else '❌'} {kind:5s} {rname:36s} {cfg:10s} {elapsed:5.1f}s {tokens:6d} tok" + (f"  err={err}" if err else ""))
    print(f"\n{sum(1 for r in results if r[3])}/{len(results)} succeeded")


if __name__ == "__main__":
    asyncio.run(main())
