#!/usr/bin/env bash
# One-time setup on a fresh GPU host (Ubuntu with NVIDIA driver preinstalled,
# e.g. a GCP Deep Learning image, or a RunPod/Vast CUDA image).
# Brings up Ollama + the OWASP lab + seeds the targets. Pull the models and run
# scripts/run_sweep.sh afterwards.
set -e
cd "$(dirname "$0")/.."

echo "== GPU =="; nvidia-smi || { echo "no GPU visible — fix drivers first"; exit 1; }

echo "== Docker =="
command -v docker >/dev/null || { curl -fsSL https://get.docker.com | sh; }

echo "== Ollama (auto-detects the GPU) =="
command -v ollama >/dev/null || { curl -fsSL https://ollama.com/install.sh | sh; }

echo "== Lab =="
sudo docker compose up -d
sleep 20

echo "== Seed targets =="
# sqli-labs (A03)
sudo docker exec agent-runner sh -lc \
  'curl -s -o /dev/null "http://172.20.0.11/sql-connections/setup-db.php" || true'
# DVWA (A07) — needs dvwa-db up (in compose)
sudo docker exec agent-runner sh -lc '
  H=http://172.20.0.12; J=/tmp/s.jar; rm -f $J
  T=$(curl -s -c $J "$H/setup.php" | grep -oP "user_token.*?value=.\K[0-9a-f]{32}" | head -1)
  curl -s -b $J -c $J --data "create_db=1&user_token=$T" "$H/setup.php" -o /dev/null || true'
echo "   (WebGoat registers its own user per run; mutillidae/juice-shop need no seed)"

cat <<'NOTE'

== NEXT: pull the sweep models, then run the sweep ==
Verify the exact HF GGUF repo names on huggingface.co before pulling (authors and
tags change). Example (abliterated Q4_K_M), then alias to short names:

  ollama pull hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-abliterated-GGUF:Q4_K_M
  ollama cp   hf.co/bartowski/Qwen2.5-Coder-7B-Instruct-abliterated-GGUF:Q4_K_M q7b
  # ... repeat for 14B, 32B, and Qwen2.5-72B-Instruct-abliterated (general, needs ~80GB VRAM) -> q72b

Then, inside tmux:
  MODELS="q7b q14b q32b" N=15 bash scripts/run_sweep.sh          # L4 can do up to 32B
  # add the 72B only where it can matter (needs an 80GB GPU):
  MODELS="q72b" BIG_MODEL="q72b" BIG_CELLS="A01 A03 A05" N=15 bash scripts/run_sweep.sh
NOTE
