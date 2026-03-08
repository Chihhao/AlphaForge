# 台股綜合分析器 - API 串接說明文件

> 本文來源：https://hackmd.io/SfcWlHm_SzucAv_LdqNVjw
> 版本：v1.0  
> 更新日期：2024-02-24  
> 檔案：taiwan-stock-analyzer.html

---

## 📊 平台串接總覽

本程式共串接 **12 個平台**，包含 3 個官方 API、2 個第三方 API、2 個代理服務、5 個外部連結整合。

---

## 1️⃣ 台灣證券交易所 (TWSE)

**網域：** `twse.com.tw` / `mis.twse.com.tw`

### API 端點列表

| 功能 | API 端點 | 方法 | 用途 |
|------|---------|------|------|
| 個股日成交 | `/exchangeReport/STOCK_DAY` | GET | 上市股票歷史 K 線數據（開高低收量） |
| 大盤指數 | `/rwd/zh/afterTrading/MI_INDEX` | GET | 加權指數、成交量、漲跌家數 |
| 三大法人 | `/rwd/zh/fund/T86` | GET | 上市股票法人買賣超數據 |
| 融資融券 | `/rwd/zh/marginTrading/MI_MARGN` | GET | 上市股票信用交易數據 |
| 即時報價 | `mis.twse.com.tw/stock/api/getStockInfo.jsp` | GET | 盤中即時股價、五檔報價 |

### 請求範例

```javascript
// 個股日成交資料
const url = `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=${dateStr}&stockNo=${stockCode}`;

// 即時報價
const url = `https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_${code}.tw&json=1&delay=0&_=${Date.now()}`;

// 三大法人買賣超
const url = `https://www.twse.com.tw/rwd/zh/fund/T86?date=${dateStr}&selectType=ALLBUT0999&response=json`;
```

### 回傳資料格式

```json
// 個股日成交
{
  "stat": "OK",
  "title": "111年02月 2330 台積電 各日成交資訊",
  "data": [
    ["111/02/07", "47,270,577", "27,280,839,858", "580.00", "583.00", "575.00", "580.00", "+5.00", "33,023"]
    // [日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數]
  ]
}
```

---

## 2️⃣ 櫃買中心 (TPEx)

**網域：** `tpex.org.tw`

### API 端點列表

| 功能 | API 端點 | 方法 | 用途 |
|------|---------|------|------|
| 個股日成交 | `/web/stock/aftertrading/daily_trading_info/st43_result.php` | GET | 上櫃股票歷史 K 線數據 |
| 每日收盤行情 | `/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php` | GET | 上櫃全部股票收盤資料 |
| 三大法人 | `/web/stock/3insti/daily_trade/3itrade_hedge_result.php` | GET | 上櫃股票法人買賣超 |
| 融資融券 | `/web/stock/margin_trading/margin_balance/margin_bal_result.php` | GET | 上櫃股票信用交易 |
| 櫃買指數 | `/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php` | GET | OTC 指數行情 |

### 請求範例

```javascript
// 個股日成交（上櫃）
const url = `https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php?l=zh-tw&d=${dateStr}&stkno=${stockCode}`;

