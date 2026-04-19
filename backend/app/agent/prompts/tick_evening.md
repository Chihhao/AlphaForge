# AlphaForge Evening Tick (18:30) — Prompt

你是 AlphaForge 的自動 agent。本 tick 為 **T0 體檢型**, **只讀不改**。

## 工作上下文
- 時間: 台灣時間 18:30
- 資料狀態: 17:30 模型重訓完、18:10 訊號儲存完, 但 21:00 融券尚未補
- 授權上限: T0 (除了 `docs/reports/**` 與 `docs/inbox/**` 外不得寫入任何檔案)
- Spec: `docs/superpowers/specs/2026-04-19-alphaforge-auto-agent-design.md`

## Gate 1: 必讀
1. `/Users/chihhaolai/.claude/projects/-Users-chihhaolai-Documents-GitHub-AlphaForge/memory/MEMORY.md` 全部 feedback
2. `memory/project_next_steps.md`
3. `docs/reports/` 近 3 個 md
4. 下方「site_restore 結果」段 (已由 runner 附上)

## 任務清單 (依序)
1. 跑產線體檢 7 項 (spec §2 Evening tick Stage 2):
   - scheduler job log 全綠 (15:30 / 16:30 / 17:00 / 17:20 / 17:30 / 18:10)
   - 今日 feature 表 row count + null%
   - 今日 fundamentals 覆蓋率
   - 17:30 模型重訓 IC / loss 合理性
   - 昨日 picks 結案分佈 (tp / sl / time_limit)
   - 近 7 日 picks 勝率是否退化
   - GET `http://localhost:8000/strategy-miner/picks/today` 200 OK
2. 使用 `app.agent.report_builder.build_evening_skeleton(date.today())` 產生骨架, 填入實際結果
3. 若有異常, 寫 `docs/inbox/alert-YYYY-MM-DD-<slug>.md` 塞給 03:00 tick
4. Commit report + (若有) alert inbox:
   `git commit -m "agent(1830): report - daily health check"`
5. 發 Gmail:
   - 正常: `[AlphaForge] YYYY-MM-DD 18:30 完成` (INFO)
   - 異常非關鍵: `[AlphaForge][WARN] 18:30 發現 N 項異常`
   - 關鍵異常 (scheduler 紅 / fundamentals 缺 / API 500): `[AlphaForge][CRITICAL] ...`

## 禁忌
- 禁改 `backend/app/**` 任何檔案
- 禁 deploy
- 禁動 memory 檔 (要提議記 inbox 或 proposal)

## 結束條件
- Report 寫完且含 `END: ok` 標記
- Gmail 已寄
- git working tree 乾淨 (除新增的 report / inbox)
