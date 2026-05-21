"""
加工圖號 / Section Mark 偵測器。
從圖紙中讀取加工編號、剖面標記、零件號碼等文字標記。
"""

import re
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SectionMark:
    """一個加工圖號 / 剖面標記。"""
    text: str                          # OCR 辨識文字
    mark_type: str                     # 'drawing_number' | 'part_number' | 'section_cut' | 'detail_ref' | 'material_mark' | 'revision' | 'other'
    position: tuple = (0, 0)           # (x, y) 中心點
    bbox: tuple = (0, 0, 0, 0)         # (x, y, w, h)
    confidence: float = 0.0            # OCR 信心度
    bubble_id: str = ''                # 圓框編號 (如有)


@dataclass
class SectionMarkReport:
    """加工圖號偵測報告。"""
    marks: list = field(default_factory=list)               # list[SectionMark]
    drawing_numbers: list = field(default_factory=list)      # 圖紙編號
    part_numbers: list = field(default_factory=list)         # 零件編號
    section_refs: list = field(default_factory=list)         # 剖面參照
    material_marks: list = field(default_factory=list)       # 材料標記
    summary: dict = field(default_factory=dict)


class SectionMarkDetector:
    """
    從圖紙中偵測並 OCR 辨識加工圖號 / Section Marks。

    辨識目標:
      - 圖紙編號 (如 ACB-ACD-0060, FAC-5062)
      - 零件/面板編號
      - 剖面切線標記 (如 A-A, B-B)
      - 大樣參照 (圓框數字)
      - 材料標記 (如 AL-6063, SS304)
    """

    # 常見的加工圖號格式
    DRAWING_NUMBER_PATTERNS = [
        re.compile(r'[A-Z]{2,4}-[A-Z]{2,4}-\d{3,5}', re.IGNORECASE),    # ACB-ACD-0060
        re.compile(r'[A-Z]{2,4}-[A-Z]{2,4}-[A-Z]{3,4}-\d{4,5}', re.IGNORECASE),  # ACB-TG-FAC-0005
        re.compile(r'FAC\d{4}', re.IGNORECASE),                            # FAC5062
        re.compile(r'[A-Z]\d{3,4}', re.IGNORECASE),                        # A0203
        re.compile(r'[A-Z]{2,3}-\d{2,4}', re.IGNORECASE),                  # ACB-0203
    ]

    # 剖面標記格式
    SECTION_CUT_PATTERNS = [
        re.compile(r'[A-Za-z]+\s*[-–—]\s*[A-Za-z]+'),                    # A-A, B-B
        re.compile(r'剖面\s*[A-Za-z]'),                                   # 剖面 A
        re.compile(r'SEC(TION)?\.?\s*[A-Za-z]', re.IGNORECASE),           # SECTION A
    ]

    # 材料標記
    MATERIAL_PATTERNS = [
        re.compile(r'AL[-\s]?\d{4}', re.IGNORECASE),                      # AL 6063
        re.compile(r'SS[-\s]?\d{3,4}', re.IGNORECASE),                    # SS 304
        re.compile(r'\(\s*[A-Z]{2,4}\s*\)'),                               # (AL), (SS)
    ]

    def __init__(self, tesseract_cmd: str = 'tesseract'):
        self.tesseract_cmd = tesseract_cmd
        self._tesseract_available: Optional[bool] = None

    def _check_tesseract(self) -> bool:
        """檢查 tesseract 是否可用。"""
        if self._tesseract_available is not None:
            return self._tesseract_available
        import subprocess
        try:
            subprocess.run([self.tesseract_cmd, '--version'],
                           capture_output=True, timeout=5)
            self._tesseract_available = True
        except Exception:
            self._tesseract_available = False
        return self._tesseract_available

    def detect(self, gray_image: np.ndarray, binary_image: np.ndarray) -> SectionMarkReport:
        """
        從圖紙中偵測所有 Section Marks 並回傳結構化報告。
        """
        report = SectionMarkReport()

        # 1. 找所有可能的標記區域 (文字區域 + 圓框)
        roi_regions = self._find_mark_regions(gray_image, binary_image)

        # 2. OCR 每個區域
        for region in roi_regions:
            marks = self._ocr_region(gray_image, region)
            for mark in marks:
                if mark.mark_type != 'other' or len(mark.text.strip()) >= 2:
                    report.marks.append(mark)

        # 3. 歸類
        for mark in report.marks:
            self._classify_mark(mark, report)

        # 4. 生成摘要
        report.summary = self._build_summary(report)

        return report

    # -----------------------------------------------------------------
    def _find_mark_regions(self, gray: np.ndarray, binary: np.ndarray) -> list:
        """
        找出所有可能是加工標記的區域。
        包括：文字區塊、圓框/橢圓框、矩形框內文字。
        回傳 [(x, y, w, h, roi_binary), ...]
        """
        regions = []

        # A. MSER 文字區域
        try:
            mser = cv2.MSER_create(
                _delta=5, _min_area=30, _max_area=5000,
                _max_variation=0.25, _min_diversity=0.2
            )
            mser_regions, _ = mser.detectRegions(gray)
            for r in mser_regions:
                x, y, w, h = cv2.boundingRect(r)
                if 5 < w < gray.shape[1] * 0.3 and 5 < h < gray.shape[0] * 0.1:
                    regions.append((x, y, w, h))
        except Exception:
            pass

        # B. 圓框內的文字 (callout bubbles)
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.5, minDist=30,
            param1=80, param2=30, minRadius=15, maxRadius=80
        )
        if circles is not None:
            for circle in circles[0]:
                x, y, r = circle
                r = int(r)
                # 擷取圓框內部區域
                x1, y1 = max(0, int(x) - r), max(0, int(y) - r)
                x2, y2 = min(gray.shape[1], int(x) + r), min(gray.shape[0], int(y) + r)
                regions.append((x1, y1, x2 - x1, y2 - y1))

        # C. 連通域 (矩形框內文字)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 500:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # 合理的標記尺寸
            if 20 < w < 400 and 10 < h < 100:
                regions.append((x, y, w, h))

        # 去重 (合併重疊區域)
        return self._merge_overlapping(regions)

    @staticmethod
    def _merge_overlapping(regions: list, iou_thresh: float = 0.5) -> list:
        """合併重疊的 bounding box。"""
        if not regions:
            return []
        # 簡單合併: 按 x 排序，合併重疊的
        rects = sorted(regions, key=lambda r: (r[0], r[1]))
        merged = [list(rects[0])]
        for rect in rects[1:]:
            x, y, w, h = rect
            px, py, pw, ph = merged[-1]
            # 計算 IoU
            ix = max(x, px)
            iy = max(y, py)
            iw = min(x + w, px + pw) - ix
            ih = min(y + h, py + ph) - iy
            if iw > 0 and ih > 0:
                iou = (iw * ih) / min(w * h, pw * ph)
                if iou > iou_thresh:
                    # 合併
                    nx = min(x, px)
                    ny = min(y, py)
                    nw = max(x + w, px + pw) - nx
                    nh = max(y + h, py + ph) - ny
                    merged[-1] = [nx, ny, nw, nh]
                    continue
            merged.append([x, y, w, h])
        return [tuple(m) for m in merged]

    # -----------------------------------------------------------------
    def _ocr_region(self, gray: np.ndarray, region: tuple) -> list:
        """對一個區域做 OCR，回傳辨識結果。"""
        x, y, w, h = region
        roi = gray[y:y + h, x:x + w]

        if roi.size == 0:
            return []

        marks = []

        if self._check_tesseract():
            marks = self._tesseract_ocr(roi, x, y, w, h)

        # 同時也試圖從圓框編號模式中提取
        bubble_text = self._detect_bubble_text(roi, x, y, w, h)
        if bubble_text:
            marks.append(bubble_text)

        return marks

    def _tesseract_ocr(self, roi: np.ndarray, x: int, y: int, w: int, h: int) -> list:
        """使用 Tesseract 做 OCR。"""
        import subprocess
        import tempfile
        import os

        try:
            # 預處理: 放大 + 二值化以提升 OCR 準確度
            if roi.shape[0] < 30:
                roi = cv2.resize(roi, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

            # 寫入暫存檔
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, roi)
                tmp_path = tmp.name

            # 跑 tesseract
            result = subprocess.run(
                [self.tesseract_cmd, tmp_path, 'stdout', '-l', 'eng+chi_sim', '--psm', '6'],
                capture_output=True, text=True, timeout=10
            )
            os.unlink(tmp_path)

            text = result.stdout.strip()
            if not text:
                return []

            # 計算信心度 (從 stderr 提取)
            conf = 0.7  # 預設
            stderr = result.stderr
            conf_match = re.search(r'Confidence:\s*(\d+)', stderr)
            if conf_match:
                conf = int(conf_match.group(1)) / 100.0

            lines = [l.strip() for l in text.split('\n') if l.strip()]
            marks = []
            for line in lines:
                if len(line) >= 2:
                    marks.append(SectionMark(
                        text=line,
                        mark_type='other',
                        position=(x + w // 2, y + h // 2),
                        bbox=(x, y, w, h),
                        confidence=conf,
                    ))
            return marks

        except Exception:
            return []

    def _detect_bubble_text(self, roi: np.ndarray, x: int, y: int, w: int, h: int) -> Optional[SectionMark]:
        """嘗試從圓框/橢圓框擷取內部的數字。"""
        if roi.size == 0:
            return None

        # 計算圓形區域的中心
        h_img, w_img = roi.shape[:2]
        center_x, center_y = w_img // 2, h_img // 2

        # 圓框特徵: 邊緣有圓形，內部有文字
        edges = cv2.Canny(roi, 50, 150)
        circles = cv2.HoughCircles(
            roi, cv2.HOUGH_GRADIENT, dp=1.2, minDist=10,
            param1=50, param2=20, minRadius=5, maxRadius=min(w_img, h_img) // 2
        )

        if circles is not None:
            # 有圓框，嘗試用 simple 模板匹配內部數字
            # (目前用 tesseract 處理；如 tesseract 不可用，回傳位置資訊)
            return SectionMark(
                text='',
                mark_type='detail_ref',
                position=(x + center_x, y + center_y),
                bbox=(x, y, w, h),
                confidence=0.5,
                bubble_id=f'bubble_{x}_{y}',
            )

        return None

    # -----------------------------------------------------------------
    def _classify_mark(self, mark: SectionMark, report: SectionMarkReport):
        """將 mark 歸類到對應的類別。"""
        text = mark.text.strip()

        # 圖紙編號
        for pat in self.DRAWING_NUMBER_PATTERNS:
            if pat.search(text):
                mark.mark_type = 'drawing_number'
                report.drawing_numbers.append(mark)
                return

        # 剖面標記
        for pat in self.SECTION_CUT_PATTERNS:
            if pat.search(text):
                mark.mark_type = 'section_cut'
                report.section_refs.append(mark)
                return

        # 材料標記
        for pat in self.MATERIAL_PATTERNS:
            if pat.search(text):
                mark.mark_type = 'material_mark'
                report.material_marks.append(mark)
                return

        # 零件編號 (純數字或字母+數字組合)
        if re.match(r'^[A-Z]?\d{2,5}[A-Z]?$', text):
            mark.mark_type = 'part_number'
            report.part_numbers.append(mark)
            return

        # 其他留在 report.marks 中，不額外歸類

    def _build_summary(self, report: SectionMarkReport) -> dict:
        return {
            'total_marks': len(report.marks),
            'drawing_numbers': len(report.drawing_numbers),
            'part_numbers': len(report.part_numbers),
            'section_refs': len(report.section_refs),
            'material_marks': len(report.material_marks),
            'drawing_number_list': list(set(m.text for m in report.drawing_numbers)),
            'part_number_list': list(set(m.text for m in report.part_numbers))[:50],
            'section_ref_list': list(set(m.text for m in report.section_refs)),
            'material_list': list(set(m.text for m in report.material_marks)),
        }
