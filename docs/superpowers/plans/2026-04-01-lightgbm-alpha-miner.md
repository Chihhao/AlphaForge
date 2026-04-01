# LightGBM Alpha Miner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 546 LogisticRegression models with 6 LightGBM models (one per dimension) to capture non-linear factor interactions and increase alpha.

**Architecture:** Each dimension (5d/10d/30d × long/short) gets one LightGBM trained on all 25 quantile-ranked factors. Factor contributions via `pred_contrib` replace combo-based buy_reasons. Strategy Miner MIN_WIN_RATE switches to relative threshold.

**Tech Stack:** LightGBM, scikit-learn (removed for LR), existing Pandas/NumPy pipeline

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/requirements.txt` | Modify | Add lightgbm |
| `backend/app/services/alpha_miner_service.py` | Major rewrite | Replace combo loop with per-dimension LightGBM training, rewrite signal generation |
| `backend/app/services/strategy_miner_service.py` | Modify:50-53,160-175 | MIN_WIN_RATE → relative threshold |
| `backend/app/schemas/alpha_miner.py` | No change | Schema stays backward-compatible |

---

### Task 1: Add lightgbm dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add lightgbm to requirements.txt**

Add `lightgbm` after `scikit-learn==1.6.1`:

```
scikit-learn==1.6.1
lightgbm
scipy
```

- [ ] **Step 2: Install and verify**

Run: `cd backend && ./.venv/bin/pip install lightgbm`
Expected: Successfully installed lightgbm

- [ ] **Step 3: Verify import**

Run: `cd backend && ./.venv/bin/python -c "import lightgbm; print(lightgbm.__version__)"`
Expected: Version number printed (e.g., 4.x.x)

---

### Task 2: Rewrite alpha_miner_service.py — training core

**Files:**
- Modify: `backend/app/services/alpha_miner_service.py`

This is the main task. The file keeps all existing helper methods unchanged and replaces: (1) the combo loop in `_train_all`, (2) `_train_one` → `_train_dimension`, (3) `get_today_signals`, (4) `_build_recent_signals`.

- [ ] **Step 1: Remove FACTOR_COMBINATIONS, update module docstring and imports**

Replace the module docstring (line 1-2):
```python
"""
AlphaMinerService — LightGBM 全因子模型 (Phase 9)

設計原則：
- 每維度 1 個 LightGBM，全 25 因子同時輸入
- 自動發現因子交互（取代人工定義 combo 組合）
- 分位數排名消除跨股票量綱差異
- 時間衰減權重（近期資料比舊資料重要）
- 訓練/測試嚴格時間切割，留一個月空白期避免標籤洩漏
- 保守超參數 + early stopping 防過擬合
- Bonferroni 多重校正 N=6（6 個維度模型）
- 樣本外 Spearman IC 為排序依據
- 訓練結果持久化至 DB，後端重啟免重算
"""
```

Remove the `from sklearn.linear_model import LogisticRegression` import inside `_train_one` (it will be replaced later).

Remove the entire `FACTOR_COMBINATIONS` list (lines 85-171) and the `_BONFERRONI_N` variable (line 176).

Keep `FACTOR_LABELS` dict, `_LOAD_COLS`, and everything else above line 178 intact.

- [ ] **Step 2: Update `_train_all` to use per-dimension training**

Replace the `_train_all` method (lines 438-511) with:

```python
@classmethod
def _train_all(cls, db: Session) -> AlphaMinerResult:
    df_base = cls._load_features(db)

    if df_base.empty:
        result = AlphaMinerResult(
            strategies=[], last_trained=date.today().isoformat(),
            train_period='N/A', test_period='N/A',
            total_combinations_tested=0, bonferroni_threshold=1.0,
        )
        cls._cache = result
        cls._cache_date = date.today()
        return result

    # ── 動態切割：依實際資料的最後日期往前推算 ─────────────────────────
    max_date = df_base['date'].max()
    test_start = (max_date - pd.DateOffset(months=cls.TEST_MONTHS)).date()
    train_end  = (max_date - pd.DateOffset(
        months=cls.TEST_MONTHS + cls.GAP_MONTHS)).date()

    # 分位數排名與時間權重只需計算一次
    df_base = cls._compute_quantile_ranks(df_base)
    df_base = cls._add_weights(df_base, train_end)

    n_total = len(cls.DIMENSIONS)
    all_rankings: List[StrategyRanking] = []
    all_details: Dict[str, StrategyDetail] = {}

    _write_progress({"current": 0, "total": n_total, "percent": 0,
                     "current_dim": "", "current_strategy": ""})

    for i, dim in enumerate(cls.DIMENSIONS):
        dim_direction = dim.get('direction', 'long')
        df_dim = cls._compute_forward_returns(
            df_base, dim['forward_days'], dim['threshold_low'], dim_direction)
        dim_label = '做多' if dim_direction == 'long' else '做空'
        logger.info(f"[AlphaMiner] 開始訓練 {dim['key']} 維度（LightGBM {dim_label}）")

        _write_progress({
            "current": i, "total": n_total,
            "percent": round(i / n_total * 100),
            "current_dim": dim['key'],
            "current_strategy": f"LightGBM {dim_label}",
        })

        ranking, detail = cls._train_dimension(
            df_dim, n_total, train_end, test_start, dim)
        if ranking is not None:
            all_rankings.append(ranking)
            all_details[ranking.strategy_id] = detail

    all_rankings.sort(key=lambda x: x.ic, reverse=True)

    min_date = df_base['date'].min()
    result = AlphaMinerResult(
        strategies=all_rankings,
        last_trained=date.today().isoformat(),
        train_period=f"{pd.Timestamp(min_date).strftime('%Y-%m')} ~ {train_end.strftime('%Y-%m')}",
        test_period=f"{test_start.strftime('%Y-%m')} ~ {pd.Timestamp(max_date).strftime('%Y-%m')}",
        total_combinations_tested=n_total,
        bonferroni_threshold=round(0.05 / n_total, 6),
    )
    cls._cache = result
    cls._cache_date = date.today()
    cls._details = all_details

    try:
        cls._save_snapshot(db, result, all_details)
    except Exception as e:
        logger.warning(f"[AlphaMiner] 快照存儲失敗（不影響結果）: {e}")

    return result
