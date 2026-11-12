#!/usr/bin/env bash
# Run on a RENTED GPU box (RunPod / Lambda / Vast). This box ONLY serves the
# models via Ollama; the OWASP lab and the harness stay on the CPU box and call
# this box's Ollama over the network (so there is no docker/lab to set up here).
#
# After this finishes, run the sweep FROM the CPU box (e.g. tfg-brain):
#   OLLAMA_HOST=http://<THIS_BOX_IP>:11434 MODELS="q7b q14b q32b" N=15 \
#     bash scripts/run_sweep.sh
#
# SECURITY: this serves Ollama with no auth on all interfaces. Fine for a
# short-lived throwaway box; if possible, firewall port 11434 to the CPU box's IP.
set -e

echo "== GPU =="; nvidia-smi | head -15 || { echo "no GPU visible"; exit 1; }

echo "== Ollama =="
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
export OLLAMA_HOST=0.0.0.0:11434      # listen on all interfaces
pkill -f "ollama serve" 2>/dev/null || true
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 4

echo "== Pull sweep models =="
# VERIFY the exact HF GGUF repo names on huggingface.co first (authors/tags move).
# Each pull is aliased to a short name used by run_sweep.sh (q7b/q14b/q32b/q72b).
pull() { ollama pull "$1" && ollama cp "$1" "$2"; }
pull hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-abliterated-GGUF:Q4_K_M  q7b
pull hf.co/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF:Q4_K_M q14b
pull hf.co/bartowski/Qwen2.5-Coder-32B-Instruct-abliterated-GGUF:Q4_K_M q32b
# 72B needs an 80GB GPU; general-instruct (not coder) — uncomment on an A100/H100-80GB:
# pull hf.co/bartowski/Qwen2.5-72B-Instruct-abliterated-GGUF:Q4_K_M       q72b

echo "== Ready =="; ollama list
IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "<THIS_BOX_IP>")
echo "Now, on the CPU box (tfg-brain):"
echo "  OLLAMA_HOST=http://$IP:11434 MODELS=\"q7b q14b q32b\" N=15 bash scripts/run_sweep.sh"
