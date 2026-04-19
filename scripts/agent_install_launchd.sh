#!/bin/bash
# 安裝 / 卸載 AlphaForge agent launchd plists
set -euo pipefail

CMD="${1:-install}"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
SRC="/Users/chihhaolai/Documents/GitHub/AlphaForge/launchd"
PLISTS=("com.alphaforge.agent.evening.plist" "com.alphaforge.agent.night.plist")

case "$CMD" in
  install)
    mkdir -p "$LAUNCH_AGENTS"
    for p in "${PLISTS[@]}"; do
      cp "$SRC/$p" "$LAUNCH_AGENTS/$p"
      launchctl unload "$LAUNCH_AGENTS/$p" 2>/dev/null || true
      launchctl load "$LAUNCH_AGENTS/$p"
      echo "installed $p"
    done
    ;;
  uninstall)
    for p in "${PLISTS[@]}"; do
      launchctl unload "$LAUNCH_AGENTS/$p" 2>/dev/null || true
      rm -f "$LAUNCH_AGENTS/$p"
      echo "removed $p"
    done
    ;;
  status)
    launchctl list | grep alphaforge.agent || echo "no alphaforge.agent job loaded"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status}"; exit 1 ;;
esac
