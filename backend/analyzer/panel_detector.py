"""
偵測幕牆面板/單元邊界。
在位置圖中找出每個面板的矩形區域，並歸類面板類型。
"""

import cv2
import numpy as np
from dataclasses import dataclass, field


@dataclass
class Panel:
    """一個幕牆面板單元。"""
    id: int
    bbox: tuple            # (x, y, w, h) — 像素座標
    area: float            # 面積 (px²)
    aspect_ratio: float    # 寬高比
    grid_cell: str = ''    # 網格位置，例如 'A-1'
    panel_type: str = ''   # vision / spandrel / operable / louver / other
    glass_type: str = ''   # 玻璃類型標記
    confidence: float = 0.0


@dataclass
class PanelLayout:
    """整幅位置圖的面板佈局。"""
    panels: list = field(default_factory=list)
    type_summary: dict = field(default_factory=dict)      # {type: count}
    aspect_summary: dict = field(default_factory=dict)    # {aspect_group: count}

    @property
    def total_panels(self) -> int:
        return len(self.panels)


class PanelDetector:
    """從位置圖中抽取面板輪廓與分類。"""

    PANEL_TYPES = {
        'vision':    '視野玻璃面板',
        'spandrel':  '背襯面板 (非視野區)',
        'operable':  '可開啟窗面板',
        'louver':    '百葉面板',
        'structural': '結構面板 (無玻璃)',
        'other':     '其他',
    }

    def detect(self, binary_image: np.ndarray, grid_system) -> PanelLayout:
        """
        以軸網為基礎，在每個網格單元內尋找面板輪廓。
        """
        panels = []
        h_lines = sorted(grid_system.horizontal_lines, key=lambda l: l.position)
        v_lines = sorted(grid_system.vertical_lines, key=lambda l: l.position)

        # 使用輪廓偵測找所有矩形邊界
        contours, _ = cv2.findContours(binary_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 過濾出可能是面板的矩形輪廓
        panel_contours = []
        min_area = binary_image.shape[0] * binary_image.shape[1] * 0.0001  # 最小 0.01%
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4:  # 四邊形
                x, y, w, h = cv2.boundingRect(cnt)
                aspect = w / h if h > 0 else 0
                # 合理長寬比 (幕牆面板通常在 0.3 ~ 3.0 之間)
                if 0.2 < aspect < 5.0:
                    panel_contours.append((x, y, w, h, cnt, area, aspect))

        # 為每個面板分配網格位置和類型
        for i, (x, y, w, h, cnt, area, aspect) in enumerate(panel_contours):
            # 找所屬網格
            grid_cell = self._find_grid_cell(x + w // 2, y + h // 2, h_lines, v_lines)

            # 判定面板類型
            panel_type = self._classify_panel(aspect, area, binary_image[y:y + h, x:x + w])

            panels.append(Panel(
                id=i + 1,
                bbox=(x, y, w, h),
                area=area,
                aspect_ratio=aspect,
                grid_cell=grid_cell,
                panel_type=panel_type,
                confidence=0.85,
            ))

        # 統計摘要
        type_summary = {}
        for p in panels:
            type_summary[p.panel_type] = type_summary.get(p.panel_type, 0) + 1

        aspect_groups = {'窄型 (<0.6)': 0, '標準 (0.6-1.5)': 0, '寬型 (1.5-3.0)': 0, '特寬 (>3.0)': 0}
        for p in panels:
            ar = p.aspect_ratio
            if ar < 0.6:
                aspect_groups['窄型 (<0.6)'] += 1
            elif ar <= 1.5:
                aspect_groups['標準 (0.6-1.5)'] += 1
            elif ar <= 3.0:
                aspect_groups['寬型 (1.5-3.0)'] += 1
            else:
                aspect_groups['特寬 (>3.0)'] += 1

        return PanelLayout(
            panels=panels,
            type_summary=type_summary,
            aspect_summary=aspect_groups,
        )

    def _find_grid_cell(self, cx: int, cy: int, h_lines: list, v_lines: list) -> str:
        """根據中心點找出所屬網格位置。"""
        # 找水平軸 (由下往上)
        h_label = '?'
        for i in range(len(h_lines) - 1):
            if h_lines[i + 1].position <= cy <= h_lines[i].position:
                h_label = h_lines[i].label
                break
        if h_label == '?' and h_lines:
            h_label = h_lines[-1].label

        # 找垂直軸 (由左往右)
        v_label = '?'
        for i in range(len(v_lines) - 1):
            if v_lines[i].position <= cx <= v_lines[i + 1].position:
                v_label = v_lines[i].label
                break
        if v_label == '?' and v_lines:
            v_label = v_lines[-1].label

        return f"{h_label}-{v_label}"

    def _classify_panel(self, aspect: float, area: float, roi: np.ndarray) -> str:
        """根據幾何特徵與區域紋理分類面板類型。"""
        # 基於長寬比的初步分類
        if aspect > 3.0:
            return 'louver'
        if aspect < 0.4:
            return 'structural'

        # 基於區域內部紋理判斷
        if roi.size > 0:
            # 內部白色像素密度 (二值影像中 white=前景)
            fill_ratio = np.sum(roi > 0) / roi.size
            if fill_ratio < 0.05:
                return 'vision'     # 大片空白 = 視野玻璃
            elif fill_ratio < 0.2:
                return 'spandrel'   # 少許紋理 = 背襯面板
            elif fill_ratio > 0.5:
                return 'operable'   # 密集線條 = 可開啟窗

        return 'vision'  # 預設
