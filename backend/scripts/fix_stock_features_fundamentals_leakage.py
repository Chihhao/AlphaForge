"""第二階段 fix: 修 stock_features 的 roe / revenue_yoy / rev_surprise / rev_accel
用 historical 值取代既有 latest snapshot。

資料來源:
- stock_revenue_history (年/月) → revenue_yoy / rev_surprise / rev_accel
- stock_eps_history (年/季) + stock_valuation_daily.pb_ratio + close → roe

公告日近似:
- 月營收: 該月結束 + 10 天 (e.g. 2026-04 → 2026-05-10)
- 季報 EPS: 季結束 + 45 天 (e.g. 2025-Q1 → 2025-05-15)

對 pick_date d, 找該 stock 「publish_date <= d」的最新一筆。

ROE derivation (避免缺 historical book value):
    roe ≈ TTM_EPS / book_value_per_share
    book_value_per_share = close / pb_ratio  (已有 historical)
    → roe ≈ TTM_EPS × pb_ratio / close × 100  (轉 % 對齊既有單位)

只動 4 欄位, 不動 pb_ratio / yield_rate (第一階段已修)。

Usage (從 backend/ 目錄):
    ./.venv/bin/python -m scripts.fix_stock_features_fundamentals_leakage
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


def _load_db_url() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise RuntimeError("DATABASE_URL not in backend/.env")


def main() -> int:
    db_url = _load_db_url()
    engine = create_engine(db_url, pool_pre_ping=True)

    print("==== 第二階段 fundamentals leakage fix ====")
    print("動的欄位: revenue_yoy / rev_surprise / rev_accel / roe")
    print()

    with engine.connect() as conn:
        # 1. 拉 stock_features (近 1 年, 對應 stock_valuation_daily 範圍)
        print("[1/5] load stock_features ...")
        sf = pd.read_sql(text("""
            SELECT id, stock_id, date, close, pb_ratio
            FROM stock_features
            WHERE date >= '2025-05-15' AND date <= '2026-05-14'
        """), conn)
        sf["date"] = pd.to_datetime(sf["date"])
        print(f"  loaded {len(sf)} rows")

        # 2. 拉月營收
        print("[2/5] load stock_revenue_history ...")
        rev = pd.read_sql(text("""
            SELECT stock_id, year, month, revenue, revenue_yoy
            FROM stock_revenue_history
            WHERE revenue > 0
        """), conn)
        print(f"  loaded {len(rev)} rows")

        # 3. 拉季 EPS
        print("[3/5] load stock_eps_history ...")
        eps = pd.read_sql(text("""
            SELECT stock_id, year, quarter, eps
            FROM stock_eps_history
            WHERE eps IS NOT NULL
        """), conn)
        print(f"  loaded {len(eps)} rows")

    # --- 月營收 publish_date (該月底 + 10 天) ---
    rev["month_end"] = pd.to_datetime(
        rev[["year", "month"]].assign(day=1)
    ) + pd.offsets.MonthEnd(0)
    rev["publish_date"] = rev["month_end"] + pd.Timedelta(days=10)

    # 計算 historical rev_surprise (該月營收 vs 前 3 月均) + rev_accel (本月 yoy - 上月 yoy)
    rev = rev.sort_values(["stock_id", "year", "month"]).reset_index(drop=True)
    rev["prev3_mean"] = (
        rev.groupby("stock_id")["revenue"]
        .transform(lambda x: x.shift(1).rolling(3, min_periods=3).mean())
    )
    rev["rev_surprise_hist"] = (rev["revenue"] - rev["prev3_mean"]) / rev["prev3_mean"] * 100
    rev["prev_yoy"] = rev.groupby("stock_id")["revenue_yoy"].shift(1)
    rev["rev_accel_hist"] = rev["revenue_yoy"] - rev["prev_yoy"]
    rev = rev.sort_values(["stock_id", "publish_date"]).reset_index(drop=True)
    rev_lookup = rev[["stock_id", "publish_date", "revenue_yoy", "rev_surprise_hist", "rev_accel_hist"]].rename(
        columns={"revenue_yoy": "revenue_yoy_hist"}
    )

    # --- 季報 publish_date (該季底 + 45 天) ---
    quarter_end_map = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    def _qpub(row):
        m, d = quarter_end_map[int(row["quarter"])]
        return pd.Timestamp(int(row["year"]), m, d) + pd.Timedelta(days=45)
    eps["publish_date"] = eps.apply(_qpub, axis=1)
    eps = eps.sort_values(["stock_id", "publish_date"]).reset_index(drop=True)
    # TTM_EPS = 過去 4 季 EPS 累計
    eps["ttm_eps"] = (
        eps.groupby("stock_id")["eps"]
        .transform(lambda x: x.rolling(4, min_periods=4).sum())
    )
    eps_lookup = eps[["stock_id", "publish_date", "ttm_eps"]]

    # --- 對 stock_features 用 merge_asof 拿 historical ---
    print("[4/5] merge_asof historical ...")
    # merge_asof 要求 left 按 on column (date) 全局 sorted; right 也是 (publish_date)
    sf = sf.sort_values("date").reset_index(drop=True)
    rev_lookup = rev_lookup.sort_values("publish_date").reset_index(drop=True)
    eps_lookup = eps_lookup.sort_values("publish_date").reset_index(drop=True)

    sf = pd.merge_asof(
        sf, rev_lookup,
        left_on="date", right_on="publish_date",
        by="stock_id", direction="backward",
    )
    sf = sf.rename(columns={"publish_date": "_rev_pub"})

    sf = pd.merge_asof(
        sf, eps_lookup,
        left_on="date", right_on="publish_date",
        by="stock_id", direction="backward",
    )
    sf = sf.rename(columns={"publish_date": "_eps_pub"})

    # ROE = TTM_EPS × pb_ratio / close × 100 (對齊既有單位 %)
    sf["roe_hist"] = sf["ttm_eps"] * sf["pb_ratio"] / sf["close"] * 100
    # close = 0 或 pb = NaN 都會自然 NaN, 不需 special handle

    # --- UPDATE stock_features ---
    print("[5/5] UPDATE stock_features (revenue_yoy / rev_surprise / rev_accel / roe) ...")

    # 將 NaN 換成 None 給 SQL
    update_df = sf[["id", "revenue_yoy_hist", "rev_surprise_hist", "rev_accel_hist", "roe_hist"]].copy()
    update_df = update_df.astype(object).where(pd.notna(update_df), None)

    with engine.begin() as conn:
        # 先看修改前 sample
        before = conn.execute(text("""
            SELECT date, revenue_yoy, rev_surprise, rev_accel, roe
            FROM stock_features
            WHERE stock_id = '2330' AND date IN ('2025-06-02', '2025-09-01', '2026-01-02', '2026-05-13')
            ORDER BY date
        """)).fetchall()
        print("BEFORE 2330 sample:")
        for row in before:
            print(f"  {row.date}: revyoy={row.revenue_yoy}, rev_surp={row.rev_surprise}, rev_accel={row.rev_accel}, roe={row.roe}")

        # batch UPDATE: 用 temp values
        # 簡化: 一個 row 一個 UPDATE (336k rows 可能慢, 但 transaction inside, 一次 commit)
        total = len(update_df)
        rows_iter = update_df.itertuples(index=False)
        batch_size = 5000
        batch = []
        done = 0
        for r in rows_iter:
            batch.append({
                "id": r.id,
                "revenue_yoy": r.revenue_yoy_hist,
                "rev_surprise": r.rev_surprise_hist,
                "rev_accel": r.rev_accel_hist,
                "roe": r.roe_hist,
            })
            if len(batch) >= batch_size:
                conn.execute(text("""
                    UPDATE stock_features SET
                      revenue_yoy = :revenue_yoy,
                      rev_surprise = :rev_surprise,
                      rev_accel = :rev_accel,
                      roe = :roe
                    WHERE id = :id
                """), batch)
                done += len(batch)
                if done % 50000 == 0:
                    print(f"  {done}/{total} rows updated ...")
                batch = []
        if batch:
            conn.execute(text("""
                UPDATE stock_features SET
                  revenue_yoy = :revenue_yoy,
                  rev_surprise = :rev_surprise,
                  rev_accel = :rev_accel,
                  roe = :roe
                WHERE id = :id
            """), batch)
            done += len(batch)
        print(f"  total {done} rows updated")

        after = conn.execute(text("""
            SELECT date, revenue_yoy, rev_surprise, rev_accel, roe
            FROM stock_features
            WHERE stock_id = '2330' AND date IN ('2025-06-02', '2025-09-01', '2026-01-02', '2026-05-13')
            ORDER BY date
        """)).fetchall()
        print("AFTER 2330 sample:")
        for row in after:
            print(f"  {row.date}: revyoy={row.revenue_yoy}, rev_surp={row.rev_surprise}, rev_accel={row.rev_accel}, roe={row.roe}")

        r2 = conn.execute(text("""
            SELECT stock_id,
                   COUNT(DISTINCT revenue_yoy) AS revyoy_distinct,
                   COUNT(DISTINCT rev_surprise) AS surp_distinct,
                   COUNT(DISTINCT roe) AS roe_distinct,
                   COUNT(*) AS rows
            FROM stock_features
            WHERE stock_id IN ('2330', '2317', '2454')
              AND date BETWEEN '2025-05-15' AND '2026-05-14'
            GROUP BY stock_id
        """)).fetchall()
        print("distinct values (應該都 > 1):")
        for row in r2:
            print(f"  {row.stock_id}: revyoy_distinct={row.revyoy_distinct}, surp_distinct={row.surp_distinct}, roe_distinct={row.roe_distinct}, rows={row.rows}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
