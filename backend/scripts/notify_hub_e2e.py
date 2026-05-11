"""End-to-end smoke test against real NAS notify-hub.

需要 backend/.env 設好 NOTIFY_HUB_URL / NOTIFY_HUB_TOKEN。

Usage (從 backend/ 目錄):
    ./.venv/bin/python -m scripts.notify_hub_e2e

預期: 你手機 Telegram 收到一則 "Phase 2 e2e test" 與兩個按鈕, 按一個,
script 印 status=approved / rejected。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    repo_backend = Path(__file__).resolve().parents[1]
    _load_env_file(repo_backend / ".notify-hub.env")
    sys.path.insert(0, str(repo_backend))

    from app.agent.notify_hub_client import approve_and_wait

    items = [
        {"id": "1", "type": "test", "summary": "Phase 2 e2e — 按我同意", "detail": "本訊號為測試, 不會落地任何動作。"},
        {"id": "2", "type": "test", "summary": "Phase 2 e2e — 按我拒絕", "detail": "本訊號為測試。"},
    ]
    title = "Phase 2 e2e test"
    print(f"approve_and_wait title={title!r} ...")
    result = approve_and_wait(
        project="alphaforge",
        title=title,
        items=items,
        timeout_seconds=180,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("approved", "rejected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
