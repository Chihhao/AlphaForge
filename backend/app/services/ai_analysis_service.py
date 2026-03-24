"""個股 AI 分析服務：以 (stock_id, date) 快取，同日多人查詢只打一次 Groq API"""

import httpx
from datetime import date, timedelta
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.config import settings
from app.models.stock_ai_analysis import StockAIAnalysis
from app.models.stock_price import StockPrice
from app.models.stock_feature import StockFeature
from app.models.stock_fundamental import StockFundamental

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
HISTORY_DAYS = 10


def _fetch_history(db: Session, stock_id: str) -> list[dict]:
    """從 stock_features 取最近 HISTORY_DAYS 筆（含今日）"""
    rows = (
        db.query(StockFeature)
        .filter(StockFeature.stock_id == stock_id)
        .order_by(StockFeature.date.desc())
        .limit(HISTORY_DAYS)
        .all()
    )
    return list(reversed(rows))  # 由舊到新


def _fetch_fundamental(db: Session, stock_id: str):
    return (
        db.query(StockFundamental)
        .filter(StockFundamental.stock_id == stock_id)
        .order_by(StockFundamental.updated_at.desc())
        .first()
    )


def _build_prompt(stock_id: str, stock_name: str, history: list, fundamental) -> str:
    # 優先從 fundamental 取真實股名
    display_name = stock_name if stock_name != stock_id else stock_id

    # 歷史走勢表
    rows = []
    for f in history:
        rows.append(
            f"  {f.date}  收盤:{f.close:.1f}  漲跌:{f.change_pct:+.2f}%"
            f"  量比:{f.vol_ratio:.2f}"
            f"  RSI:{f.rsi14:.1f}  KD({f.k:.0f}/{f.d:.0f})"
            f"  BB%B:{f.bb_pctb:.2f}"
            f"  MA排列:{'多頭' if f.ma_trend == 1 else '非多頭'}"
        )
    history_text = "\n".join(rows) if rows else "（無歷史資料）"

    # 最新一筆
    latest = history[-1] if history else None
    macd_desc = "（無資料）"
    if latest:
        macd_desc = f"DIF {latest.macd_dif:.3f} / DEA {latest.macd_dea:.3f}，柱狀{'翻正' if latest.macd_osc > 0 else '翻負'}"

    # 基本面
    fund_text = "（無基本面資料）"
    if fundamental:
        parts = []
        if fundamental.pe_ratio:
            parts.append(f"本益比 {fundamental.pe_ratio:.1f}")
        if fundamental.roe_latest:
            parts.append(f"ROE {fundamental.roe_latest:.1f}%")
        if fundamental.yield_rate:
            parts.append(f"殖利率 {fundamental.yield_rate:.1f}%")
        if fundamental.pb_ratio:
            parts.append(f"淨值比 {fundamental.pb_ratio:.2f}")
        fund_text = "　".join(parts) if parts else fund_text

    return f"""你是台股分析助理。請用**繁體中文**輸出 **Markdown 格式**，文字要白話易懂，直接從數據說話，禁止使用「新手」「保持客觀」「盲目跟風」「情緒化」等套話。

**股票：{display_name}（{stock_id}）**

**近 {HISTORY_DAYS} 日走勢：**
```
{history_text}
```
**MACD：** {macd_desc}
**基本面：** {fund_text}

---

請依以下三個標題輸出，每個標題下用條列式（- ）說明，每點一句話，直接引用數字：

### 📈 近期走勢
- 從收盤價、漲跌幅、量比的變化，說明最近發生了什麼事

### 🔍 指標解讀
- 說明 RSI 數值代表什麼（例：RSI 68，熱度偏高但尚未超買）
- 說明 KD 狀態（例：K 值 72 站上 D 值，短線動能偏強）
- 說明布林位置（BB%B）代表價格在通道的哪個位置
- 說明 MACD 是翻正還是翻負

### 💡 值得注意
- 從數據中點出 1–2 個具體觀察，例如量比異常、指標背離、均線狀態等

---

### 📊 看漲分數

根據以上數據給出 0–100 整數分數。評分標準如下，請嚴格遵守，**大多數股票應落在 40–65 之間**：

| 分數區間 | 代表意義 | 常見條件 |
|---|---|---|
| 80–100 | 強烈看漲 | MA多頭排列 + RSI 50–70 + 量比持續放大 + MACD翻正 + BB%B上升 |
| 65–79 | 偏多 | 多數指標偏多，但有1–2項疑慮 |
| 40–64 | 中性 | 多空指標混雜，無明確方向 |
| 20–39 | 偏空 | RSI 下行 + 量縮 + 均線空頭或纏繞 |
| 0–19 | 強烈看跌 | 多項指標同時惡化，如RSI<30 + 跌破MA + 量比萎縮 |

**重要：若無明確多頭訊號，請勿給出 70 以上的分數。**

格式固定如下（不得更改格式）：

**分數：XX／100** — 理由說明"""


def get_or_create_analysis(
    db: Session,
    stock_id: str,
    stock_name: str,
    today: str,
    force_refresh: bool = False,
) -> dict:
    """
    主入口：回傳今日分析。有快取直接回傳，否則呼叫 Groq 並存入 DB。
    today: YYYY-MM-DD 字串
    """
    if not force_refresh:
        cached = (
            db.query(StockAIAnalysis)
            .filter(StockAIAnalysis.stock_id == stock_id, StockAIAnalysis.date == today)
            .first()
        )
        if cached:
            return {
                "analysis": cached.analysis_text,
                "model": cached.model,
                "cached_at": cached.created_at.strftime("%Y-%m-%d %H:%M"),
                "from_cache": True,
            }

    api_key = getattr(settings, "GROQ_API_KEY", None)
    if not api_key:
        raise ValueError("GROQ_API_KEY 未設定，請在 backend/.env 加入")

    history = _fetch_history(db, stock_id)
    fundamental = _fetch_fundamental(db, stock_id)
    # 優先用 DB 裡的真實股名
    real_name = (fundamental.stock_name if fundamental and fundamental.stock_name else stock_name)
    prompt = _build_prompt(stock_id, real_name, history, fundamental)

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.5,
            },
        )

    if resp.status_code != 200:
        err = resp.json().get("error", {}).get("message", f"HTTP {resp.status_code}")
        raise RuntimeError(f"Groq API 錯誤：{err}")

    text = resp.json()["choices"][0]["message"]["content"].strip()

    # upsert（SQLite 相容：先查後寫）
    existing = (
        db.query(StockAIAnalysis)
        .filter(StockAIAnalysis.stock_id == stock_id, StockAIAnalysis.date == today)
        .first()
    )
    if existing:
        existing.analysis_text = text
        existing.model = GROQ_MODEL
        existing.created_at = datetime.utcnow()
    else:
        db.add(StockAIAnalysis(
            stock_id=stock_id,
            date=today,
            analysis_text=text,
            model=GROQ_MODEL,
        ))
    db.commit()

    return {
        "analysis": text,
        "model": GROQ_MODEL,
        "cached_at": None,
        "from_cache": False,
    }
