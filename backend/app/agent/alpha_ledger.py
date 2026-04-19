from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict
import httpx


@dataclass
class LedgerEntry:
    dimension: str          # "5d" | "10d" | "20d"
    n: int
    wr: float               # win rate (return_pct > 0)
    avg_return: float       # 平均 return_pct (percentage, 2.5 = +2.5%)


def summarise(days: int = 7,
              base_url: str = "http://localhost:8000",
              timeout: float = 5.0) -> Dict[str, LedgerEntry]:
    """Fetch concluded picks via HTTP endpoint, aggregate by time_dimension.

    Endpoint 回傳最多 60 日內已結案 picks。days 參數用 pick_date 再 cutoff 一次。
    """
    url = f"{base_url.rstrip('/')}/strategy-miner/picks/concluded"
    resp = httpx.get(url, params={"limit": 200, "offset": 0}, timeout=timeout)
    resp.raise_for_status()
    items = resp.json().get("items", [])

    cutoff = date.today() - timedelta(days=days)
    by_dim: Dict[str, list] = defaultdict(list)
    for it in items:
        pd = date.fromisoformat(it["pick_date"])
        if pd < cutoff:
            continue
        dim = it.get("time_dimension") or "10d"
        ret = it.get("return_pct")
        if ret is None:
            continue
        by_dim[dim].append(ret)

    out: Dict[str, LedgerEntry] = {}
    for dim, returns in by_dim.items():
        n = len(returns)
        wins = sum(1 for r in returns if r > 0)
        out[dim] = LedgerEntry(
            dimension=dim, n=n,
            wr=(wins / n) if n else 0.0,
            avg_return=(sum(returns) / n) if n else 0.0,
        )
    return out
