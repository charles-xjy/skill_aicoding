#!/usr/bin/env python3
"""Grade routing + planning runs for remote-sensing-analysis skill.

Reads each run's output file, evaluates assertions programmatically, and writes
grading.json (with summary + expectations[text/passed/evidence]) into each run dir.
Layout expected: iteration-1/eval-*/{with_skill,without_skill}/run-1/{outputs/,grading.json}
"""
import re, json, sys
from pathlib import Path

ITER = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "iteration-1"
# _cases.json lives in iteration-1; fall back there so any iteration can be graded
_cases_file = ITER / "_cases.json"
if not _cases_file.exists():
    _cases_file = Path(__file__).parent / "iteration-1" / "_cases.json"
CASES = {c["name"]: c for c in json.loads(_cases_file.read_text(encoding="utf-8"))}
SKILL_NAME = "remote-sensing-analysis"


def extract_json(text):
    """Mirror production supervisor_agent_main.py:278-289: ```json block, else outermost braces."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    return None


def triggered_skill(text):
    """Mirror production: detect {"skill": "..."} JSON. Returns (bool, matched_name)."""
    if not text:
        return False, None
    m = re.search(r'\{[^{}]*"skill"\s*:\s*"([^"]+)"[^{}]*\}', text)
    return (True, m.group(1)) if m else (False, None)


def grade_routing(run_dir, case):
    out = run_dir / "outputs" / "decision.md"
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    triggered, matched = triggered_skill(text)
    expected = case["should_trigger"]
    passed = (triggered == expected) and ((not expected) or (matched == SKILL_NAME))
    return [{
        "text": f"路由决策正确（{'应触发技能' if expected else '不应触发'}）",
        "passed": passed,
        "evidence": f"触发={triggered}, 匹配={matched!r}, 期望触发={expected} | 输出前200字: {text[:200]!r}",
    }]


def grade_planning(run_dir, case):
    out = run_dir / "outputs" / "task_plan.md"
    text = out.read_text(encoding="utf-8") if out.exists() else ""
    plan = extract_json(text)
    exps = []
    valid = plan is not None and isinstance(plan.get("tasks"), list) and len(plan["tasks"]) > 0
    exps.append({
        "text": "输出是合法 JSON 且含 tasks 数组",
        "passed": valid,
        "evidence": (f"解析成功, tasks={len(plan.get('tasks', []))} 个") if valid else f"解析失败 | 输出前300字: {text[:300]!r}",
    })
    if not valid:
        for label in ["最后一个任务 agent 是 analysis_agent",
                      f"image_agent 数量正确（路径{'A:1' if case['path']=='A' else 'B:0'}）",
                      "search_agent 数量在 2-4 之间",
                      f"image_agent years={case.get('years')}"]:
            if label.startswith("image_agent years") and not case.get("years"):
                continue
            exps.append({"text": label, "passed": False, "evidence": "JSON 无效,无法检查"})
        return exps

    tasks = plan["tasks"]
    agents = [t.get("agent", "") for t in tasks]
    exps.append({
        "text": "最后一个任务的 agent 是 analysis_agent",
        "passed": bool(agents) and agents[-1] == "analysis_agent",
        "evidence": f"agents 序列: {agents}",
    })
    img_count = agents.count("image_agent")
    expected_img = 1 if case["path"] == "A" else 0
    exps.append({
        "text": f"image_agent 数量正确（期望 {expected_img}，路径{case['path']}）",
        "passed": img_count == expected_img,
        "evidence": f"image_agent={img_count}, 期望={expected_img}",
    })
    sc = agents.count("search_agent")
    exps.append({
        "text": "search_agent 任务数量在 2-4 之间",
        "passed": 2 <= sc <= 4,
        "evidence": f"search_agent={sc}",
    })
    if case.get("years") and case["path"] == "A":
        img_tasks = [t for t in tasks if t.get("agent") == "image_agent"]
        yrs = img_tasks[0].get("years") if img_tasks else None
        try:
            yrs_norm = [int(y) for y in yrs] if yrs is not None else None
        except (TypeError, ValueError):
            yrs_norm = yrs
        exps.append({
            "text": f"image_agent years={case['years']}",
            "passed": yrs_norm == case["years"],
            "evidence": f"实际 years={yrs!r}, 期望={case['years']}",
        })
    return exps


def write_grading(run_dir, exps):
    passed = sum(1 for e in exps if e["passed"])
    total = len(exps)
    g = {
        "summary": {
            "pass_rate": round(passed / total, 4) if total else 0.0,
            "passed": passed, "failed": total - passed, "total": total,
        },
        "expectations": exps,
        "timing": {"total_duration_seconds": 0.0},
    }
    (run_dir / "grading.json").write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")
    return g["summary"]["pass_rate"]


def main():
    results = []
    for edir in sorted(ITER.glob("eval-*")):
        meta_path = edir / "eval_metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        ename = meta["eval_name"]
        if ename.startswith("route-"):
            case = CASES.get(ename[len("route-"):])
            # grade every config subdir present (with_skill, old_skill, without_skill, ...)
            for cdir in sorted(edir.iterdir()):
                if not cdir.is_dir() or cdir.name.startswith("_"):
                    continue
                rd = cdir / "run-1"
                if rd.is_dir() and case:
                    results.append((ename, cdir.name, write_grading(rd, grade_routing(rd, case))))
        elif ename.startswith("plan-"):
            case = CASES.get(ename[len("plan-"):])
            for cdir in sorted(edir.iterdir()):
                if not cdir.is_dir() or cdir.name.startswith("_"):
                    continue
                rd = cdir / "run-1"
                if rd.is_dir() and case:
                    results.append((ename, cdir.name, write_grading(rd, grade_planning(rd, case))))

    print("=== GRADING RESULTS ===")
    for ename, cfg, pr in results:
        print(f"  {ename:42s} {cfg:14s} {pr*100:3.0f}%")
    # group by config
    from collections import defaultdict
    by_cfg = defaultdict(list)
    for _, cfg, pr in results:
        by_cfg[cfg].append(pr)
    print()
    for cfg, prs in by_cfg.items():
        print(f"  {cfg:14s} mean: {sum(prs)/len(prs)*100:.0f}%  ({len(prs)} runs)")


if __name__ == "__main__":
    main()
