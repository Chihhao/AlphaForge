# AlphaForge 學習日誌 - Day 13b
**日期**：2026-03-15（下午場）
**主題**：Phase 5A 多時間維度 + 效能危機排查 + multiprocessing 架構重構

---

## 學習重點 (The "Why")

### 1. 「魔法數字」vs 「收斂條件」

把 `max_iter=500` 降到 `max_iter=100` 來加速訓練，被使用者指出這是 **magic number**。

正確做法：讓模型自己決定何時停，用 **`tol`（收斂門檻）** 控制，`max_iter` 只當安全帽：

```python
# 錯誤：硬設 100 次就停，不管有沒有收斂
LogisticRegression(max_iter=100)

# 正確：梯度範數 < 0.001 就停，最多 500 次
LogisticRegression(tol=1e-3, max_iter=500)
```

為什麼用 `tol=1e-3` 而不是預設的 `1e-4`？因為金融資料天生高噪音，精度到 0.0001 對預測結果毫無意義，`1e-3` 讓它更早停下來又不影響品質。

---

### 2. CPU 密集任務不能跑在 `threading.Thread` 裡

Phase 5A 加入多時間維度後，訓練模型數從 63 → 189（× 3 維度），首次重訓跑了超過 **2 小時**都沒完成，且整個 HTTP 伺服器完全沒有回應。

**根本原因**：Python 的 GIL（Global Interpreter Lock）。

```
threading.Thread（錯誤架構）
  主程序 (uvicorn HTTP server)
    └── 背景執行緒（訓練）← 搶 GIL
        ↑ CPU 密集：numpy/sklearn 在 C 層頻繁重新獲取 GIL
  → HTTP 請求排隊等 GIL，全部 timeout
```

```
multiprocessing.Process（正確架構）
  主程序 (uvicorn HTTP server) ← 擁有自己的 GIL，HTTP 永遠回應
  訓練子程序 ← 完全獨立的 Python 解釋器，不跟主程序競爭
```

**教訓**：I/O 密集（等網路、等硬碟）→ `threading` 沒問題。CPU 密集（numpy、sklearn）→ 一定要用 `multiprocessing`。

---

### 3. 進度跨 Process 傳遞：用檔案，不用共享記憶體

子程序更新 `cls._progress` dict，主程序讀不到（各自有獨立記憶體空間）。

最簡單的解法：**JSON 檔案作為跨 process 通訊橋梁**。

```
訓練子程序 → 每個模型寫完 → /tmp/alpha_miner_progress.json
主程序     → GET /training-progress → 讀 JSON 檔案 → 秒回
```

不用 `multiprocessing.Manager().dict()`（有 proxy overhead），也不用 Redis（過度設計），檔案讀寫夠快、夠簡單。

---

### 4. 三個效能問題，三個層次的解法

| 問題 | 層次 | 解法 |
|---|---|---|
| 資料載入 21 秒 | I/O | ORM `.all()` → `pd.read_sql()`（直接 SQL，省去 Python 物件建構） |
| 日期比較每次逐列 | 算法 | `.dt.date` Python 物件 → `pd.Timestamp()` 向量化比較 |
| 時間衰減 `.apply()` | 算法 | Python 函數逐列 → 向量化 `(1 - delta * 0.2).clip(0.2)` |
| GIL 搶佔 | 架構 | `threading.Thread` → `multiprocessing.Process` |

其中架構問題最根本，算法問題加速但沒根治。

---

### 5. `pd.read_sql` 需要搭配 `db.bind`

SQLAlchemy Session 的 `session.bind` 可以直接傳給 `pd.read_sql`，不需要另外建 engine 連線。但 raw SQL 要注意 SQL injection（這裡 cutoff 是程式生成的日期字串，不是使用者輸入，安全）。

---

## 開發成果

### Phase 5A：多時間維度訓練（今天才真正完成）

**之前的 Phase 5A（Day 13）**：只修改了勝率門檻（>0% → >3%）和新增比較欄位，持有期仍然只有 10 日。

**今天的 Phase 5A（真正的多時間維度）**：

| 持有期 | 訓練 label 門檻 | 報告第二門檻 |
|---|---|---|
| 5日  | > 3% | > 5% |
| 10日 | > 3% | > 5% |
| 30日 | > 5% | > 10% |

- `strategy_id` 格式改為 `{dim}_{factors}`（e.g. `10d_rsi14_vol_ratio`）
- Bonferroni 校正各維度獨立（N=63，不跨維度）
- 前端新增持有期 Tab 切換（預設 10d）
- 表格新增第二門檻勝率欄，括號顯示市場基準

**Schema 新增欄位**：
```python
time_dimension: str           # "5d" | "10d" | "30d"
threshold_low: float          # 訓練 label 用的低門檻
threshold_high: float         # 報告用的高門檻
win_rate_outsample_hi: float  # Top20% 中 > threshold_high 的比例
market_win_rate_hi: float     # 全市場 > threshold_high 的比例
```

