#!/bin/bash
# AlphaForge agent evening tick wrapper (18:30)
set -euo pipefail

REPO="/Users/chihhaolai/Documents/GitHub/AlphaForge"
LOG_DIR="$HOME/Library/Logs/AlphaForgeAgent"
mkdir -p "$LOG_DIR"
TS=$(date +"%Y-%m-%d_%H%M")
LOG="$LOG_DIR/evening-$TS.log"

cd "$REPO/backend"

{
  echo "=== evening tick start $TS ==="

  PROMPT=$("$REPO/backend/.venv/bin/python" -m scripts.agent_run --tick=evening)

  if [[ -z "$PROMPT" ]]; then
    echo "ERROR: empty prompt from agent_run"
    exit 1
  fi

  # 未整合 claude -p 前, 只印 prompt 做 dry-run 驗證
  if [[ "${AGENT_DRY_RUN:-0}" == "1" ]]; then
    echo "$PROMPT"
  else
    # TODO (phase2): pipe 到 claude -p, 待 notify-hub 上線後啟用
    echo "[phase1] prompt-only mode, not invoking claude -p"
    echo "$PROMPT"
  fi

  echo "=== evening tick end ==="
} >> "$LOG" 2>&1