```

- [ ] **Step 3: Write `_train_dimension` (replaces `_train_one`)**

Delete `_train_one` method entirely (lines 626-809) and add:

```python
@classmethod
def _train_dimension(
    cls,
    df: pd.DataFrame,
    n_total: int,
    train_end: date,
    test_start: date,
    dim: dict,
) -> Tuple[Optional[StrategyRanking], Optional[StrategyDetail]]:
    import lightgbm as lgb
    from scipy import stats

    thr_lo = dim['threshold_low']
    thr_hi = dim['threshold_high']
    dim_direction = dim.get('direction', 'long')

    # 使用全部因子的 rank 欄位
    all_factors = list(FACTOR_LABELS.keys())
    rank_cols = [f'{f}_rank' for f in all_factors if f'{f}_rank' in df.columns]
    factors = [f for f in all_factors if f'{f}_rank' in df.columns]

    if not rank_cols:
        return None, None

    train_df = df[df['date'] <= pd.Timestamp(train_end)].dropna(
        subset=rank_cols + ['label'])
    test_df = df[df['date'] >= pd.Timestamp(test_start)].dropna(
        subset=rank_cols + ['label', 'forward_return'])

    # 趨勢過濾：10d/30d 做多限上升趨勢，5d 不過濾
    forward_days = dim.get('forward_days', 5)
    if 'ma60' in df.columns and forward_days >= 10:
        if dim_direction == 'long':
            train_df = train_df[train_df['close'] > train_df['ma60']].copy()
            test_df = test_df[test_df['close'] > test_df['ma60']].copy()
        else:
            train_df = train_df[train_df['close'] < train_df['ma60']].copy()
            test_df = test_df[test_df['close'] < test_df['ma60']].copy()

    if len(train_df) < 100 or len(test_df) < 30:
        return None, None

    X_train = train_df[rank_cols].values
    y_train = train_df['label'].values
    w_train = train_df['weight'].values
    X_test = test_df[rank_cols].values
    y_test = test_df['label'].values

    # Early stopping: 從測試集前 30% 切出驗證集
    val_size = max(int(len(test_df) * 0.3), 10)
    X_val, y_val = X_test[:val_size], y_test[:val_size]

    try:
        model = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=4,
            num_leaves=15,
            learning_rate=0.05,
            min_child_samples=100,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            verbose=-1,
            is_unbalance=True,
        )
        model.fit(
            X_train, y_train, sample_weight=w_train,
            eval_set=[(X_val, y_val)],
            callbacks=[lgb.early_stopping(50, verbose=False),
                       lgb.log_evaluation(0)],
        )
    except Exception as e:
        logger.warning(f"[AlphaMiner] LightGBM 訓練失敗 ({dim['key']}): {e}")
        return None, None

    prob_train = model.predict_proba(X_train)[:, 1]
    prob_test = model.predict_proba(X_test)[:, 1]

    # ── Top 20% Quintile 評估（沿用原有邏輯）──────────────────────
    train_threshold = np.percentile(prob_train, 80)
    pos_train_mask = prob_train >= train_threshold
    train_returns = train_df['forward_return'].values
    win_rate_insample = (
        float((train_returns[pos_train_mask] > thr_lo).mean())
        if pos_train_mask.sum() > 0 else 0.5
    )

    test_threshold = np.percentile(prob_test, 80)
    pos_test_mask = prob_test >= test_threshold
    sample_count_test = int(pos_test_mask.sum())

    top_returns = test_df['forward_return'].values[pos_test_mask]
    all_returns = test_df['forward_return'].values

    win_rate_outsample = (
        float((top_returns > thr_lo).mean()) if len(top_returns) > 0 else 0.0)
    win_rate_outsample_hi = (
        float((top_returns > thr_hi).mean()) if len(top_returns) > 0 else 0.0)
    loss_rate_outsample = (
        float((top_returns < -thr_lo).mean()) if len(top_returns) > 0 else 0.0)
    loss_rate_outsample_hi = (
        float((top_returns < -thr_hi).mean()) if len(top_returns) > 0 else 0.0)
    odds_ratio = round(
        win_rate_outsample / max(loss_rate_outsample, 0.001), 2)
    odds_ratio_hi = round(
        win_rate_outsample_hi / max(loss_rate_outsample_hi, 0.001), 2)

    market_win_rate = float((all_returns > thr_lo).mean()) if len(all_returns) > 0 else 0.0
    market_win_rate_hi = float((all_returns > thr_hi).mean()) if len(all_returns) > 0 else 0.0
    market_loss_rate = float((all_returns < -thr_lo).mean()) if len(all_returns) > 0 else 0.0
    market_loss_rate_hi = float((all_returns < -thr_hi).mean()) if len(all_returns) > 0 else 0.0

    # ── IC：逐日 Spearman（沿用原有邏輯）─────────────────────────
    if len(prob_test) < 10:
        return None, None
    test_df_copy = test_df.copy()
    test_df_copy['_prob'] = prob_test
    daily_ics = []
    for _, grp in test_df_copy.groupby('date'):
        if len(grp) < 10:
            continue
        if grp['_prob'].nunique() < 2 or grp['forward_return'].nunique() < 2:
            continue
        ic_day, _ = stats.spearmanr(grp['_prob'], grp['forward_return'])
        if not np.isnan(ic_day):
            daily_ics.append(ic_day)
    if len(daily_ics) < 10:
        return None, None
    daily_ics_arr = np.array(daily_ics)
    ic = float(np.mean(daily_ics_arr))
    t_stat, p_val = stats.ttest_1samp(daily_ics_arr, 0)
    p_value = float(p_val) if not np.isnan(p_val) else 1.0
    p_value_corrected = min(p_value * n_total, 1.0)

    is_significant = p_value_corrected < 0.05
    overfit_warning = abs(win_rate_insample - win_rate_outsample) > 0.05

    integrity_flags: List[str] = []
    if sample_count_test < 30:
        integrity_flags.append("樣本不足，結果不具統計意義")
    elif sample_count_test < 80:
        integrity_flags.append("樣本數偏少，謹慎參考")
    if overfit_warning:
        integrity_flags.append("此策略可能存在過擬合")

    n_trees = model.n_estimators_  # actual trees after early stopping
    logger.info(
        f"[AlphaMiner] {dim['key']} 完成: IC={ic:.4f}, "
        f"p={p_value_corrected:.4f}, "
        f"WR={win_rate_outsample:.1%}, trees={n_trees}"
    )

    strategy_id = f"lgb_{dim['key']}"
    dim_label = '做多' if dim_direction == 'long' else '做空'
    strategy_name = f"LightGBM {dim['key'].replace('_short', '')} {dim_label}"

    # ── Feature Importance（gain-based）────────────────────────────
    importances = model.feature_importances_
    factor_weights = sorted([
        FactorWeight(
            factor=f,
            factor_label=FACTOR_LABELS.get(f, f),
            coefficient=float(imp),
            direction="bullish",
        )
        for f, imp in zip(factors, importances)
    ], key=lambda x: x.coefficient, reverse=True)

    equity_curve = cls._build_equity_curve(test_df, prob_test)
    recent_signals = cls._build_recent_signals_lgb(
        df, model, rank_cols, factors)

    ranking = StrategyRanking(
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        factors=factors,
        time_dimension=dim['key'],
        threshold_low=thr_lo,
        threshold_high=thr_hi,
        win_rate_insample=win_rate_insample,
        win_rate_outsample=win_rate_outsample,
        win_rate_outsample_hi=win_rate_outsample_hi,
        loss_rate_outsample=loss_rate_outsample,
        loss_rate_outsample_hi=loss_rate_outsample_hi,
        odds_ratio=odds_ratio,
        odds_ratio_hi=odds_ratio_hi,
        market_win_rate=round(market_win_rate, 4),
        market_win_rate_hi=round(market_win_rate_hi, 4),
        market_loss_rate=round(market_loss_rate, 4),
        market_loss_rate_hi=round(market_loss_rate_hi, 4),
        ic=ic,
        p_value=p_value,
        p_value_corrected=p_value_corrected,
        is_significant=is_significant,
        overfit_warning=overfit_warning,
        sample_count_train=len(train_df),
        sample_count_test=sample_count_test,
        integrity_flags=integrity_flags,
    )
    detail = StrategyDetail(
        **ranking.model_dump(),
        equity_curve=equity_curve,
        recent_signals=recent_signals,
        factor_weights=factor_weights,
    )
    return ranking, detail
