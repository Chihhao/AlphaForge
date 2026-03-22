# AlphaForge Bug 追蹤報告

> 建立日期：2026-03-22
> 最後更新：2026-03-22（批次修復 BUG-001~006、008、009）
> 狀態說明：🔴 待修 / 🟡 待修（中） / 🟢 待修（低） / ✅ 已修

---

## 🔴 高優先（功能失效 / 資料正確性）

### BUG-001：`signals/today` 重訓後嚴重少報訊號
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** `backend/app/services/alpha_miner_service.py` line 290-292
- **現象：** 今日實際有 32 隻訊號股已入庫，但 `/alpha-miner/signals/today` 只回傳 2 隻
- **根因：** `get_today_signals()` 依賴 `_details` 記憶體快取。`_details` 採懶加載設計，只有用戶曾開啟過詳情的策略才有資料。重訓後快取被清空，大多數策略的 `recent_signals` 為空，導致訊號被過濾掉。
- **影響：** 每日精選頁面顯示嚴重不足的推薦標的，用戶體驗極差
- **修復方向：**
  - 前端改用 `alpha_signal_history` 表（`/alpha-miner/signals/history`）取得當日訊號，不依賴即時快取
  - 或後端在訓練完成後預熱全部 `_details`（成本較高）

---

### BUG-002：排程 `save_today_signals` 執行時訓練尚未完成
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** `backend/app/core/scheduler.py`
- **現象：** 17:10 觸發重訓（non-blocking 子程序），17:15 執行 `save_today_signals()`，但訓練需 20-40 分鐘，此時 `is_training=True`，函式直接 return 空值
- **影響：** `alpha_signal_history` 每日可能入庫空資料，造成歷史訊號缺漏，個股展開看不到歷史紀錄
- **修復方向：**
  - 將 `save_today_signals` 排程延後至 17:45 或 18:00（留足緩衝）
  - 或在訓練子程序完成時自動觸發 `save_today_signals()`（事件驅動，更可靠）

---

### BUG-003：`shift(4)` 與「5日變化」命名語意不符
- **狀態：** ✅ 非 bug（2026-03-22）
- **位置：** `backend/app/services/feature_service.py` `_build_chip_features()`
- **現象：**
  ```python
  # 命名「5日變化」，但 shift(4) 是取「4個交易日前」的值
  margin_shift = raw.groupby('stock_id')['margin_balance'].transform(lambda x: x.shift(4))
  raw['margin_chg_5d'] = ...
  hold_shift = raw.groupby('stock_id')['foreign_hold_pct'].transform(lambda x: x.shift(4))
  raw['foreign_hold_chg_5d'] = raw['foreign_hold_pct'] - hold_shift
  ```
- **影響：** `margin_chg_5d`、`foreign_hold_chg_5d` 特徵數值偏移一天，Alpha Miner 訓練的 IC 計算有系統性誤差
- **修復方向：** 確認語意後統一——若「5日」指「過去5個交易日含今日」則用 `shift(4)`（正確）；若指「過去5個交易日不含今日」則用 `shift(5)`。確認後在 CLAUDE.md 記錄定義，並重訓。

---

## 🟡 中優先（資料品質 / 展示正確性）

### BUG-004：`alpha_signal_history` 歷史只有 7 週（2026-02-02 起）
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** DB 表 `alpha_signal_history`
- **現象：** 個股展開後歷史訊號紀錄極少，大多數股票顯示「無歷史紀錄」
- **根因：** 此表從 2026-02-02 才開始記錄，且受 BUG-002 影響，部分日期可能為空
- **影響：** 前端每日精選的「歷史紀錄」區塊幾乎沒有資料，功能形同虛設
- **修復方向：** 撰寫一次性回補腳本，將 `stock_features` 歷史資料跑過 `get_today_signals()` 邏輯，補填 2024-03 以來的訊號到 `alpha_signal_history` 表

---

### BUG-005：`update_signal_returns()` 持有期到期判定與報酬計算不一致
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** `backend/app/services/alpha_miner_service.py` line 859, 905-908
- **現象：**
  ```python
  HOLDING = {"5d": 7, "10d": 14, "30d": 35}   # 到期判定用（含 buffer）
  holding_days = {"5d": 5, "10d": 10, "30d": 30}  # 報酬計算用（不含 buffer）
  ```
