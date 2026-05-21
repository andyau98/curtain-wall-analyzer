"""
DWG 加工圖資料庫工具
====================
從 DWG 檔提取文字 → 識別圖號與尺寸 → 存入 SQLite → 建立位置圖↔加工圖對應關係。

必要條件: 已編譯的 libredwg (dwgread 工具)
用法:
  ./venv/bin/python dwg_db.py init "圖紙目錄"              # 建立/重建資料庫
  ./venv/bin/python dwg_db.py query "ACB-ACD-0060"         # 查詢指定加工圖
  ./venv/bin/python dwg_db.py layout                        # 顯示位置圖→加工圖對照
  ./venv/bin/python dwg_db.py missing                       # 檢查缺檔
  ./venv/bin/python dwg_db.py export                        # 匯出 JSON
"""

import sqlite3
import json
import re
import os
import sys
import subprocess
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# 常數 / 配置
# ---------------------------------------------------------------------------
DWGREAD = Path("/tmp/libredwg-0.13.4/programs/.libs/dwgread")
LIB_PATH = Path("/tmp/libredwg-0.13.4/src/.libs")

# 圖號 regex (從 DWG 文字中提取)
# ACB-ACD-0060, ACB-TG-FAC-0005, HGRH-ACB-0203, GK-NE-0002 等
RE_DRAWING_NUMBER = re.compile(r'^([A-Z]{2,4}-[A-Z]{2,4}-\d{4})(-\d{2})?$')
RE_DRAWING_NUMBER_3PART = re.compile(r'^([A-Z]{2,4}-[A-Z]{2,4}-[A-Z]{3,4}-\d{4})$')
RE_DRAWING_NUMBER_ANY = re.compile(r'^([A-Z]{2,4}-[A-Z]{2,4}(?:-[A-Z]{3,4})?-\d{4})(-\d{2})?$')
# 位置圖 pattern (含有 "TG" 或 "Setting" 或 "位置" 的通常是總圖)
RE_LAYOUT_KEYWORDS = re.compile(r'TG-|位置|LAYOUT|SETTING|layout|setting', re.IGNORECASE)

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_code TEXT,
    requisition_no TEXT,
    folder_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drawings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    filename TEXT NOT NULL,
    file_path TEXT,
    drawing_number TEXT,
    drawing_type TEXT CHECK(drawing_type IN ('fabrication', 'layout', 'unknown')),
    width_mm REAL,
    height_mm REAL,
    quantity INTEGER DEFAULT 1,
    material TEXT,
    color TEXT,
    has_sub_parts INTEGER DEFAULT 0,
    sub_part_list TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS text_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drawing_id INTEGER,
    text_content TEXT NOT NULL,
    entity_type TEXT,
    FOREIGN KEY (drawing_id) REFERENCES drawings(id)
);

CREATE TABLE IF NOT EXISTS drawing_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    target_drawing_number TEXT,
    FOREIGN KEY (source_id) REFERENCES drawings(id)
);

