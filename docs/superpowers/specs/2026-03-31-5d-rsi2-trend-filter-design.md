# 5D 策略強化：RSI(2) + 趨勢過濾器

> 日期：2026-03-31
> 狀態：設計確認

## 背景

5d 維度策略診斷結果顯示：
- 因子 IC 很強（bias10 = -0.097），均值回歸訊號確實存在
- 但扣除 0.6% 交易成本後，5d 做多勝率僅 45.0%，與隨機基準（44.9%）幾乎無差異
- 核心問題：0.6% 成本佔 5 日平均報酬（+0.27%）的 222%
- 純因子 bias10 最超賣 5% 選股，扣成本後仍有 +0.72%（p ≈ 0），證明訊號品質足夠，但需要更精準的進場

學術研究指出兩個關鍵改善方向：
1. **RSI(2)**（Connors 策略）：2 期 RSI 比 14 期更能捕捉極端超賣/超買，適合短期反轉
2. **趨勢過濾**：只在順勢環境做均值回歸（做多需 close > MA60，做空需 close < MA60），避免在下跌趨勢中接刀

## 改動範圍

### 1. RSI(2) 因子新增

#### indicator_service.py
不需修改。現有 `calculate_rsi_vec(df, window)` 已支援任意 window 參數。

#### stock_feature.py (Model)
新增欄位：
```python
rsi2 = Column(Float, nullable=True)  # 2期 RSI（極短期超賣/超買）
```

#### feature_service.py
在 `compute_daily` 和 `compute_batch` 中新增：
```python
df['rsi2'] = IndicatorService.calculate_rsi_vec(df, 2)
```
並在寫入 DB 的 dict 中加入 `rsi2=_safe_float(row.get('rsi2'))`。

#### alpha_miner_service.py
- `FACTOR_LABELS` 新增：`'rsi2': 'RSI(2)'`
- `_LOAD_COLS` 自動包含（已從 FACTOR_LABELS keys 生成）
- `FACTOR_COMBINATIONS` 新增 6 組：

| 組合 | 邏輯 |
|------|------|
| `['rsi2']` | RSI(2) 單因子 |
| `['rsi2', 'vol_ratio']` | 極短期超賣 + 放量 |
| `['rsi2', 'pb_ratio']` | 極短期超賣 + 低估值 |
| `['rsi2', 'foreign_buy_5d']` | 極短期超賣 + 外資買超 |
| `['rsi2', 'bias10']` | 兩個最強均值回歸因子聯合 |
| `['rsi2', 'bias10', 'vol_ratio']` | 三因子：超賣 + 乖離 + 量 |

Bonferroni N：85 → 91（自動計算，不需手動更新）。

#### DB Migration
```sql
ALTER TABLE stock_features ADD COLUMN rsi2 FLOAT;
```

### 2. 趨勢過濾器

#### 作用位置：Alpha Miner 訓練層

在 `_train_one` 方法中，train/test split 之後加入趨勢過濾：

```python
# 做多維度：只保留 close > ma60 的樣本（順勢做多）
# 做空維度：只保留 close < ma60 的樣本（順勢做空）
if direction == 'long':
    train_df = train_df[train_df['close'] > train_df['ma60']]
    test_df = test_df[test_df['close'] > test_df['ma60']]
else:
    train_df = train_df[train_df['close'] < train_df['ma60']]
    test_df = test_df[test_df['close'] < test_df['ma60']]
```

#### 資料載入
`_LOAD_COLS` 需加入 `'ma60'`。目前 `ma60` 在 `stock_features` 表中已存在但未被 Alpha Miner 載入。

做法：在 `_LOAD_COLS` 定義處手動加入 `'ma60'`：
```python
_LOAD_COLS = ['stock_id', 'date', 'close', 'ma60'] + list(FACTOR_LABELS.keys())
```
`ma60` 不加入 `FACTOR_LABELS`，因為它不是訓練因子，只是過濾條件。

#### 不需改動的地方
- `get_today_signals`：訓練時已過濾，模型自然只對順勢股票給高分
- `strategy_miner_service.py`：消費 alpha_signal_history，不需知道過濾邏輯
- 前端：無影響

### 3. Backfill

#### 輕量 RSI(2) 回補腳本 `backfill_rsi2.py`
- 只針對 `rsi2 IS NULL` 的記錄補算
- 讀取 stock_prices 的 close → 按 stock_id 分組計算 RSI(2) → UPDATE stock_features
- 預估 2~3 分鐘完成

#### 後續重跑
1. Alpha Miner 重訓（含新因子 + 趨勢過濾）— 部署後自動觸發
2. Strategy Miner 重跑 — `backfill_strategy_miner.py`

## 驗證標準

| 指標 | 改善前 | 目標 |
|------|--------|------|
| 5d long 勝率（>0%） | 45.0% | 47%+ |
| 5d long vs 隨機差距 | +0.1pp | +3pp+ |
| 5d short 平均報酬 | 虧損 | 收窄或轉正 |

驗證工具：`scripts/diagnose_5d.py`（已存在）。

## 不做的事

- 不改前端 UI
- 不新增測試檔（改動為新增欄位和參數，不破壞既有邏輯，跑現有 pytest 即可）
- 不動 Strategy Miner 的 ATR 停損停利邏輯
- 不動 10d/30d 維度的門檻設定（它們也受益於趨勢過濾，但不做額外調整）
