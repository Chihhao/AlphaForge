###### tags: `AlphaForge`,`agent`,`安裝`

# AlphaForge Auto Agent — Install Guide

`文件版本: 2026-04-19a`

## 前置

- macOS
- `backend/.venv` 已建立 + requirements.txt 安裝完
- 倉庫路徑為 `/Users/chihhaolai/Documents/GitHub/AlphaForge`

## 安裝 launchd

```bash
cd /Users/chihhaolai/Documents/GitHub/AlphaForge
bash scripts/agent_install_launchd.sh install
bash scripts/agent_install_launchd.sh status
```

## 手動觸發 (測試)

```bash
launchctl start com.alphaforge.agent.evening
launchctl start com.alphaforge.agent.night
tail -f ~/Library/Logs/AlphaForgeAgent/evening-*.log
```

## 卸載

```bash
bash scripts/agent_install_launchd.sh uninstall
```

## Phase 1 範圍限制

目前 wrapper **只印 prompt, 不真的呼叫 `claude -p`**。要啟用完整 agent 需等:

1. notify-hub spec + 實作完成 (外部依賴)
2. Wrapper script 改 `AGENT_DRY_RUN=1` 為實際 `claude -p "$PROMPT"` pipe

兩者完成前, 建議:
- 保留 launchd 安裝但**不要真的啟用時段自動跑** (uninstall 後等 phase 2)
- 僅用 `launchctl start` 手動觸發驗證 log / prompt 格式

## 日誌位置

```
~/Library/Logs/AlphaForgeAgent/
├── evening-YYYY-MM-DD_HHMM.log   # wrapper 輸出
├── night-YYYY-MM-DD_HHMM.log
├── evening-launchd.out            # launchd 自身 stdout
└── evening-launchd.err            # launchd 自身 stderr
```