CREATE INDEX IF NOT EXISTS idx_drawings_number ON drawings(drawing_number);
CREATE INDEX IF NOT EXISTS idx_drawings_type ON drawings(drawing_type);
CREATE INDEX IF NOT EXISTS idx_text_drawing ON text_entities(drawing_id);
CREATE INDEX IF NOT EXISTS idx_refs_source ON drawing_refs(source_id);
CREATE INDEX IF NOT EXISTS idx_refs_target ON drawing_refs(target_drawing_number);
"""

# ---------------------------------------------------------------------------
# DWG 讀取層
# ---------------------------------------------------------------------------
def run_dwgread(dwg_path: str) -> dict:
    """執行 dwgread -O JSON，回傳解析後的 dict。"""
    env = os.environ.copy()
    env["DYLD_LIBRARY_PATH"] = str(LIB_PATH)
    r = subprocess.run(
        [str(DWGREAD), "-O", "JSON", str(dwg_path)],
        capture_output=True, timeout=60, env=env
    )
    if r.returncode != 0:
        raise RuntimeError(f"dwgread 失敗: {r.stderr.decode('utf-8','replace')[:300]}")
    raw = r.stdout.decode("utf-8", errors="replace")
    return json.loads(raw)


def extract_text_from_dwg(dwg_path: str) -> list[dict]:
    """從單一 DWG 提取所有文字 (MTEXT + INSERT/ATTRIB)。"""
    data = run_dwgread(dwg_path)
    objects = data.get("OBJECTS", [])

    # handle → object 索引
    handle_map = {}
    for obj in objects:
        h = obj.get("handle")
        if h:
            handle_map[tuple(h)] = obj

    results = []
    for obj in objects:
        entity = obj.get("entity", "")
        dwg_type = obj.get("type")

        # MTEXT: 直接有文字，需清除格式標籤
        if entity == "MTEXT" or dwg_type == 44:
            text = obj.get("text", "")
            if text:
                clean = re.sub(r'\{[^}]*\}', '', text)        # {\fSimSun|...}
                clean = clean.replace('\\P', '\n')              # 段落
                clean = re.sub(r'\\[A-Za-z][^;]*;', '', clean) # \A1; 等
                if clean.strip():
                    results.append({"text": clean.strip(), "entity": "MTEXT"})

        # INSERT: 區塊引用，文字在 attribs 子物件中
        elif entity == "INSERT" and obj.get("has_attribs"):
            for ah in obj.get("attribs", []):
                attr = handle_map.get(tuple(ah))
                if attr:
                    text = attr.get("text", attr.get("text_value", ""))
                    if text and str(text).strip():
                        results.append({"text": str(text).strip(), "entity": "ATTRIB"})

        # 獨立的 ATTRIB / ATTDEF
        elif entity in ("ATTRIB", "ATTDEF") or dwg_type in (33, 34):
            text = obj.get("text", obj.get("text_value", ""))
            if text and str(text).strip():
                results.append({"text": str(text).strip(), "entity": entity})

    return results


# ---------------------------------------------------------------------------
# 圖紙分析
# ---------------------------------------------------------------------------
def classify_drawing(texts: list[str]) -> str:
    """
    判定圖紙類型:
      'layout'      — 位置圖 (含有大量其他圖號引用)
      'fabrication' — 加工圖 (只含自身圖號 + 尺寸)
      'unknown'     — 無法判定
    """
    joined = " ".join(texts)
    if RE_LAYOUT_KEYWORDS.search(joined):
        return "layout"
    # 計算引用了多少其他圖號
    refs = set()
    for t in texts:
        t = t.strip()
        m = RE_DRAWING_NUMBER_ANY.match(t)
        if m:
            refs.add(m.group(1))
    return "layout" if len(refs) >= 5 else "fabrication"


def extract_dimensions(texts: list[str]) -> dict:
    """從文字清單中嘗試提取尺寸與材料資訊 (依賴位置圖中的慣例排列)。"""
    info = {"width_mm": None, "height_mm": None, "quantity": 1,
            "material": None, "color": None}
    for i, t in enumerate(texts):
        t = t.strip()
        # 材料
        if "铝板" in t or "鋁板" in t:
            info["material"] = t
        # 顏色
        if "Pantone" in t or "Cool Grey" in t:
            info["color"] = t
    return info


def analyze_folder(folder_path: str) -> dict:
    """
    分析整個資料夾:
      1. 讀取所有 DWG
      2. 提取文字
      3. 識別位置圖 vs 加工圖
      4. 建立對應關係
    """
    folder = Path(folder_path)
    dwg_files = sorted(folder.glob("*.dwg"))
    if not dwg_files:
        raise FileNotFoundError(f"目錄中沒有 DWG 檔案: {folder_path}")

    drawings = {}
    for dwg_path in dwg_files:
        name = dwg_path.stem
        print(f"  讀取: {name}")
        try:
            entries = extract_text_from_dwg(str(dwg_path))
        except Exception as e:
            print(f"    [錯誤] {e}")
            continue

        texts = [e["text"] for e in entries]
        dtype = classify_drawing(texts)

        # 自身圖號: 優先從檔名推導, 其次從文字中找
        own_numbers = set()
        # 檔名本身就是圖號 (如 ACB-ACD-0060, ACB-TG-FAC-0005)
        if RE_DRAWING_NUMBER_ANY.match(name):
            own_numbers.add(RE_DRAWING_NUMBER_ANY.match(name).group(1))
        # 也從文字中搜尋 (補強)
        for t in texts:
            t = t.strip()
            m = RE_DRAWING_NUMBER_ANY.match(t)
            if m:
                own_numbers.add(m.group(1))

        # 找所有引用的圖號 (含外部)
        refs = set()
        for t in texts:
            t = t.strip()
            m = RE_DRAWING_NUMBER_ANY.match(t)
            if m:
                refs.add(m.group(1))

        # 自身的 primary drawing number: 優先取檔名
        primary_dn = None
        if RE_DRAWING_NUMBER_ANY.match(name):
            primary_dn = RE_DRAWING_NUMBER_ANY.match(name).group(1)
        elif own_numbers:
            primary_dn = sorted(own_numbers)[0]

        drawings[name] = {
            "path": str(dwg_path),
            "type": dtype,
            "primary_dn": primary_dn,
            "own_numbers": sorted(own_numbers),
            "references": sorted(refs),
            "text_count": len(entries),
            "all_texts": texts,
            "entries": entries,
        }

    # 識別主位置圖
    layout_drawing = None
    for name, info in drawings.items():
        if info["type"] == "layout":
            # 選引用最多的那張作為主位置圖
            if layout_drawing is None or len(info["references"]) > len(drawings[layout_drawing]["references"]):
                layout_drawing = name

    # 建立對應: 位置圖引用 → 加工圖檔案
    cross_ref = {"layout": layout_drawing, "mappings": [], "missing_files": [], "external_refs": []}
    if layout_drawing and layout_drawing in drawings:
        layout_refs = set(drawings[layout_drawing]["references"])
        fab_files = {name for name, info in drawings.items() if info["type"] == "fabrication"}
        for ref in sorted(layout_refs):
            if ref in fab_files:
                cross_ref["mappings"].append(ref)
            elif ref == drawings[layout_drawing].get("own_numbers", [None])[0]:
                pass  # 位置圖自身
            else:
                cross_ref["external_refs"].append(ref)

        layout_own = {drawings[layout_drawing].get("primary_dn", "")}
        # external = refs that are not fab files, not layout's own number, not project codes
        fab_drawing_numbers = set()
        for fn in fab_files:
            fab_drawing_numbers.add(drawings[fn].get("primary_dn", fn))
        ignore = fab_drawing_numbers | layout_own | {r for r in layout_refs if re.match(r'^HGRH-', r)}
        cross_ref["missing_files"] = sorted(layout_refs - ignore)

    # 從位置圖文字提取每張加工圖的尺寸 (文字順序: 圖號, W, H, Color)
    if layout_drawing:
        layout_texts = drawings[layout_drawing]["all_texts"]
        dims_set = set()  # 只取首次出現的尺寸
        for i, t in enumerate(layout_texts):
            t = t.strip()
            m = RE_DRAWING_NUMBER_ANY.match(t)
            if m and m.group(1) in cross_ref["mappings"]:
                dn = m.group(1)
                is_first = dn not in dims_set
                dims_set.add(dn)
                if is_first:
                    w = layout_texts[i+1].strip() if i+1 < len(layout_texts) else None
                    h = layout_texts[i+2].strip() if i+2 < len(layout_texts) else None
                    color = layout_texts[i+3].strip() if i+3 < len(layout_texts) and "Pantone" in layout_texts[i+3] else None
                    try:
                        drawings[dn]["width_mm"] = float(w) if w and w.replace('.', '').replace('-', '').isdigit() else None
                    except ValueError:
                        pass
                    try:
                        drawings[dn]["height_mm"] = float(h) if h and h.replace('.', '').replace('-', '').isdigit() else None
                    except ValueError:
                        pass
                    if color:
                        drawings[dn]["color"] = color
                # 數量 = 此圖號在位置圖中出現的次數
                drawings[dn]["quantity"] = sum(1 for x in layout_texts if x.strip() == dn or (x.strip().startswith(dn + '-')))

    return {"drawings": drawings, "cross_ref": cross_ref}


# ---------------------------------------------------------------------------
# SQLite 操作
# ---------------------------------------------------------------------------
def init_db(db_path: str, folder_path: str):
    """初始化資料庫: 分析資料夾 → 寫入 SQLite。"""
    print(f"分析目錄: {folder_path}")
    result = analyze_folder(folder_path)
    drawings = result["drawings"]
    cross_ref = result["cross_ref"]

    # 清除舊資料庫
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.executescript(DB_SCHEMA)

    # 建立 project
    folder_name = Path(folder_path).name
    # 從檔名猜 project code
    proj_match = re.search(r'(HGRH-\w+-\w+)', folder_name)
    proj_code = proj_match.group(1) if proj_match else folder_name
    conn.execute("INSERT INTO projects (project_code, folder_path) VALUES (?, ?)",
                 [proj_code, str(folder_path)])
    project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 寫入圖紙
    for name in sorted(drawings):
        info = drawings[name]
        conn.execute("""
            INSERT INTO drawings (project_id, filename, file_path, drawing_number,
                drawing_type, width_mm, height_mm, quantity, material, color,
                has_sub_parts, sub_part_list)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            project_id, name + ".dwg", info["path"],
            info.get("primary_dn"),
            info["type"],
            info.get("width_mm"), info.get("height_mm"),
            info.get("quantity", 1),
            info.get("material"), info.get("color"),
            0, None
        ])
        drawing_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 寫入文字實體
        for entry in info.get("entries", []):
            conn.execute("INSERT INTO text_entities (drawing_id, text_content, entity_type) VALUES (?, ?, ?)",
                         [drawing_id, entry["text"], entry["entity"]])

        # 寫入引用關係
        for ref in info.get("references", []):
            conn.execute("INSERT INTO drawing_refs (source_id, target_drawing_number) VALUES (?, ?)",
                         [drawing_id, ref])

    conn.commit()

    # 顯示摘要
    fab_count = sum(1 for info in drawings.values() if info["type"] == "fabrication")
    layout_count = sum(1 for info in drawings.values() if info["type"] == "layout")
    print(f"\n✅ 資料庫已建立: {db_path}")
    print(f"   專案: {proj_code}")
    print(f"   位置圖: {layout_count} 張")
    print(f"   加工圖: {fab_count} 張")
    print(f"   位置圖引用: {len(cross_ref['mappings'])} 個加工圖號")
    if cross_ref["external_refs"]:
        print(f"   外部引用: {len(cross_ref['external_refs'])} 個")
    if cross_ref["missing_files"]:
        print(f"   ⚠️  缺檔: {cross_ref['missing_files']}")

    conn.close()
    return result


