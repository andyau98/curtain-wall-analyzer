"""
解析幕牆圖紙中的尺寸標註與加工標記。
識別: 尺寸線、標註文字、加工符號、剖切符號。
"""

import re
import cv2
import numpy as np
from dataclasses import dataclass, field


@dataclass
class Dimension:
    """一組尺寸標註。"""
    value: str                # 標註值，如 "1200"
    unit: str = 'mm'          # 單位
    position: tuple = (0, 0)  # (x, y) 像素位置
    orientation: str = ''     # 'horizontal' | 'vertical'
    dimension_type: str = ''  # 'overall' | 'bay' | 'detail' | 'elevation'


@dataclass
class Annotation:
    """一個文字標註/加工標記。"""
    text: str
    position: tuple = (0, 0)
    annotation_type: str = ''   # 'material' | 'finish' | 'note' | 'revision' | 'title'
    bbox: tuple = (0, 0, 0, 0)  # (x, y, w, h)


@dataclass
class FabricationMark:
    """加工圖標記。"""
    mark_type: str             # 'weld' | 'cut' | 'drill' | 'notch' | 'fold' | 'assembly'
    position: tuple = (0, 0)
    description: str = ''
    confidence: float = 0.0


@dataclass
class DrawingAnnotations:
    """圖紙標註的完整解析結果。"""
    dimensions: list = field(default_factory=list)       # list[Dimension]
    annotations: list = field(default_factory=list)       # list[Annotation]
    fab_marks: list = field(default_factory=list)         # list[FabricationMark]
    title_block: dict = field(default_factory=dict)       # 圖框資訊


class DimensionParser:
    """分析位置圖中的尺寸標註和加工標記。"""

    # 常見加工符號的幾何模板
    FAB_MARK_TEMPLATES = {
        'weld':    '焊接符號 (三角形/箭頭)',
        'cut':     '切割線 (虛線/點劃線)',
        'drill':   '鑽孔標記 (十字圓)',
        'notch':   '開槽標記 (U形/V形)',
        'fold':    '折彎線 (鏈線)',
        'assembly': '組裝編號 (圓框數字)',
    }

    def parse(self, gray_image: np.ndarray, binary_image: np.ndarray) -> DrawingAnnotations:
        """
        綜合解析圖紙上的標註資訊。
        注意: 完整的 OCR 需要 tesseract；此處提供結構化框架，
        在無 tesseract 環境下以規則為基礎識別標註位置。
        """
        result = DrawingAnnotations()

        # 1. 尺寸線偵測 (基於形態學)
        result.dimensions = self._detect_dimension_lines(binary_image)

        # 2. 文字區域偵測 (MSER / 連通域)
        result.annotations = self._detect_text_regions(gray_image)

        # 3. 加工符號偵測 (模板匹配 + 形狀分析)
        result.fab_marks = self._detect_fab_marks(binary_image)

        # 4. 圖框資訊
        result.title_block = self._extract_title_block(binary_image, gray_image.shape)

        return result

    # -----------------------------------------------------------------
    def _detect_dimension_lines(self, binary: np.ndarray) -> list:
        """偵測尺寸標註線 (短平行線 + 箭頭)。"""
        dimensions = []

        # 尺寸線特徵: 短線段、端點有斜線或箭頭
        lines = cv2.HoughLinesP(binary, 1, np.pi / 180, threshold=50,
                                minLineLength=30, maxLineGap=5)

        if lines is None:
            return dimensions

        # 分群
        h_dim_lines = []
        v_dim_lines = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            if length < 20 or length > 300:  # 尺寸線通常不長不短
                continue
            if abs(y1 - y2) < 3:
                h_dim_lines.append(((y1 + y2) // 2, (x1 + x2) // 2, length))
            elif abs(x1 - x2) < 3:
                v_dim_lines.append(((x1 + x2) // 2, (y1 + y2) // 2, length))

        # 水平尺寸標註
        for y, cx, length in h_dim_lines:
            dimensions.append(Dimension(
                value=f"~{length}px",
                unit='px',
                position=(cx, y),
                orientation='horizontal',
                dimension_type='detail',
            ))

        # 垂直尺寸標註
        for cx, cy, length in v_dim_lines:
            dimensions.append(Dimension(
                value=f"~{length}px",
                unit='px',
                position=(cx, cy),
                orientation='vertical',
                dimension_type='detail',
            ))

        return dimensions

    # -----------------------------------------------------------------
    def _detect_text_regions(self, gray: np.ndarray) -> list:
        """使用 MSER 找出文字區域。"""
        annotations = []
        try:
            mser = cv2.MSER_create()
            regions, _ = mser.detectRegions(gray)
            for i, region in enumerate(regions):
                x, y, w, h = cv2.boundingRect(region)
                if w < 8 or h < 8 or w > gray.shape[1] * 0.5:
                    continue
                aspect = w / h if h > 0 else 0
                if aspect < 0.2 or aspect > 10:  # 排除非文字
                    continue
                annotations.append(Annotation(
                    text='',
                    position=(x + w // 2, y + h // 2),
                    annotation_type='note',
                    bbox=(x, y, w, h),
                ))
        except Exception:
            pass  # MSER 在某些 OpenCV 版本不可用
        return annotations

    # -----------------------------------------------------------------
    def _detect_fab_marks(self, binary: np.ndarray) -> list:
        """偵測加工符號: 焊接、切割、鑽孔、開槽、折彎標記。"""
        marks = []

        # 圓形偵測 (鑽孔標記、組裝編號圓框)
        circles = cv2.HoughCircles(
            cv2.bitwise_not(binary), cv2.HOUGH_GRADIENT,
            dp=1, minDist=20, param1=50, param2=15,
            minRadius=5, maxRadius=30
        )
        if circles is not None:
            for circle in circles[0]:
                x, y, r = circle
                marks.append(FabricationMark(
                    mark_type='drill',
                    position=(int(x), int(y)),
                    description=f'鑽孔標記 r={r:.0f}px',
                    confidence=0.7,
                ))

        # 三角形/箭頭偵測 (焊接符號)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)
            if len(approx) == 3:  # 三角形 = 可能是焊接符號
                M = cv2.moments(cnt)
                if M['m00'] > 0:
                    cx, cy = int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])
                    area = cv2.contourArea(cnt)
                    if 50 < area < 2000:
                        marks.append(FabricationMark(
                            mark_type='weld',
                            position=(cx, cy),
                            description='焊接符號 (三角形)',
                            confidence=0.6,
                        ))

        return marks

    # -----------------------------------------------------------------
    def _extract_title_block(self, binary: np.ndarray, shape: tuple) -> dict:
        """辨識圖框/標題欄區域 (通常在右下角)。"""
        h, w = shape
        # 圖框通常在右下角約 20% 的區域
        roi = binary[int(h * 0.75):h, int(w * 0.6):w]
        white_pixel_ratio = np.sum(roi > 0) / roi.size if roi.size > 0 else 0

        return {
            'position': '右下角',
            'area_ratio': f'{white_pixel_ratio:.2%}',
            'detected': white_pixel_ratio > 0.05,
            'estimated_size': f'{roi.shape[1]}x{roi.shape[0]}px',
        }
