# 幕牆圖紙結構分析系統

Curtain Wall Drawing Structure Analyzer — 從 DWG 加工圖中提取文字、建立位置圖與加工圖對應關係。

## 功能

- **DWG 文字直接提取** — 使用 libredwg 從 AutoCAD DWG 檔提取所有文字（MTEXT、ATTRIB），100% 準確，不需 OCR
- **位置圖 ↔ 加工圖對照** — 自動識別位置圖（TG）與加工圖（ACD），建立雙向對應關係
- **反向查詢** — 輸入加工圖號 → 找出對應的位置圖，附尺寸、數量、顏色
- **SQLite 資料庫** — 持久化儲存所有圖紙文字與對應關係，支援直接 SQL 查詢
- **Web UI** — FastAPI 後端 + 原生 HTML/CSS/JS 前端，雙分頁設計
- **macOS 原生資料夾選擇器** — 一鍵選取圖紙資料夾初始化

## 快速開始

```bash
git clone https://github.com/andyau98/curtain-wall-analyzer.git
cd curtain-wall-analyzer

# 安裝依賴
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# 安裝 libredwg（DWg 文字提取必要）
brew install autoconf automake libtool pkg-config
cd /tmp
curl -sLO https://github.com/LibreDWG/libredwg/releases/download/0.13.4/libredwg-0.13.4.tar.xz
tar xf libredwg-0.13.4.tar.xz && cd libredwg-0.13.4
./configure --disable-bindings && make -j4
```

## 使用方式

### Web UI

```bash
./run.sh
# 打開 http://localhost:8765
# Tab 1: 圖紙分析 — 上傳 PDF/PNG 用規則引擎分析
# Tab 2: DWG 資料庫 — 初始化資料夾、查詢加工圖、找位置圖
```

### CLI

```bash
source venv/bin/activate

# 初始化資料庫（從 DWG 資料夾建立索引）
python dwg_db.py init "圖紙目錄路徑"

# 輸入加工圖號 → 找對應位置圖
python dwg_db.py find "ACB-ACD-0064"

# 顯示位置圖 → 加工圖完整對照表
python dwg_db.py layout

# 查詢單張圖的詳細資訊
python dwg_db.py query "ACB-ACD-0064"

# 檢查缺檔
python dwg_db.py missing

# 匯出 JSON
python dwg_db.py export -o results.json
```

## 架構

```
curtain-wall-analyzer/
├── backend/
│   ├── app.py                      # FastAPI 後端（含 DB API）
│   ├── analyzer/                   # OpenCV 規則引擎
│   │   ├── structure_analyzer.py   # 主分析管線（7 步驟）
│   │   ├── drawing_parser.py       # PDF/圖片載入與預處理
│   │   ├── grid_detector.py        # 軸線網格偵測
│   │   ├── panel_detector.py       # 面板輪廓與分類
│   │   ├── dimension_parser.py     # 尺寸標註與加工符號
│   │   └── section_mark_detector.py # OCR 圖號偵測
│   └── ai_explainer/               # Claude API 選擇性 AI 講解
├── frontend/
│   ├── index.html                  # 雙分頁 UI
│   ├── js/app.js                   # Tab 1: 圖紙分析 + Tab 2: DWG 資料庫
│   └── css/style.css
├── dwg_db.py                       # CLI 工具（DWG → SQLite → 查詢）
├── batch_scan.py                   # 傳統 PDF 批次掃描
└── run.sh                          # 一鍵啟動
```

## 為什麼用 DWG 不用 PDF

| | DWG | PDF |
|---|---|---|
| 文字提取方式 | 直接讀取向量文字 | OCR（Tesseract） |
| 準確度 | **100%** | 40-70% |
| 位置圖（CAD 線條圖） | 完美提取全部文字 | 幾乎無法讀取 |
| 依賴 | libredwg（開源） | Tesseract + pdf2image |

## SQLite 資料庫結構

由 `dwg_db.py init` 建立 `dwg_index.db`，包含：

| 資料表 | 內容 |
|--------|------|
| `projects` | 專案資訊 |
| `drawings` | 圖紙 metadata（圖號、類型、尺寸、數量、顏色） |
| `text_entities` | 每張圖的所有文字實體 |
| `drawing_refs` | 圖紙之間的引用關係 |

```sql
-- 找出所有引用 ACB-ACD-0064 的圖紙
SELECT d.filename FROM drawings d
JOIN drawing_refs r ON d.id = r.source_id
WHERE r.target_drawing_number = 'ACB-ACD-0064';
```

## API 端點

| 端點 | 功能 |
|------|------|
| `GET /api/db/projects` | 列出所有資料庫 |
| `GET /api/db/status` | 資料庫狀態 |
| `POST /api/db/init?folder_path=` | 初始化資料夾 |
| `GET /api/db/pick-folder` | macOS 原生資料夾選擇器 |
| `GET /api/db/layout` | 位置圖 → 加工圖對照 |
| `GET /api/db/find-layout?dn=` | 加工圖號 → 找位置圖 |
| `GET /api/db/drawings?search=` | 搜尋圖紙 |
| `GET /api/db/drawings/{圖號}` | 圖紙細節（含文字內容） |
| `GET /api/db/missing` | 檢查缺檔 |
| `GET /api/db/fab-to-layout` | 全部加工圖 → 位置圖對照表 |

## License

MIT
