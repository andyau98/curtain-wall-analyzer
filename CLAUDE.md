# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

```bash
# Start the dev server (auto-creates venv, installs deps, starts on :8765)
./run.sh

# DWG 加工圖資料庫工具 (從 DWG 提取文字，建立 SQLite)
./venv/bin/python dwg_db.py init "圖紙目錄路徑"          # 建立/重建資料庫
./venv/bin/python dwg_db.py layout [目錄]                # 顯示位置圖→加工圖對照表
./venv/bin/python dwg_db.py query <圖號> [目錄]          # 查詢指定加工圖詳細資訊
./venv/bin/python dwg_db.py missing [目錄]               # 檢查位置圖引用但缺檔的圖號
./venv/bin/python dwg_db.py export [目錄] -o out.json    # 匯出完整 JSON

# 傳統 PDF 批次掃描 (使用 OpenCV 視覺分析)
./venv/bin/python batch_scan.py /path/to/drawings/

# Install backend dependencies
./venv/bin/pip install -r backend/requirements.txt
```

## 加工圖 ↔ 位置圖 對應方法

此為處理幕牆鋁板加工圖的標準工作流程。

### 核心原理

- **位置圖** (Layout/Setting-out Drawing，檔名通常含 "TG") 是總覽圖紙，列出所有加工圖的編號、尺寸 (W×H)、顏色和數量
- **加工圖** (Fabrication/Shop Drawing，檔名通常含 "ACD") 是每塊鋁板的詳細加工尺寸
- 位置圖中列出的圖號應與資料夾中的 DWG 檔案一一對應

### 為什麼用 DWG 不用 PDF

DWG 是 AutoCAD 原生向量格式，文字以 TEXT/MTEXT/ATTRIB 實體儲存，可直接 100% 精確提取。PDF 是渲染後的像素，OCR 準確度僅 40-70%，且 CAD 線條太細導致總圖幾乎無法讀取。

### 步驟

1. **安裝 libredwg** (一次性):
   ```bash
   brew install autoconf automake libtool pkg-config
   cd /tmp && curl -sLO https://github.com/LibreDWG/libredwg/releases/download/0.13.4/libredwg-0.13.4.tar.xz
   tar xf libredwg-0.13.4.tar.xz && cd libredwg-0.13.4
   ./configure --disable-bindings && make -j4
   ```
   工具安裝在 `/tmp/libredwg-0.13.4/programs/.libs/dwgread`

2. **建立資料庫**: `./venv/bin/python dwg_db.py init "圖紙目錄"`
   - 對每個 DWG 執行 `dwgread -O JSON` 提取所有文字
   - 自動識別位置圖 vs 加工圖 (位置圖引用 ≥5 個其他圖號)
   - 從位置圖中解析每張加工圖的 W×H×數量×顏色
   - 存入 SQLite (`dwg_index.db`)

3. **驗證對應**: `./venv/bin/python dwg_db.py layout` 顯示完整對照表
   - 若位置圖引用但缺檔案，會在 init 時顯示警告
   - 外部引用 (如 GK-NE-0002) 表示其他批次的圖紙

### DWG 文字提取技術細節

使用 libredwg 的 `dwgread -O JSON` 輸出 DWG 完整結構，再解析三種文字載體：
- **MTEXT** (type 44): 多行文字，`text` 欄位含格式化標籤如 `{\fSimSun|...}`，需正則清除
- **INSERT** (type 7): 圖塊引用，文字儲存在 `attribs` 指向的 ATTRIB 子實體中
- **ATTRIB/ATTDEF** (type 33/34): 屬性定義與值，獨立文字實體

## Architecture

**FastAPI backend** (port 8765) serving a vanilla HTML/JS/CSS frontend. The core is a rules-based computer vision pipeline — no AI required for analysis. AI explanation is an optional add-on via Claude API.

### Analysis pipeline (`backend/analyzer/structure_analyzer.py:65-103`)

The `StructureAnalyzer.analyze()` method runs a 7-step pipeline on each uploaded drawing:

