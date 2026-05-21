"""
偵測幕牆位置圖中的軸線網格系統。
幕牆圖的核心結構: 水平軸 (A, B, C...) 與垂直軸 (1, 2, 3...)
"""

import cv2
import numpy as np
from dataclasses import dataclass, field


@dataclass
class GridLine:
    """一條軸線。"""
    orientation: str        # 'horizontal' | 'vertical'
    position: int           # 像素座標 (水平線: y, 垂直線: x)
    length: int             # 線段長度 (px)
    thickness: float        # 平均線寬 (px)
    confidence: float       # 0-1 信心度
    label: str = ''         # 軸號，例如 'A', '1'


@dataclass
class GridSystem:
    """完整的軸網系統。"""
    horizontal_lines: list = field(default_factory=list)   # list of GridLine
    vertical_lines: list = field(default_factory=list)     # list of GridLine
    intersections: list = field(default_factory=list)      # [(x, y), ...]
    grid_spacing_h: list = field(default_factory=list)     # 水平間距
    grid_spacing_v: list = field(default_factory=list)     # 垂直間距

    @property
    def total_axes(self) -> int:
        return len(self.horizontal_lines) + len(self.vertical_lines)

    @property
    def bay_count(self) -> int:
        """跨數 (格數)。"""
        h = max(1, len(self.vertical_lines) - 1)
        v = max(1, len(self.horizontal_lines) - 1)
        return h * v


class GridDetector:
    """從圖紙影像中偵測軸線網格。"""

    def detect(self, binary_image: np.ndarray) -> GridSystem:
        h_lines = self._detect_horizontal(binary_image)
        v_lines = self._detect_vertical(binary_image)
        h_lines = self._filter_by_cluster(h_lines)
        v_lines = self._filter_by_cluster(v_lines)
        h_lines = self._assign_h_labels(h_lines)
        v_lines = self._assign_v_labels(v_lines)
        intersections = self._find_intersections(h_lines, v_lines, binary_image.shape)
        h_spacing = self._calc_spacing([l.position for l in h_lines])
        v_spacing = self._calc_spacing([l.position for l in v_lines])

        return GridSystem(
            horizontal_lines=h_lines,
            vertical_lines=v_lines,
            intersections=intersections,
            grid_spacing_h=h_spacing,
            grid_spacing_v=v_spacing,
        )

    # ---------- 水平線 ----------
    def _detect_horizontal(self, binary: np.ndarray) -> list:
        """用形態學運算擷取水平長線。"""
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

        lines = cv2.HoughLinesP(horizontal, 1, np.pi / 2, threshold=100,
                                minLineLength=binary.shape[1] * 0.3,
                                maxLineGap=20)
        results = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if abs(y1 - y2) < 3:  # 近水平
                    length = abs(x2 - x1)
                    results.append(GridLine(
                        orientation='horizontal',
                        position=(y1 + y2) // 2,
                        length=length,
                        thickness=self._estimate_thickness(binary, (y1 + y2) // 2, 'h'),
                        confidence=min(1.0, length / binary.shape[1]),
                    ))
        return results

    # ---------- 垂直線 ----------
    def _detect_vertical(self, binary: np.ndarray) -> list:
        """用形態學運算擷取垂直長線。"""
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 50))
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

        lines = cv2.HoughLinesP(vertical, 1, np.pi / 180, threshold=100,
                                minLineLength=binary.shape[0] * 0.3,
                                maxLineGap=20)
        results = []
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if abs(x1 - x2) < 3:  # 近垂直
                    length = abs(y2 - y1)
                    results.append(GridLine(
                        orientation='vertical',
                        position=(x1 + x2) // 2,
                        length=length,
                        thickness=self._estimate_thickness(binary, (x1 + x2) // 2, 'v'),
                        confidence=min(1.0, length / binary.shape[0]),
                    ))
        return results

    # ---------- 聚類去重 ----------
    def _filter_by_cluster(self, lines: list, tolerance: int = 10) -> list:
        """相近的線歸為同一條，取平均位置。"""
        if not lines:
            return []
        lines = sorted(lines, key=lambda l: l.position)
        clusters = []
        current_cluster = [lines[0]]
        for line in lines[1:]:
            if abs(line.position - current_cluster[-1].position) <= tolerance:
                current_cluster.append(line)
            else:
                clusters.append(current_cluster)
                current_cluster = [line]
        clusters.append(current_cluster)

        merged = []
        for cluster in clusters:
            avg_pos = int(np.mean([l.position for l in cluster]))
            best = max(cluster, key=lambda l: l.confidence)
            best.position = avg_pos
            merged.append(best)
        return merged

    # ---------- 軸號 ----------
    def _assign_h_labels(self, lines: list) -> list:
        """由下往上標 A, B, C..."""
        lines = sorted(lines, key=lambda l: l.position, reverse=True)
        for i, line in enumerate(lines):
            line.label = chr(65 + i) if i < 26 else f"A{chr(65 + i - 26)}"
        return lines

    def _assign_v_labels(self, lines: list) -> list:
        """由左往右標 1, 2, 3..."""
        lines = sorted(lines, key=lambda l: l.position)
        for i, line in enumerate(lines):
            line.label = str(i + 1)
        return lines

    # ---------- 輔助 ----------
    def _estimate_thickness(self, binary: np.ndarray, pos: int, orientation: str) -> float:
        """取軸線位置的橫切面估算線寬。"""
        margin = 5
        if orientation == 'h':
            if pos < margin or pos + margin >= binary.shape[0]:
                return 1.0
            strip = binary[pos - margin:pos + margin, :]
            row_profile = np.mean(strip, axis=0)
            runs = self._count_crossings(row_profile)
            return runs if runs > 0 else 1.0
        else:
            if pos < margin or pos + margin >= binary.shape[1]:
                return 1.0
            strip = binary[:, pos - margin:pos + margin]
            col_profile = np.mean(strip, axis=1)
            runs = self._count_crossings(col_profile)
            return runs if runs > 0 else 1.0

    @staticmethod
    def _count_crossings(profile: np.ndarray) -> float:
        """計算 profile 穿越 50% 的次數來估算線寬。"""
        threshold = np.max(profile) * 0.5
        above = profile > threshold
        transitions = np.sum(np.diff(above.astype(int)) != 0)
        return transitions / 2.0

    def _find_intersections(self, h_lines: list, v_lines: list, shape: tuple) -> list:
        """計算水平軸與垂直軸的交點。"""
        pts = []
        for hl in h_lines:
            for vl in v_lines:
                x, y = vl.position, hl.position
                if 0 <= x < shape[1] and 0 <= y < shape[0]:
                    pts.append({'x': x, 'y': y, 'h_axis': hl.label, 'v_axis': vl.label})
        return pts

    @staticmethod
    def _calc_spacing(positions: list) -> list:
        """計算相鄰軸線間距。"""
        if len(positions) < 2:
            return []
        pos = sorted(positions)
        return [pos[i + 1] - pos[i] for i in range(len(pos) - 1)]
