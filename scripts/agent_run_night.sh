#!/bin/bash
# AlphaForge agent night tick wrapper (03:00)
set -euo pipefail

REPO="/Users/chihhaolai/Documents/GitHub/AlphaForge"
LOG_DIR="$HOME/Library/Logs/AlphaForgeAgent"
mkdir -p "$LOG_DIR"
TS=$(date +"%Y-%m-%d_%H%M")
LOG="$LOG_DIR/night-$TS.log"

cd "$REPO/backend"

{
  echo "=== night tick start $TS ==="

  PROMPT=$("$REPO/backend/.venv/bin/python" -m scripts.agent_run --tick=night)

  if [[ -z "$PROMPT" ]]; then
    echo "ERROR: empty prompt from agent_run"
    exit 1
  fi

  if [[ "${AGENT_DRY_RUN:-0}" == "1" ]]; then
    echo "$PROMPT"
  else
    echo "[phase1] prompt-only mode, not invoking claude -p"
    echo "$PROMPT"
  fi

  echo "=== night tick end ==="
} >> "$LOG" 2>&1