// 三大法人（上櫃）
const url = `https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d=${dateStr}&s=0,asc`;
```

### 注意事項

- 日期格式為民國年：`112/02/24`
- 需透過 CORS Proxy 存取

---

## 3️⃣ Yahoo Finance

**網域：** `query1.finance.yahoo.com` / `tw.stock.yahoo.com`

### API 端點列表

| 功能 | API 端點 | 用途 |
|------|---------|------|
| 歷史股價 | `/v8/finance/chart/{symbol}` | 歷史 K 線數據（備援來源） |
| 即時報價 | `/v8/finance/chart/{symbol}?interval=1m&range=1d` | 盤中即時股價 |
| 當日走勢 | `tw.stock.yahoo.com/_td-stock/api/resource/FinanceChartService.ApacLibraCharts` | 分鐘級別走勢圖 |

### 請求範例

```javascript
// 歷史股價
const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?period1=${startTimestamp}&period2=${endTimestamp}&interval=1d`;

// 即時走勢（分鐘）
const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1m&range=1d&_=${Date.now()}`;
```

### 股票代號格式

| 市場 | 格式 | 範例 |
|------|------|------|
| 上市 | `{代號}.TW` | `2330.TW` |
| 上櫃 | `{代號}.TWO` | `6510.TWO` |

---

## 4️⃣ FinMind

**網域：** `api.finmindtrade.com`

### API 端點

| 功能 | 端點 | 用途 |
|------|------|------|
| 歷史股價 | `/api/v4/data?dataset=TaiwanStockPrice` | 第三備援數據來源 |

### 請求範例

```javascript
const url = `https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=${stockCode}&start_date=${startStr}&end_date=${endStr}`;
```

### 注意事項

- 免費版有請求次數限制
- 建議作為最後備援使用

---

## 5️⃣ 公開資訊觀測站 (MOPS)

**網域：** `mops.twse.com.tw`

### API 端點

| 功能 | 端點 | 用途 |
|------|------|------|
| 公司公告 | `/mops/web/ajax_t05st01` | 重大訊息、財報公告 |

### 請求範例

```javascript
const url = `https://mops.twse.com.tw/mops/web/ajax_t05st01?encodeURIComponent=1&step=1&firstin=1&off=1&keyword4=${code}&code1=&TYPEK2=&checkbtn=1&queryName=co_id&TYPEK=all&co_id=${code}`;
```

---

## 6️⃣ CORS Proxy 服務

由於瀏覽器安全限制，部分 API 需透過代理服務存取。

### 使用的代理服務

| 服務 | 網址 | 用途 |
|------|------|------|
| AllOrigins | `https://api.allorigins.win/raw?url=` | 主要代理 |
| CodeTabs | `https://api.codetabs.com/v1/proxy?quest=` | 備用代理 |

### 使用方式

```javascript
const proxyUrls = [
    'https://api.allorigins.win/raw?url=',
    'https://api.codetabs.com/v1/proxy?quest='
];

const response = await fetch(proxyUrls[0] + encodeURIComponent(targetUrl));
```

---

## 🔗 外部連結整合

以下平台提供快速跳轉連結，非 API 串接：

### 7️⃣ Goodinfo 台灣股市資訊網

**網域：** `goodinfo.tw`

| 功能 | 連結格式 |
|------|---------|
| 個股詳情 | `https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID=${code}` |
| 營收圖表 | `https://goodinfo.tw/tw/ShowSaleMonChart.asp?STOCK_ID=${code}` |
| 股利政策 | `https://goodinfo.tw/tw/StockDividendPolicy.asp?STOCK_ID=${code}` |
| 買賣超 | `https://goodinfo.tw/tw/ShowBuySaleChart.asp?STOCK_ID=${code}` |
| 經營績效 | `https://goodinfo.tw/tw/StockBzPerformance.asp?STOCK_ID=${code}` |

### 8️⃣ 鉅亨網 (CNYes)

**網域：** `cnyes.com`

| 功能 | 連結格式 |
|------|---------|
| 個股資訊 | `https://www.cnyes.com/twstock/${code}` |
| 技術分析 | `https://www.cnyes.com/twstock/${code}/technical` |
| 新聞搜尋 | `https://www.cnyes.com/search/news?keyword=${code}` |
| 營收數據 | `https://www.cnyes.com/twstock/${code}/revenue` |

### 9️⃣ 嗨投資 HiStock

**網域：** `histock.tw`

| 功能 | 連結格式 |
|------|---------|
| 每月營收 | `https://histock.tw/stock/${code}/%E6%AF%8F%E6%9C%88%E7%87%9F%E6%94%B6` |

### 🔟 玩股網 WantGoo

**網域：** `wantgoo.com`

| 功能 | 連結格式 |
|------|---------|
| 個股資訊 | `https://www.wantgoo.com/stock/${code}` |

### 1️⃣1️⃣ MoneyDJ 理財網

**網域：** `moneydj.com`

