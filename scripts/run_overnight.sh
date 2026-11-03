#!/usr/bin/env bash
# Overnight data collection for the CALIBRATED, reachable cells only.
#
# Runs on the GCP box. LAUNCH IT INSIDE tmux so it survives SSH disconnect and
# laptop shutdown:
#     tmux new -s night
#     bash scripts/run_overnight.sh 30     # 30 runs/cell/condition (default)
#     # Ctrl-b then d  to detach; reconnect later with:  tmux attach -t night
#
# Only cells whose success_pattern is calibrated AND whose target is reachable
# are included. webgoat (A02/A08/A10) is unhealthy; A04/A07 not calibrated yet.
# Order: oneshot first (fast -> breadth early), then blind, then informed; the
# slow SQLi cell (A03) is last in each pass so the easy cells complete first.
#
# Runs are independent and logged incrementally to runs/run_*.jsonl, so a partial
# night is fully usable: analyze.py works on whatever exists.
set -u
cd "$(dirname "$0")/.."

N="${1:-30}"                 # runs per cell per condition
CATS="A01 A05 A06 A03"       # calibrated + reachable (easy -> hard)
RUNNER="python3 -I harness/agent_runner.py"
LOG="runs/overnight_$(date +%Y%m%d_%H%M%S).log"
mkdir -p runs

echo "START $(date)  N=$N  cats=[$CATS]" | tee -a "$LOG"
for COND in oneshot blind informed; do
  for C in $CATS; do
    echo "=== $(date +%F_%H:%M:%S)  $C  $COND  x$N ===" | tee -a "$LOG"
    # keep going even if one cell errors out
    $RUNNER --only "$C" --condition "$COND" --runs-per-cell "$N" >> "$LOG" 2>&1 \
      || echo "!! $C $COND exited non-zero" | tee -a "$LOG"
  done
done
echo "DONE  $(date)" | tee -a "$LOG"
echo "summary:" | tee -a "$LOG"
python3 -I harness/analyze.py runs/ 2>&1 | tee -a "$LOG"