def get_db_path(folder_path: str = None) -> str:
    """預設 DB 路徑: 專案目錄下的 dwg_index.db"""
    if folder_path:
        return str(Path(folder_path) / "dwg_index.db")
    return "dwg_index.db"


# ---------------------------------------------------------------------------
# 查詢功能
# ---------------------------------------------------------------------------
def query_drawing(db_path: str, drawing_number: str):
    """查詢指定圖號的所有資訊。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    d = conn.execute("""
        SELECT d.*, p.project_code
        FROM drawings d
        JOIN projects p ON d.project_id = p.id
        WHERE d.drawing_number = ? OR d.filename LIKE ?
    """, [drawing_number, f"%{drawing_number}%"]).fetchone()

    if not d:
        print(f"找不到: {drawing_number}")
        conn.close()
        return

    print(f"圖號: {d['drawing_number']}")
    print(f"檔案: {d['filename']}")
    print(f"類型: {d['drawing_type']}")
    print(f"尺寸: {d['width_mm']} × {d['height_mm']} mm")
    print(f"數量: {d['quantity']}")
    print(f"顏色: {d['color'] or '-'}")
    print(f"專案: {d['project_code']}")

    # 文字內容
    texts = conn.execute("SELECT text_content, entity_type FROM text_entities WHERE drawing_id = ?",
                         [d['id']]).fetchall()
    print(f"\n文字內容 ({len(texts)} 個):")
    for t in texts:
        print(f"  [{t['entity_type']}] {t['text_content']}")

    # 引用了哪些圖
    refs = conn.execute("SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?",
                        [d['id']]).fetchall()
    if refs:
        print(f"\n引用的圖號 ({len(refs)} 個):")
        for r in refs:
            print(f"  → {r['target_drawing_number']}")

    # 被哪些圖引用
    back_refs = conn.execute("""
        SELECT d2.drawing_number, d2.filename
        FROM drawing_refs r
        JOIN drawings d2 ON r.source_id = d2.id
        WHERE r.target_drawing_number = ?
    """, [d['drawing_number']]).fetchall()
    if back_refs:
        print(f"\n被以下圖紙引用 ({len(back_refs)} 個):")
        for br in back_refs:
            print(f"  ← {br['drawing_number']} ({br['filename']})")

    conn.close()


def show_layout_map(db_path: str):
    """顯示位置圖 → 加工圖的完整對照表。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    layouts = conn.execute("""
        SELECT d.*, p.project_code
        FROM drawings d JOIN projects p ON d.project_id = p.id
        WHERE d.drawing_type = 'layout'
    """).fetchall()
    if not layouts:
        print("找不到位置圖")
        conn.close()
        return

    for layout in layouts:
        refs = conn.execute("""
            SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?
        """, [layout['id']]).fetchall()

        fab_refs = []
        external_refs = []
        for r in refs:
            dn = r['target_drawing_number']
            fab = conn.execute("SELECT * FROM drawings WHERE drawing_number = ?", [dn]).fetchone()
            if fab:
                fab_refs.append(fab)
            else:
                external_refs.append(dn)

        print(f"\n位置圖: {layout['drawing_number']} ({layout['filename']})")
        print(f"專案: {layout['project_code']}")
        print(f"引用 {len(fab_refs)} 張加工圖, {len(external_refs)} 個外部引用")
        print(f"\n{'圖號':<22} {'寬 W':<10} {'高 H':<10} {'數量':<5} {'顏色'}")
        print("-" * 70)
        for fab in fab_refs:
            print(f"{fab['drawing_number']:<22} {str(fab['width_mm'] or '-'):<10} "
                  f"{str(fab['height_mm'] or '-'):<10} {fab['quantity']:<5} {fab['color'] or '-'}")

        if external_refs:
            print(f"\n外部引用 (不在本資料夾):")
            for ext in sorted(set(external_refs)):
                print(f"  → {ext}")

    conn.close()