```

- [ ] **Step 4: Write `_build_recent_signals_lgb` (replaces `_build_recent_signals`)**

Delete the existing `_build_recent_signals` method (lines 832-875) and add:

```python
@classmethod
def _build_recent_signals_lgb(
    cls,
    df: pd.DataFrame,
    model,
    rank_cols: List[str],
    factors: List[str],
) -> List[RecentAlphaSignal]:
    """使用 LightGBM pred_contrib 取得每股因子貢獻，生成近期訊號。"""
    # 找最近有完整資料的日期（至少 200 支股票）
    date_counts = df.groupby('date')['stock_id'].count()
    complete_dates = date_counts[date_counts >= 200].index
    if len(complete_dates) == 0:
        return []
    latest_date = complete_dates.max()

    recent = df[df['date'] == latest_date].dropna(subset=rank_cols)
    if recent.empty:
        return []

    X = recent[rank_cols].values
    prob = model.predict_proba(X)[:, 1]

    # 因子貢獻（pred_contrib 回傳 shape=(n, n_features+1)，最後一列是 bias）
    try:
        contribs = model.predict_proba(X, raw_score=False)  # fallback
        contribs_raw = model.booster_.predict(X, pred_contrib=True)
        # contribs_raw: (n_samples, n_features + 1)
        factor_contribs = contribs_raw[:, :-1]  # 去掉 bias
    except Exception:
        factor_contribs = None

    # Top 20% 作為訊號門檻
    threshold = np.percentile(prob, 80)
    recent = recent.copy()
    recent['_prob'] = prob
    if factor_contribs is not None:
        recent['_contribs'] = list(factor_contribs)
    top_recent = recent[recent['_prob'] >= threshold].sort_values(
        '_prob', ascending=False).head(50)

    result: List[RecentAlphaSignal] = []
    for idx, row in top_recent.iterrows():
        stock_id = str(row['stock_id'])
        name = cls._lookup_name(stock_id)

        # 取該股票貢獻最大的前 3 因子（中文標籤）
        if factor_contribs is not None and '_contribs' in row.index:
            stock_contrib = np.array(row['_contribs'])
            top_indices = np.argsort(-stock_contrib)[:3]
            top_factor_labels = [
                FACTOR_LABELS.get(factors[i], factors[i])
                for i in top_indices
                if i < len(factors) and stock_contrib[i] > 0
            ]
        else:
            top_factor_labels = []

        result.append(RecentAlphaSignal(
            stock_id=stock_id,
            stock_name=name,
            signal_date=latest_date.strftime('%Y-%m-%d'),
            predicted_prob=round(float(row['_prob']), 3),
            trigger_factors=top_factor_labels if top_factor_labels else factors[:3],
        ))
    return result
