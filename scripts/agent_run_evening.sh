#!/bin/bash
# AlphaForge agent evening tick wrapper (18:30, Phase 2: 真實 claude -p 整合)
set -euo pipefail

REPO="/Users/chihhaolai/Documents/GitHub/AlphaForge"
LOG_DIR="$HOME/Library/Logs/AlphaForgeAgent"
mkdir -p "$LOG_DIR"
TS=$(date +"%Y-%m-%d_%H%M")
LOG="$LOG_DIR/evening-$TS.log"

# launchd 環境 minimal, 補 PATH 給 claude 子 process 用 (git, brew tools)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# 拿 prompt 從 backend cwd (python -m scripts.agent_run 需要 backend 在 sys.path)
cd "$REPO/backend"

{
  echo "=== evening tick start $TS ==="

  PROMPT=$("$REPO/backend/.venv/bin/python" -m scripts.agent_run --tick=evening)

  if [[ -z "$PROMPT" ]]; then
    echo "ERROR: empty prompt from agent_run"
    exit 1
  fi

  if [[ "${AGENT_DRY_RUN:-0}" == "1" ]]; then
    # dry-run 模式: 只印 prompt, 不真的跑 agent (debug 用)
    echo "$PROMPT"
  else
    # source agent env (evening 不用但留著無害, night 才用)
    if [[ -f "$REPO/backend/.notify-hub.env" ]]; then
      set -a
      source "$REPO/backend/.notify-hub.env"
      set +a
    fi

    # invoke claude -p, cwd = repo root (讓 prompt 內 `cd backend && ...` 生效)
    cd "$REPO"
    echo "--- invoking claude -p (Phase 2) ---"
    echo "$PROMPT" | /Users/chihhaolai/.local/bin/claude -p --dangerously-skip-permissions
  fi

  echo "=== evening tick end ==="
} >> "$LOG" 2>&1
