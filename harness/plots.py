"""
plots.py — publication figures from a directory of run_*.jsonl logs.

Builds on analyze.summarize (so numbers match the tables) and renders PNGs with a
colorblind-safe (Okabe-Ito) categorical palette, direct value labels, recessive
grid and no dual axes.

Usage:
    python -I plots.py runs/                 # writes figures/*.png
    python -I plots.py runs/ --out figs      # custom output dir

Figures:
    fig1_success_by_condition.png   success rate, condition x OWASP cell (headline)
    fig2_termination_tokens.png     per-run tokens at termination by condition
                                    (one-shot clusters low; loop piles at the cap
                                    = operational exhaustion)
    fig3_failure_modes.png          failure-mode composition per condition x cell
"""

from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyze  # noqa: E402  (also pulls scorer)

# Okabe-Ito, colorblind-safe. Colour follows the CONDITION (entity), fixed order.
COND_COLOR = {
    "oneshot":  "#0072B2",   # blue
    "blind":    "#E69F00",   # orange
    "informed": "#009E73",   # green
    "guided":   "#CC79A7",   # reddish-purple (Okabe-Ito)
    "unknown":  "#999999",   # grey (pre-condition legacy runs)
}
COND_ORDER = ["oneshot", "blind", "informed", "guided", "unknown"]
MODE_COLOR = {
    "success": "#009E73", "oneshot_hit": "#009E73",
    "oneshot_miss": "#E69F00", "capitulation": "#D55E00",
    "context_exhaustion": "#CC79A7", "step_exhaustion": "#56B4E9",
    "no_command": "#F0E442", "incomplete_giveup": "#999999",
    "interrupted": "#DDDDDD",
}
INK, MUTED, GRID = "#222222", "#555555", "#DDDDDD"


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=GRID, lw=0.8)
    ax.xaxis.grid(False)


def _cell(target: str) -> str:
    return (target or "?").split("@")[0]


def _present(per_run, key_order, get):
    seen = []
    for r in per_run:
        v = get(r)
        if v not in seen:
            seen.append(v)
    return [k for k in key_order if k in seen] + [v for v in seen if v not in key_order]


def fig_success(per_run, out):
    cats = sorted({_cell(r["target"]) for r in per_run})
    conds = _present(per_run, COND_ORDER, lambda r: r["condition"])
    # success rate per (cond, cat), ignoring interrupted runs
    rate, n = {}, {}
    for c in conds:
        for cat in cats:
            rr = [r for r in per_run if r["condition"] == c and _cell(r["target"]) == cat
                  and r["mode"] != "interrupted"]
            n[(c, cat)] = len(rr)
            rate[(c, cat)] = (sum(1 for r in rr if r["success"]) / len(rr)) if rr else None

    fig, ax = plt.subplots(figsize=(10, 4.8))
    w = 0.82 / max(len(conds), 1)
    x = range(len(cats))
    for i, c in enumerate(conds):
        xs = [xi + i * w for xi in x]
        ys = [(rate[(c, cat)] or 0) * 100 for cat in cats]
        bars = ax.bar(xs, ys, width=w * 0.92, color=COND_COLOR.get(c, "#999"),
                      label=c, zorder=3)
        for xi, cat, b in zip(xs, cats, bars):
            if rate[(c, cat)] is None:
                continue
            ax.text(xi, b.get_height() + 1.2, f"{b.get_height():.0f}%",
                    ha="center", va="bottom", fontsize=8, color=INK)
            ax.text(xi, -4, f"n={n[(c, cat)]}", ha="center", va="top",
                    fontsize=6.5, color=MUTED)
    ax.set_xticks([xi + w * (len(conds) - 1) / 2 for xi in x])
    ax.set_xticklabels(cats)
    ax.set_ylim(0, 100)
    ax.set_ylabel("success rate (%)")
    ax.set_title("Task success by condition and OWASP cell", color=INK, fontsize=11)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    _style(ax)
    fig.tight_layout()
    p = os.path.join(out, "fig1_success_by_condition.png")
    fig.savefig(p, dpi=200); plt.close(fig)
    return p


def fig_tokens(per_run, out, max_tokens):
    conds = _present(per_run, COND_ORDER, lambda r: r["condition"])
    scored = [r for r in per_run if r["mode"] != "interrupted"]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    import random
    random.seed(0)
    for i, c in enumerate(conds):
        ys = [r["final_tokens"] for r in scored if r["condition"] == c]
        xs = [i + (random.random() - 0.5) * 0.35 for _ in ys]
        ax.scatter(xs, ys, s=16, color=COND_COLOR.get(c, "#999"), alpha=0.6,
                   edgecolors="white", linewidths=0.4, zorder=3)
        if ys:
            med = sorted(ys)[len(ys) // 2]
            ax.plot([i - 0.25, i + 0.25], [med, med], color=INK, lw=1.6, zorder=4)
            ax.text(i + 0.3, med, f"med {med:,}", fontsize=7, color=INK, va="center")
    ax.axhline(max_tokens, color=MUTED, lw=1, ls="--", zorder=2)
    ax.text(len(conds) - 0.5, max_tokens, f" budget {max_tokens:,}", fontsize=7,
            color=MUTED, va="bottom", ha="right")
    ax.set_xticks(range(len(conds)))
    ax.set_xticklabels(conds)
    ax.set_ylabel("tokens at termination")
    ax.set_title("Where runs end: one-shot vs. loop (operational exhaustion)",
                 color=INK, fontsize=11)
    _style(ax)
    fig.tight_layout()
    p = os.path.join(out, "fig2_termination_tokens.png")
    fig.savefig(p, dpi=200); plt.close(fig)
    return p


def fig_modes(per_run, out):
    groups = {}
    for r in per_run:
        groups.setdefault((r["condition"], _cell(r["target"])), []).append(r["mode"])
    keys = sorted(groups, key=lambda k: (COND_ORDER.index(k[0]) if k[0] in COND_ORDER
                                         else 9, k[1]))
    labels = [f"{c}\n{cat}" for c, cat in keys]
    modes = []
    for k in keys:
        for m in groups[k]:
            if m not in modes:
                modes.append(m)
    fig, ax = plt.subplots(figsize=(max(8, len(keys) * 0.9), 4.8))
    bottoms = [0] * len(keys)
    for m in modes:
        vals = [sum(1 for x in groups[k] if x == m) for k in keys]
        ax.bar(range(len(keys)), vals, bottom=bottoms, width=0.7,
               color=MODE_COLOR.get(m, "#999"), label=m, zorder=3)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_ylabel("runs")
    ax.set_title("Failure-mode composition per condition and cell", color=INK, fontsize=11)
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="upper left", bbox_to_anchor=(1, 1))
    _style(ax)
    fig.tight_layout()
    p = os.path.join(out, "fig3_failure_modes.png")
    fig.savefig(p, dpi=200); plt.close(fig)
    return p


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    out = "figures"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    if not args:
        print(__doc__); return 2
    import glob
    target = args[0]
    paths = (sorted(glob.glob(os.path.join(target, "run_*.jsonl")))
             if os.path.isdir(target) else [target])
    if not paths:
        print("no run_*.jsonl files found"); return 1
    os.makedirs(out, exist_ok=True)
    res = analyze.summarize(paths, analyze._matrix_max_tokens(None))
    pr = res["per_run"]
    print("wrote:")
    print(" ", fig_success(pr, out))
    print(" ", fig_tokens(pr, out, res["max_tokens"]))
    print(" ", fig_modes(pr, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