### 架構修正：`multiprocessing.Process`

**新增模組級函數**：
```python
def _run_training_subprocess() -> None:
    # 訓練子程序進入點（multiprocessing 需要 module-level function）
    db = SessionLocal()
    AlphaMinerService._train_all(db)
```

**進度檔案工具**：
```python
_PROGRESS_FILE = '/tmp/alpha_miner_progress.json'
def _write_progress(data: dict) -> None: ...
def _read_progress() -> dict: ...
```

**`get_progress()` 改為讀檔案**：
```python
def get_progress(cls) -> dict:
    is_training = cls._process is not None and cls._process.is_alive()
    p = _read_progress()
    p['is_training'] = is_training
    return p
```

**子程序完成偵測**（在 `get_strategies` 裡）：
```python
if cls._process is not None and not cls._process.is_alive():
    cls._process.join()
    cls._process = None
    cls._load_snapshot(db, today)  # 從 DB 快照恢復結果
```

### 排程：17:10 自動重訓

`scheduler.py` 新增第五梯次：
```
17:05 特徵計算完成（FeatureService.compute_daily）
17:10 Alpha Miner 重訓（invalidate_cache + 啟動子程序）← 新增
```

---

## 今日訓練結果（Phase 5A 多維度，2026-03-15）

**資料範圍**：2024-03 ~ 2026-03（2 年）
**模型數**：189 組（63 × 3 維度）
**顯著策略數**：161 / 189

**Top 5（依 IC 降序）**：

| # | 維度 | 策略 | IC | 勝率>5% | 勝率>10% | 市場基準>5% |
|---|---|---|---|---|---|---|
| 1 | **30d** | 投信5日累積 | **0.1331** | 31.4% | 20.4% | 26.4% |
| 2 | **30d** | 自營商5日累積 + 投信5日累積 | 0.1327 | 31.4% | 20.4% | 26.4% |
| 3 | **30d** | 乖離率20 + 量比 + 營收YoY | 0.1061 | 38.2% | 27.3% | 26.4% |
| 4 | **30d** | 營收YoY | 0.1055 | 37.6% | 26.6% | 26.4% |
| 5 | **30d** | KD-K + 營收YoY | 0.1052 | 37.9% | 26.9% | 26.4% |

**觀察**：
- 30日維度 IC 整體高於 5d/10d——基本面因子（營收YoY、殖利率）在中線表現最強，符合預期
- 投信5日累積在三個維度均顯著，且 30d IC 從 Phase 4B 的 0.0892 提升至 **0.1331**
- `營收YoY + 股淨比` 30d 勝率高達 **42.4% vs 26.4%** 市場基準，賠率比可觀

---

## 遇到的問題與解法

### 訓練 2 小時仍未完成，HTTP 完全無回應
- **診斷**：ORM 載入 1.4M 列 × Python 物件 → 資料量問題；threading 搶 GIL → 架構問題
- **解法**：資料窗口縮短至 2 年（1.4M→930K）+ `pd.read_sql` + multiprocessing.Process
- **結果**：訓練約 8 分鐘完成，HTTP 全程響應

### `thr_lo` 在賦值前被引用（UnboundLocalError）
- **原因**：`thr_lo = dim['threshold_low']` 寫在函數中段，但 `win_rate_insample` 早在前段就用到 `thr_lo`
- **解法**：把 `thr_lo`, `thr_hi` 賦值移到 `_train_one` 函數最前面

### 進度 `total=0` 卡住不動
- **原因**：progress 在子程序更新 class variable，主程序讀不到（不同記憶體空間）
- **解法**：改用 `/tmp/alpha_miner_progress.json` 跨 process 傳遞

---

## 接下來的方向

- 部署到 NAS（架構修改幅度大，需測試）
- Phase 6 規劃：考慮加入外資持股比例變化因子、產業相對強度

---

## 今日心得

> 「今天遇到的問題不是功能問題，而是架構問題。Thread 和 Process 的區別在入門教材裡看起來很無聊，但真正讓 HTTP 伺服器凍結 20 分鐘之後，才深刻理解為什麼 CPU 密集任務不能用 threading。
>
> 更有趣的是排查過程：從『跑太久』→ 發現是 ORM 載入慢 → 改 read_sql → 仍然慢 → 發現是 GIL → 改 multiprocessing → HTTP 立刻回應。每一步都是一個獨立的問題，但堆在一起看起來像同一個症狀。
>
> `tol=1e-3` 比 `max_iter=100` 更正確，不是因為它更快，而是因為它有明確的語意：『當模型停止進步時就停』，而不是『數到 100 就停』。這種思考方式——用有意義的條件取代魔法數字——適用於所有工程決策。」
