"""批次掃描所有圖紙，提取加工圖號"""
import sys
import json
import glob
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))
from analyzer.structure_analyzer import StructureAnalyzer
from analyzer.section_mark_detector import SectionMarkDetector

DRAWINGS_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Desktop/Claude Code/F5062 HGRH-ACB0203-FAC5062 铝板加工图 (For ACB_大格栅) 华顶送工地"
)

print(f"掃描目錄: {DRAWINGS_DIR}\n")

pdf_files = sorted(glob.glob(os.path.join(DRAWINGS_DIR, "*.pdf")))
# Filter out the summary PDF
pdf_files = [f for f in pdf_files if not os.path.basename(f).startswith("HGRH-ACB0203")]

print(f"共 {len(pdf_files)} 個 PDF\n")
print(f"{'檔案':<30} {'類型':<14} {'圖紙編號'}")
print("-" * 90)

analyzer = StructureAnalyzer(dpi=200)  # Low DPI for speed

all_marks = {}

for pdf_path in pdf_files:
    fname = os.path.basename(pdf_path)
    try:
        result = analyzer.analyze(pdf_path)
        sm = result.section_marks
        dn_list = sm.get("summary", {}).get("drawing_number_list", [])
        dn_str = ", ".join(dn_list) if dn_list else "(未偵測到)"
        print(f"{fname:<30} {result.drawing_type:<14} {dn_str}")
        all_marks[fname] = {
            "drawing_type": result.drawing_type,
            "drawing_numbers": dn_list,
            "total_marks": sm.get("total_marks", 0),
            "fab_marks": result.annotations.get("fab_mark_count", 0),
            "dimensions": result.annotations.get("dimension_count", 0),
        }
    except Exception as e:
        print(f"{fname:<30} ERROR           {e}")

print("\n" + "=" * 90)
print("所有加工圖號彙總:")
print("=" * 90)

all_dn = set()
for fname, info in all_marks.items():
    for dn in info["drawing_numbers"]:
        all_dn.add(dn)

for dn in sorted(all_dn):
    print(f"  {dn}")

print(f"\n共 {len(all_dn)} 個不重複的加工圖號")

# 輸出 JSON
output_path = os.path.join(os.path.dirname(DRAWINGS_DIR), "batch_scan_result.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump({"scan_results": all_marks, "all_drawing_numbers": sorted(all_dn)}, f, ensure_ascii=False, indent=2)
print(f"\n完整結果已存至: {output_path}")