def check_missing(db_path: str):
    """檢查位置圖有引用但缺檔案的圖號。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    layouts = conn.execute("SELECT * FROM drawings WHERE drawing_type = 'layout'").fetchall()
    for layout in layouts:
        refs = conn.execute("SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?",
                            [layout['id']]).fetchall()
        missing = []
        own_dn = layout['drawing_number']
        own_fn = layout['filename']
        for r in refs:
            dn = r['target_drawing_number']
            if dn == own_dn:
                continue
            if re.match(r'^HGRH-', dn):
                continue
            # 同時檢查 drawing_number 和 filename
            fab = conn.execute(
                "SELECT id FROM drawings WHERE drawing_number = ? OR filename = ?",
                [dn, dn + ".dwg"]
            ).fetchone()
            if not fab:
                missing.append(dn)

        if missing:
            print(f"位置圖 {layout['drawing_number']} 引用但缺檔 ({len(missing)} 個):")
            for m in sorted(set(missing)):
                print(f"  ❌ {m}")
        else:
            print("✅ 所有引用的加工圖都有對應檔案。")

    conn.close()


def export_json(db_path: str, output_path: str = None):
    """匯出整個資料庫為 JSON。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    projects = [dict(r) for r in conn.execute("SELECT * FROM projects").fetchall()]
    drawings = []
    for d in conn.execute("SELECT * FROM drawings").fetchall():
        d = dict(d)
        d["texts"] = [dict(t) for t in conn.execute(
            "SELECT text_content, entity_type FROM text_entities WHERE drawing_id = ?", [d["id"]]).fetchall()]
        d["refs"] = [r["target_drawing_number"] for r in conn.execute(
            "SELECT target_drawing_number FROM drawing_refs WHERE source_id = ?", [d["id"]]).fetchall()]
        drawings.append(d)

    output = {"projects": projects, "drawings": drawings}
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"已匯出至: {output_path}")
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def find_layout(db_path: str, drawing_number: str):
    """輸入加工圖號，找出對應的位置圖。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    fab = conn.execute("""
        SELECT d.*, p.project_code
        FROM drawings d JOIN projects p ON d.project_id = p.id
        WHERE d.drawing_number = ? OR d.filename = ? OR d.filename LIKE ?
    """, [drawing_number, drawing_number + ".dwg", f"%{drawing_number}%"]).fetchone()

    if not fab:
        print(f"找不到: {drawing_number}")
        conn.close()
        return

    print(f"\n加工圖: {fab['drawing_number']}")
    print(f"檔案:   {fab['filename']}")
    print(f"尺寸:   {fab['width_mm'] or '?'} × {fab['height_mm'] or '?'} mm")
    print(f"數量:   {fab['quantity']}")
    print(f"顏色:   {fab['color'] or '-'}")
    print(f"專案:   {fab['project_code']}")

    # 找位置圖
    refs = conn.execute("""
        SELECT d.drawing_number, d.filename, d.drawing_type
        FROM drawing_refs r
        JOIN drawings d ON r.source_id = d.id
        WHERE r.target_drawing_number = ?
          AND d.drawing_number != ?
    """, [fab['drawing_number'], fab['drawing_number']]).fetchall()

    layouts = [r for r in refs if r['drawing_type'] == 'layout']
    if layouts:
        print(f"\n對應的位置圖 ({len(layouts)} 張):")
        for l in layouts:
            print(f"  → {l['drawing_number']}  ({l['filename']})")
    else:
        print(f"\n⚠ 未被任何位置圖引用")

    conn.close()


def print_usage():
    print("""用法:
  ./venv/bin/python dwg_db.py init <圖紙目錄>              建立/重建資料庫
  ./venv/bin/python dwg_db.py find <加工圖號> [目錄]        輸入加工圖號 → 找對應位置圖
  ./venv/bin/python dwg_db.py query <圖號或檔名>            查詢指定圖紙
  ./venv/bin/python dwg_db.py layout [目錄]                 顯示位置圖→加工圖對照
  ./venv/bin/python dwg_db.py missing [目錄]                檢查缺檔
  ./venv/bin/python dwg_db.py export [目錄] [-o out.json]   匯出 JSON
