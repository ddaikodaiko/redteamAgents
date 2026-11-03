"""
mock_agent.py — scripted, seeded stand-in for the OpenCode + Ollama agent.

It calls NO model and touches NO target. It fabricates realistic run traces so
the logging + scoring pipeline (step_logger -> scorer) can be validated end to
end BEFORE wiring the real harness on the GCP instance. When the real agent is
ready, it replaces this file and keeps the same RunLogger calls.

Each simulated run mixes the failure modes the four metric families catch, and
the probability of those modes RISES with cumulative tokens, so family 4
(exhaustion) shows a genuine downward P(success) curve and family 2 (amnesia)
degrades under context pressure.

Usage:
    python -I mock_agent.py --out runs/ --runs-per-cell 6 --seed 1337
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # keep step_logger importable under `python -I`

from step_logger import RunLogger

MATRIX = os.path.join(HERE, "..", "run-matrix.json")

VALID_CMDS = [
    "sqlmap -u {url}/?id=1 --batch --dbs",
    "curl -s {url}/rest/products/search?q=test",
    "nmap -sV -p- {ip}",
    "ffuf -u {url}/FUZZ -w /usr/share/wordlists/common.txt",
    "curl -s -X POST {url}/login -d 'user=admin&pass=admin'",
]
# Hallucinated: flags/options that do not exist on the real tools.
INVALID_CMDS = [
    "sqlmap -u {url} --extract-all-databases --auto-pwn",
    "curl --sql-inject {url}",
    "nmap --find-sqli {ip}",
    "ffuf --exploit {url}",
]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def simulate_run(logger: RunLogger, cell: dict, cfg: dict, rng: random.Random) -> None:
    url = cell.get("base_url") or "http://172.20.0.11"
    ip = cell.get("target_ip") or "172.20.0.11"
    max_steps = cfg["max_steps"]
    max_tokens = cfg["max_tokens"]
    probe_every = cfg["probe_every_tokens"]

    # Each run draws a token budget; higher budgets model harder/longer tasks.
    budget = rng.randint(4000, max_tokens)
    tokens = 0
    next_probe = probe_every
    prev_cmd = prev_out = None

    for _ in range(max_steps):
        pressure = tokens / max_tokens  # 0..1, drives failure-mode probabilities
        p_loop = 0.05 + 0.45 * pressure
        p_halluc = 0.05 + 0.40 * pressure

        if prev_cmd is not None and rng.random() < p_loop:
            # Loop: repeat the previous command and output verbatim (no state change).
            cmd, out, valid, exit_code = prev_cmd, prev_out, True, 0
        elif rng.random() < p_halluc:
            cmd = rng.choice(INVALID_CMDS).format(url=url, ip=ip)
            out = "error: unrecognized option"
            valid, exit_code = False, 2
        else:
            cmd = rng.choice(VALID_CMDS).format(url=url, ip=ip)
            # Verbose JSON-ish targets occasionally dump large responses.
            out = "available databases [2]:" if rng.random() > 0.3 else "{" + "x" * rng.randint(400, 4000) + "}"
            valid, exit_code = True, 0

        step_tokens = rng.randint(300, 1500) + (len(out) if len(out) > 1000 else 0)
        tokens += step_tokens
        logger.log_step(cmd, tool=cmd.split()[0], cumulative_tokens=tokens,
                        stdout=out, exit_code=exit_code, command_valid=valid)
        prev_cmd, prev_out = cmd, out

        # Amnesia probes at token checkpoints; retention decays with pressure.
        while tokens >= next_probe:
            retention_p = _sigmoid(2.0 - 4.0 * (next_probe / max_tokens))
            logger.log_probe(after_tokens=next_probe,
                             retained=rng.random() < retention_p,
                             question=(cell.get("probes") or [""])[0])
            next_probe += probe_every

        if tokens >= budget:
            break

    # Success probability falls as the final token total grows (exhaustion).
    p_success = _sigmoid(3.0 - 6.0 * (tokens / max_tokens))
    logger.finish(success=rng.random() < p_success,
                  reason=f"tokens={tokens} budget={budget}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs")
    ap.add_argument("--runs-per-cell", type=int, default=6)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--matrix", default=MATRIX)
    args = ap.parse_args()

    with open(args.matrix, "r", encoding="utf-8") as fh:
        matrix = json.load(fh)
    cfg = dict(matrix["run_config"])
    seed = args.seed if args.seed is not None else cfg.get("seed", 1337)
    model = cfg.get("model", "mock")

    cells = [c for c in matrix["owasp_top_10_2021"] if c.get("target_ip")]  # skip A09
    os.makedirs(args.out, exist_ok=True)

    n = 0
    for ci, cell in enumerate(cells):
        for r in range(args.runs_per_cell):
            rng = random.Random(seed * 100003 + ci * 997 + r)
            logger = RunLogger(args.out, target=f"{cell['id']}@{cell['app']}",
                               model=f"{model}(mock)")
            simulate_run(logger, cell, cfg, rng)
            n += 1

    print(f"wrote {n} runs to {os.path.abspath(args.out)} "
          f"({len(cells)} cells x {args.runs_per_cell}, seed={seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