1. **`DrawingParser`** — loads PDF/PNG/JPG/TIFF, produces `gray` and adaptive-threshold `binary` arrays per page
2. **Drawing type classifier** — uses morphological line ratios to distinguish position (layout), fabrication (shop), detail, and assembly drawings
3. **`GridDetector`** — morphological opening + HoughLinesP to find horizontal/vertical axis lines; clusters, labels (A/B/C... bottom-up, 1/2/3... left-right), finds intersections
4. **`PanelDetector`** — finds quadrilateral contours within grid cells; classifies each as vision/spandrel/operable/louver/structural based on aspect ratio and fill density
5. **`DimensionParser`** — HoughLinesP for dimension lines, MSER for text regions, HoughCircles + contour analysis for fabrication marks (weld triangles, drill circles)
6. **`SectionMarkDetector`** — MSER + HoughCircles + contours to find text regions, then regex classifies OCR results into drawing numbers (`ACB-ACD-0060`), part numbers, section cuts (`A-A`), material marks (`AL-6063`)
7. **Summary generation** — aggregates all results into a `DrawingStructure` dataclass, serialized to JSON for the frontend

### Data types

All analysis results flow through `@dataclass` containers defined in each module:
- `DrawingStructure` → `GridSystem` / `PanelLayout` / `DrawingAnnotations` / `SectionMarkReport`
- Numpy values are sanitized to native Python via `_sanitize()` in `app.py` before JSON serialization

### API endpoints (`backend/app.py`)

| Endpoint | Purpose |
|---|---|
| `POST /api/analyze` | Upload + rules-based analysis (no AI) |
| `POST /api/analyze-and-explain?use_ai=true` | Analysis + optional Claude AI explanation |
| `GET /api/explain/{file_id}` | Re-run AI explanation on a previously uploaded file |
| `GET /api/drawing-types` | Returns metadata about the 4 recognized drawing types |

### Frontend

Vanilla JS SPA (`frontend/js/app.js`): drag-and-drop upload, toggles between rules-only and AI-assisted analysis, renders grid tables, panel distribution bars, annotation tables, and section mark lists into card sections.

### Key dependencies

- `opencv-python-headless` — all image processing and CV algorithms
- `pytesseract` — OCR for section marks (optional; detection still runs without it)
- `pdf2image` — PDF → numpy array conversion
- `anthropic` — Claude API for optional AI explanations
- `fastapi` + `uvicorn` — web server

## Design notes

- The system is designed to work fully offline without AI — the Claude API integration is purely for generating human-readable explanations and is gated behind the `use_ai` toggle
- Tesseract is optional; `SectionMarkDetector._check_tesseract()` gates OCR calls, and the detector falls back to position-only results when Tesseract is unavailable
- All processing uses CPU-bound OpenCV operations; no GPU acceleration
- The `dpi` parameter on `DrawingParser` and `StructureAnalyzer` controls PDF rasterization resolution (defaults to 300, lowered to 200 for batch scanning)

### SQLite 資料庫結構 (`dwg_index.db`)

由 `dwg_db.py init` 建立，包含四張表：
- **projects** — 專案資訊 (project_code, folder_path)
- **drawings** — 每張圖紙的 metadata (drawing_number, drawing_type, width_mm, height_mm, quantity, color, material)
- **text_entities** — 從 DWG 提取的每一條文字 (text_content, entity_type)
- **drawing_refs** — 圖紙之間的引用關係 (source → target_drawing_number)

可直接用 SQLite 查詢，例如：
```sql
-- 找出所有引用 ACB-ACD-0064 的圖紙
SELECT d.filename FROM drawings d
JOIN drawing_refs r ON d.id = r.source_id
WHERE r.target_drawing_number = 'ACB-ACD-0064';

-- 找出尺寸大於 2000mm 的加工圖
SELECT drawing_number, width_mm, height_mm FROM drawings
WHERE drawing_type = 'fabrication' AND height_mm > 2000;
```
