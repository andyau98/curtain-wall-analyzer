"""
將 PDF / 圖片轉換為統一的可分析格式。
支援 PDF (經由 pdf2image) 及常見圖片格式。
"""

import os
import cv2
import numpy as np
from PIL import Image
from pdf2image import convert_from_path


class DrawingParser:
    """載入並預處理幕牆圖紙，輸出統一的分析用影像陣列。"""

    SUPPORTED_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'}

    def __init__(self, filepath: str, dpi: int = 300):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"圖紙不存在: {filepath}")
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self.SUPPORTED_EXT:
            raise ValueError(f"不支援的格式: {ext}，支援格式: {self.SUPPORTED_EXT}")
        self.filepath = filepath
        self.ext = ext
        self.dpi = dpi
        self.pages = []          # list of np.array (BGR)
        self.gray_pages = []     # list of np.array (grayscale)
        self.binary_pages = []   # list of np.array (binary threshold)

    def parse(self) -> int:
        """載入全部頁面，返回頁數。"""
        if self.ext == '.pdf':
            self._parse_pdf()
        else:
            self._parse_image()
        self._preprocess()
        return len(self.pages)

    def _parse_pdf(self):
        images = convert_from_path(self.filepath, dpi=self.dpi)
        for img in images:
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            self.pages.append(cv_img)

    def _parse_image(self):
        cv_img = cv2.imread(self.filepath)
        if cv_img is None:
            raise ValueError(f"無法讀取圖檔: {self.filepath}")
        self.pages.append(cv_img)

    def _preprocess(self):
        for page in self.pages:
            gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
            self.gray_pages.append(gray)
            # 自適應二值化，適合線條圖
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, 15, 8
            )
            self.binary_pages.append(binary)

    def get_page(self, idx: int = 0):
        return {
            'color': self.pages[idx],
            'gray': self.gray_pages[idx],
            'binary': self.binary_pages[idx],
        }
