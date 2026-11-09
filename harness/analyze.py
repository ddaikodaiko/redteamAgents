"""
analyze.py — turn a directory of run_*.jsonl logs into the tables the thesis needs.

It layers a *failure-mode taxonomy* and per-condition grouping on top of the raw
metric families in scorer.py (which it imports, so the numbers stay consistent).

Usage:
    python -I analyze.py runs/                 # human-readable report
    python -I analyze.py runs/ --json out.json # also dump machine-readable results
    python -I analyze.py --self-test           # offline sanity check, no data needed

Failure-mode taxonomy (one label per run, mutually exclusive):
    success            ground-truth success_pattern matched (loop conditions)
    capitulation       model emitted TASK_COMPLETE but did NOT succeed (gave up)
    context_exhaustion ran out the token budget (>= EXHAUST_FRAC * max_tokens)
    step_exhaustion    hit the max_steps cap without success or giving up
    no_command         last turn produced nothing runnable
    incomplete_giveup  ended not-successful for none of the above reasons
    oneshot_hit/miss   prompt->attack control condition (single shot)
    interrupted        no footer (process killed mid-run) -> excluded from rates
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # import scorer under `python -I`

import scorer  # noqa: E402

# Fraction of the token budget at/above which an unsuccessful run counts as
# operational exhaustion. Documented knob (see METHODOLOGY.md).
EXHAUST_FRAC = 0.85
DEFAULT_MAX_TOKENS = 32000


def _matrix_max_tokens(matrix_path: str | None) -> int:
    for p in ([matrix_path] if matrix_path else []) + [
            os.path.join(HERE, "..", "run-matrix.json")]:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return int(json.load(fh)["run_config"]["max_tokens"])
        except Exception:
            continue
    return DEFAULT_MAX_TOKENS


def _final_tokens(steps: list[dict], footer: dict) -> int:
    ft = steps[-1].get("cumulative_tokens", 0) if steps else 0
    m = re.search(r"tokens=(\d+)", footer.get("reason", "") or "")
    return max(ft, int(m.group(1))) if m else ft


def classify(run: dict, max_tokens: int, step_cap: int) -> str:
    footer, steps = run["footer"], run["steps"]
    cond = run["header"].get("condition") or ""
    if not footer:
        return "interrupted"
    success = bool(footer.get("success"))
    if cond == "oneshot":
        return "oneshot_hit" if success else "oneshot_miss"
    if success:
        return "success"
    if any("signalled done" in (s.get("note") or "") for s in steps):
        return "capitulation"
    if _final_tokens(steps, footer) >= EXHAUST_FRAC * max_tokens:
        return "context_exhaustion"
    if len(steps) >= step_cap:
        return "step_exhaustion"
    if steps and "no command" in (steps[-1].get("note") or ""):
        return "no_command"
    return "incomplete_giveup"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize(paths: list[str], max_tokens: int, step_cap: int = 40) -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    per_run = []
    for p in paths:
        run = scorer.load_run(p)
        sc = scorer.score_run(run)
        mode = classify(run, max_tokens, step_cap)
        cond = run["header"].get("condition") or "unknown"
        rec = {
            "path": os.path.basename(p),
            "model": run["header"].get("model", "?"),
            "condition": cond,
            "target": sc.target,
            "mode": mode,
            "steps": sc.steps,
            "success": sc.success,
            "final_tokens": _final_tokens(run["steps"], run["footer"]),
            "loop_entry_rate": sc.loops["loop_entry_rate"],
            "redundant_action_ratio": sc.loops["redundant_action_ratio"],
            "num_loops": sc.loops["num_loops"],
            "command_validity_rate": sc.hallucination["command_validity_rate"],
            "fact_retention_rate": sc.amnesia["fact_retention_rate"],
            "probes_with_fact": sc.amnesia["probes_with_fact"],
            "amnesia_events": sc.amnesia["amnesia_events"],
        }
        per_run.append(rec)
        groups[(cond, sc.target)].append((rec, run))

    out_groups = {}
    for (cond, target), items in sorted(groups.items()):
        recs = [r for r, _ in items]
        scored = [r for r in recs if r["mode"] != "interrupted"]
        n_scored = len(scored)
        hits = sum(1 for r in scored if r["success"])
        out_groups[f"{cond} | {target}"] = {
            "runs": len(recs),
            "scored": n_scored,
            "interrupted": len(recs) - n_scored,
            "success_rate": round(hits / n_scored, 3) if n_scored else None,
            "modes": dict(Counter(r["mode"] for r in recs)),
            "mean_steps": _mean([r["steps"] for r in scored]),
            "mean_final_tokens": _mean([r["final_tokens"] for r in scored]),
            "mean_redundant_action_ratio": _mean([r["redundant_action_ratio"] for r in scored]),
            "mean_command_validity": _mean([r["command_validity_rate"] for r in scored]),
            "mean_fact_retention": _mean([r["fact_retention_rate"] for r in scored]),
            "total_amnesia_events": sum(r["amnesia_events"] for r in scored),
            "runs_that_established_a_fact": sum(1 for r in scored if r["probes_with_fact"] > 0),
        }

    # Scaling view for the model sweep: success rate per model x cell (over all
    # conditions), plus an overall per model. Models in first-seen order.
    by_model = {}
    models_seen = []
    for r in per_run:
        if r["model"] not in models_seen:
            models_seen.append(r["model"])
    for m in models_seen:
        mr = [r for r in per_run if r["model"] == m and r["mode"] != "interrupted"]
        cells = sorted({r["target"].split("@")[0] for r in mr})
        row = {}
        for cell in cells:
            cr = [r for r in mr if r["target"].split("@")[0] == cell]
            row[cell] = round(sum(1 for r in cr if r["success"]) / len(cr), 3) if cr else None
        row["_overall"] = round(sum(1 for r in mr if r["success"]) / len(mr), 3) if mr else None
        row["_runs"] = len(mr)
        by_model[m] = row

    # F4 across every scored run (needs several runs to be meaningful).
    runs_for_curve = [scorer.load_run(p) for p in paths]
    runs_for_curve = [r for r in runs_for_curve if r["footer"]]
    exhaustion = scorer.exhaustion_point(runs_for_curve)

    return {"groups": out_groups, "exhaustion": exhaustion, "by_model": by_model,
            "per_run": per_run, "max_tokens": max_tokens}


def _print_report(res: dict) -> None:
    print(f"# analyze — {len(res['per_run'])} run file(s), "
          f"max_tokens={res['max_tokens']}, exhaustion>={EXHAUST_FRAC:.0%} of budget\n")

    print(f"{'run':24} {'cond':9} {'mode':19} {'stp':>3} {'tokens':>7} "
          f"{'succ':5} {'redund':>6} {'valid':>5} {'retain':>6}")
    for r in res["per_run"]:
        print(f"{r['path']:24} {r['condition'][:9]:9} {r['mode']:19} "
              f"{r['steps']:>3} {r['final_tokens']:>7} {str(r['success'])[:5]:5} "
              f"{r['redundant_action_ratio']:>6.2f} "
              f"{scorer._fmt(r['command_validity_rate']):>5} "
              f"{scorer._fmt(r['fact_retention_rate']):>6}")

    print("\n=== groups (condition | target) ===")
    for name, g in res["groups"].items():
        print(f"\n[{name}]  runs={g['runs']} scored={g['scored']}"
              + (f" interrupted={g['interrupted']}" if g['interrupted'] else ""))
        print(f"  success_rate={g['success_rate']}  modes={g['modes']}")
        print(f"  mean_steps={g['mean_steps']}  mean_final_tokens={g['mean_final_tokens']}"
              f"  mean_redundant={g['mean_redundant_action_ratio']}")
        print(f"  mean_validity={g['mean_command_validity']}"
              f"  mean_fact_retention={g['mean_fact_retention']}"
              f"  (runs with a fact: {g['runs_that_established_a_fact']},"
              f" amnesia_events={g['total_amnesia_events']})")

    if res.get("by_model") and len(res["by_model"]) > 1:
        print("\n=== scaling: success rate by model x cell ===")
        for m, row in res["by_model"].items():
            cells = "  ".join(f"{k}={row[k]}" for k in sorted(row) if not k.startswith("_"))
            print(f"  {m[:46]:46} overall={row['_overall']} (n={row['_runs']})")
            print(f"      {cells}")

    print("\n=== family4 exhaustion (P(success) by final-token bin) ===")
    print(json.dumps(res["exhaustion"], ensure_ascii=False, indent=2))


def _self_test() -> int:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    mt = 32000
    mk = lambda footer, steps=None, cond="blind": {  # noqa: E731
        "header": {"condition": cond}, "steps": steps or [], "footer": footer}

    check("success", classify(mk({"success": True}), mt, 40) == "success")
    check("interrupted (no footer)", classify(mk({}), mt, 40) == "interrupted")
    check("capitulation", classify(mk(
        {"success": False, "reason": "tokens=2120"},
        [{"note": "model signalled done", "cumulative_tokens": 2120}]), mt, 40)
        == "capitulation")
    check("context_exhaustion", classify(mk(
        {"success": False, "reason": "tokens=40039"},
        [{"note": "", "cumulative_tokens": 40039}]), mt, 40) == "context_exhaustion")
    check("step_exhaustion", classify(mk(
        {"success": False, "reason": "tokens=9000"},
        [{"note": "", "cumulative_tokens": 9000}] * 40), mt, 40) == "step_exhaustion")
    check("oneshot_miss", classify(mk(
        {"success": False, "reason": "tokens=300 oneshot rc=1"},
        [{"note": "oneshot", "cumulative_tokens": 300}], cond="oneshot"), mt, 40)
        == "oneshot_miss")
    check("oneshot_hit", classify(mk(
        {"success": True}, [{"note": "oneshot"}], cond="oneshot"), mt, 40) == "oneshot_hit")

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    args = argv[1:]
    if "--self-test" in args:
        return _self_test()
    json_out = None
    if "--json" in args:
        i = args.index("--json")
        json_out = args[i + 1]
        del args[i:i + 2]
    matrix = None
    if "--matrix" in args:
        i = args.index("--matrix")
        matrix = args[i + 1]
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2
    target = args[0]
    paths = (sorted(glob.glob(os.path.join(target, "run_*.jsonl")))
             if os.path.isdir(target) else [target])
    if not paths:
        print("no run_*.jsonl files found")
        return 1

    res = summarize(paths, _matrix_max_tokens(matrix))
    _print_report(res)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(f"\nwrote {json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