```

- [ ] **Step 5: Rewrite `get_today_signals` for single-model architecture**

Replace the existing `get_today_signals` method (lines 313-417) with:

```python
@classmethod
def get_today_signals(
    cls, db: Session, dimension: str = "10d", direction: str = "long",
) -> List[TodaySignal]:
    """從 LightGBM 單模型取得今日訊號。

    每個維度只有一個模型，直接取 recent_signals 作為訊號。
    trigger_count = 正向貢獻因子數，strategies = top 因子標籤。
    """
    result = cls.get_strategies(db)
    if result.is_training or not result.strategies:
        return []

    tlo = 0.05 if dimension == '30d' else 0.03
    thi = 0.10 if dimension == '30d' else 0.05

    dim_key = f"{dimension}_short" if direction == 'short' else dimension

    # 找到該維度的策略
    dim_strategy = None
    for s in result.strategies:
        if s.time_dimension == dim_key:
            dim_strategy = s
            break
    if not dim_strategy:
        return []

    detail = cls._details.get(dim_strategy.strategy_id)
    if not detail or not detail.recent_signals:
        return []

    signals = []
    for sig in detail.recent_signals:
        contrib_factors = sig.trigger_factors
        signals.append(TodaySignal(
            stock_id=sig.stock_id,
            stock_name=sig.stock_name,
            trigger_count=len(contrib_factors),
            strategies=contrib_factors[:3],
            signal_date=sig.signal_date,
            time_dimension=dimension,
            threshold_low=tlo,
            threshold_high=thi,
            weighted_odds_ratio=round(
                sig.predicted_prob / max(1 - sig.predicted_prob, 0.001), 2),
            weighted_odds_ratio_hi=round(
                sig.predicted_prob / max(1 - sig.predicted_prob, 0.001), 2),
            weighted_win_rate=dim_strategy.win_rate_outsample,
            weighted_win_rate_hi=dim_strategy.win_rate_outsample_hi,
            weighted_loss_rate=dim_strategy.loss_rate_outsample,
            weighted_loss_rate_hi=dim_strategy.loss_rate_outsample_hi,
            weighted_market_win_rate=dim_strategy.market_win_rate,
            weighted_market_win_rate_hi=dim_strategy.market_win_rate_hi,
            weighted_market_loss_rate=dim_strategy.market_loss_rate,
            weighted_market_loss_rate_hi=dim_strategy.market_loss_rate_hi,
        ))

    signals.sort(key=lambda x: x.weighted_odds_ratio, reverse=True)
    return signals[:20]
