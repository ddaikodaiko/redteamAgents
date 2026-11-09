#!/usr/bin/env bash
# Model-capability sweep: run the full matrix once per model.
#
# On the GPU box, inside tmux:
#   MODELS="q7b q14b q32b q72b" N=15 bash scripts/run_sweep.sh
# where each MODELS entry is an Ollama model name (see scripts/gpu_setup.sh).
# Every run records its model in the log header, so analyze.py groups by model
# (the scaling view) with no extra flags. Runs are appended to runs/, so a later
# re-run with a higher N just adds more — no rework.
#
# Cost control for a slow large model: set BIG_MODEL to it and BIG_CELLS to the
# cells with signal, e.g.  BIG_MODEL="q72b" BIG_CELLS="A01 A03 A05"  so the 72B
# only runs where it can matter.
set -u
cd "$(dirname "$0")/.."

N="${N:-15}"
MODELS="${MODELS:?set MODELS to space-separated ollama model names}"
CELLS="${CELLS:-A01 A02 A03 A04 A05 A06 A07 A08 A10}"
CONDS="${CONDS:-oneshot blind informed guided}"
BIG_MODEL="${BIG_MODEL:-}"
BIG_CELLS="${BIG_CELLS:-A01 A03 A05}"
LOG="runs/sweep_$(date +%Y%m%d_%H%M%S).log"
mkdir -p runs

echo "START $(date)  N=$N  models=[$MODELS]  conds=[$CONDS]" | tee -a "$LOG"
for M in $MODELS; do
  cells="$CELLS"
  [ "$M" = "$BIG_MODEL" ] && cells="$BIG_CELLS"
  for C in $cells; do
    for COND in $CONDS; do
      echo "=== $(date +%F_%H:%M:%S)  model=$M  $C  $COND  x$N ===" | tee -a "$LOG"
      python3 -I harness/agent_runner.py --model "$M" --only "$C" \
        --condition "$COND" --runs-per-cell "$N" >> "$LOG" 2>&1 \
        || echo "!! $M $C $COND exited non-zero" | tee -a "$LOG"
    done
  done
done
echo "DONE  $(date)" | tee -a "$LOG"
python3 -I harness/analyze.py runs/ 2>&1 | tee -a "$LOG"