| 功能 | 連結格式 |
|------|---------|
| K 線圖表 | `https://www.moneydj.com/kline/klinechart.djhtm?a=${code}` |

### 1️⃣2️⃣ Yahoo 股市（台灣）

**網域：** `tw.stock.yahoo.com`

| 功能 | 連結格式 |
|------|---------|
| 個股頁面 | `https://tw.stock.yahoo.com/quote/${code}.TW` |
| 新聞 | `https://tw.stock.yahoo.com/quote/${code}.TW/news` |
| 法人進出 | `https://tw.stock.yahoo.com/quote/${code}.TW/institutional-trading` |
| 營收 | `https://tw.stock.yahoo.com/quote/${code}.TW/revenue` |

---

## 📈 數據流程圖

```
┌─────────────────────────────────────────────────────────────┐
│                      台股綜合分析器                           │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   上市股票     │    │   上櫃股票     │    │   即時數據     │
│    (TWSE)     │    │    (TPEx)     │    │              │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ • 歷史 K 線    │    │ • 歷史 K 線    │    │ • 盤中報價     │
│ • 三大法人     │    │ • 三大法人     │    │ • 五檔掛單     │
│ • 融資融券     │    │ • 融資融券     │    │ • 大盤指數     │
│ • 大盤指數     │    │ • 櫃買指數     │    │              │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └──────────┬──────────┘                     │
                   ▼                                │
           ┌───────────────┐                        │
           │  Yahoo Finance │◄───────────────────────┘
           │   (備援來源)    │
           └───────────────┘
                   │
                   ▼
           ┌───────────────┐
           │    FinMind    │
           │  (第三備援)    │
           └───────────────┘
```

---

## 🎯 各平台使用時機

| 情境 | 主要來源 | 備援來源 |
|------|---------|---------|
| 上市股票歷史數據 | TWSE | Yahoo → FinMind |
| 上櫃股票歷史數據 | TPEx | Yahoo → FinMind |
| 即時報價 | TWSE (mis) | Yahoo Finance |
| 三大法人（上市）| TWSE | - |
| 三大法人（上櫃）| TPEx | - |
| 大盤指數 | TWSE (mis) | Yahoo Finance |
| 公司公告 | MOPS | - |

---

## ✅ 平台統計

| 類型 | 數量 | 平台 |
|------|------|------|
| **官方 API** | 3 | TWSE、TPEx、MOPS |
| **第三方 API** | 2 | Yahoo Finance、FinMind |
| **代理服務** | 2 | AllOrigins、CodeTabs |
| **外部連結** | 5 | Goodinfo、鉅亨、HiStock、玩股網、MoneyDJ |
| **總計** | **12** | - |

---

## 🔧 技術備註

### CORS 問題處理

1. **mis.twse.com.tw** - 支援 CORS，可直接請求
2. **www.twse.com.tw** - 需透過 Proxy
3. **tpex.org.tw** - 需透過 Proxy
4. **Yahoo Finance** - 部分端點支援 CORS

### 錯誤處理機制

```javascript
async function fetchWithFallback(primaryUrl, fallbackUrl) {
    try {
        const response = await fetch(primaryUrl);
        if (!response.ok) throw new Error('Primary failed');
        return await response.json();
    } catch (error) {
        console.log('Trying fallback...');
        const response = await fetch(fallbackUrl);
        return await response.json();
    }
}
```

### 市場自動偵測

當選定市場查無資料時，系統會自動嘗試另一個市場：

```
上市查無資料 → 自動嘗試上櫃
上櫃查無資料 → 自動嘗試上市
```

---

## 📝 更新日誌

| 日期 | 版本 | 更新內容 |
|------|------|---------|
| 2024-02-24 | v57 |  |

---

## 📄 授權聲明

本文件僅供學習研究用途，各 API 之使用須遵守原平台之服務條款。

- 台灣證券交易所：https://www.twse.com.tw
- 櫃買中心：https://www.tpex.org.tw
- Yahoo Finance：https://finance.yahoo.com
- FinMind：https://finmindtrade.com
