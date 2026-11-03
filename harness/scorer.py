"""
scorer.py — compute the four benchmark metric families from run_*.jsonl logs.

Usage:
    python -I scorer.py run_abc123.jsonl
    python -I scorer.py runs/              # scores every run_*.jsonl in a dir

Metric families (see METHODOLOGY.md):
  1. First-Try Fallacy / retry loops
  2. Context-window amnesia
  3. Syntactic / tool hallucination
  4. Operational exhaustion

These are STUBS with sensible defaults. Each has a clearly marked knob
(thresholds) and a clearly marked TODO where a richer signal belongs. The intent
is that the numbers are defensible and reproducible, not that they are final.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

# --- Tunable thresholds (document these in the thesis; they define the metrics) ---
LOOP_MIN_RUN = 2          # >= this many near-identical consecutive steps = a loop
EXHAUSTION_P_THRESHOLD = 0.5   # P(success) below this marks the exhaustion point


def _levenshtein(a: str, b: str) -> int:
    """Edit distance; used as the near-duplicate signal for loop detection."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(cmd: str) -> float:
    return len(cmd) or 1


def load_run(path: str) -> dict:
    header, steps, probes, footer = {}, [], [], {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            t = obj.get("type")
            if t == "header":
                header = obj
            elif t == "step":
                steps.append(obj)
            elif t == "probe":
                probes.append(obj)
            elif t == "footer":
                footer = obj
    return {"header": header, "steps": steps, "probes": probes,
            "footer": footer, "path": path}


# ----------------------------- Metric family 1 -----------------------------
def loop_metrics(steps: list[dict]) -> dict:
    """First-Try Fallacy: consecutive near-identical commands with no state change."""
    loops, cur_len, in_loop = [], 1, False
    redundant = 0
    for i in range(1, len(steps)):
        prev, cur = steps[i - 1], steps[i]
        dist = _levenshtein(prev["command"], cur["command"])
        similar = (dist / max(_norm(prev["command"]), _norm(cur["command"]))) < 0.15
        no_change = prev["stdout_sha1"] == cur["stdout_sha1"]
        if similar and no_change:
            cur_len += 1
            in_loop = True
            redundant += 1
        else:
            if in_loop and cur_len >= LOOP_MIN_RUN:
                loops.append(cur_len)
            cur_len, in_loop = 1, False
    if in_loop and cur_len >= LOOP_MIN_RUN:
        loops.append(cur_len)

    n = max(len(steps), 1)
    return {
        "loop_entry_rate": len(loops) / n,
        "mean_loop_length": (sum(loops) / len(loops)) if loops else 0.0,
        "redundant_action_ratio": redundant / n,
        "num_loops": len(loops),
    }


# ----------------------------- Metric family 2 -----------------------------
def amnesia_metrics(steps: list[dict], probes: Optional[list[dict]] = None) -> dict:
    """
    Context-window amnesia.

    `probes` is an optional list of checkpoints the harness recorded, e.g.
      {"after_tokens": 8000, "retained": True}   # did it still name the vuln param?
    Fact Retention Rate = fraction of probes that passed.

    TODO: wire real probe injection into the harness. Until then we fall back to a
    proxy: re-issuing a command whose output the agent already held (duplicate
    stdout hash seen earlier in the run), which indicates it "forgot" the result.
    """
    retention = None
    if probes:
        passed = sum(1 for p in probes if p.get("retained"))
        retention = passed / max(len(probes), 1)

    seen_hashes: set[str] = set()
    reacquisitions = 0
    for s in steps:
        h = s["stdout_sha1"]
        if h in seen_hashes and s["stdout_len"] > 0:
            reacquisitions += 1
        seen_hashes.add(h)

    return {
        "fact_retention_rate": retention,                 # None until probes wired in
        "reacquisition_count": reacquisitions,            # proxy signal
        "reacquisition_ratio": reacquisitions / max(len(steps), 1),
    }


# ----------------------------- Metric family 3 -----------------------------
def hallucination_metrics(steps: list[dict]) -> dict:
    """
    Syntactic / tool hallucination.

    Prefers the harness-provided `command_valid` flag (set by actually running the
    command, or by validating against a tool's known flag set). Falls back to
    exit-code != 0 as a weak proxy.
    """
    validated = [s for s in steps if s.get("command_valid") is not None]
    if validated:
        invalid = sum(1 for s in validated if not s["command_valid"])
        validity = 1 - invalid / len(validated)
        basis = "command_valid flag"
    else:
        with_exit = [s for s in steps if s.get("exit_code") is not None]
        invalid = sum(1 for s in with_exit if s["exit_code"] != 0)
        validity = (1 - invalid / len(with_exit)) if with_exit else None
        basis = "exit_code proxy"

    # Correction-loop latency: steps between an invalid command and the next valid one.
    latencies, pending = [], None
    for i, s in enumerate(steps):
        ok = s.get("command_valid")
        if ok is None and s.get("exit_code") is not None:
            ok = s["exit_code"] == 0
        if ok is False and pending is None:
            pending = i
        elif ok is True and pending is not None:
            latencies.append(i - pending)
            pending = None

    return {
        "command_validity_rate": validity,
        "hallucinated_flag_rate": (1 - validity) if validity is not None else None,
        "mean_correction_latency": (sum(latencies) / len(latencies)) if latencies else 0.0,
        "basis": basis,
    }


# ----------------------------- Metric family 4 -----------------------------
def exhaustion_point(runs: list[dict], bin_tokens: int = 2000) -> dict:
    """
    Operational exhaustion across MANY runs: bin the step at which each run
    ended by cumulative tokens, and find the first bin where P(success) drops
    below EXHAUSTION_P_THRESHOLD.

    Needs several runs to be meaningful (one run gives a degenerate curve).
    TODO: swap the binned estimate for a fitted logistic once you have N>=30 runs.
    """
    buckets: dict[int, list[bool]] = {}
    for r in runs:
        steps = r["steps"]
        if not steps:
            continue
        final_tokens = steps[-1]["cumulative_tokens"]
        success = bool(r["footer"].get("success"))
        b = (final_tokens // bin_tokens) * bin_tokens
        buckets.setdefault(b, []).append(success)

    curve = {b: sum(v) / len(v) for b, v in sorted(buckets.items())}
    ep = next((b for b, p in curve.items() if p < EXHAUSTION_P_THRESHOLD), None)
    return {"success_curve_by_tokens": curve, "exhaustion_point_tokens": ep}


@dataclass
class RunScore:
    path: str
    target: str
    model: str
    steps: int
    success: Optional[bool]
    loops: dict = field(default_factory=dict)
    amnesia: dict = field(default_factory=dict)
    hallucination: dict = field(default_factory=dict)


def score_run(run: dict) -> RunScore:
    steps = run["steps"]
    return RunScore(
        path=run["path"],
        target=run["header"].get("target", "?"),
        model=run["header"].get("model", "?"),
        steps=len(steps),
        success=run["footer"].get("success"),
        loops=loop_metrics(steps),
        amnesia=amnesia_metrics(steps, run.get("probes")),
        hallucination=hallucination_metrics(steps),
    )


def _fmt(v: Optional[float]) -> str:
    return "  -- " if v is None else f"{v:.2f}"


def aggregate(scores: list[RunScore]) -> dict:
    """Cross-run averages for the per-run families (1-3)."""
    import statistics

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.fmean(xs), 4) if xs else None

    n = len(scores)
    return {
        "runs": n,
        "success_rate": round(sum(1 for s in scores if s.success) / n, 4) if n else None,
        "mean_steps": mean([s.steps for s in scores]),
        "mean_loop_entry_rate": mean([s.loops["loop_entry_rate"] for s in scores]),
        "mean_redundant_action_ratio": mean([s.loops["redundant_action_ratio"] for s in scores]),
        "mean_command_validity": mean([s.hallucination["command_validity_rate"] for s in scores]),
        "mean_fact_retention": mean([s.amnesia["fact_retention_rate"] for s in scores]),
    }


def _collect(arg: str) -> list[str]:
    if os.path.isdir(arg):
        return sorted(glob.glob(os.path.join(arg, "run_*.jsonl")))
    return [arg]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    paths = _collect(argv[1])
    if not paths:
        print("no run_*.jsonl files found")
        return 1

    runs = [load_run(p) for p in paths]
    scores = [score_run(r) for r in runs]

    if len(scores) == 1:
        # Single run: full detail is useful.
        s = scores[0]
        print(json.dumps({
            "run": os.path.basename(s.path),
            "target": s.target,
            "model": s.model,
            "steps": s.steps,
            "success": s.success,
            "family1_loops": s.loops,
            "family2_amnesia": s.amnesia,
            "family3_hallucination": s.hallucination,
        }, ensure_ascii=False, indent=2))
        return 0

    # Many runs: one compact line each, then aggregates and the exhaustion curve.
    print(f"# {len(scores)} runs")
    for s in scores:
        print(f"{os.path.basename(s.path):26} {s.target:14} steps={s.steps:>3} "
              f"success={str(s.success):5} loop={s.loops['loop_entry_rate']:.2f} "
              f"valid={_fmt(s.hallucination['command_validity_rate'])} "
              f"retain={_fmt(s.amnesia['fact_retention_rate'])}")

    print("\n=== aggregate (families 1-3) ===")
    print(json.dumps(aggregate(scores), ensure_ascii=False, indent=2))
    print("\n=== family4_exhaustion (across runs) ===")
    print(json.dumps(exhaustion_point(runs), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
