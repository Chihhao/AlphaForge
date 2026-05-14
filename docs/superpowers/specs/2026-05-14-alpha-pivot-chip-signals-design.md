###### tags: `專案`,`AlphaForge`,`alpha 研究`,`規格`,`pivot`

# AlphaForge Alpha Pivot — 籌碼/法人/事件 訊號研究 設計規格

`文件版本: 2026-05-14a`

## 0. 背景與目標

### 0.1 為何 pivot

使用者觀察 5 個月後感覺「幾乎沒有 alpha, 想放棄目前算法」。2026-05-14 拉 NAS 結案 picks (164 條) 驗證:

| 維度 | n | win rate | avg return | median |
|---|---|---|---|---|
| 5d | 84 | 54.8% | **+0.98%** | +1.15% |
| 10d | 75 | 52.0% | **-1.42%** | +1.17% |
| 20d | 5 | 20% | -3.71% | -4.44% (樣本太小) |

5d 微正 (扣手續費接近零), 10d **負 avg**, 20d 沒夠樣本。使用者「沒 alpha」感受成立。

### 0.2 目標

不放棄前 5 個月成果 (現有 14 因子 + LightGBM + 5d/10d/20d 架構保留), 但加一個 **orthogonal alpha source**: 籌碼 / 法人 / 事件訊號。希望:

1. 找出**現有 14 因子裡誰真有貢獻、誰拖累** (Phase 1 輕量診斷, 對齊 memory `feedback_diagnose_before_model`)
2. 加入**跟技術+基本面因子不重複的新訊號** (Phase 2 prototype), 用 walk-forward 驗 incremental alpha

完成定義 (Acceptance):
- Phase 1 ablation report 列 top-5 正向 / top-5 負向因子, 提砍/加權建議
- Phase 2 三大法人連續買賣訊號 IC > 0.03 (5d 或 10d 任一), wr > 53%, 跟既有 LightGBM 輸出 correlation < 0.3 (證明 orthogonal)

## 1. Scope

### 1.1 Phase 1 — 14 因子 ablation 診斷 (2-3 天)

In scope:
- 拉 NAS production `stock_picks`(結案) + `stock_features`(picks 當日 feature) join
- 對每個現有因子 (14 個): 算「該因子 top-quintile picks 的 wr / avg_return」vs「bottom-quintile」, 看單因子 IC
- 對 quality gates: 量能 / 流動性 / 趨勢 filter, 看是否在拖累 (gate 阻擋了 alpha 反而留下噪音?)
- 對 universe 切片: 大型股 (市值 > 500 億) / 中小型 / 主題股, 看 alpha 是否集中
- 輸出: `docs/reports/2026-MM-DD-factor-ablation.md` + `backend/scripts/research_factor_ablation.py`

Out of scope:
- 重訓 LightGBM (等 Phase 1 結論再決定)
- 改 production picks 邏輯

### 1.2 Phase 2 — 籌碼訊號 prototype (3-7 天)

In scope:
- 新增 `stock_chip_daily` 表 (TWSE 三大法人買賣超: foreign / trust / dealer, 各 buy / sell / net)
- TWSE 公開 API crawler (`backend/app/data/chip_crawler.py`)
- Backfill 近 1 年資料 (~250 trading days × ~1700 stocks)
- 第一個訊號: **「三大法人連續買進 N 日後 5d/10d 後續報酬」**
  - 對每個 stock, 算外資 / 投信 連續淨買 ≥ 3 日的事件
  - 計算事件後 5d / 10d / 20d 報酬分佈
  - walk-forward 驗 IC + wr + avg_return + 大盤 benchmark 對比
- 輸出: `backend/scripts/research_chip_signals.py` + `docs/reports/2026-MM-DD-chip-signal-prototype.md`

Out of scope (Phase 3 候選):
- 整合進 LightGBM 重訓
- 改 production picks endpoint
- 自動排程更新籌碼資料
- 融資融券 / 月營收 drift / 內部人申報轉讓 (Phase 2 先只做三大法人, prototype 證明有 alpha 才擴)