- **影響：** `actual_return` 的結算日期可能有 2-5 天誤差，歷史訊號績效數字不準
- **修復方向：** 統一語意——到期判定和報酬計算應使用同一天數，buffer 另外處理（如驗證價格資料存在後再結算）

---

### BUG-006：勝率「35.2%」展示語意不清，用戶誤解
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** `frontend/pages/strategy.tsx` PickCard Row 3
- **現象：** 用戶看到「勝率 35.2%」，以為是「每次推薦有 35% 機會賺錢」，實際應理解為「訊號觸發後持有 10 天漲超 5% 的歷史機率（市場基準約 24%）」
- **影響：** 用戶對推薦系統失去信心，誤判推薦品質
- **修復方向：** Row 3 文字改為更明確的說明，例如：「漲逾5% 機率：35.2%（市場 24.5%）」

---

### BUG-007：`foreign_hold_pct` 歷史資料永久缺失 ~700 天
- **狀態：** 🟡 已知限制（TWSE API 只保留近 1 年，長期等資料累積）
- **位置：** DB 表 `stock_chip_data.foreign_hold_pct`
- **現象：** TWSE MI_QFIIS API 只保留近 1 年資料，2024-03 ~ 2025-03 約 700 天的外資持股比率永久無法取得
- **影響：** `foreign_hold_pct` / `foreign_hold_chg_5d` 兩個 Phase 6 因子樣本不足，Alpha Miner 測試全部顯示「不顯著」；這兩個因子實際上沒有預測力（在訓練集上）
- **修復方向：** 接受此限制，在 Alpha Miner 因子標籤旁加上「⚠ 樣本不足」提示；長期等待資料累積（約 2025-03 後有完整 2 年資料）

---

### BUG-008：`backfill()` 先刪後寫缺少 rollback 保護
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** `backend/app/services/feature_service.py` line 302-308
- **現象：**
  ```python
  db.execute(delete(StockFeature).where(...))
  db.flush()   # flush 後若寫入失敗，資料永久遺失
  # ... 批量寫入 ...
  ```
- **影響：** 回補中斷時，特徵資料出現永久缺口，影響後續 Alpha Miner 訓練
- **修復方向：** 整個 delete + insert 包在同一個 transaction，失敗時 rollback；或改為 upsert（`INSERT ... ON CONFLICT DO UPDATE`）避免先刪

---

## 🟢 低優先（效能優化）

### BUG-009：`_lookup_name()` 快取未命中時每次查 DB
- **狀態：** ✅ 已修（2026-03-22）
- **位置：** `backend/app/services/alpha_miner_service.py` line 198-222
- **現象：** `_build_recent_signals()` loop 中最多呼叫 50 次 `_lookup_name()`，查詢失敗時不寫入快取，下次仍重複查 DB
- **影響：** 訓練期間輕微效能下降
- **修復方向：** 查詢失敗時也寫入快取（`_stock_names[sid] = sid`）

---

## 已修復

| Bug | 修復日期 | 說明 |
|-----|---------|------|
| BUG-001 | 2026-03-22 | 前端改用 `/alpha-miner/signals/history` 取代 `today` API |
| BUG-002 | 2026-03-22 | 排程延後至 17:45，加入等待訓練完成的 poll loop |
| BUG-003 | 2026-03-22 | 確認非 bug：shift(4) = 5期差，語意正確 |
| BUG-004 | 2026-03-22 | 新增 `backfill_signal_history.py` 腳本支援 `--start-date` |
| BUG-005 | 2026-03-22 | `_find_price` 加入最多 5 天的 fallback 交易日邏輯 |
| BUG-006 | 2026-03-22 | 顯示文字改為「漲>X%機率」，說明更清楚 |
| BUG-008 | 2026-03-22 | feature_service backfill 改為逐日 UPSERT |
| BUG-009 | 2026-03-22 | `_lookup_name` 查詢失敗也快取，避免重複查 DB |

---

## 修復優先順序

```
BUG-001 → BUG-006 → BUG-002 → BUG-004 → BUG-003 → BUG-005 → BUG-008 → BUG-007 → BUG-009
  (前端改用history)  (說明文字)  (排程修正)  (歷史回補)  (shift修正)  (持有期)  (rollback)  (限制)   (效能)
```
