"""
幕牆圖紙分析系統 — FastAPI 後端。
提供兩個核心端點:
  - /analyze    規則引擎自動分析 (不需 AI)
  - /explain    AI 講解 (可選，需 API key)
"""

import os
import json
import uuid
import shutil
import numpy as np
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from analyzer.structure_analyzer import StructureAnalyzer
from ai_explainer import AIExplainer


# ---- Numpy → native Python conversion ----
def _sanitize(obj):
    """Recursively convert numpy types to native Python so json.dumps can handle them."""
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return [_sanitize(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {_sanitize(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(x) for x in obj]
    return obj


class NumpyJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            _sanitize(content),
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


# Use our encoder as default
app = FastAPI(
    title="幕牆圖紙結構分析系統",
    version="1.0.0",
    default_response_class=NumpyJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

analyzer = StructureAnalyzer(dpi=300)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "curtain-wall-analyzer"}


@app.post("/api/analyze")
async def analyze_drawing(file: UploadFile = File(...)):
    """
    上傳幕牆圖紙，規則引擎自動分析結構。
    支援 PDF / PNG / JPG / TIFF。
    不需 AI，完全本機運算。
    """
    # 儲存上傳檔案
    ext = Path(file.filename).suffix.lower()
    if ext not in {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'}:
        return NumpyJSONResponse(
            status_code=400,
            content={"error": f"不支援的格式: {ext}，請上傳 PDF/PNG/JPG/TIFF"}
        )

    file_id = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 執行分析
    try:
        result = analyzer.analyze(str(save_path))
        return NumpyJSONResponse(content={
            "file_id": file_id,
            "filename": file.filename,
            "analysis": result.to_dict(),
        })
    except Exception as e:
        return NumpyJSONResponse(
            status_code=500,
            content={"error": f"分析失敗: {str(e)}"}
        )


@app.post("/api/analyze-and-explain")
async def analyze_and_explain(
    file: UploadFile = File(...),
    use_ai: bool = Query(False, description="是否使用 AI 講解"),
):
    """
    分析 + 可選 AI 講解。
    use_ai=true 時需設定環境變數 ANTHROPIC_API_KEY。
    """
    ext = Path(file.filename).suffix.lower()
    file_id = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"{file_id}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        result = analyzer.analyze(str(save_path))
        response_data = {
            "file_id": file_id,
            "filename": file.filename,
            "analysis": result.to_dict(),
        }

        if use_ai:
            try:
                explainer = AIExplainer()
                explanation = explainer.explain_drawing_structure(result.to_dict())
                response_data["ai_explanation"] = explanation
            except Exception as e:
                response_data["ai_explanation"] = f"AI 講解失敗: {e}"

        return NumpyJSONResponse(content=response_data)
    except Exception as e:
        return NumpyJSONResponse(
            status_code=500,
            content={"error": f"分析失敗: {str(e)}"}
        )


@app.get("/api/explain/{file_id}")
async def explain_result(file_id: str):
    """
    對已分析結果進行 AI 講解 (適用於已有分析結果的情境)。
    """
    # 尋找上傳檔案
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        return NumpyJSONResponse(status_code=404, content={"error": "找不到該檔案"})

    try:
        result = analyzer.analyze(str(matches[0]))
        explainer = AIExplainer()
        explanation = explainer.explain_drawing_structure(result.to_dict())
        return NumpyJSONResponse(content={
            "file_id": file_id,
            "explanation": explanation,
        })
    except Exception as e:
        return NumpyJSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/drawing-types")
def get_drawing_types():
    """返回系統可識別的圖紙類型與其結構說明。"""
    return {
        "drawing_types": {
            "position": {
                "name_zh": "位置圖 (Setting-out / Layout Drawing)",
                "description": "顯示幕牆單元在建築立面上的位置、軸網、面板編號及整體尺寸",
                "key_elements": ["軸線網格", "面板佈局", "立面尺寸", "面板編號", "基準線標註"],
                "typical_scale": "1:100 ~ 1:200",
            },
            "fabrication": {
                "name_zh": "加工圖 (Fabrication / Shop Drawing)",
                "description": "個別面板或構件的詳細加工尺寸、材料、表面處理及組裝要求",
                "key_elements": ["加工尺寸", "公差標註", "焊接符號", "切割線", "鑽孔位置", "材料標記", "表面處理"],
                "typical_scale": "1:1 ~ 1:20",
            },
            "detail": {
                "name_zh": "大樣圖 (Detail Drawing)",
                "description": "局部節點的放大細節，顯示連接方式、密封系統、防水設計",
                "key_elements": ["節點構造", "螺絲/錨栓", "密封膠", "防水設計", "伸縮縫"],
                "typical_scale": "1:1 ~ 1:10",
            },
            "assembly": {
                "name_zh": "組裝圖 (Assembly Drawing)",
                "description": "顯示多個構件的組裝關係與安裝順序",
                "key_elements": ["組裝軸測圖", "零件編號", "安裝順序", "連接細節"],
                "typical_scale": "1:5 ~ 1:50",
            },
        }
    }


# ===================================================================
# DWG 資料庫 API — 多資料庫支援、資料夾初始化、查詢
# ===================================================================
import sqlite3
import subprocess as _sp
import threading as _th

DB_FILENAME = "dwg_index.db"

# ---- libredwg 工具路徑 ----
_DWGREAD = "/tmp/libredwg-0.13.4/programs/.libs/dwgread"
_DWGREAD_LIB = "/tmp/libredwg-0.13.4/src/.libs"

# ---- Schema (與 dwg_db.py 保持一致) ----
_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_code TEXT, requisition_no TEXT, folder_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS drawings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, filename TEXT NOT NULL, file_path TEXT,
    drawing_number TEXT,
    drawing_type TEXT CHECK(drawing_type IN ('fabrication','layout','unknown')),
    width_mm REAL, height_mm REAL, quantity INTEGER DEFAULT 1,
    material TEXT, color TEXT, has_sub_parts INTEGER DEFAULT 0, sub_part_list TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE TABLE IF NOT EXISTS text_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drawing_id INTEGER, text_content TEXT NOT NULL, entity_type TEXT,
    FOREIGN KEY (drawing_id) REFERENCES drawings(id)
);
CREATE TABLE IF NOT EXISTS drawing_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER, target_drawing_number TEXT,
    FOREIGN KEY (source_id) REFERENCES drawings(id)
);
CREATE INDEX IF NOT EXISTS idx_drawings_number ON drawings(drawing_number);
CREATE INDEX IF NOT EXISTS idx_drawings_type ON drawings(drawing_type);
CREATE INDEX IF NOT EXISTS idx_text_drawing ON text_entities(drawing_id);
CREATE INDEX IF NOT EXISTS idx_refs_source ON drawing_refs(source_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON drawing_refs(target_drawing_number);
"""


def _find_all_dbs() -> list[dict]:
    """搜尋所有 dwg_index.db，回傳 [{db_path, project_code, folder_path}, ...]."""
    dbs = []
    search_roots = [
        Path(__file__).parent.parent,        # curtain-wall-analyzer/
        Path(__file__).parent.parent.parent,  # ~/Desktop/Claude Code/
    ]
    seen = set()
    for root in search_roots:
        if not root.exists():
            continue
        for db_file in root.rglob(DB_FILENAME):
            # 限制深度避免搜太久
            try:
                rel = db_file.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > 4:
                continue
            if str(db_file) in seen:
                continue
            seen.add(str(db_file))
            try:
                c = sqlite3.connect(str(db_file))
                c.row_factory = sqlite3.Row
                proj = c.execute("SELECT project_code, folder_path FROM projects ORDER BY id DESC LIMIT 1").fetchone()
                fab_n = c.execute("SELECT COUNT(*) as n FROM drawings WHERE drawing_type='fabrication'").fetchone()["n"]
                lay_n = c.execute("SELECT COUNT(*) as n FROM drawings WHERE drawing_type='layout'").fetchone()["n"]
                c.close()
                dbs.append({
                    "db_path": str(db_file),
                    "project_code": proj["project_code"] if proj else db_file.parent.name,
                    "folder_path": proj["folder_path"] if proj else str(db_file.parent),
                    "fab_count": fab_n,
                    "layout_count": lay_n,
                })
            except Exception:
                pass
    return dbs


def _resolve_db(db_param: str | None = None) -> tuple:
    """根據 db 參數解析要使用的資料庫。回傳 (conn, db_path) 或 (None, None)。"""
    all_dbs = _find_all_dbs()
    if not all_dbs:
        return None, None

    target = None
    if db_param:
        for d in all_dbs:
            if db_param in d["db_path"] or db_param == d["project_code"]:
                target = d["db_path"]
                break
    if not target:
        target = all_dbs[0]["db_path"]

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn, target


# ---- 初始化 (從 DWG 資料夾建立資料庫) ----
import re as _re

_RE_DN = _re.compile(r'^([A-Z]{2,4}-[A-Z]{2,4}(?:-[A-Z]{3,4})?-\d{4})(-\d{2})?$')
_RE_LAYOUT = _re.compile(r'TG-|位置|LAYOUT|SETTING', _re.IGNORECASE)


def _dwg_extract_text(dwg_path: str) -> list[dict]:
    """從單一 DWG 提取所有文字。"""
    env = os.environ.copy()
    env["DYLD_LIBRARY_PATH"] = _DWGREAD_LIB
    r = _sp.run([_DWGREAD, "-O", "JSON", str(dwg_path)],
                capture_output=True, timeout=60, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"dwgread failed: {r.stderr.decode('utf-8','replace')[:200]}")
    # DWG 文字可能含非 UTF-8 字元 (Big5 中文、CAD 特殊符號)，用 replace 處理
    raw = r.stdout.decode("utf-8", errors="replace")
    data = json.loads(raw)
    objects = data.get("OBJECTS", [])

    handle_map = {}
    for obj in objects:
        h = obj.get("handle")
        if h:
            handle_map[tuple(h)] = obj

    results = []
    for obj in objects:
        entity = obj.get("entity", "")
        dwg_type = obj.get("type")
        if entity == "MTEXT" or dwg_type == 44:
            text = obj.get("text", "")
            if text:
                clean = _re.sub(r'\{[^}]*\}', '', text)
                clean = clean.replace('\\P', '\n')
                clean = _re.sub(r'\\[A-Za-z][^;]*;', '', clean)
                if clean.strip():
                    results.append({"text": clean.strip(), "entity": "MTEXT"})
        elif entity == "INSERT" and obj.get("has_attribs"):
            for ah in obj.get("attribs", []):
                attr = handle_map.get(tuple(ah))
                if attr:
                    text = attr.get("text", attr.get("text_value", ""))
                    if text and str(text).strip():
                        results.append({"text": str(text).strip(), "entity": "ATTRIB"})
        elif entity in ("ATTRIB", "ATTDEF") or dwg_type in (33, 34):
            text = obj.get("text", obj.get("text_value", ""))
            if text and str(text).strip():
                results.append({"text": str(text).strip(), "entity": entity})
    return results


def _build_db_from_folder(folder_path: str, db_path: str) -> dict:
    """從 DWG 資料夾建立 SQLite 資料庫。回傳摘要 dict。"""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"資料夾不存在: {folder_path}")
    dwg_files = sorted(folder.glob("*.dwg"))
    if not dwg_files:
        raise ValueError(f"資料夾中沒有 DWG 檔案: {folder_path}")

    # 清除舊 DB
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.executescript(_DB_SCHEMA)

    # Project
    folder_name = folder.name
    proj_match = _re.search(r'(HGRH-\w+-\w+)', folder_name)
    proj_code = proj_match.group(1) if proj_match else folder_name
    conn.execute("INSERT INTO projects (project_code, folder_path) VALUES (?, ?)",
                 [proj_code, str(folder)])
    project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 先收集所有圖紙的文字
    drawings_data = {}
    for dwg_path in dwg_files:
        name = dwg_path.stem
        entries = _dwg_extract_text(str(dwg_path))
        texts = [e["text"] for e in entries]

        # 類型判定
        joined = " ".join(texts)
        refs_in_text = set()
        for t in texts:
            m = _RE_DN.match(t.strip())
            if m:
                refs_in_text.add(m.group(1))
        dtype = "layout" if len(refs_in_text) >= 5 else "fabrication"

        # 自身圖號 (優先取檔名)
        primary_dn = None
        m = _RE_DN.match(name)
        if m:
            primary_dn = m.group(1)
        elif refs_in_text:
            primary_dn = sorted(refs_in_text)[0]

        drawings_data[name] = {
            "path": str(dwg_path), "type": dtype, "primary_dn": primary_dn,
            "own_numbers": sorted(refs_in_text),
            "references": sorted(refs_in_text), "texts": texts, "entries": entries,
        }

    # 找出位置圖 (引用最多的)
    layout_name = None
    for name, info in drawings_data.items():
        if info["type"] == "layout":
            if layout_name is None or len(info["references"]) > len(drawings_data[layout_name]["references"]):
                layout_name = name

    # 從位置圖提取每張加工圖的尺寸
    dim_map = {}
    if layout_name:
        layout_texts = drawings_data[layout_name]["texts"]
        seen = set()
        for i, t in enumerate(layout_texts):
            t = t.strip()
            m = _RE_DN.match(t)
            if not m:
                continue
            dn = m.group(1)
            if dn not in drawings_data:
                continue
            is_first = dn not in seen
            seen.add(dn)
            if is_first and i + 2 < len(layout_texts):
                w_raw = layout_texts[i+1].strip()
                h_raw = layout_texts[i+2].strip()
                try:
                    w = float(w_raw) if w_raw.replace('.', '').replace('-', '').isdigit() else None
                except ValueError:
                    w = None
                try:
                    h = float(h_raw) if h_raw.replace('.', '').replace('-', '').isdigit() else None
                except ValueError:
                    h = None
                color = layout_texts[i+3].strip() if i+3 < len(layout_texts) and "Pantone" in layout_texts[i+3] else None
                qty = sum(1 for x in layout_texts if x.strip() == dn or x.strip().startswith(dn + '-'))
                dim_map[dn] = {"width_mm": w, "height_mm": h, "color": color, "quantity": qty}

    # 寫入圖紙
    for name in sorted(drawings_data):
        info = drawings_data[name]
        dims = dim_map.get(info["primary_dn"], {})
        conn.execute("""
            INSERT INTO drawings (project_id, filename, file_path, drawing_number,
                drawing_type, width_mm, height_mm, quantity, material, color)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [project_id, name + ".dwg", info["path"], info.get("primary_dn"),
              info["type"], dims.get("width_mm"), dims.get("height_mm"),
              dims.get("quantity", 1), None, dims.get("color")])
        drawing_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for entry in info["entries"]:
            conn.execute("INSERT INTO text_entities (drawing_id, text_content, entity_type) VALUES (?, ?, ?)",
                         [drawing_id, entry["text"], entry["entity"]])
        for ref in info["references"]:
            conn.execute("INSERT INTO drawing_refs (source_id, target_drawing_number) VALUES (?, ?)",
                         [drawing_id, ref])

    conn.commit()
    fab_count = sum(1 for i in drawings_data.values() if i["type"] == "fabrication")
    layout_count = sum(1 for i in drawings_data.values() if i["type"] == "layout")
    conn.close()

    return {
        "project_code": proj_code, "folder_path": str(folder), "db_path": db_path,
        "fab_count": fab_count, "layout_count": layout_count,
        "total_dwgs": len(dwg_files),
    }


_init_status = {}  # {folder_path: {"status": "running"|"done"|"error", "result": ..., "error": ...}}


def _init_worker(folder_path: str, db_path: str, task_key: str):
    try:
        result = _build_db_from_folder(folder_path, db_path)
        _init_status[task_key] = {"status": "done", "result": result}
    except Exception as e:
        _init_status[task_key] = {"status": "error", "error": str(e)}


@app.get("/api/db/pick-folder")
def db_pick_folder():
    """打開 macOS 原生資料夾選擇器，回傳選擇的路徑。"""
    script = '''
    tell application "Finder"
        activate
        set folderPath to choose folder with prompt "選擇包含 DWG 圖紙的資料夾:"
        set posixPath to POSIX path of folderPath
        return posixPath
    end tell
    '''
    try:
        r = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return JSONResponse(status_code=500, content={"error": f"無法開啟選擇器: {r.stderr.strip()}"})
        path = r.stdout.strip()
        if not path:
            return JSONResponse(status_code=400, content={"error": "未選擇資料夾"})
        return {"folder_path": path}
    except _sp.TimeoutExpired:
        return JSONResponse(status_code=500, content={"error": "選擇器逾時"})


@app.post("/api/db/init")
def db_init(folder_path: str = Query(..., description="DWG 圖紙資料夾的絕對路徑")):
    """對指定資料夾初始化 DWG 資料庫（背景執行）。"""
    if not os.path.isdir(folder_path):
        return JSONResponse(status_code=400, content={"error": f"資料夾不存在: {folder_path}"})
    if not os.path.exists(_DWGREAD):
        return JSONResponse(status_code=500, content={"error": "伺服器上找不到 dwgread 工具"})

    db_path = str(Path(folder_path) / DB_FILENAME)
    task_key = folder_path

    if task_key in _init_status and _init_status[task_key]["status"] == "running":
        return {"status": "running", "message": "此資料夾正在初始化中..."}

    _init_status[task_key] = {"status": "running"}
    _th.Thread(target=_init_worker, args=(folder_path, db_path, task_key), daemon=True).start()
    return {"status": "running", "message": f"開始初始化: {folder_path}", "db_path": db_path}


@app.get("/api/db/init-status")
def db_init_status(folder_path: str = Query(..., description="資料夾路徑")):
    """查詢初始化進度。"""
    s = _init_status.get(folder_path)
    if not s:
        return {"status": "unknown", "message": "無此初始化任務"}
    return s


# ---- 多資料庫查詢 ----
@app.get("/api/db/projects")
def db_projects():
    """列出所有可用的資料庫。"""
    dbs = _find_all_dbs()
    return {"projects": dbs, "count": len(dbs)}


@app.get("/api/db/status")
def db_status(db: str = Query("", description="資料庫路徑或專案代號 (可省略，自動選第一個)")):
    """檢查 DWG 資料庫狀態。"""
    conn, db_path = _resolve_db(db if db else None)
    if conn is None:
        return {"exists": False, "message": "找不到任何 dwg_index.db，請先初始化資料夾"}

    project = conn.execute("SELECT * FROM projects ORDER BY id DESC LIMIT 1").fetchone()
    fab_count = conn.execute("SELECT COUNT(*) as n FROM drawings WHERE drawing_type='fabrication'").fetchone()["n"]
    layout_count = conn.execute("SELECT COUNT(*) as n FROM drawings WHERE drawing_type='layout'").fetchone()["n"]
    text_count = conn.execute("SELECT COUNT(*) as n FROM text_entities").fetchone()["n"]
    ref_count = conn.execute("SELECT COUNT(*) as n FROM drawing_refs").fetchone()["n"]
    conn.close()

    return {
        "exists": True, "db_path": db_path,
        "project_code": project["project_code"] if project else None,
        "folder_path": project["folder_path"] if project else None,
        "fab_count": fab_count, "layout_count": layout_count,
        "text_count": text_count, "ref_count": ref_count,
        "all_projects": _find_all_dbs(),
    }


@app.get("/api/db/layout")
def db_layout(db: str = Query("", description="資料庫路徑或專案代號")):
    conn, _ = _resolve_db(db if db else None)
    if conn is None:
        return JSONResponse(status_code=404, content={"error": "資料庫不存在"})

    # 取得所有位置圖
    layouts = conn.execute("""
        SELECT d.*, p.project_code FROM drawings d JOIN projects p ON d.project_id = p.id
        WHERE d.drawing_type = 'layout' ORDER BY d.drawing_number
    """).fetchall()
    if not layouts:
        conn.close(); return JSONResponse(status_code=404, content={"error": "找不到位置圖"})

    all_layouts = []
    all_fab_dns = set()
    all_external = set()

    for layout in layouts:
        layout_data = dict(layout)
        ref_rows = conn.execute("SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?",
                                [layout["id"]]).fetchall()
        fab_list, external_list = [], []
        for r in ref_rows:
            dn = r["target_drawing_number"]
            fab = conn.execute("SELECT * FROM drawings WHERE drawing_number = ?", [dn]).fetchone()
            if fab:
                fab_list.append(dict(fab))
                all_fab_dns.add(dn)
            elif not dn.startswith("HGRH-") and not dn.startswith("AFB-ACD-") and not dn.startswith("ACB-ACD-"):
                pass  # skip external drawing refs that look like fab drawings
            else:
                external_list.append(dn)
                all_external.add(dn)

        all_layouts.append({
            "layout": layout_data,
            "fabrication_drawings": fab_list,
            "external_refs": sorted(set(external_list)),
            "fab_count": len(fab_list),
        })

    conn.close()
    return {
        "layouts": all_layouts,
        "total_layouts": len(all_layouts),
        "total_fab_in_layouts": len(all_fab_dns),
        "all_external_refs": sorted(all_external),
    }


@app.get("/api/db/fab-to-layout")
def db_fab_to_layout(db: str = Query("")):
    """列出所有加工圖，顯示每張對應哪張位置圖。"""
    conn, _ = _resolve_db(db if db else None)
    if conn is None:
        return JSONResponse(status_code=404, content={"error": "資料庫不存在"})

    # 取得所有加工圖
    fabs = conn.execute("""
        SELECT * FROM drawings WHERE drawing_type = 'fabrication'
        ORDER BY drawing_number
    """).fetchall()

    # 對每張加工圖，找引用它的位置圖
    results = []
    for fab in fabs:
        fab_dict = dict(fab)
        refs = conn.execute("""
            SELECT d.drawing_number, d.filename, d.drawing_type
            FROM drawing_refs r
            JOIN drawings d ON r.source_id = d.id
            WHERE r.target_drawing_number = ?
              AND d.drawing_number != ?
              AND d.drawing_type = 'layout'
        """, [fab["drawing_number"], fab["drawing_number"]]).fetchall()

        fab_dict["layout_drawings"] = [
            {"drawing_number": r["drawing_number"], "filename": r["filename"]}
            for r in refs
        ]
        fab_dict["layout_count"] = len(refs)
        results.append(fab_dict)

    conn.close()
    return {"fabrication_drawings": results, "count": len(results)}


@app.get("/api/db/find-layout")
def db_find_layout(dn: str = Query(...), db: str = Query("")):
    """輸入加工圖號 → 找對應的位置圖。"""
    conn, _ = _resolve_db(db if db else None)
    if conn is None:
        return JSONResponse(status_code=404, content={"error": "資料庫不存在"})
    fab = conn.execute("""
        SELECT d.*, p.project_code FROM drawings d JOIN projects p ON d.project_id = p.id
        WHERE d.drawing_number = ? OR d.filename = ? OR d.filename LIKE ?
    """, [dn, dn + ".dwg", f"%{dn}%"]).fetchone()
    if not fab:
        conn.close(); return JSONResponse(status_code=404, content={"error": f"找不到加工圖: {dn}", "found": False})
    fab_data = dict(fab)
    refs = conn.execute("""
        SELECT d.drawing_number, d.filename, d.drawing_type
        FROM drawing_refs r JOIN drawings d ON r.source_id = d.id
        WHERE r.target_drawing_number = ? AND d.drawing_number != ?
    """, [fab["drawing_number"], fab["drawing_number"]]).fetchall()
    texts = conn.execute("SELECT text_content, entity_type FROM text_entities WHERE drawing_id = ?",
                         [fab["id"]]).fetchall()
    conn.close()
    return {
        "found": True, "fabrication": fab_data,
        "layout_drawings": [{"drawing_number": r["drawing_number"],
                              "filename": r["filename"],
                              "drawing_type": r["drawing_type"]} for r in refs],
        "layout_count": len(refs),
        "texts": [{"text": t["text_content"], "entity": t["entity_type"]} for t in texts],
    }


@app.get("/api/db/drawings")
def db_drawings(search: str = Query(""), limit: int = Query(200), db: str = Query("")):
    conn, _ = _resolve_db(db if db else None)
    if conn is None:
        return JSONResponse(status_code=404, content={"error": "資料庫不存在"})
    if search:
        rows = conn.execute("SELECT * FROM drawings WHERE drawing_number LIKE ? OR filename LIKE ? ORDER BY drawing_number LIMIT ?",
                            [f"%{search}%", f"%{search}%", limit]).fetchall()
    else:
        rows = conn.execute("SELECT * FROM drawings ORDER BY drawing_type, drawing_number LIMIT ?", [limit]).fetchall()
    conn.close()
    return {"count": len(rows), "drawings": [dict(r) for r in rows]}


@app.get("/api/db/drawings/{drawing_number}")
def db_drawing_detail(drawing_number: str, db: str = Query("")):
    conn, _ = _resolve_db(db if db else None)
    if conn is None:
        return JSONResponse(status_code=404, content={"error": "資料庫不存在"})
    d = conn.execute("""
        SELECT d.*, p.project_code FROM drawings d JOIN projects p ON d.project_id = p.id
        WHERE d.drawing_number = ? OR d.filename LIKE ?
    """, [drawing_number, f"%{drawing_number}%"]).fetchone()
    if not d:
        conn.close(); return JSONResponse(status_code=404, content={"error": f"找不到: {drawing_number}"})
    drawing = dict(d)
    texts = conn.execute("SELECT text_content, entity_type FROM text_entities WHERE drawing_id = ?",
                         [d["id"]]).fetchall()
    drawing["texts"] = [{"text": t["text_content"], "entity": t["entity_type"]} for t in texts]
    refs = conn.execute("SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?",
                        [d["id"]]).fetchall()
    drawing["refs"] = [r["target_drawing_number"] for r in refs]
    back_refs = conn.execute("""
        SELECT d2.drawing_number, d2.filename FROM drawing_refs r
        JOIN drawings d2 ON r.source_id = d2.id WHERE r.target_drawing_number = ?
    """, [d["drawing_number"]]).fetchall()
    drawing["referenced_by"] = [{"drawing_number": br["drawing_number"], "filename": br["filename"]} for br in back_refs]
    conn.close()
    return drawing


@app.get("/api/db/missing")
def db_missing(db: str = Query("")):
    conn, _ = _resolve_db(db if db else None)
    if conn is None:
        return JSONResponse(status_code=404, content={"error": "資料庫不存在"})
    layout = conn.execute("SELECT * FROM drawings WHERE drawing_type = 'layout'").fetchone()
    if not layout:
        conn.close(); return {"missing": [], "message": "找不到位置圖"}
    refs = conn.execute("SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?",
                        [layout["id"]]).fetchall()
    missing = []
    for r in refs:
        dn = r["target_drawing_number"]
        if dn == layout["drawing_number"] or dn.startswith("HGRH-"): continue
        fab = conn.execute("SELECT id FROM drawings WHERE drawing_number = ? OR filename = ?",
                           [dn, dn + ".dwg"]).fetchone()
        if not fab: missing.append(dn)
    conn.close()
    return {"missing": sorted(set(missing)), "count": len(set(missing))}


# ------ 靜態檔案 (前端) ------
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