### 1.3 後續 Phase 3 (本 spec 之外)

- 籌碼訊號整合 LightGBM ensemble (作 14+N 因子)
- production picks 整合
- 自動排程更新 (APScheduler 加 job)

## 2. 高階架構

```
Phase 1 (ablation):
  NAS Postgres stock_picks + stock_features
        │
        ▼
  research_factor_ablation.py
    - per-factor IC (quintile spread)
    - quality gate impact
    - universe slice
        │
        ▼
  docs/reports/2026-MM-DD-factor-ablation.md
  (user 決定砍哪些因子 / 留哪些 / 加哪些權重)


Phase 2 (chip signals):
  TWSE 公開 API (三大法人買賣超)
        │
        ▼
  chip_crawler.py + alembic migration
        │
        ▼
  stock_chip_daily 表 (NAS Postgres)
        │
        ▼
  research_chip_signals.py
    - 事件: 連續淨買 N 日
    - 事件後 5d/10d/20d 報酬
    - walk-forward IC + 大盤 benchmark + LightGBM 輸出 correlation
        │
        ▼
  docs/reports/2026-MM-DD-chip-signal-prototype.md
  (user 決定 Phase 3 整不整合)
```

兩個 Phase 互相獨立, 但結果會 inform 對方:
- Phase 1 結果 → 知道現有架構哪邊弱, 為 Phase 2 整合提供方向
- Phase 2 結果 → 若 IC 顯著, 進 Phase 3 整合 LightGBM

## 3. Components spec

### 3.1 Phase 1: `research_factor_ablation.py`

職責: 對結案 picks + 當日 features 跑因子貢獻分析。

主要函式:
```python
def load_picks_with_features() -> pd.DataFrame:
    """從 NAS Postgres join stock_picks (concluded) + stock_features by (stock_id, pick_date)。"""

def per_factor_ic(df: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """每個因子 quintile spread (top-q wr/avg - bot-q wr/avg) + Spearman IC + p-value。"""

def quality_gate_impact(df: pd.DataFrame) -> dict:
    """有/沒 pass quality gate 兩組對比, 看 gate 是否真的擋掉爛 picks。"""

def universe_slice_alpha(df: pd.DataFrame) -> dict:
    """按 market_cap quintile / TWSE-vs-TPEx / 主題股 (半導體/金融/傳產) 切片, 看 alpha 分佈。"""

def main():
    """讀資料、跑三個分析、輸出 markdown report。"""
```

輸入: NAS Postgres (`DATABASE_URL` from backend/.env), 或從 production API `/strategy-miner/picks/concluded` pull 全量 + 對應 features。

輸出: `docs/reports/YYYY-MM-DD-factor-ablation.md`:
```markdown
# 14 因子 Ablation Report

## 樣本: N picks (5d / 10d / 20d), MM-DD 至 MM-DD

## Per-Factor IC (Spearman 排序)
| 因子 | IC | p-value | top-q wr | bot-q wr | spread |
|---|---|---|---|---|---|
| rsi_14 | 0.08 | 0.03 | 58% | 49% | +9pp |
...

## Quality Gate 影響
- gate 後 vs 前: wr / avg / sample 對比

## Universe 切片
- 大型股 / 中小型 / 主題股 alpha 分佈

## 結論建議
- 砍因子: ...
- 留因子: ...
- 加權建議: ...
```

### 3.2 Phase 2: `chip_crawler.py`

職責: 從 TWSE 公開 API 拉每日三大法人買賣超。

主要函式:
```python
def fetch_chip_daily(date: date) -> list[dict]:
    """GET https://www.twse.com.tw/fund/T86?date=YYYYMMDD&selectType=ALL
    return [{stock_id, foreign_buy, foreign_sell, foreign_net,
             trust_buy, trust_sell, trust_net,
             dealer_buy, dealer_sell, dealer_net}, ...]"""

def backfill_chip(start_date: date, end_date: date, batch_size: int = 5):
    """Daily loop fetch + upsert, rate limit 1 req/sec, retry 3 次。"""
```