""")


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    cmd = sys.argv[1]

    if not DWGREAD.exists():
        print("錯誤: 找不到 dwgread 工具。請先編譯 libredwg。")
        print("  brew install autoconf automake libtool pkg-config")
        print("  cd /tmp && curl -sLO https://github.com/LibreDWG/libredwg/releases/download/0.13.4/libredwg-0.13.4.tar.xz")
        print("  tar xf libredwg-0.13.4.tar.xz && cd libredwg-0.13.4")
        print("  ./configure --disable-bindings && make -j4")
        sys.exit(1)

    if cmd == "init":
        if len(sys.argv) < 3:
            print("用法: dwg_db.py init <圖紙目錄>")
            sys.exit(1)
        folder = sys.argv[2]
        db_path = get_db_path(folder)
        init_db(db_path, folder)

    elif cmd == "find":
        if len(sys.argv) < 3:
            print("用法: dwg_db.py find <加工圖號> [目錄]")
            sys.exit(1)
        extra = sys.argv[3] if len(sys.argv) > 3 else None
        db_path = _find_db(extra)
        if not db_path:
            print("找不到資料庫。請先執行 init，或指定目錄路徑。")
            sys.exit(1)
        find_layout(db_path, sys.argv[2])

    elif cmd == "query":
        if len(sys.argv) < 3:
            print("用法: dwg_db.py query <圖號> [目錄或db路徑]")
            sys.exit(1)
        extra = sys.argv[3] if len(sys.argv) > 3 else None
        db_path = _find_db(extra)
        if not db_path:
            print("找不到資料庫。請先執行 init，或指定資料庫/目錄路徑。")
            sys.exit(1)
        query_drawing(db_path, sys.argv[2])

    elif cmd == "layout":
        extra = sys.argv[2] if len(sys.argv) > 2 else None
        db_path = _find_db(extra)
        if not db_path:
            print("找不到資料庫。請先執行 init，或指定資料庫/目錄路徑。")
            sys.exit(1)
        show_layout_map(db_path)

    elif cmd == "missing":
        extra = sys.argv[2] if len(sys.argv) > 2 else None
        db_path = _find_db(extra)
        if not db_path:
            print("找不到資料庫。請先執行 init，或指定資料庫/目錄路徑。")
            sys.exit(1)
        check_missing(db_path)

    elif cmd == "export":
        output = None
        extra = None
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "-o" and i+1 < len(args):
                output = args[i+1]
                i += 2
            else:
                extra = args[i]
                i += 1
        db_path = _find_db(extra)
        if not db_path:
            print("找不到資料庫。請先執行 init，或指定資料庫/目錄路徑。")
            sys.exit(1)
        export_json(db_path, output)

    else:
        print(f"未知指令: {cmd}")
        print_usage()
        sys.exit(1)


def _find_db(extra_path: str = None):
    """在常用位置找 dwg_index.db。"""
    candidates = []
    if extra_path:
        p = Path(extra_path)
        if p.is_file():
            candidates.append(str(p))
        elif p.is_dir():
            candidates.append(str(p / "dwg_index.db"))
        else:
            # 可能是圖號，嘗試在附近目錄找
            candidates.append(str(Path.cwd() / "dwg_index.db"))

    candidates.append(str(Path.cwd() / "dwg_index.db"))
    candidates.append(str(Path.cwd().parent / "dwg_index.db"))

    # 搜尋工作目錄下兩層
    for root, dirs, files in os.walk(Path.cwd(), followlinks=False):
        depth = len(Path(root).relative_to(Path.cwd()).parts)
        if depth > 2:
            dirs.clear()
            continue
        if "dwg_index.db" in files:
            candidates.append(str(Path(root) / "dwg_index.db"))

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


if __name__ == "__main__":
    main()
