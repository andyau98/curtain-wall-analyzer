"""
幕牆圖紙結構分析主引擎。
協調所有子分析器，產出完整結構報告。
"""

import json
import cv2
import numpy as np
from dataclasses import dataclass, field, asdict
from .drawing_parser import DrawingParser
from .grid_detector import GridDetector, GridSystem
from .panel_detector import PanelDetector, PanelLayout
from .dimension_parser import DimensionParser, DrawingAnnotations
from .section_mark_detector import SectionMarkDetector


@dataclass
class DrawingStructure:
    """一幅幕牆圖的完整結構分析結果。"""
    filename: str = ''
    page_count: int = 0
    image_size: tuple = (0, 0)          # (width, height) px
    dpi: int = 300

    # 圖紙類型判定
    drawing_type: str = ''               # 'position' | 'fabrication' | 'detail' | 'assembly'
    drawing_type_confidence: float = 0.0

    # 子結構
    grid_system: dict = field(default_factory=dict)
    panel_layout: dict = field(default_factory=dict)
    annotations: dict = field(default_factory=dict)
    section_marks: dict = field(default_factory=dict)

    # 結構化摘要
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=_json_fallback)


def _json_fallback(obj):
    """Fallback for types that json doesn't handle (e.g. numpy int32/float64)."""
    if hasattr(obj, 'item'):
        return obj.item()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class StructureAnalyzer:
    """
    幕牆圖紙結構分析總引擎。
    規則驅動，不依賴外部 AI — 適合批量自動運行。
    """

    def __init__(self, dpi: int = 300):
        self.dpi = dpi
        self.grid_detector = GridDetector()
        self.panel_detector = PanelDetector()
        self.dimension_parser = DimensionParser()
        self.section_mark_detector = SectionMarkDetector()

    def analyze(self, filepath: str) -> DrawingStructure:
        """完整分析一幅幕牆圖紙。"""
        # 1. 載入圖紙
        parser = DrawingParser(filepath, dpi=self.dpi)
        page_count = parser.parse()
        page = parser.get_page(0)

        h, w = page['gray'].shape
        structure = DrawingStructure(
            filename=filepath,
            page_count=page_count,
            image_size=(w, h),
            dpi=self.dpi,
        )

        # 2. 判定圖紙類型 (位置圖 vs 加工圖 vs 大樣圖)
        structure.drawing_type, structure.drawing_type_confidence = \
            self._classify_drawing(page['binary'])

        # 3. 軸網分析
        grid = self.grid_detector.detect(page['binary'])
        structure.grid_system = self._grid_to_dict(grid)

        # 4. 面板佈局分析
        panel_layout = self.panel_detector.detect(page['binary'], grid)
        structure.panel_layout = self._panel_layout_to_dict(panel_layout)

        # 5. 標註 / 加工符號分析
        annotations = self.dimension_parser.parse(page['gray'], page['binary'])
        structure.annotations = self._annotations_to_dict(annotations)

        # 6. Section Mark / 加工圖號偵測 (OCR)
        section_marks = self.section_mark_detector.detect(page['gray'], page['binary'])
        structure.section_marks = self._section_marks_to_dict(section_marks)

        # 7. 生成摘要
        structure.summary = self._build_summary(structure)

        return structure

    # -----------------------------------------------------------------
    def _classify_drawing(self, binary: np.ndarray) -> tuple:
        """
        根據圖面特徵判定圖紙類型。
        位置圖: 大量長軸線、均勻面板分佈
        加工圖: 單一或少量面板、大量尺寸標註、加工符號
        大樣圖: 局部放大、細部標註密集
        """
        h, w = binary.shape

        # 長線密度 (軸線特徵)
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 4, 1))
        h_long = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
        h_line_ratio = np.sum(h_long > 0) / binary.size

        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 4))
        v_long = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
        v_line_ratio = np.sum(v_long > 0) / binary.size

        # 總線條密度
        total_line_ratio = np.sum(binary > 0) / binary.size

        # 判定 (加工圖通常同時有軸線和密集細部標註)
        has_grid = h_line_ratio > 0.002 and v_line_ratio > 0.002
        is_dense = total_line_ratio > 0.015

        if has_grid and is_dense:
            return 'fabrication', 0.85   # 有軸網 + 密集標註 = 加工圖
        elif has_grid and not is_dense:
            return 'position', 0.85      # 有軸網 + 稀疏 = 位置圖
        elif is_dense and total_line_ratio > 0.12:
            return 'detail', 0.75        # 非常密集 = 大樣圖
        elif is_dense:
            return 'fabrication', 0.75   # 密集但無明顯軸網 = 也可能是加工圖
        else:
            return 'position', 0.5

    # -----------------------------------------------------------------
    def _grid_to_dict(self, grid: GridSystem) -> dict:
        return {
            'horizontal_axes': [
                {'label': l.label, 'position_px': l.position, 'length_px': l.length,
                 'confidence': l.confidence}
                for l in grid.horizontal_lines
            ],
            'vertical_axes': [
                {'label': l.label, 'position_px': l.position, 'length_px': l.length,
                 'confidence': l.confidence}
                for l in grid.vertical_lines
            ],
            'total_axes': grid.total_axes,
            'bay_count': grid.bay_count,
            'intersection_count': len(grid.intersections),
            'horizontal_spacing': grid.grid_spacing_h,
            'vertical_spacing': grid.grid_spacing_v,
        }

    def _panel_layout_to_dict(self, layout: PanelLayout) -> dict:
        panels_data = []
        for p in layout.panels:
            panels_data.append({
                'id': p.id,
                'position': {'x': p.bbox[0], 'y': p.bbox[1], 'w': p.bbox[2], 'h': p.bbox[3]},
                'area_px2': p.area,
                'aspect_ratio': round(p.aspect_ratio, 3),
                'grid_cell': p.grid_cell,
                'type': p.panel_type,
                'confidence': p.confidence,
            })
        return {
            'total_panels': layout.total_panels,
            'type_summary': layout.type_summary,
            'aspect_summary': layout.aspect_summary,
            'panels': panels_data,
        }

    def _annotations_to_dict(self, ann: DrawingAnnotations) -> dict:
        return {
            'dimension_count': len(ann.dimensions),
            'dimensions': [
                {'value': d.value, 'unit': d.unit, 'position': d.position,
                 'orientation': d.orientation, 'type': d.dimension_type}
                for d in ann.dimensions[:20]  # 最多回傳 20 組
            ],
            'text_region_count': len(ann.annotations),
            'text_regions': [
                {'position': a.position, 'type': a.annotation_type, 'bbox': a.bbox}
                for a in ann.annotations[:20]
            ],
            'fab_mark_count': len(ann.fab_marks),
            'fab_marks': [
                {'type': m.mark_type, 'position': m.position,
                 'description': m.description, 'confidence': m.confidence}
                for m in ann.fab_marks[:20]
            ],
            'title_block': ann.title_block,
        }

    def _section_marks_to_dict(self, report) -> dict:
        return {
            'total_marks': report.summary.get('total_marks', 0),
            'drawing_numbers': [
                {'text': m.text, 'position': list(m.position), 'confidence': m.confidence}
                for m in report.drawing_numbers
            ],
            'part_numbers': [
                {'text': m.text, 'position': list(m.position), 'confidence': m.confidence}
                for m in report.part_numbers[:50]
            ],
            'section_refs': [
                {'text': m.text, 'position': list(m.position), 'confidence': m.confidence}
                for m in report.section_refs
            ],
            'material_marks': [
                {'text': m.text, 'position': list(m.position), 'confidence': m.confidence}
                for m in report.material_marks
            ],
            'summary': report.summary,
        }

    def _build_summary(self, s: DrawingStructure) -> dict:
        """產出人可讀的結構摘要。"""
        g = s.grid_system
        p = s.panel_layout
        a = s.annotations

        lines = []
        lines.append(f"圖紙類型: {s.drawing_type} (信心度: {s.drawing_type_confidence:.0%})")
        lines.append(f"頁數: {s.page_count} | 尺寸: {s.image_size[0]}x{s.image_size[1]}px @{s.dpi}DPI")

        if g.get('total_axes', 0) > 0:
            lines.append(
                f"軸網: {g['total_axes']} 條軸線 "
                f"(水平 {len(g.get('horizontal_axes', []))} / 垂直 {len(g.get('vertical_axes', []))}), "
                f"共 {g.get('bay_count', 0)} 跨"
            )

        if p.get('total_panels', 0) > 0:
            lines.append(f"面板: 共 {p['total_panels']} 個")
            ts = p.get('type_summary', {})
            for t, c in ts.items():
                lines.append(f"  - {t}: {c} 個")

        sm = s.section_marks
        sm_summary = sm.get('summary', {})
        lines.append(f"標註: {a.get('dimension_count', 0)} 組尺寸, "
                     f"{a.get('text_region_count', 0)} 個文字區域, "
                     f"{a.get('fab_mark_count', 0)} 個加工標記")
        if sm_summary.get('total_marks', 0) > 0:
            dn_list = sm_summary.get('drawing_number_list', [])
            lines.append(f"Section Mark: {sm_summary['total_marks']} 個標記, "
                         f"圖紙編號: {sm_summary.get('drawing_numbers', 0)} 個"
                         + (f" ({', '.join(dn_list[:5])})" if dn_list else ""))

        return {
            'text': '\n'.join(lines),
            'drawing_type': s.drawing_type,
            'axes': g.get('total_axes', 0),
            'panels': p.get('total_panels', 0),
            'dimensions': a.get('dimension_count', 0),
            'fab_marks': a.get('fab_mark_count', 0),
            'section_marks': sm_summary.get('total_marks', 0),
            'drawing_numbers': sm_summary.get('drawing_numbers', 0),
            'title_block_detected': a.get('title_block', {}).get('detected', False),
        }