Schema (`backend/app/models/chip_metrics.py` + alembic migration):
```sql
CREATE TABLE stock_chip_daily (
    id SERIAL PRIMARY KEY,
    stock_id VARCHAR(10) NOT NULL,
    date DATE NOT NULL,
    foreign_buy BIGINT, foreign_sell BIGINT, foreign_net BIGINT,
    trust_buy BIGINT, trust_sell BIGINT, trust_net BIGINT,
    dealer_buy BIGINT, dealer_sell BIGINT, dealer_net BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (stock_id, date)
);
CREATE INDEX idx_chip_stock_date ON stock_chip_daily (stock_id, date);
```

### 3.3 Phase 2: `research_chip_signals.py`

職責: 對籌碼資料跑第一個訊號 (連續淨買事件 → 後續報酬)。

主要函式:
```python
def find_consecutive_buy_events(min_days: int = 3) -> pd.DataFrame:
    """對每個 stock, 找外資 / 投信 連續 net > 0 持續 ≥ min_days 的事件 row。
    return [{stock_id, event_date, foreign_consecutive_days, trust_consecutive_days, ...}]"""

def event_post_returns(events: pd.DataFrame, horizons: list[int] = [5, 10, 20]) -> pd.DataFrame:
    """對每個事件, 算 event_date + h 日後 close / event_date close - 1。"""

def walk_forward_backtest(events: pd.DataFrame) -> dict:
    """走 walk-forward, 分 train / test windows, 算各 horizon 的 wr / avg / IC。
    對比 same period TAIEX 大盤報酬作 benchmark。"""

def correlation_with_lightgbm(events: pd.DataFrame) -> float:
    """事件當日 stock 對應的現有 LightGBM 輸出 score, 算 correlation。
    < 0.3 = orthogonal (好)。"""

def main():
    """跑 backtest + 寫 report。"""
```

輸出: `docs/reports/YYYY-MM-DD-chip-signal-prototype.md`:
```markdown
# 三大法人連續淨買訊號 Prototype Report

## 事件樣本: N 事件 (date range), foreign / trust 各佔比

## Walk-forward Backtest
| Horizon | n | wr | avg_return | TAIEX baseline | spread | IC |
|---|---|---|---|---|---|---|
| 5d | ... | 56% | +1.5% | +0.3% | +1.2pp | 0.04 |
...

## Correlation with LightGBM
- foreign event: 0.18 (orthogonal ✅)
- trust event: 0.24 (orthogonal ✅)

## 結論
- 5d / 10d 是否 IC > 0.03 + wr > 53% + correlation < 0.3?
- Phase 3 整合決策建議
```

## 4. Data flow

### Phase 1 流程
1. 從 NAS Postgres pull 結案 picks (164 + 後續累積) + 各 pick `pick_date` 對應 stock_features row
2. join 成 dataframe (~164 rows × 14 因子)
3. 跑三類分析: per-factor IC / quality gate / universe slice
4. 輸出 markdown report

### Phase 2 流程
1. chip_crawler 拉近 1 年 TWSE T86 (三大法人) 資料 → `stock_chip_daily`
2. research_chip_signals 從 `stock_chip_daily` 找連續淨買事件 (foreign / trust 分別)
3. 對每事件算事件後 5d/10d/20d 報酬 (從 `stock_prices`)
4. walk-forward backtest: 分 quarter 看穩定性, 對比 TAIEX
5. 算事件當日對應 stock 的 LightGBM 輸出 score (從 `strategy_results` 或重算), 跟事件 binary 算 correlation
6. 輸出 markdown report

## 5. Risks & Mitigations

