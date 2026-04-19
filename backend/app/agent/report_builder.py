from __future__ import annotations
from datetime import date


def build_evening_skeleton(report_date: date) -> str:
    d = report_date.strftime("%Y-%m-%d")
    return f"""###### tags: `AlphaForge`,`agent-report`,`evening`

# {d} Evening Tick (18:30)

`文件版本: {d}a`

## 產線體檢
- [ ] scheduler jobs 15:30 / 16:30 / 17:00 / 17:20 / 17:30 / 18:10 綠燈
- [ ] feature row count + null%
- [ ] fundamentals 覆蓋率
- [ ] 17:30 模型重訓 IC / loss
- [ ] 昨日 picks 結案 (tp / sl / time_limit)
- [ ] 近 7 日 picks 勝率退化
- [ ] GET /picks/today 健康

## 異常分流
(若無異常寫「無」, 若有寫入 docs/inbox/alert-*.md 並於此列連結)

## Alpha ledger
- 本 tick IC / wr / avg_top 變化: 未測 (T0 體檢不跑研究)
- 新發現: -
- 否證: -
- 下一步候選: -

## 可逆清單
(T0 tick 不 commit production, 應為空)

END: ok
"""


def build_night_skeleton(report_date: date) -> str:
    d = report_date.strftime("%Y-%m-%d")
    return f"""###### tags: `AlphaForge`,`agent-report`,`night`

# {d} Night Tick (03:00)

`文件版本: {d}a`

## 現場還原結果
(引用 site_restore checklist)

## 候選題 + Gate 2 checklist
### 題 1: <主題>
- [ ] Alpha-first
- [ ] 有 benchmark
- [ ] 含 long-short
- [ ] 先診斷根因
- [ ] 不偽造數據
- [ ] Partial IC 非充分
- [ ] 100% 結果找偏差
- [ ] 資料正確性優先
→ 判定: PASS/FAIL, Tier: T?

### 棄選清單
(列 Gate 2 fail 的題, 附理由)

## 執行摘要
- 選題: <主題>
- Tier: T?
- 動作: <commit SHA 清單, 跑的 script, deploy 結果>

## Alpha ledger
- 本 tick IC / wr / avg_top 變化: <數字>
- 新發現: <一句>
- 否證: <一句>
- 下一步候選: <一行>

## 可逆清單
- commit <sha>: <說明>
  rollback: git revert <sha>
- deploy <ts> backend:<sha>
  rollback: docker tag alphaforge-backend:<previous> alphaforge-backend:latest && ./deploy.sh 3

## Pending approvals (若有)
(列 notify-hub 已發但未回的 proposal; hub 未實作時寫入 docs/proposals/ 等 git mv)

END: ok | deployed | aborted
"""
