# AlphaForge 專案開發規則

這些規則定義了 AlphaForge 專案的技術標準、架構與開發流程，AI 應始終遵循。

## 🛠 技術棧 (Technology Stack)

### 前端 (Frontend)
- **框架**: Next.js (TypeScript), Tailwind CSS.
- **重要**: 前端路徑有 `basePath` 設定，存取網址必須包含 `/alphaforge`。
- **啟動指令**: `INTERNAL_API_URL=http://localhost:8000 npm run dev`
- **最佳實踐**: 強烈建議在**獨立終端機**視窗中保持執行 `npm run dev`，這能確保最穩定的 HMR (熱更新) 且避免背景程序衝突。
- **清理指令**: 若遇到 404 異常重整，請執行 `npm run clean` 後再重啟。

### 後端 (Backend)
- **框架**: FastAPI / Python 3.11+
- **啟動指令**: `./.venv/bin/python main.py`
- **預設網址**: `http://localhost:8000`
- **數據向量化**: 涉及到技術指標（如 KD, MACD）計算時，應優先使用 Pandas/Numpy 的向量化運算而非循環。

## 📂 專案結構與路徑 (Agentic Context)

- **核心指令與規則**: `/.agent/rules.md` (即此文件)
- **擴充技能庫**: `/.agent/skills/`
- **前端目錄**: `/frontend`
- **後端目錄**: `/backend`
- **NAS 部署目錄**: `/volume1/homes/chihhaolai/Drive/Documents_Mac_Lai/GitHub/AlphaForge`

## 💡 核心開發原則 (Design System)

### 1. 知識庫與提示元件 (Glossary & EducationalHint)
為了保持 `glossary.json` 的整潔，我們在系統內定義了專屬的 Markdown 微語法。這些語法會在前端的 `EducationalHint` 元件中自動轉換，提供具有強烈**金融情緒色彩**的視覺回饋。

| 語法 | 意義 / 情境 | 渲染樣式 | 範例 |
| :--- | :--- | :--- | :--- |
| `**關鍵字**` | 中性的名詞強調、公式變量、重要狀態。 | **亮金色粗體** (`text-gold-400 font-bold`) | `**大成交量**` |
| `++正向字++` | 多頭、買進訊號、利多消息、強勢狀態。 | **翠綠色粗體** (`text-emerald-400 font-bold`) | `++黃金交叉++` |
| `--負向字--` | 空頭、賣出訊號、利空消息、弱勢與風險。 | **玫瑰紅粗體** (`text-rose-400 font-bold`) | `--死亡交叉--` |

### 2. UI 設計原則
- **一體化深色主題**：遵循深色玻璃擬態 (Glassmorphism) 主題，背景以 `bg-gray-800` 或 `zinc-900` 為主。
- **顏色語意嚴謹制**：金色代表提示與重點，綠色僅限用於正向報酬/看多訊號，紅色僅限用於負向報酬/看空訊號。
- **學習型工具**: 保持「白話文」風格，將複雜數據轉化為易懂的教育提示。

## 🚀 遠端部署 (Synology NAS)
關於 NAS 部署流程、環境變數與 `@eaDir` 問題排除，請參考專屬技能：
👉 `/.agent/skills/docker-nas-ops-helper/SKILL.md`

## 🐛 常見除錯與測試經驗 (Debugging & Testing)

1. **Next.js 404 無限重整 (Missing required error components)**:
   - **原因**: 當背景同時執行 `npm run dev` (熱更新) 與 `npm run build` 時，Next.js 的 `.next` 快取資料夾會發生衝突。
   - **解法**: 
     ```bash
     cd frontend
     killall -9 node
     rm -rf .next
     npm run dev &
     ```