| 風險 | 緩解 |
|---|---|
| Phase 1 樣本不足 (5d 84 / 10d 75 / 20d 5) | 不單看顯著性, 顯式列 CI 與 n; 20d 標明「樣本太小不可信」, 不下結論 |
| Phase 1 因子 IC noise | bootstrap CI + 多個 quintile cut 對照, 不只一個 split |
| TWSE T86 API 限流 | rate limit 1 req/sec, retry 3 次 exponential backoff |
| 籌碼 backfill 慢 | 近 1 年 ~250 days × 1 req = 約 5 分鐘 (1 req/sec); 若失敗可斷點續傳 |
| 籌碼資料缺失 (停牌 / 新上市) | dataframe 用 left join, NaN → drop event sample |
| 三大法人連續淨買訊號可能已被市場 price in | walk-forward + 對比 TAIEX baseline; 若無 alpha 是預期結果, 換 Phase 2 第二個 source (融資融券 / 月營收) |
| Phase 2 走完 IC < 0.03 | 不強加進 Phase 3; user 重新決定方向 (本 spec 設計成 prototype 失敗可接受) |

## 6. Acceptance Criteria

### Phase 1 完成
- [ ] `research_factor_ablation.py` 可從 NAS 拉資料 + 跑分析無 error
- [ ] `docs/reports/YYYY-MM-DD-factor-ablation.md` 寫出: 14 因子 IC 排名 + quality gate 對比 + universe 切片
- [ ] User 看完 report 同意 (或修改) 後續因子去留決策
- [ ] commit + 跟 memory `feedback_data_validation` 對齊 (有 benchmark / CI / p-value)

### Phase 2 完成
- [ ] `stock_chip_daily` 表建好, alembic migration 跑過, ~1 年資料 backfill 完
- [ ] `research_chip_signals.py` 跑出 walk-forward backtest 報告
- [ ] Verdict 二選一:
  - **Pass**: 5d 或 10d IC > 0.03 + wr > 53% + LightGBM correlation < 0.3 → 進 Phase 3 整合計畫
  - **Fail**: 任一條件沒過 → 寫進 report, 換 Phase 2 second source (融資融券 / 月營收 drift)

## 7. 影響面

### 7.1 跟現有架構

- 現有 14 因子 / LightGBM / picks 流程**完全不動** (Phase 1 純讀, Phase 2 新建表)
- 不改 production endpoint
- 不改 scheduler

### 7.2 跟 memory feedback

- ✅ `feedback_alpha_first`: 一切以 alpha 為優先 (找新 alpha source)
- ✅ `feedback_diagnose_before_model`: 換 model 前先診斷 (Phase 1 ablation)
- ✅ `feedback_data_validation`: 有 benchmark + CI + p-value
- ✅ `feedback_no_speculation`: walk-forward backtest + 對比 TAIEX baseline
- ✅ `feedback_use_historical_backtest`: 用歷史資料先驗
- ✅ `feedback_no_sqlite`: 用 NAS Postgres
- ✅ `feedback_longshort_validation`: long-only spec (跟既有一致, short 已 memory 寫過放棄)
- ✅ `feedback_main_only_workflow`: 直接 main 動

## 8. Implementation Plan 預覽 (給 writing-plans skill 用)

預估 9-12 tasks, 分兩 phase:

**Phase 1** (3-4 tasks):
1. `research_factor_ablation.py` 骨架 + load_picks_with_features
2. per_factor_ic + unit test (mock data)
3. quality_gate_impact + universe_slice_alpha
4. main + 輸出 markdown + 跑出 report → user review

**Phase 2** (6-8 tasks):
5. alembic migration: `stock_chip_daily` 表
6. `chip_crawler.py` fetch_chip_daily + unit test
7. backfill_chip + 跑近 1 年 backfill
8. `research_chip_signals.py` find_consecutive_buy_events + unit test
9. event_post_returns + walk_forward_backtest
10. correlation_with_lightgbm
11. main + 跑出 prototype report → user verdict
12. (conditional) Phase 3 整合計畫 spec (僅 Phase 2 Pass 時開)

每 task 自帶 TDD red-green-refactor + 一個 commit。
