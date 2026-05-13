###### tags: `AlphaForge`,`agent`,`安裝`

# AlphaForge Auto Agent — Install Guide

`文件版本: 2026-05-13a`

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

## Phase 2 啟用 (2026-05-13 上線)

Wrapper 已切到 `claude -p --dangerously-skip-permissions` pipe 模式, 真實跑 agent。需要的環境:

- `claude` CLI 在 `/Users/chihhaolai/.local/bin/claude` (Claude Code 已裝)
- `backend/.notify-hub.env` 已填 `NOTIFY_HUB_URL` / `NOTIFY_HUB_TOKEN` (wrapper source 給 agent Stage 6 用)
- `backend/.venv` 已建 + Phase 1/2 helpers (`app.agent.*`) import OK

排程:
- evening (`com.alphaforge.agent.evening`): **18:30** 跑 T0 體檢
- night (`com.alphaforge.agent.night`): **03:00** 跑 T0-T2 主力 + Stage 6 approval 推 Telegram

### Dry-run 驗證 (建議先跑)

第一次正式排程跑會真的 commit / 寄 Gmail / 推 Telegram, 建議先 dry-run:

```bash
AGENT_DRY_RUN=1 bash scripts/agent_run_evening.sh
AGENT_DRY_RUN=1 bash scripts/agent_run_night.sh
tail ~/Library/Logs/AlphaForgeAgent/evening-*.log
tail ~/Library/Logs/AlphaForgeAgent/night-*.log
```

預期: log 內含完整 prompt + `=== <tick> tick end ===`, **不含** `--- invoking claude -p ---` 字串 (dry-run 不跑 claude)。

## 日誌位置

```
~/Library/Logs/AlphaForgeAgent/
├── evening-YYYY-MM-DD_HHMM.log   # wrapper 輸出
├── night-YYYY-MM-DD_HHMM.log
├── evening-launchd.out            # launchd 自身 stdout
└── evening-launchd.err            # launchd 自身 stderr
```