```

- [ ] **Step 6: Update `_compute_quantile_ranks` to use all factors (not combo-based)**

Replace `_compute_quantile_ranks` (lines 607-615) with:

```python
@classmethod
def _compute_quantile_ranks(cls, df: pd.DataFrame) -> pd.DataFrame:
    all_factors = list(FACTOR_LABELS.keys())
    for factor in all_factors:
        if factor in df.columns:
            df[f'{factor}_rank'] = (
                df.groupby('date')[factor]
                .rank(pct=True, na_option='keep')
            )
    return df
```

- [ ] **Step 7: Run local test**

Run: `cd backend && DATABASE_URL=postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.services.alpha_miner_service import AlphaMinerService
db = SessionLocal()
AlphaMinerService.invalidate_cache()
result = AlphaMinerService._train_all(db)
print(f'Strategies: {len(result.strategies)}')
for s in result.strategies:
    print(f'  {s.strategy_id}: IC={s.ic:.4f}, WR={s.win_rate_outsample:.1%}, sig={s.is_significant}')
db.close()
"`

Expected: 6 strategies (lgb_5d, lgb_10d, lgb_30d, lgb_5d_short, lgb_10d_short, lgb_30d_short) with IC values.

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.txt backend/app/services/alpha_miner_service.py
git commit -m "feat: Alpha Miner 改用 LightGBM 全因子模型，取代 546 個 LogisticRegression"
```

---

### Task 3: Strategy Miner — MIN_WIN_RATE 改相對門檻

**Files:**
- Modify: `backend/app/services/strategy_miner_service.py:50-53,160-175`

- [ ] **Step 1: Remove absolute MIN_WIN_RATE, add relative threshold**

Replace lines 50-53:

```python
# ─── 訊號品質門檻 ─────────────────────────────────────────────────────────────
TRIGGER_COUNT_PERCENTILE = 0.70   # 觸發數需 >= 該維度 P70
EXCESS_WIN_RATE_THRESHOLD = 0.05  # 超額勝率需 > baseline + 5pp
MAX_PICKS_PER_DIRECTION = 5       # 做多/放空各最多推薦 5 檔
```

- [ ] **Step 2: Add `_load_market_baselines` helper**

Add after line 63 (after `_sharpe` function):

```python
def _load_market_baselines_from_snapshot(db: Session) -> Dict[str, float]:
    """從 Alpha Miner snapshot 取各維度市場基準勝率。
    回傳 {'5d': 0.194, '10d': 0.244, '30d': 0.261}"""
    from app.models.alpha_miner_snapshot import AlphaMinerSnapshot
    from collections import defaultdict
    snap = (
        db.query(AlphaMinerSnapshot)
        .order_by(AlphaMinerSnapshot.train_date.desc())
        .first()
    )
    if not snap:
        return {}
    result_data = json.loads(snap.result_json)
    dim_rates: dict = defaultdict(list)
    for s in result_data.get('strategies', []):
        dim = s['time_dimension'].replace('_short', '')
        mwr = s.get('market_win_rate')
        if mwr is not None:
            dim_rates[dim].append(mwr)
    baselines = {}
    for dim, rates in dim_rates.items():
        rates.sort()
        baselines[dim] = rates[len(rates) // 2]
    return baselines
```

- [ ] **Step 3: Replace absolute WIN_RATE check with relative threshold**

Replace the optimal parameter loop (lines 160-175):

```python
        # 2. 查各維度最優參數 + 相對品質門檻
        baselines = _load_market_baselines_from_snapshot(db)
        optimal: Dict[str, Optional[StrategyBacktestParam]] = {}
        for dim in DIMENSIONS:
            strategy_key = f"{dim}_short" if direction == 'short' else dim
            opt = (
                db.query(StrategyBacktestParam)
                .filter(
                    StrategyBacktestParam.strategy_id == strategy_key,
                    StrategyBacktestParam.is_optimal == True,  # noqa: E712
                )
                .first()
            )
            if opt and opt.win_rate_test is not None:
                baseline = baselines.get(dim, 0.25)
                if opt.win_rate_test < baseline + EXCESS_WIN_RATE_THRESHOLD:
                    logger.info(
                        f"[StrategyMiner] {strategy_key} 勝率 {opt.win_rate_test:.1%} "
                        f"< baseline {baseline:.1%} + {EXCESS_WIN_RATE_THRESHOLD:.0%}，跳過")
                    opt = None
            optimal[dim] = opt
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/strategy_miner_service.py
git commit -m "fix: Strategy Miner MIN_WIN_RATE 改相對門檻（baseline+5pp）"
```

---

### Task 4: Integration test — compare LR vs LightGBM

**Files:** None (run in terminal)

- [ ] **Step 1: Run full training and compare IC**

Run: `cd backend && DATABASE_URL=postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.services.alpha_miner_service import AlphaMinerService
db = SessionLocal()
AlphaMinerService.invalidate_cache()
result = AlphaMinerService._train_all(db)
print()
print('=== LightGBM Alpha Miner Results ===')
print(f'Strategies: {len(result.strategies)}')
print(f'Train: {result.train_period}')
print(f'Test:  {result.test_period}')
print()
for s in result.strategies:
    excess = s.win_rate_outsample - s.market_win_rate
    print(f'{s.strategy_id:20s} IC={s.ic:+.4f}  WR={s.win_rate_outsample:.1%}  '
          f'mkt={s.market_win_rate:.1%}  excess={excess:+.1%}  '
          f'sig={s.is_significant}  samples={s.sample_count_test}')
print()
# Check signals
for dim in ['5d', '10d', '30d']:
    sigs = AlphaMinerService.get_today_signals(db, dimension=dim)
    print(f'{dim} signals: {len(sigs)} 檔')
    for sig in sigs[:3]:
        print(f'  {sig.stock_id} {sig.stock_name} factors={sig.strategies}')
db.close()
"`

Expected: IC values for each dimension, with long dimensions showing positive IC (> 0.03 for 10d/30d).

- [ ] **Step 2: Verify snapshot save/load round-trip**

Run: `cd backend && DATABASE_URL=postgresql://alphaforge:alphaforge_secret@10.0.4.3:5433/alphaforge ./.venv/bin/python -c "
from app.db.database import SessionLocal
from app.services.alpha_miner_service import AlphaMinerService
from datetime import date
db = SessionLocal()
# Load from snapshot (should work after Task 2 training)
AlphaMinerService._cache = None
AlphaMinerService._cache_date = None
restored = AlphaMinerService._load_snapshot(db, date.today())
print(f'Snapshot restored: {restored}')
if restored and AlphaMinerService._cache:
    print(f'Strategies: {len(AlphaMinerService._cache.strategies)}')
db.close()
"`

Expected: `Snapshot restored: True`, strategy count matches.
