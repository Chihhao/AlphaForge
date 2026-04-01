# LightGBM Alpha Miner — 設計規格

## 目標

用 LightGBM 替換 Alpha Miner 的 LogisticRegression，從「91 combo × 6 dim = 546 個小模型」改為「每維度 1 個全因子模型 = 6 個模型」。目的是**增加 alpha**——讓模型自動發現高維因子交互，取代人工窮舉 2-3 因子組合。

## 現有架構問題

- 91 個 combo 各自只有 2-3 個因子，LR 只能做線性組合
- 無法捕捉「RSI 超賣 + 外資連買 + PB 低估 + 營收成長」這類多因子共振
- 人工定義 combo 列表（FACTOR_COMBINATIONS）本身是 alpha 的瓶頸

## 架構變更

### 訓練流程

**之前**：`_train_all()` → loop DIMENSIONS × FACTOR_COMBINATIONS → `_train_one()` × 546

**之後**：`_train_all()` → loop DIMENSIONS → `_train_dimension()` × 6

每個 `_train_dimension()`:
1. 準備特徵：25 因子 quantile rank（沿用 `_compute_quantile_ranks`）
2. 準備標籤：沿用 `_compute_forward_returns`
3. 時間權重：沿用 `_add_weights`
4. 趨勢過濾：10d/30d 做多限 close > MA60，5d 不過濾（沿用）
5. 訓練 LightGBM
6. 評估：Top 20% Quintile 勝率、Daily Spearman IC、t-test

### LightGBM 超參數

```python
params = {
    'objective': 'binary',
    'metric': 'auc',
    'n_estimators': 300,
    'max_depth': 4,
    'num_leaves': 15,          # 2^4 - 1，配合 max_depth
    'learning_rate': 0.05,
    'min_child_samples': 100,  # 防過擬合：葉節點最少 100 筆
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'reg_alpha': 0.1,          # L1
    'reg_lambda': 1.0,         # L2
    'random_state': 42,
    'verbose': -1,
    'is_unbalance': True,      # 對應原本 class_weight='balanced'
}
```

使用 early stopping（validation set = 測試集前 30%）避免過擬合：
```python
model.fit(X_train, y_train, sample_weight=w_train,
          eval_set=[(X_val, y_val)],
          callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
```

### 訊號產生

`get_today_signals()` 改為：
1. 從快取取出該維度的 LightGBM 模型
2. 對最新一天全市場資料打分：`model.predict_proba(X)`
3. 取 Top 20% 股票
4. 用 `model.predict(X, pred_contrib=True)` 取每股因子貢獻
5. 取貢獻最大前 3 因子 → `buy_reasons`
6. 正向貢獻因子數量 → `trigger_count`（與 Strategy Miner 相容）

### 輸出 Schema 變更

#### `AlphaMinerResult.strategies`

從 412 筆縮減為 6 筆（每維度一筆）。每筆 `StrategyRanking`:
- `strategy_id`: e.g. `"lgb_10d"`, `"lgb_30d_short"`
- `strategy_name`: e.g. `"LightGBM 10d 做多"`
- `factors`: 全部 25 因子列表
- `ic`, `win_rate_outsample` 等：整個模型的指標
- `is_significant`: Bonferroni 校正 N=6

#### `StrategyDetail.factor_weights`

改為全局 feature importance（gain-based），25 筆 `FactorWeight`：
- `coefficient` → feature importance 值
- `direction` → 該因子在模型中的主要方向（透過 SHAP contribution 的符號判斷）

#### `TodaySignal`

Schema 不變。語義調整：
- `trigger_count` → 正向貢獻因子數（原本為「幾個 combo 同時觸發」）
- `strategies` → top 3 貢獻因子的中文名（原本為 combo 策略名列表）
- `weighted_win_rate` → 該維度模型的 OOS 勝率
- `weighted_odds_ratio` → 個股的 predicted_prob / (1 - predicted_prob)

### Strategy Miner 相容性

#### `alpha_signal_history` 表

欄位不變。寫入邏輯沿用 `save_today_signals()`，來源從「多 combo 彙整」改為「單模型 Top20%」。

#### `MIN_WIN_RATE` 門檻

Strategy Miner 的 `_generate_direction_picks()` 目前用 `StrategyBacktestParam` 的 per-combo 勝率過濾。改為：
- `strategy_id` 對齊新格式（`lgb_5d`, `lgb_10d`, `lgb_30d`）
- 勝率檢查改為維度級：模型 OOS 勝率 > market_baseline + 5pp（相對門檻）
- 自然解決「空頭市場所有 combo 被過濾」的問題

### 不變的部分

- `_compute_quantile_ranks()`：沿用
- `_add_weights()`：沿用
- `_compute_forward_returns()`：沿用
- `_build_equity_curve()`：沿用
- `_save_snapshot()` / `_load_snapshot()`：沿用（JSON 格式自動適配新 schema）
- 訓練/測試時間切割邏輯：沿用
- multiprocessing 子程序架構：沿用
- 所有 API endpoints：路徑不變
- 前端：不需改動

## 依賴

- 新增 `lightgbm` 到 `backend/requirements.txt`
- 不需要 `shap` 套件（使用 LightGBM 內建 `pred_contrib`）

## 檔案影響

| 檔案 | 改動程度 |
|------|----------|
| `alpha_miner_service.py` | **大改**：移除 FACTOR_COMBINATIONS loop，新增 `_train_dimension()`，改寫 `get_today_signals()` |
| `alpha_miner.py` (schemas) | 小改：schema 不變，部分欄位語義調整 |
| `strategy_miner_service.py` | 小改：`MIN_WIN_RATE` 改相對門檻，`strategy_id` 格式適配 |
| `requirements.txt` | 新增 `lightgbm` |
| 其他檔案 | 不動 |

## 風險

1. **LightGBM 過擬合**：用保守超參數 + early stopping + 淺樹（depth=4）緩解
2. **NAS 環境安裝**：LightGBM 需要 C++ 編譯，Docker 環境需確認能安裝
3. **Alpha 未必提升**：如果因子本身就沒有非線性交互，LightGBM 不會比 LR 好。但 25 因子涵蓋技術/基本/籌碼三面，存在交互的可能性很高
